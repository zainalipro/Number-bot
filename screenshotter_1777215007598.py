"""Headless-browser based capture of register / login pages with the form
filled and submitted, returning PNG screenshots so the user can visually
decide success vs failure for each (platform, number) pair."""

import asyncio
import logging
import io
import re
from PIL import Image, ImageDraw, ImageFont

from platform_checker import (
    GENERIC_PLATFORM_URLS,
    random_user_data,
)

logger = logging.getLogger(__name__)

LAUNCH_ARGS = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
VIEWPORT = {"width": 1280, "height": 900}
NAV_TIMEOUT_MS = 15000
ACTION_TIMEOUT_MS = 8000


PLATFORM_PAGES: dict[str, dict[str, str]] = {
    "Google":    {"signup": "https://accounts.google.com/signup",
                  "signin": "https://accounts.google.com/signin"},
    "Microsoft": {"signup": "https://signup.live.com/signup",
                  "signin": "https://login.live.com/"},
    "FACEBOOK":  {"signup": "https://www.facebook.com/r.php",
                  "signin": "https://www.facebook.com/login/"},
    "Instagram": {"signup": "https://www.instagram.com/accounts/emailsignup/",
                  "signin": "https://www.instagram.com/accounts/login/"},
    "TikTok":    {"signup": "https://www.tiktok.com/signup/phone-or-email/phone",
                  "signin": "https://www.tiktok.com/login/phone-or-email/phone"},
    "Apple":     {"signup": "https://appleid.apple.com/account",
                  "signin": "https://appleid.apple.com/sign-in"},
    "Amazon":    {"signup": "https://www.amazon.com/ap/register",
                  "signin": "https://www.amazon.com/ap/signin"},
    "Snapchat":  {"signup": "https://accounts.snapchat.com/accounts/signup",
                  "signin": "https://accounts.snapchat.com/accounts/login"},
    "WhatsApp":  {"signup": "https://www.whatsapp.com/",
                  "signin": "https://web.whatsapp.com/"},
    "Telegram":  {"signup": "https://my.telegram.org/auth",
                  "signin": "https://web.telegram.org/"},
    "github":    {"signup": "https://github.com/signup",
                  "signin": "https://github.com/login"},
    "Uber":      {"signup": "https://auth.uber.com/v2/",
                  "signin": "https://auth.uber.com/v2/"},
    "Booking":   {"signup": "https://account.booking.com/register",
                  "signin": "https://account.booking.com/sign-in"},
    "OKru":      {"signup": "https://ok.ru/dk?st.cmd=anonymRegistrationEnterPhone",
                  "signin": "https://ok.ru/"},
    "SAMSUNG":   {"signup": "https://account.samsung.com/membership/intro",
                  "signin": "https://account.samsung.com/"},
    "TINDER":    {"signup": "https://tinder.com/",
                  "signin": "https://tinder.com/"},
    "LINE":      {"signup": "https://account.line.biz/signup",
                  "signin": "https://account.line.biz/login"},
    "Viber":     {"signup": "https://www.viber.com/",
                  "signin": "https://www.viber.com/"},
    "Huawei":    {"signup": "https://id.huawei.com/CAS/portal/userRegister/regbyphone.html",
                  "signin": "https://id.huawei.com/"},
}


def _signup_url(platform: str) -> str:
    p = PLATFORM_PAGES.get(platform, {})
    return p.get("signup") or GENERIC_PLATFORM_URLS.get(platform, "")


def _signin_url(platform: str) -> str:
    p = PLATFORM_PAGES.get(platform, {})
    return p.get("signin") or GENERIC_PLATFORM_URLS.get(platform, "")


def _placeholder_png(platform: str, number: str, kind: str, reason: str) -> bytes:
    W, H = 1100, 720
    img = Image.new("RGB", (W, H), (24, 24, 32))
    d = ImageDraw.Draw(img)
    try:
        f_big = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 32)
        f_med = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)
        f_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
    except Exception:
        f_big = f_med = f_small = ImageFont.load_default()
    d.rectangle([(0, 0), (8, H)], fill=(231, 76, 60))
    d.text((40, 40), f"{kind} screenshot unavailable", font=f_big, fill=(255, 230, 230))
    d.text((40, 110), f"Platform: {platform}", font=f_med, fill=(220, 220, 230))
    d.text((40, 150), f"Number:   +{number}", font=f_med, fill=(220, 220, 230))
    d.text((40, 210), "Reason:", font=f_small, fill=(180, 180, 200))
    for i, chunk in enumerate(_wrap(reason, 80)[:8]):
        d.text((40, 240 + i * 26), chunk, font=f_small, fill=(255, 200, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _wrap(s: str, n: int) -> list[str]:
    s = (s or "").strip()
    return [s[i:i + n] for i in range(0, len(s), n)] or [""]


_FORM_SCAN_JS = r"""
(kind) => {
    function isVisible(el) {
        const r = el.getBoundingClientRect();
        const cs = window.getComputedStyle(el);
        return r.width > 0 && r.height > 0 &&
               cs.visibility !== 'hidden' && cs.display !== 'none';
    }

    const SIGNUP_KW = ['sign up','signup','register','create account','create an account','join','new account','créer','registrieren','registrarse','регистрация','إنشاء','sign-up'];
    const SIGNIN_KW = ['sign in','signin','log in','login','log-in','sign-in','iniciar sesión','se connecter','anmelden','войти','تسجيل الدخول'];
    const NEG_KW    = ['subscribe','newsletter','search','filter','coupon','promo','discount','feedback','contact us','review','comment','quote','enquiry','enquire'];

    function scoreText(text, action, kind) {
        text = (text || '').toLowerCase();
        action = (action || '').toLowerCase();
        let s = 0;
        const wanted = (kind === 'Signup') ? SIGNUP_KW : SIGNIN_KW;
        const other  = (kind === 'Signup') ? SIGNIN_KW : SIGNUP_KW;
        for (const k of wanted) {
            if (text.includes(k))   s += 25;
            if (action.includes(k.replace(/\s+/g,''))) s += 25;
        }
        for (const k of other) {
            if (text.includes(k))   s += 5;
        }
        for (const k of NEG_KW) {
            if (text.includes(k))   s -= 80;
            if (action.includes(k)) s -= 80;
        }
        return s;
    }

    const forms = Array.from(document.querySelectorAll('form')).filter(isVisible);
    const results = [];
    forms.forEach((f, fi) => {
        const inputs = Array.from(f.querySelectorAll('input,select,textarea')).filter(el => {
            return el.type !== 'hidden' && isVisible(el);
        });
        if (inputs.length === 0) return;
        const buttonText = Array.from(f.querySelectorAll('button, input[type=submit], [role=button]'))
            .map(b => (b.innerText || b.value || '').trim()).join(' ');
        const text = (f.innerText || '') + ' ' + buttonText;
        const action = f.action || '';
        const hasPassword = inputs.some(e => (e.type || '').toLowerCase() === 'password');
        let s = scoreText(text, action, kind);
        if (hasPassword) s += 60;
        s += Math.min(inputs.length, 6) * 3;
        // Tag the form so we can address it later
        f.setAttribute('data-pw-form-idx', String(fi));
        results.push({
            idx: fi,
            score: s,
            hasPassword: hasPassword,
            inputCount: inputs.length,
            text: text.slice(0, 200),
            action: action,
            inputs: inputs.map((el, i) => {
                el.setAttribute('data-pw-field-idx', `${fi}-${i}`);
                return {
                    fi: fi, i: i,
                    tag: el.tagName.toLowerCase(),
                    type: (el.type || '').toLowerCase(),
                    name: (el.name || '').toLowerCase(),
                    id: (el.id || '').toLowerCase(),
                    placeholder: (el.placeholder || '').toLowerCase(),
                    ariaLabel: (el.getAttribute('aria-label') || '').toLowerCase(),
                    autocomplete: (el.autocomplete || '').toLowerCase(),
                };
            }),
        });
    });

    // Also consider "loose" inputs not inside a <form> — group them as a synthetic form
    const looseInputs = Array.from(document.querySelectorAll('input,select,textarea')).filter(el => {
        return el.type !== 'hidden' && !el.closest('form') && isVisible(el);
    });
    if (looseInputs.length > 0) {
        const text = looseInputs.map(el => {
            const labels = el.labels ? Array.from(el.labels).map(l => l.innerText).join(' ') : '';
            return labels + ' ' + (el.placeholder || '') + ' ' + (el.getAttribute('aria-label') || '');
        }).join(' ');
        const hasPassword = looseInputs.some(e => (e.type || '').toLowerCase() === 'password');
        let s = scoreText(text + ' ' + document.title, '', kind);
        if (hasPassword) s += 60;
        s += Math.min(looseInputs.length, 6) * 3;
        const fi = forms.length;
        results.push({
            idx: fi, score: s, hasPassword: hasPassword, inputCount: looseInputs.length,
            text: text.slice(0, 200), action: '(no form)',
            inputs: looseInputs.map((el, i) => {
                el.setAttribute('data-pw-field-idx', `${fi}-${i}`);
                return {
                    fi: fi, i: i,
                    tag: el.tagName.toLowerCase(),
                    type: (el.type || '').toLowerCase(),
                    name: (el.name || '').toLowerCase(),
                    id: (el.id || '').toLowerCase(),
                    placeholder: (el.placeholder || '').toLowerCase(),
                    ariaLabel: (el.getAttribute('aria-label') || '').toLowerCase(),
                    autocomplete: (el.autocomplete || '').toLowerCase(),
                };
            }),
        });
    }

    results.sort((a, b) => b.score - a.score);
    return results;
}
"""


def _classify_field(f: dict) -> str:
    ident = " ".join((f.get(k) or "") for k in ("name", "id", "placeholder", "ariaLabel", "autocomplete"))
    t = f.get("type") or ""
    if t == "tel" or any(k in ident for k in ("phone", "mobile", "msisdn", "whatsapp")) or " tel" in (" " + ident):
        return "phone"
    if t == "email" or "email" in ident or "e-mail" in ident or "mail" in ident:
        return "email"
    if t == "password" or "pass" in ident:
        return "password"
    if "first" in ident or "given" in ident or "fname" in ident:
        return "first"
    if "last" in ident or "surname" in ident or "family" in ident or "lname" in ident:
        return "last"
    if "user" in ident or "login" in ident or "handle" in ident or "nick" in ident or "screen" in ident:
        return "username"
    if "fullname" in ident or "displayname" in ident or ident.strip() == "name":
        return "fullname"
    if "birth" in ident or "dob" in ident or "age" in ident:
        return "dob"
    if "zip" in ident or "postal" in ident or "postcode" in ident:
        return "zip"
    if "code" in ident or "captcha" in ident or "otp" in ident:
        return "skip"
    if t in ("text", "search") and not ident:
        return "text"
    if t == "text":
        return "text"
    return "skip"


async def _fill_chosen_form(page, form: dict, number: str) -> tuple[int, bool]:
    """Fill only inputs that belong to the chosen form, then submit it."""
    rd = random_user_data()
    filled = 0
    for f in form.get("inputs", []):
        kind = _classify_field(f)
        if kind == "skip":
            continue
        value = ""
        if kind == "phone":
            value = f"+{number}"
        elif kind == "email":
            value = rd["email"]
        elif kind == "password":
            value = rd["password"]
        elif kind == "first":
            value = rd["first_name"]
        elif kind == "last":
            value = rd["last_name"]
        elif kind == "username":
            value = rd["username"]
        elif kind == "fullname":
            value = rd["full_name"]
        elif kind == "dob":
            value = "1995-06-15"
        elif kind == "zip":
            value = "10001"
        elif kind == "text":
            value = rd["username"]
        if not value:
            continue
        try:
            sel = f'[data-pw-field-idx="{f["fi"]}-{f["i"]}"]'
            await page.locator(sel).first.fill(value, timeout=ACTION_TIMEOUT_MS)
            filled += 1
        except Exception as e:
            logger.debug(f"fill skip {f.get('name')}: {e}")

    submitted = False
    fi = form["idx"]
    for sel in [
        f'[data-pw-form-idx="{fi}"] button[type="submit"]',
        f'[data-pw-form-idx="{fi}"] input[type="submit"]',
        f'[data-pw-form-idx="{fi}"] button:has-text("Sign up")',
        f'[data-pw-form-idx="{fi}"] button:has-text("Create")',
        f'[data-pw-form-idx="{fi}"] button:has-text("Register")',
        f'[data-pw-form-idx="{fi}"] button:has-text("Continue")',
        f'[data-pw-form-idx="{fi}"] button:has-text("Next")',
        f'[data-pw-form-idx="{fi}"] button:has-text("Log in")',
        f'[data-pw-form-idx="{fi}"] button:has-text("Login")',
        f'[data-pw-form-idx="{fi}"] button:has-text("Sign in")',
        f'[data-pw-form-idx="{fi}"] button:not(:has-text("Subscribe"))',
        # Fall back to any button on the page that matches auth keywords
        'button:has-text("Create account")',
        'button:has-text("Sign up")',
        'button:has-text("Log in")',
        'button:has-text("Sign in")',
        'div[role="button"]:has-text("Sign up")',
        'div[role="button"]:has-text("Log in")',
    ]:
        try:
            btn = page.locator(sel).first
            if await btn.count() and await btn.is_visible():
                txt = (await btn.inner_text(timeout=2000)).strip().lower()
                if "subscribe" in txt or "newsletter" in txt or "search" in txt:
                    continue
                await btn.click(timeout=ACTION_TIMEOUT_MS, no_wait_after=True)
                submitted = True
                break
        except Exception:
            continue

    if not submitted and filled > 0:
        try:
            await page.keyboard.press("Enter")
            submitted = True
        except Exception:
            pass
    return filled, submitted


async def _find_best_form(page, kind: str) -> dict | None:
    try:
        forms = await page.evaluate(_FORM_SCAN_JS, kind)
    except Exception as e:
        logger.debug(f"form scan error: {e}")
        return None
    if not forms:
        return None
    return forms[0]


async def _page_looks_blocked(page) -> str | None:
    """Return a human reason string if page shows Cloudflare/anti-bot wall,
    else None."""
    try:
        title = (await page.title()) or ""
    except Exception:
        title = ""
    try:
        body = await page.evaluate(
            "document.body ? document.body.innerText.slice(0, 800) : ''"
        )
    except Exception:
        body = ""
    blob = (title + " " + body).lower()
    needles = [
        "attention required",
        "cloudflare",
        "checking your browser",
        "verify you are human",
        "access denied",
        "blocked",
        "captcha",
        "press & hold",
        "are you a robot",
    ]
    for n in needles:
        if n in blob:
            return f"Anti-bot wall detected ({n!r}) — title: {title.strip()[:80]}"
    return None


CANDIDATE_PATHS = {
    "Signup": [
        "/signup", "/register",
        "/account/register", "/customer/account/create",
        "/users/sign_up",
    ],
    "Signin": [
        "/login", "/signin",
        "/account/login", "/customer/account/login",
        "/users/sign_in",
    ],
}

LINK_KEYWORDS = {
    "Signup": ["sign up", "create account", "register", "join now", "create an account", "sign up / sign in"],
    "Signin": ["sign in", "log in", "login", "my account", "sign up / sign in"],
}


async def _try_click_auth_link(page, kind: str) -> bool:
    """Click a visible Sign Up / Login link/button on the current page."""
    for kw in LINK_KEYWORDS[kind]:
        for sel in [
            f'a:text-matches("(?i)^\\s*{re.escape(kw)}\\s*$")',
            f'button:text-matches("(?i)^\\s*{re.escape(kw)}\\s*$")',
            f'a:has-text("{kw}")',
            f'button:has-text("{kw}")',
            f'[role="button"]:has-text("{kw}")',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() and await el.is_visible():
                    await el.click(timeout=ACTION_TIMEOUT_MS, no_wait_after=True)
                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=8000)
                    except Exception:
                        pass
                    await page.wait_for_timeout(1200)
                    return True
            except Exception:
                continue
    return False


async def _navigate_to_real_auth_page(page, base_url: str, kind: str) -> dict | None:
    """Try common URL paths under the same origin. If we find a page with a
    real auth form, stay there and return the form. If none of the paths
    yield an auth form, navigate BACK to base_url so we don't leave the page
    sitting on a 404 from the last candidate path."""
    from urllib.parse import urlsplit, urlunsplit
    parts = urlsplit(base_url)
    origin = urlunsplit((parts.scheme or "https", parts.netloc, "", "", ""))
    for path in CANDIDATE_PATHS[kind]:
        try:
            await page.goto(origin + path, timeout=8000, wait_until="domcontentloaded")
            try:
                await page.wait_for_load_state("networkidle", timeout=2500)
            except Exception:
                pass
            await page.wait_for_timeout(500)
            best = await _find_best_form(page, kind)
            if best and best.get("score", 0) >= 25:
                logger.info(f"  → found auth form at {origin + path}")
                return best
        except Exception as e:
            logger.debug(f"candidate path {path} failed: {e}")
            continue
    # No candidate path worked — restore base_url so the screenshot doesn't
    # show a 404 from the last attempted path.
    try:
        await page.goto(base_url, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
        try:
            await page.wait_for_load_state("networkidle", timeout=3000)
        except Exception:
            pass
        await page.wait_for_timeout(800)
    except Exception:
        pass
    return None


async def _capture_page(browser, platform: str, number: str, url: str, kind: str) -> bytes:
    """Open url in a fresh page, fill the visible form, submit, wait briefly
    for navigation/network to settle, then screenshot the final state."""
    if not url:
        return _placeholder_png(platform, number, kind, "no URL configured for this platform")

    context = await browser.new_context(
        viewport=VIEWPORT,
        user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"),
        ignore_https_errors=True,
        locale="en-US",
    )
    page = await context.new_page()
    try:
        try:
            await page.goto(url, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
        except Exception as e:
            shot = await page.screenshot(full_page=False, timeout=ACTION_TIMEOUT_MS)
            return shot if shot else _placeholder_png(platform, number, kind, f"navigation failed: {e}")

        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        try:
            await page.wait_for_function(
                "document.body && document.body.innerText.trim().length > 30",
                timeout=6000,
            )
        except Exception:
            pass
        await page.wait_for_timeout(1200)

        # Bail early on Cloudflare/anti-bot walls — they will never reveal
        # an auth form, and screenshotting the wall is the most useful proof.
        block_reason = await _page_looks_blocked(page)

        best = await _find_best_form(page, kind) if not block_reason else None
        STRONG = 25

        # If the form on this page doesn't look like a real auth form,
        # try clicking an in-page auth link to reveal one.
        if not block_reason and (not best or best.get("score", 0) < STRONG):
            if await _try_click_auth_link(page, kind):
                better = await _find_best_form(page, kind)
                if better and (not best or better.get("score", 0) > best.get("score", 0)):
                    best = better

        # Still no strong form? Try common auth URL paths under the same origin.
        # _navigate_to_real_auth_page returns the form it found (if any) and
        # leaves the page on that URL, otherwise it restores the original URL.
        if not block_reason and (not best or best.get("score", 0) < STRONG):
            via_path = await _navigate_to_real_auth_page(page, url, kind)
            if via_path:
                best = via_path
            else:
                # We're back on the original URL; re-scan in case the form
                # is a low-score-but-usable form (e.g., Google's email step).
                rescan = await _find_best_form(page, kind)
                if rescan and (not best or rescan.get("score", 0) >= best.get("score", 0)):
                    best = rescan

        if best and best.get("inputCount", 0) > 0:
            logger.info(f"{platform} {kind}: chose form score={best['score']} "
                        f"hasPwd={best.get('hasPassword')} inputs={best.get('inputCount')} "
                        f"url={page.url} text={best.get('text','')[:80]!r}")
            await _fill_chosen_form(page, best, number)
        else:
            if block_reason:
                logger.info(f"{platform} {kind}: blocked — {block_reason}")
            else:
                logger.info(f"{platform} {kind}: no auth form found at {page.url}")

        try:
            await page.wait_for_load_state("networkidle", timeout=6000)
        except Exception:
            pass
        await page.wait_for_timeout(2500)

        try:
            body_len = await page.evaluate("document.body ? document.body.innerText.length : 0")
        except Exception:
            body_len = 0
        try:
            current_url = page.url
        except Exception:
            current_url = url
        try:
            shot = await page.screenshot(full_page=False, timeout=ACTION_TIMEOUT_MS)
        except Exception as e:
            return _placeholder_png(platform, number, kind, f"screenshot failed: {e}")
        if body_len < 5 or len(shot) < 8000:
            return _placeholder_png(
                platform, number, kind,
                f"Page rendered blank — likely anti-bot block from {platform}. "
                f"URL: {current_url}",
            )
        return shot
    finally:
        try:
            await context.close()
        except Exception:
            pass


async def capture_signup_and_signin(platform: str, number: str, browser) -> tuple[bytes, bytes]:
    """Returns (signup_png, signin_png) — final-state screenshots after
    filling and submitting both forms."""
    signup_url = _signup_url(platform)
    signin_url = _signin_url(platform)
    try:
        signup_png = await _capture_page(browser, platform, number, signup_url, "Signup")
    except Exception as e:
        logger.error(f"signup screenshot {platform}/{number}: {e}")
        signup_png = _placeholder_png(platform, number, "Signup", f"{type(e).__name__}: {e}")
    try:
        signin_png = await _capture_page(browser, platform, number, signin_url, "Signin")
    except Exception as e:
        logger.error(f"signin screenshot {platform}/{number}: {e}")
        signin_png = _placeholder_png(platform, number, "Signin", f"{type(e).__name__}: {e}")
    return signup_png, signin_png


class BrowserPool:
    """Single shared Playwright browser kept alive across all checks."""

    def __init__(self):
        self._pw = None
        self._browser = None
        self._lock = asyncio.Lock()

    async def get(self):
        async with self._lock:
            if self._browser is not None:
                return self._browser
            from playwright.async_api import async_playwright
            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(headless=True, args=LAUNCH_ARGS)
            logger.info("Playwright Chromium launched")
            return self._browser

    async def close(self):
        async with self._lock:
            if self._browser:
                try:
                    await self._browser.close()
                except Exception:
                    pass
                self._browser = None
            if self._pw:
                try:
                    await self._pw.stop()
                except Exception:
                    pass
                self._pw = None


browser_pool = BrowserPool()


async def capture_for(platform: str, number: str, timeout: float = 70.0) -> tuple[bytes, bytes]:
    """Wall-clock-capped capture; on timeout returns placeholders."""
    try:
        browser = await browser_pool.get()
    except Exception as e:
        logger.error(f"browser launch error: {e}")
        return (_placeholder_png(platform, number, "Signup", f"browser launch failed: {e}"),
                _placeholder_png(platform, number, "Signin", f"browser launch failed: {e}"))
    try:
        return await asyncio.wait_for(
            capture_signup_and_signin(platform, number, browser),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        return (_placeholder_png(platform, number, "Signup", f"timed out after {timeout}s"),
                _placeholder_png(platform, number, "Signin", f"timed out after {timeout}s"))
    except Exception as e:
        return (_placeholder_png(platform, number, "Signup", f"capture error: {e}"),
                _placeholder_png(platform, number, "Signin", f"capture error: {e}"))
