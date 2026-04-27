import asyncio
import logging
import io
import time
import random
import string
import httpx
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont


_TEMP_MAIL_DOMAINS = [
    "mailinator.com", "guerrillamail.com", "1secmail.com",
    "yopmail.com", "trashmail.com", "tempmail.dev",
]
_FIRST_NAMES = ["Alex", "Sam", "Jordan", "Taylor", "Casey", "Morgan", "Riley",
                "Jamie", "Robin", "Drew", "Avery", "Quinn", "Skyler", "Reese"]
_LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia",
               "Miller", "Davis", "Lopez", "Wilson", "Anderson", "Thomas"]


def random_user_data() -> dict:
    """Return random fake form data — used to satisfy register/login forms
    that require fields beyond the phone number. Email uses a temp-mail domain."""
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    first = random.choice(_FIRST_NAMES)
    last = random.choice(_LAST_NAMES)
    username = f"{first.lower()}{last.lower()}{suffix[:4]}"
    domain = random.choice(_TEMP_MAIL_DOMAINS)
    email = f"{username}@{domain}"
    password = (
        "".join(random.choices(string.ascii_uppercase, k=2))
        + "".join(random.choices(string.ascii_lowercase, k=4))
        + "".join(random.choices(string.digits, k=3))
        + random.choice("!@#$%&*")
    )
    return {
        "first_name": first,
        "last_name": last,
        "full_name": f"{first} {last}",
        "name": f"{first} {last}",
        "username": username,
        "user": username,
        "login": username,
        "email": email,
        "mail": email,
        "password": password,
        "pass": password,
        "passwd": password,
        "dob": "1995-06-15",
        "birthdate": "1995-06-15",
        "gender": "M",
        "country": "US",
    }


def merge_random_fields(payload: dict, fields: list[str] | None = None) -> dict:
    """Merge random user data into payload for the requested form field names
    (only adds keys that aren't already present)."""
    rd = random_user_data()
    keys = fields if fields else list(rd.keys())
    out = dict(payload)
    for k in keys:
        if k not in out and k in rd:
            out[k] = rd[k]
    return out

logger = logging.getLogger(__name__)

PLATFORMS = [
    "Amazon", "Uber", "WhatsApp", "FACEBOOK", "CENTREPOINT", "2SIM-OTP",
    "ITCOTP", "TWVerify", "Zameeli", "TINDER", "Link", "Melbet", "MeApp",
    "AUTHMSG", "Google", "TrackMan", "TikTok", "1xBet", "Authentify",
    "LINE", "AEROFLOT", "16049699289", "Qsms", "Sinch", "SinchVerify",
    "OKru", "Aramex", "MOFA", "METLIFEOMAN", "DARWINBOX", "Amber",
    "KOTAKB", "Cognito", "HOME CENTRE", "14154888349", "github", "Huawei",
    "DFR-Islamic", "67788", "DANUBE", "ChatGPT", "Emirates", "Microsoft",
    "EYEWA", "Snapchat", "Viber", "REDTAG", "Verify", "YESBNK", "Tabby",
    "iATSMS", "HONOR", "Booking", "Secure", "NXCOMM", "CivilDef", "Agoda",
    "Arab Bank", "Instagram", "22670339876", "KALYAN", "GIG GULF",
    "Planity", "Apple", "Shop", "EZVIZ", "SAMSUNG"
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

STATUS_REGISTERED = "registered"
STATUS_NOT_FOUND = "not_found"
STATUS_UNKNOWN = "unknown"
STATUS_ERROR = "error"
STATUS_OTP_SENT = "otp_sent"
STATUS_OTP_FAILED = "otp_failed"

PLATFORM_COLORS = {
    STATUS_REGISTERED: (39, 174, 96),
    STATUS_NOT_FOUND:  (231, 76, 60),
    STATUS_UNKNOWN:    (243, 156, 18),
    STATUS_ERROR:      (127, 140, 141),
    STATUS_OTP_SENT:   (52, 152, 219),
    STATUS_OTP_FAILED: (155, 89, 182),
}

PLATFORM_ICONS = {
    "WhatsApp":    "💬", "FACEBOOK":  "📘", "Instagram":  "📸",
    "Google":      "🔍", "Microsoft": "🪟", "Amazon":     "🛒",
    "Apple":       "🍎", "Snapchat":  "👻", "TikTok":     "🎵",
    "Viber":       "📳", "LINE":      "💚", "Telegram":   "✈️",
    "Uber":        "🚗", "TINDER":    "🔥", "OKru":       "🌐",
    "github":      "🐙", "Booking":   "🏨", "Agoda":      "🏩",
    "Tabby":       "💳", "SAMSUNG":   "📱", "Huawei":     "📲",
    "Melbet":      "🎰", "1xBet":     "🎲", "Emirates":   "✈️",
    "AEROFLOT":    "🛫", "Aramex":    "📦", "ChatGPT":    "🤖",
}


STATUS_LABELS = {
    STATUS_REGISTERED: "✅ REGISTERED",
    STATUS_NOT_FOUND:  "❌ NOT FOUND",
    STATUS_UNKNOWN:    "⚠️ UNKNOWN",
    STATUS_ERROR:      "⛔ ERROR",
    STATUS_OTP_SENT:   "📨 OTP SENT",
    STATUS_OTP_FAILED: "🚫 OTP FAILED",
}


def _load_fonts():
    try:
        return (
            ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 26),
            ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18),
            ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16),
            ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14),
            ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 16),
        )
    except Exception:
        f = ImageFont.load_default()
        return f, f, f, f, f


def make_result_card(
    platform: str,
    number: str,
    final_status: str,
    signup_status: str,
    signup_msg: str,
    signin_status: str,
    signin_msg: str,
    url: str = "",
) -> bytes:
    """Combined signup + signin result card."""
    W, H = 980, 440
    bg = (18, 18, 24)
    accent = PLATFORM_COLORS.get(final_status, (127, 140, 141))
    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)

    draw.rectangle([(0, 0), (8, H)], fill=accent)
    draw.rectangle([(0, 0), (W, H)], outline=(40, 40, 52), width=2)

    f_big, f_med, f_small, f_xs, f_mono = _load_fonts()

    icon = PLATFORM_ICONS.get(platform, "🌐")
    draw.text((28, 20), f"{icon}  {platform}", font=f_big, fill=(255, 255, 255))

    final_label = STATUS_LABELS.get(final_status, "⚠️ UNKNOWN")
    draw.rectangle([(W - 250, 18), (W - 20, 58)], fill=accent)
    draw.text((W - 240, 28), final_label, font=f_small, fill=(255, 255, 255))

    draw.line([(20, 70), (W - 20, 70)], fill=(50, 50, 65), width=1)
    draw.text((20, 84), "📞  Number:", font=f_small, fill=(150, 150, 180))
    draw.text((150, 82), f"+{number}", font=f_mono, fill=(100, 220, 255))

    def _section(title, status, msg, y):
        sec_color = PLATFORM_COLORS.get(status, (127, 140, 141))
        draw.rectangle([(20, y), (W - 20, y + 110)], fill=(28, 28, 38), outline=(50, 50, 65), width=1)
        draw.rectangle([(20, y), (24, y + 110)], fill=sec_color)
        draw.text((40, y + 8), title, font=f_med, fill=(220, 220, 220))
        sl = STATUS_LABELS.get(status, "⚠️ UNKNOWN")
        draw.rectangle([(W - 230, y + 6), (W - 30, y + 38)], fill=sec_color)
        draw.text((W - 222, y + 12), sl, font=f_xs, fill=(255, 255, 255))
        line1 = (msg or "")[:95]
        line2 = (msg or "")[95:190]
        draw.text((40, y + 44), line1, font=f_small, fill=(230, 230, 230))
        if line2:
            draw.text((40, y + 70), line2, font=f_small, fill=(200, 200, 200))

    _section("📝  SIGNUP attempt", signup_status, signup_msg, 118)
    _section("🔑  SIGNIN attempt", signin_status, signin_msg, 240)

    if url:
        draw.text((20, 372), "🔗", font=f_small, fill=(150, 150, 180))
        draw.text((46, 372), url[:110], font=f_small, fill=(100, 160, 255))

    ts = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    draw.text((20, 410), f"🕐  {ts}", font=f_xs, fill=(90, 90, 110))

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf.read()


async def _fetch(client: httpx.AsyncClient, method: str, url: str, retries: int = 1, timeout: float = 8.0, **kwargs):
    last_err = None
    for attempt in range(retries + 1):
        try:
            r = await client.request(method, url, timeout=timeout, follow_redirects=True, **kwargs)
            return r
        except Exception as e:
            last_err = e
            logger.debug(f"Fetch error {url} (attempt {attempt + 1}/{retries + 1}): {e}")
            if attempt < retries:
                await asyncio.sleep(0.5)
    logger.debug(f"Fetch failed {url} after {retries + 1} attempts: {last_err}")
    return None


def _text_of(html: str) -> str:
    try:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        return " ".join(soup.get_text(" ", strip=True).split())[:500]
    except Exception:
        return html[:300]


async def check_google(number: str) -> tuple[str, str, str]:
    url = "https://accounts.google.com/signin/v2/identifier"
    async with httpx.AsyncClient(headers=HEADERS, verify=False) as client:
        r = await _fetch(client, "GET", url)
        if not r:
            return STATUS_ERROR, "Could not reach Google", url

        data = {
            "continue": "https://www.google.com/",
            "flowName": "GlifWebSignIn",
            "flowEntry": "ServiceLogin",
            "identifier": f"+{number}",
        }
        r2 = await _fetch(client, "POST", url, data=data)
        if not r2:
            return STATUS_ERROR, "No response from Google", url

        body = _text_of(r2.text)
        if any(k in r2.text.lower() for k in ["couldn't find", "no account", "find your google account", "create account"]):
            return STATUS_NOT_FOUND, "Google: No account found for this number", url
        elif any(k in r2.text.lower() for k in ["enter your password", "welcome", "password", "next"]):
            return STATUS_REGISTERED, "Google: Account exists — prompted for password", url
        elif "verify" in r2.text.lower() or "phone" in r2.text.lower():
            return STATUS_UNKNOWN, "Google: Verification step encountered", url
        return STATUS_UNKNOWN, f"Google: {body[:120]}", url


async def check_facebook(number: str) -> tuple[str, str, str]:
    url = "https://www.facebook.com/"
    login_url = "https://www.facebook.com/login/identify/"
    async with httpx.AsyncClient(headers=HEADERS, verify=False) as client:
        r = await _fetch(client, "GET", url)
        if not r:
            return STATUS_ERROR, "Could not reach Facebook", url

        soup = BeautifulSoup(r.text, "html.parser")
        lsd = soup.find("input", {"name": "lsd"})
        lsd_val = lsd["value"] if lsd else ""

        rd = random_user_data()
        data = {
            "lsd": lsd_val,
            "email": f"+{number}",
            "pass": rd["password"],
            "login": "Log In",
            "persistent_ok": "1",
        }
        r2 = await _fetch(client, "POST", "https://www.facebook.com/login.php?login_attempt=1", data=data)
        if not r2:
            return STATUS_ERROR, "No response from Facebook", url

        body = _text_of(r2.text)
        if any(k in r2.text.lower() for k in ["the password you", "enter the password", "wrong password"]):
            return STATUS_REGISTERED, "Facebook: Account found — password prompt received", url
        elif any(k in r2.text.lower() for k in ["find your account", "find your facebook account"]):
            data2 = {"lsd": lsd_val, "query": f"+{number}", "action": "search"}
            r3 = await _fetch(client, "POST", login_url, data=data2)
            if r3 and "reset" in r3.text.lower():
                return STATUS_REGISTERED, "Facebook: Account located by phone number", url
            return STATUS_NOT_FOUND, "Facebook: No account linked to this number", url
        elif any(k in r2.text.lower() for k in ["incorrect password", "the email address"]):
            return STATUS_REGISTERED, "Facebook: Account found", url
        return STATUS_UNKNOWN, f"Facebook: {body[:120]}", url


async def check_whatsapp(number: str) -> tuple[str, str, str]:
    url = f"https://wa.me/+{number}"
    async with httpx.AsyncClient(headers=HEADERS, verify=False) as client:
        r = await _fetch(client, "GET", url)
        if not r:
            return STATUS_ERROR, "Could not reach WhatsApp", url
        body = _text_of(r.text)
        if any(k in r.text.lower() for k in ["open whatsapp", "send message", "chat with"]):
            return STATUS_REGISTERED, "WhatsApp: Number is active on WhatsApp", url
        elif any(k in r.text.lower() for k in ["invalid", "not found", "error"]):
            return STATUS_NOT_FOUND, "WhatsApp: Number not found on WhatsApp", url
        return STATUS_UNKNOWN, f"WhatsApp: {body[:120]}", url


async def check_instagram(number: str) -> tuple[str, str, str]:
    url = "https://www.instagram.com/accounts/login/"
    async with httpx.AsyncClient(headers=HEADERS, verify=False) as client:
        r = await _fetch(client, "GET", url)
        if not r:
            return STATUS_ERROR, "Could not reach Instagram", url

        soup = BeautifulSoup(r.text, "html.parser")
        csrf = r.cookies.get("csrftoken", "")

        h = {**HEADERS, "X-CSRFToken": csrf, "Referer": url, "X-Requested-With": "XMLHttpRequest"}
        data = {"username": f"+{number}", "enc_password": "#PWD_INSTAGRAM:0:0:password", "queryParams": {}, "optIntoOneTap": "false"}
        r2 = await _fetch(client, "POST", "https://www.instagram.com/api/v1/web/accounts/login/ajax/", data=data, headers=h)
        if not r2:
            return STATUS_UNKNOWN, "Instagram: Could not complete check", url

        body = r2.text.lower()
        if "checkpoint" in body or "two_factor_required" in body:
            return STATUS_REGISTERED, "Instagram: Account found — security checkpoint triggered", url
        elif "user" in body and "authenticated" in body:
            return STATUS_REGISTERED, "Instagram: Account authenticated", url
        elif "invalid_user" in body or "no_valid" in body or "doesn't exist" in body:
            return STATUS_NOT_FOUND, "Instagram: No account found for this number", url
        return STATUS_UNKNOWN, f"Instagram: {body[:120]}", url


async def check_microsoft(number: str) -> tuple[str, str, str]:
    url = "https://login.live.com/login.srf"
    async with httpx.AsyncClient(headers=HEADERS, verify=False) as client:
        r = await _fetch(client, "GET", url)
        if not r:
            return STATUS_ERROR, "Could not reach Microsoft", url

        rd = random_user_data()
        data = {
            "login": f"+{number}",
            "passwd": rd["password"],
            "KMSI": "1",
        }
        r2 = await _fetch(client, "POST", url, data=data)
        if not r2:
            return STATUS_ERROR, "No response from Microsoft", url

        body = _text_of(r2.text)
        if any(k in r2.text.lower() for k in ["enter your password", "enter password", "create a password"]):
            return STATUS_REGISTERED, "Microsoft: Account found — password prompt received", url
        elif any(k in r2.text.lower() for k in ["that microsoft account doesn't exist", "no account", "create one"]):
            return STATUS_NOT_FOUND, "Microsoft: No account found for this number", url
        return STATUS_UNKNOWN, f"Microsoft: {body[:120]}", url


async def check_amazon(number: str) -> tuple[str, str, str]:
    url = "https://www.amazon.com/ap/signin"
    async with httpx.AsyncClient(headers=HEADERS, verify=False) as client:
        r = await _fetch(client, "GET", url)
        if not r:
            return STATUS_ERROR, "Could not reach Amazon", url

        soup = BeautifulSoup(r.text, "html.parser")
        metadata = {}
        for inp in soup.find_all("input", {"type": "hidden"}):
            if inp.get("name"):
                metadata[inp["name"]] = inp.get("value", "")
        rd = random_user_data()
        metadata["email"] = f"+{number}"
        metadata["password"] = rd["password"]
        metadata["continue"] = "https://www.amazon.com/"
        metadata["action"] = "sign-in"

        r2 = await _fetch(client, "POST", url, data=metadata)
        if not r2:
            return STATUS_ERROR, "No response from Amazon", url

        body = _text_of(r2.text)
        if any(k in r2.text.lower() for k in ["enter your password", "say hi"]):
            return STATUS_REGISTERED, "Amazon: Account found — password prompt received", url
        elif any(k in r2.text.lower() for k in ["we cannot find", "no account", "cannot find account"]):
            return STATUS_NOT_FOUND, "Amazon: No account found for this number", url
        return STATUS_UNKNOWN, f"Amazon: {body[:120]}", url


async def check_uber(number: str) -> tuple[str, str, str]:
    url = "https://auth.uber.com/v2/"
    api_url = "https://auth.uber.com/v2/phone"
    async with httpx.AsyncClient(headers=HEADERS, verify=False) as client:
        h = {**HEADERS, "Content-Type": "application/json"}
        r = await _fetch(client, "POST", api_url,
                         json={"phone_number": f"+{number}"},
                         headers=h)
        if not r:
            return STATUS_ERROR, "Could not reach Uber", url
        body = r.text.lower()
        if any(k in body for k in ["password", "otp", "verification", "existing"]):
            return STATUS_REGISTERED, "Uber: Account found for this number", url
        elif any(k in body for k in ["not found", "no account", "sign up", "create"]):
            return STATUS_NOT_FOUND, "Uber: No Uber account found", url
        return STATUS_UNKNOWN, f"Uber: {body[:120]}", url


async def check_snapchat(number: str) -> tuple[str, str, str]:
    url = "https://accounts.snapchat.com/accounts/login"
    async with httpx.AsyncClient(headers=HEADERS, verify=False) as client:
        r = await _fetch(client, "GET", url)
        if not r:
            return STATUS_ERROR, "Could not reach Snapchat", url
        body = _text_of(r.text)
        return STATUS_UNKNOWN, f"Snapchat: Login page reached — manual verification required", url


async def check_tiktok(number: str) -> tuple[str, str, str]:
    url = "https://www.tiktok.com/passport/app/check_email/"
    async with httpx.AsyncClient(headers=HEADERS, verify=False) as client:
        r = await _fetch(client, "POST", url,
                         json={"mobile": f"+{number}"},
                         headers={**HEADERS, "Content-Type": "application/json"})
        if not r:
            return STATUS_UNKNOWN, "TikTok: Could not complete check", "https://www.tiktok.com"
        body = r.text.lower()
        if "registered" in body or "exist" in body or "password" in body:
            return STATUS_REGISTERED, "TikTok: Number is registered", "https://www.tiktok.com"
        elif "not registered" in body or "not exist" in body:
            return STATUS_NOT_FOUND, "TikTok: Number not registered", "https://www.tiktok.com"
        return STATUS_UNKNOWN, f"TikTok: {r.text[:120]}", "https://www.tiktok.com"


async def check_apple(number: str) -> tuple[str, str, str]:
    url = "https://appleid.apple.com/auth/verify/phone"
    async with httpx.AsyncClient(headers=HEADERS, verify=False) as client:
        h = {**HEADERS, "Content-Type": "application/json", "Origin": "https://appleid.apple.com"}
        r = await _fetch(client, "POST", url,
                         json={"phoneNumber": f"+{number}"},
                         headers=h)
        if r and r.status_code == 200:
            return STATUS_REGISTERED, "Apple: Apple ID linked to this number", url
        elif r and r.status_code in (404, 400):
            return STATUS_NOT_FOUND, "Apple: No Apple ID found for this number", url
        r2 = await _fetch(client, "GET", "https://appleid.apple.com/")
        return STATUS_UNKNOWN, "Apple: Could not verify — manual check recommended", "https://appleid.apple.com"


async def check_github(number: str) -> tuple[str, str, str]:
    url = "https://github.com/login"
    async with httpx.AsyncClient(headers=HEADERS, verify=False) as client:
        r = await _fetch(client, "GET", url)
        if not r:
            return STATUS_ERROR, "Could not reach GitHub", url

        soup = BeautifulSoup(r.text, "html.parser")
        csrf = soup.find("input", {"name": "authenticity_token"})
        csrf_val = csrf["value"] if csrf else ""

        rd = random_user_data()
        data = {
            "login": f"+{number}",
            "password": rd["password"],
            "authenticity_token": csrf_val,
            "commit": "Sign in",
        }
        r2 = await _fetch(client, "POST", url, data=data)
        if not r2:
            return STATUS_ERROR, "No response from GitHub", url

        body = _text_of(r2.text)
        if any(k in r2.text.lower() for k in ["incorrect username", "two-factor", "wrong password"]):
            return STATUS_REGISTERED, "GitHub: Account found — incorrect password response", url
        elif any(k in r2.text.lower() for k in ["username or email", "sign in to"]):
            return STATUS_NOT_FOUND, "GitHub: No account found for this number", url
        return STATUS_UNKNOWN, f"GitHub: {body[:120]}", url


async def check_booking(number: str) -> tuple[str, str, str]:
    url = "https://account.booking.com/sign-in"
    async with httpx.AsyncClient(headers=HEADERS, verify=False) as client:
        r = await _fetch(client, "GET", url)
        if not r:
            return STATUS_ERROR, "Could not reach Booking.com", url

        rd = random_user_data()
        data = {"username": f"+{number}", "loginname": f"+{number}", "password": rd["password"]}
        r2 = await _fetch(client, "POST", url, data=data)
        if not r2:
            return STATUS_UNKNOWN, "Booking.com: Could not complete check", url

        body = _text_of(r2.text)
        if any(k in r2.text.lower() for k in ["enter your password", "password", "welcome"]):
            return STATUS_REGISTERED, "Booking.com: Account found", url
        elif any(k in r2.text.lower() for k in ["no account", "sign up", "not found"]):
            return STATUS_NOT_FOUND, "Booking.com: No account found", url
        return STATUS_UNKNOWN, f"Booking.com: {body[:120]}", url


async def check_okru(number: str) -> tuple[str, str, str]:
    url = "https://ok.ru/dk?cmd=AnonymLogin&st.cmd=AnonymLogin"
    async with httpx.AsyncClient(headers=HEADERS, verify=False) as client:
        r = await _fetch(client, "GET", "https://ok.ru/")
        if not r:
            return STATUS_ERROR, "Could not reach OK.ru", "https://ok.ru"

        rd = random_user_data()
        data = {"st.email": f"+{number}", "st.password": rd["password"], "button_login": "Sign+in"}
        r2 = await _fetch(client, "POST", url, data=data)
        if not r2:
            return STATUS_UNKNOWN, "OK.ru: Could not complete check", "https://ok.ru"

        body = r2.text.lower()
        if any(k in body for k in ["wrong password", "enter password", "incorrect password"]):
            return STATUS_REGISTERED, "OK.ru: Account found for this number", "https://ok.ru"
        elif any(k in body for k in ["not registered", "no such", "sign up"]):
            return STATUS_NOT_FOUND, "OK.ru: No account found", "https://ok.ru"
        return STATUS_UNKNOWN, f"OK.ru: {body[:120]}", "https://ok.ru"


async def check_viber(number: str) -> tuple[str, str, str]:
    url = "https://www.viber.com/"
    return STATUS_UNKNOWN, "Viber: App-based verification — number submitted to Viber registry", url


async def check_telegram(number: str) -> tuple[str, str, str]:
    url = f"https://t.me/+{number}"
    async with httpx.AsyncClient(headers=HEADERS, verify=False) as client:
        r = await _fetch(client, "GET", url)
        if not r:
            return STATUS_ERROR, "Could not reach Telegram", url
        body = _text_of(r.text)
        if any(k in r.text.lower() for k in ["open telegram", "t.me", "view in telegram"]):
            return STATUS_REGISTERED, "Telegram: Number appears active on Telegram", url
        return STATUS_UNKNOWN, f"Telegram: {body[:120]}", url


async def check_samsung(number: str) -> tuple[str, str, str]:
    url = "https://account.samsung.com/"
    async with httpx.AsyncClient(headers=HEADERS, verify=False) as client:
        r = await _fetch(client, "GET", url)
        if not r:
            return STATUS_ERROR, "Could not reach Samsung", url
        body = _text_of(r.text)
        return STATUS_UNKNOWN, f"Samsung: Login page reached — {body[:100]}", url


async def check_generic(platform: str, url: str, number: str) -> tuple[str, str, str]:
    async with httpx.AsyncClient(headers=HEADERS, verify=False) as client:
        from urllib.parse import urljoin

        r = await _fetch(client, "GET", url)
        if not r:
            return STATUS_ERROR, f"{platform}: Could not reach site", url

        rd = random_user_data()
        login_url = url
        login_form = None

        try:
            soup = BeautifulSoup(r.text, "html.parser")
            for f in soup.find_all("form"):
                inputs = f.find_all("input")
                names = [(i.get("name", "") + " " + i.get("id", "")).lower() for i in inputs]
                types = [i.get("type", "").lower() for i in inputs]
                if "password" in types or any(k in " ".join(names) for k in ("phone", "mobile", "email", "username", "login")):
                    login_form = f
                    break
        except Exception as e:
            logger.debug(f"check_generic parse error {platform}: {e}")

        if not login_form:
            for path in ("/login", "/signin", "/sign-in", "/account/login", "/auth/login", "/users/sign_in"):
                cand = urljoin(url, path)
                rr = await _fetch(client, "GET", cand, retries=0, timeout=5.0)
                if not rr or rr.status_code >= 400:
                    continue
                soup = BeautifulSoup(rr.text, "html.parser")
                for f in soup.find_all("form"):
                    inputs = f.find_all("input")
                    types = [i.get("type", "").lower() for i in inputs]
                    if "password" in types:
                        login_form = f
                        login_url = cand
                        break
                if login_form:
                    break

        if not login_form:
            body = _text_of(r.text)
            return STATUS_UNKNOWN, f"{platform}: Site reached — {body[:100]}", url

        action = urljoin(login_url, login_form.get("action") or login_url)
        method = (login_form.get("method") or "POST").upper()
        payload = _fill_form_fields(login_form, number, rd)
        h = {**HEADERS, "Referer": login_url, "Origin": "/".join(login_url.split("/", 3)[:3])}
        r2 = await _fetch(client, method, action, data=payload, headers=h, retries=1, timeout=10.0)
        if not r2:
            return STATUS_UNKNOWN, f"{platform}: Login form found but POST returned no response", login_url

        bl = r2.text.lower()
        body2 = _text_of(r2.text)[:80]
        tag = f"HTTP {r2.status_code}"
        if any(k in bl for k in ("password is incorrect", "wrong password", "invalid password",
                                 "incorrect password", "two-factor", "verification code")):
            return STATUS_REGISTERED, f"{platform}: account exists — password challenge ({tag})", login_url
        if any(k in bl for k in ("no account", "not registered", "no user", "user not found",
                                 "doesn't exist", "couldn't find your account", "we cannot find")):
            return STATUS_NOT_FOUND, f"{platform}: No account found ({tag})", login_url
        if any(k in bl for k in ("captcha", "are you human", "unusual activity")):
            return STATUS_UNKNOWN, f"{platform}: CAPTCHA wall ({tag})", login_url
        return STATUS_UNKNOWN, f"{platform}: Form posted — {body2} ({tag})", login_url


PLATFORM_CHECKERS = {
    "WhatsApp":  check_whatsapp,
    "Telegram":  check_telegram,
    "FACEBOOK":  check_facebook,
    "Instagram": check_instagram,
    "Microsoft": check_microsoft,
    "Google":    check_google,
    "Amazon":    check_amazon,
    "Apple":     check_apple,
    "github":    check_github,
    "Uber":      check_uber,
    "Snapchat":  check_snapchat,
    "TikTok":    check_tiktok,
    "Viber":     check_viber,
    "Booking":   check_booking,
    "OKru":      check_okru,
    "SAMSUNG":   check_samsung,
}

GENERIC_PLATFORM_URLS = {
    "CENTREPOINT": "https://www.centrepoint.com/en-ae/login",
    "2SIM-OTP":    "https://2sim.net/",
    "ITCOTP":      "https://itc.sa/",
    "TWVerify":    "https://www.twilio.com/en-us/verify",
    "Zameeli":     "https://zameeli.com/",
    "Link":        "https://link.com/",
    "MeApp":       "https://meapp.com.sa/",
    "AUTHMSG":     "https://www.twilio.com/en-us/verify",
    "TrackMan":    "https://www.trackman.com/",
    "Authentify":  "https://www.authentify.com/",
    "Melbet":      "https://melbet.com/",
    "1xBet":       "https://1xbet.com/",
    "AEROFLOT":    "https://www.aeroflot.ru/ru-en",
    "Emirates":    "https://www.emirates.com/english/",
    "Aramex":      "https://www.aramex.com/",
    "MOFA":        "https://www.mofa.gov.sa/",
    "METLIFEOMAN": "https://www.metlife.com.om/",
    "Amber":       "https://amberapp.com/",
    "KOTAKB":      "https://www.kotak.com/",
    "Cognito":     "https://cognitoforms.com/",
    "HOME CENTRE": "https://www.homecentre.com/",
    "DANUBE":      "https://www.danubegroup.com/customer/account/login/",
    "ChatGPT":     "https://chat.openai.com/",
    "EYEWA":       "https://www.eyewa.com/",
    "REDTAG":      "https://www.redtag.com/",
    "Verify":      "https://www.twilio.com/en-us/verify",
    "YESBNK":      "https://www.yesbank.in/",
    "iATSMS":      "https://www.iat.net/",
    "HONOR":       "https://www.hihonor.com/",
    "Agoda":       "https://www.agoda.com/",
    "Secure":      "https://secure.com/",
    "NXCOMM":      "https://nxcomm.com/",
    "CivilDef":    "https://www.dcd.gov.ae/en/Pages/default.aspx",
    "DARWINBOX":   "https://darwinbox.com/",
    "KALYAN":      "https://www.kalyanjewellers.net/",
    "GIG GULF":    "https://www.giggulf.com/",
    "Qsms":        "https://qsms.com/",
    "Sinch":       "https://sinch.com/",
    "SinchVerify": "https://sinch.com/products/verification/",
    "Shop":        "https://shop.app/",
    "EZVIZ":       "https://www.ezviz.com/",
    "Tabby":       "https://tabby.ai/",
    "Planity":     "https://www.planity.com/",
    "Arab Bank":   "https://www.arabbank.com/",
    "Huawei":      "https://id.huawei.com/",
    "LINE":        "https://line.me/en/",
    "TINDER":      "https://tinder.com/",
    "16049699289": "https://www.google.com/",
    "22670339876": "https://www.facebook.com/",
    "14154888349": "https://www.apple.com/",
    "67788":       "https://www.samsung.com/",
    "DFR-Islamic": "https://www.dfr.gov.ae/",
}


def _http_tag(r) -> str:
    if r is None:
        return "no-response"
    return f"HTTP {r.status_code}"


async def signup_google(number: str) -> tuple[str, str]:
    url = "https://accounts.google.com/signup/v2/createaccount"
    async with httpx.AsyncClient(headers=HEADERS, verify=False) as client:
        rd = random_user_data()
        data = {
            "FirstName": rd["first_name"], "LastName": rd["last_name"],
            "GmailAddress": rd["username"], "Passwd": rd["password"],
            "PasswdAgain": rd["password"], "RecoveryPhoneNumber": f"+{number}",
            "flowName": "GlifWebSignIn", "flowEntry": "SignUp",
        }
        r = await _fetch(client, "POST", url, data=data)
        if not r:
            return STATUS_OTP_FAILED, "Google signup: no response"
        body = r.text.lower()
        if "phone number" in body and ("already" in body or "in use" in body or "associated" in body):
            return STATUS_REGISTERED, f"Google signup: phone already in use ({_http_tag(r)})"
        if "verify" in body or "verification" in body or "send code" in body:
            return STATUS_OTP_SENT, f"Google signup: verification step reached ({_http_tag(r)})"
        if "captcha" in body or "unusual" in body:
            return STATUS_OTP_FAILED, f"Google signup: CAPTCHA blocked ({_http_tag(r)})"
        return STATUS_OTP_FAILED, f"Google signup: blocked ({_http_tag(r)})"


async def signup_microsoft(number: str) -> tuple[str, str]:
    cred_url = "https://login.microsoftonline.com/common/GetCredentialType"
    async with httpx.AsyncClient(headers=HEADERS, verify=False) as client:
        h = {**HEADERS, "Content-Type": "application/json", "Accept": "application/json"}
        r = await _fetch(client, "POST", cred_url,
                         json={"username": f"+{number}", "isOtherIdpSupported": True},
                         headers=h)
        if r and r.status_code == 200:
            try:
                j = r.json()
                ier = j.get("IfExistsResult")
                if ier == 0:
                    return STATUS_REGISTERED, f"Microsoft: account exists for this number (IfExistsResult=0)"
                if ier == 1:
                    return STATUS_OTP_SENT, f"Microsoft: number free — signup possible (IfExistsResult=1)"
                if ier == 5:
                    return STATUS_REGISTERED, f"Microsoft: federated account exists (IfExistsResult=5)"
                if ier == 6:
                    return STATUS_REGISTERED, f"Microsoft: account exists in other IDP (IfExistsResult=6)"
                return STATUS_UNKNOWN, f"Microsoft: IfExistsResult={ier}"
            except Exception as e:
                return STATUS_UNKNOWN, f"Microsoft: parse error {e}"
        return STATUS_OTP_FAILED, f"Microsoft signup: GetCredentialType {_http_tag(r)}"


async def signup_apple(number: str) -> tuple[str, str]:
    url = "https://idmsa.apple.com/appleauth/auth/verify/phone/securitycode"
    async with httpx.AsyncClient(headers=HEADERS, verify=False) as client:
        h = {**HEADERS, "Content-Type": "application/json",
             "Origin": "https://appleid.apple.com",
             "Referer": "https://appleid.apple.com/",
             "X-Apple-Widget-Key": "d39ba9916480847e6a3d3d0e9be6c6c5"}
        payload = {"phoneNumber": {"number": f"+{number}", "countryCode": "US"}, "mode": "sms"}
        r = await _fetch(client, "PUT", url, json=payload, headers=h)
        if not r:
            return STATUS_OTP_FAILED, "Apple signup: no response"
        body = r.text.lower()
        if r.status_code == 200:
            return STATUS_OTP_SENT, f"Apple: SMS verification code sent ({_http_tag(r)})"
        if "already" in body or "in use" in body or "associated" in body:
            return STATUS_REGISTERED, f"Apple: phone already linked ({_http_tag(r)})"
        if r.status_code == 401:
            return STATUS_OTP_FAILED, f"Apple: requires session ({_http_tag(r)})"
        return STATUS_OTP_FAILED, f"Apple signup: blocked ({_http_tag(r)})"


async def signup_instagram(number: str) -> tuple[str, str]:
    url = "https://www.instagram.com/api/v1/accounts/send_signup_sms_code/"
    async with httpx.AsyncClient(headers=HEADERS, verify=False) as client:
        await _fetch(client, "GET", "https://www.instagram.com/accounts/emailsignup/")
        csrf = client.cookies.get("csrftoken", "")
        h = {**HEADERS, "X-CSRFToken": csrf,
             "X-IG-App-ID": "936619743392459",
             "X-Requested-With": "XMLHttpRequest",
             "Referer": "https://www.instagram.com/accounts/emailsignup/",
             "Origin": "https://www.instagram.com"}
        rd = random_user_data()
        data = {"phone_number": f"+{number}", "phone_id": rd["username"], "client_id": rd["username"]}
        r = await _fetch(client, "POST", url, data=data, headers=h)
        if not r:
            return STATUS_OTP_FAILED, "Instagram signup: no response"
        body = r.text.lower()
        if "sent" in body or '"status":"ok"' in body or '"status": "ok"' in body:
            return STATUS_OTP_SENT, f"Instagram: SMS signup code sent ({_http_tag(r)})"
        if "already" in body and ("phone" in body or "registered" in body):
            return STATUS_REGISTERED, f"Instagram: phone already registered ({_http_tag(r)})"
        if "checkpoint" in body or "rate" in body or "blocked" in body:
            return STATUS_OTP_FAILED, f"Instagram: checkpoint/rate-limit ({_http_tag(r)})"
        return STATUS_OTP_FAILED, f"Instagram signup: blocked ({_http_tag(r)})"


async def signup_tiktok(number: str) -> tuple[str, str]:
    url = ("https://www.tiktok.com/passport/mobile/sms_login_send_code/"
           "?aid=1988&app_name=tiktok_web&device_id=0&iid=0")
    async with httpx.AsyncClient(headers=HEADERS, verify=False) as client:
        h = {**HEADERS, "Content-Type": "application/x-www-form-urlencoded",
             "Referer": "https://www.tiktok.com/login/phone-or-email/phone",
             "Origin": "https://www.tiktok.com"}
        r = await _fetch(client, "POST", url, data={"mobile": f"+{number}", "type": "1"}, headers=h)
        if not r:
            return STATUS_OTP_FAILED, "TikTok signup: no response"
        body = r.text.lower()
        if r.status_code == 200 and ('"message":"success"' in body or "verify_ticket" in body):
            return STATUS_OTP_SENT, f"TikTok: SMS code sent ({_http_tag(r)})"
        if "already" in body or "registered" in body:
            return STATUS_REGISTERED, f"TikTok: number already registered ({_http_tag(r)})"
        return STATUS_OTP_FAILED, f"TikTok signup: blocked ({_http_tag(r)})"


async def signup_facebook(number: str) -> tuple[str, str]:
    url = "https://m.facebook.com/reg/submit/"
    async with httpx.AsyncClient(headers=HEADERS, verify=False) as client:
        await _fetch(client, "GET", "https://m.facebook.com/reg/")
        rd = random_user_data()
        data = {
            "firstname": rd["first_name"], "lastname": rd["last_name"],
            "reg_email__": f"+{number}", "reg_passwd__": rd["password"],
            "birthday_day": "15", "birthday_month": "6", "birthday_year": "1995",
            "sex": "1", "submit": "Sign Up",
        }
        r = await _fetch(client, "POST", url, data=data)
        if not r:
            return STATUS_OTP_FAILED, "Facebook signup: no response"
        body = r.text.lower()
        if "already" in body and ("account" in body or "registered" in body):
            return STATUS_REGISTERED, f"Facebook: phone already has an account ({_http_tag(r)})"
        if "confirm" in body or "code" in body or "sms" in body:
            return STATUS_OTP_SENT, f"Facebook: SMS confirmation step reached ({_http_tag(r)})"
        return STATUS_OTP_FAILED, f"Facebook signup: blocked ({_http_tag(r)})"


async def signup_whatsapp(number: str) -> tuple[str, str]:
    url = f"https://v.whatsapp.net/v2/exist?cc={number[:2]}&in={number[2:]}"
    async with httpx.AsyncClient(headers=HEADERS, verify=False) as client:
        r = await _fetch(client, "GET", url)
        if not r:
            return STATUS_OTP_FAILED, "WhatsApp: no response from registration server"
        body = r.text.lower()
        if "ok" in body or "status=\"ok\"" in body:
            return STATUS_REGISTERED, f"WhatsApp: number is registered ({_http_tag(r)})"
        if "fail" in body or "not_found" in body:
            return STATUS_OTP_SENT, f"WhatsApp: number free — signup possible ({_http_tag(r)})"
        return STATUS_OTP_FAILED, f"WhatsApp: ambiguous response ({_http_tag(r)})"


async def signup_telegram(number: str) -> tuple[str, str]:
    return STATUS_OTP_FAILED, "Telegram: signup requires MTProto API (not HTTP)"


async def signup_uber(number: str) -> tuple[str, str]:
    url = "https://auth.uber.com/v2/"
    async with httpx.AsyncClient(headers=HEADERS, verify=False) as client:
        h = {**HEADERS, "Content-Type": "application/json"}
        r = await _fetch(client, "POST", url, json={"phoneNumber": f"+{number}", "type": "PHONE_NUMBER"}, headers=h)
        if not r:
            return STATUS_OTP_FAILED, "Uber signup: no response"
        body = r.text.lower()
        if r.status_code == 200 and ("otp" in body or "verification" in body or "code" in body):
            return STATUS_OTP_SENT, f"Uber: verification code requested ({_http_tag(r)})"
        if "exists" in body or "already" in body:
            return STATUS_REGISTERED, f"Uber: account exists ({_http_tag(r)})"
        return STATUS_OTP_FAILED, f"Uber signup: blocked ({_http_tag(r)})"


def _fill_form_fields(form, number: str, rd: dict) -> dict:
    """Walk every input/select/textarea in a form and populate sensible values
    so the server gets a valid registration / login submission."""
    payload = {}
    for inp in form.find_all(["input", "select", "textarea"]):
        name = inp.get("name")
        if not name:
            continue
        t = (inp.get("type") or inp.name or "text").lower()
        val = inp.get("value", "")
        nl = name.lower()

        if t in ("submit", "button", "image"):
            payload[name] = val or "Submit"
            continue
        if t == "hidden":
            payload[name] = val
            continue
        if t == "checkbox" or "agree" in nl or "terms" in nl or "tos" in nl or "consent" in nl or "newsletter" in nl:
            payload[name] = inp.get("value", "on") or "on"
            continue
        if t == "radio":
            payload[name] = val or "1"
            continue
        if t == "select" or inp.name == "select":
            opt = inp.find("option", selected=True) or inp.find("option")
            payload[name] = opt.get("value", "") if opt else ""
            continue

        if "phone" in nl or "mobile" in nl or "tel" in nl or t == "tel" or "msisdn" in nl or "whatsapp" in nl:
            payload[name] = f"+{number}"
        elif "email" in nl or "mail" in nl or t == "email":
            payload[name] = rd["email"]
        elif "first" in nl or "fname" in nl or "given" in nl:
            payload[name] = rd["first_name"]
        elif "last" in nl or "lname" in nl or "surname" in nl or "family" in nl:
            payload[name] = rd["last_name"]
        elif "user" in nl or "login" in nl or "handle" in nl or "nick" in nl or "screen" in nl:
            payload[name] = rd["username"]
        elif nl == "name" or "fullname" in nl or "displayname" in nl or "real" in nl:
            payload[name] = rd["full_name"]
        elif "confirm" in nl and "pass" in nl:
            payload[name] = rd["password"]
        elif "pass" in nl or t == "password":
            payload[name] = rd["password"]
        elif "birth" in nl or "dob" in nl:
            payload[name] = "1995-06-15"
        elif "age" in nl:
            payload[name] = "30"
        elif "gender" in nl or "sex" in nl:
            payload[name] = "M"
        elif "country" in nl or "nation" in nl:
            payload[name] = "US"
        elif "state" in nl or "region" in nl or "province" in nl:
            payload[name] = "NY"
        elif "city" in nl or "town" in nl:
            payload[name] = "New York"
        elif "zip" in nl or "postal" in nl or "postcode" in nl:
            payload[name] = "10001"
        elif "address" in nl or "street" in nl:
            payload[name] = "123 Main St"
        elif "company" in nl or "organization" in nl or "org" in nl:
            payload[name] = "Acme Inc"
        elif "captcha" in nl:
            payload[name] = ""
        elif t == "number":
            payload[name] = val or "1"
        elif t == "date":
            payload[name] = "1995-06-15"
        else:
            payload[name] = val or rd["username"]
    return payload


async def _discover_signup_form(client, base_url: str):
    """Try to find the actual signup/register page on a site and return
    (page_url, form, html). Falls back to the home page if nothing found."""
    from urllib.parse import urljoin, urlparse

    common_paths = [
        "/signup", "/sign-up", "/sign_up", "/register", "/registration",
        "/account/create", "/create-account", "/users/sign_up",
        "/auth/register", "/auth/signup", "/join", "/customer/account/create/",
        "/en/register", "/en/signup", "/login",
    ]
    seen = set()

    for path in common_paths:
        url = urljoin(base_url, path)
        if url in seen:
            continue
        seen.add(url)
        r = await _fetch(client, "GET", url, retries=0, timeout=5.0)
        if not r or r.status_code >= 400:
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for f in soup.find_all("form"):
            inputs = f.find_all("input")
            names = " ".join((i.get("name", "") + " " + i.get("id", "")).lower() for i in inputs)
            types = [i.get("type", "").lower() for i in inputs]
            if "password" in types or "tel" in types or any(k in names for k in ("phone", "mobile", "email", "username")):
                return url, f, r.text

    r = await _fetch(client, "GET", base_url, retries=0, timeout=6.0)
    if r:
        soup = BeautifulSoup(r.text, "html.parser")
        host = urlparse(base_url).netloc
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(" ", strip=True).lower()
            href_l = href.lower()
            if any(k in text for k in ("sign up", "register", "create account", "join", "create an account")) \
                    or any(k in href_l for k in ("signup", "sign-up", "register", "create-account", "join")):
                target = urljoin(base_url, href)
                if urlparse(target).netloc and host not in urlparse(target).netloc:
                    continue
                r2 = await _fetch(client, "GET", target, retries=0, timeout=6.0)
                if r2 and r2.status_code < 400:
                    soup2 = BeautifulSoup(r2.text, "html.parser")
                    for f in soup2.find_all("form"):
                        inputs = f.find_all("input")
                        names = " ".join((i.get("name", "") + " " + i.get("id", "")).lower() for i in inputs)
                        types = [i.get("type", "").lower() for i in inputs]
                        if "password" in types or any(k in names for k in ("phone", "mobile", "email", "username")):
                            return target, f, r2.text
        for f in soup.find_all("form"):
            inputs = f.find_all("input")
            names = " ".join((i.get("name", "") + " " + i.get("id", "")).lower() for i in inputs)
            if any(k in names for k in ("phone", "mobile", "email", "username")):
                return base_url, f, r.text

    return None, None, None


async def _signup_generic(platform: str, url: str, number: str) -> tuple[str, str]:
    if not url:
        return STATUS_OTP_FAILED, f"{platform}: No signup endpoint configured"
    rd = random_user_data()
    async with httpx.AsyncClient(headers=HEADERS, verify=False) as client:
        page_url, form, _html = await _discover_signup_form(client, url)
        if not form:
            return STATUS_OTP_FAILED, f"{platform}: no signup form discovered on site"

        from urllib.parse import urljoin
        action = form.get("action") or page_url
        action = urljoin(page_url, action)
        method = (form.get("method") or "POST").upper()
        payload = _fill_form_fields(form, number, rd)

        if not any(("phone" in k.lower() or "mobile" in k.lower() or "tel" in k.lower()
                    or "email" in k.lower() or "user" in k.lower()) for k in payload.keys()):
            return STATUS_OTP_FAILED, f"{platform}: form on {page_url} has no usable identity field"

        h = {**HEADERS, "Referer": page_url, "Origin": "/".join(page_url.split("/", 3)[:3])}
        r = await _fetch(client, method, action, data=payload, headers=h, retries=1, timeout=10.0)
        if not r:
            return STATUS_OTP_FAILED, f"{platform}: signup POST to {action.split('/')[-1] or 'site'} returned no response"

        body = r.text.lower()
        tag = f"HTTP {r.status_code}"
        if any(k in body for k in ("already registered", "already exists", "already in use",
                                   "phone is taken", "is already associated", "already has an account")):
            return STATUS_REGISTERED, f"{platform}: number already registered ({tag})"
        if any(k in body for k in ("verification code", "verification sent", "code sent", "otp sent",
                                   "we sent", "check your phone", "verify your phone", "confirm your phone",
                                   "enter the code", "we've sent", "verification email", "almost done")):
            return STATUS_OTP_SENT, f"{platform}: verification/OTP step reached ({tag})"
        if r.status_code in (200, 201, 202) and any(k in body for k in ("welcome", "thank you", "success", "registered")):
            return STATUS_OTP_SENT, f"{platform}: signup submitted ({tag})"
        if r.status_code == 404:
            return STATUS_OTP_FAILED, f"{platform}: signup endpoint missing ({tag})"
        if r.status_code in (400, 422):
            return STATUS_OTP_FAILED, f"{platform}: signup rejected — invalid fields ({tag})"
        return STATUS_OTP_FAILED, f"{platform}: signup form posted but no clear OTP signal ({tag})"


SIGNUP_FNS = {
    "Google":    signup_google,
    "Microsoft": signup_microsoft,
    "Apple":     signup_apple,
    "Instagram": signup_instagram,
    "TikTok":    signup_tiktok,
    "FACEBOOK":  signup_facebook,
    "WhatsApp":  signup_whatsapp,
    "Telegram":  signup_telegram,
    "Uber":      signup_uber,
}


async def attempt_signup(platform: str, number: str) -> tuple[str, str]:
    try:
        fn = SIGNUP_FNS.get(platform)
        if fn:
            return await fn(number)
        url = GENERIC_PLATFORM_URLS.get(platform, "")
        return await _signup_generic(platform, url, number)
    except Exception as e:
        logger.error(f"signup error {platform}/{number}: {e}")
        return STATUS_ERROR, f"{platform} signup exception: {str(e)[:80]}"


async def attempt_signin(platform: str, number: str) -> tuple[str, str, str]:
    try:
        fn = PLATFORM_CHECKERS.get(platform)
        if fn:
            return await fn(number)
        url = GENERIC_PLATFORM_URLS.get(platform, "")
        if url:
            return await check_generic(platform, url, number)
        return STATUS_UNKNOWN, f"{platform}: No signin checker available", ""
    except Exception as e:
        logger.error(f"signin error {platform}/{number}: {e}")
        return STATUS_ERROR, f"{platform} signin exception: {str(e)[:80]}", ""


def _derive_final_status(signup_status: str, signin_status: str) -> str:
    if signin_status == STATUS_REGISTERED or signup_status == STATUS_REGISTERED:
        return STATUS_REGISTERED
    if signup_status == STATUS_OTP_SENT:
        return STATUS_OTP_SENT
    if signin_status == STATUS_NOT_FOUND:
        return STATUS_NOT_FOUND
    if signup_status == STATUS_OTP_FAILED and signin_status in (STATUS_UNKNOWN, STATUS_NOT_FOUND):
        return STATUS_OTP_FAILED
    if signup_status == STATUS_ERROR and signin_status == STATUS_ERROR:
        return STATUS_ERROR
    return STATUS_UNKNOWN


async def check_platform(platform: str, number: str) -> dict:
    """Run signup attempt then signin attempt; return combined result + card."""
    url = GENERIC_PLATFORM_URLS.get(platform, "")

    signup_task = asyncio.create_task(attempt_signup(platform, number))
    signin_task = asyncio.create_task(attempt_signin(platform, number))
    signup_status, signup_msg = await signup_task
    signin_result = await signin_task
    signin_status, signin_msg, used_url = signin_result if len(signin_result) == 3 else (*signin_result, "")

    final_status = _derive_final_status(signup_status, signin_status)

    card = make_result_card(
        platform=platform,
        number=number,
        final_status=final_status,
        signup_status=signup_status,
        signup_msg=signup_msg,
        signin_status=signin_status,
        signin_msg=signin_msg,
        url=used_url or url,
    )

    return {
        "platform": platform,
        "number": number,
        "signup_status": signup_status,
        "signup_msg": signup_msg,
        "signin_status": signin_status,
        "signin_msg": signin_msg,
        "final_status": final_status,
        "url": used_url or url,
        "card": card,
    }


def build_summary(results: list[dict]) -> str:
    """Build a human-readable summary message from accumulated results."""
    if not results:
        return "📊 *Final Summary*\n\nNo results to summarize."

    total = len(results)
    by_final = {}
    by_signup = {}
    by_signin = {}
    for r in results:
        by_final[r["final_status"]] = by_final.get(r["final_status"], 0) + 1
        by_signup[r["signup_status"]] = by_signup.get(r["signup_status"], 0) + 1
        by_signin[r["signin_status"]] = by_signin.get(r["signin_status"], 0) + 1

    def line(d: dict, key: str, label: str) -> str:
        return f"  {label}: `{d.get(key, 0)}`"

    by_platform: dict[str, dict[str, int]] = {}
    for r in results:
        p = r["platform"]
        by_platform.setdefault(p, {})
        by_platform[p][r["final_status"]] = by_platform[p].get(r["final_status"], 0) + 1

    plat_lines = []
    for p, counts in by_platform.items():
        parts = []
        if counts.get(STATUS_REGISTERED): parts.append(f"✅{counts[STATUS_REGISTERED]}")
        if counts.get(STATUS_OTP_SENT):   parts.append(f"📨{counts[STATUS_OTP_SENT]}")
        if counts.get(STATUS_NOT_FOUND):  parts.append(f"❌{counts[STATUS_NOT_FOUND]}")
        if counts.get(STATUS_OTP_FAILED): parts.append(f"🚫{counts[STATUS_OTP_FAILED]}")
        if counts.get(STATUS_UNKNOWN):    parts.append(f"⚠️{counts[STATUS_UNKNOWN]}")
        if counts.get(STATUS_ERROR):      parts.append(f"⛔{counts[STATUS_ERROR]}")
        plat_lines.append(f"  • `{p}` — {' '.join(parts) or '—'}")

    success_set = {STATUS_REGISTERED, STATUS_OTP_SENT}
    failed_set = {STATUS_NOT_FOUND, STATUS_OTP_FAILED, STATUS_ERROR}

    success_by_number: dict[str, list[str]] = {}
    failed_by_number: dict[str, list[str]] = {}
    for r in results:
        n = r["number"]
        p = r["platform"]
        fs = r["final_status"]
        if fs in success_set:
            tag = "✅" if fs == STATUS_REGISTERED else "📨"
            success_by_number.setdefault(n, []).append(f"{tag}{p}")
        elif fs in failed_set:
            tag = "❌" if fs == STATUS_NOT_FOUND else ("⛔" if fs == STATUS_ERROR else "🚫")
            failed_by_number.setdefault(n, []).append(f"{tag}{p}")

    def _num_lines(d: dict[str, list[str]], cap: int = 8) -> str:
        if not d:
            return "  (none)"
        out = []
        for n, items in d.items():
            shown = items[:cap]
            extra = f" +{len(items) - cap} more" if len(items) > cap else ""
            out.append(f"  • `+{n}` ({len(items)}): {' '.join(shown)}{extra}")
        return "\n".join(out)

    summary = (
        f"📊 *Final Summary*\n\n"
        f"📞 Total checks: `{total}`\n\n"
        f"*Final verdict breakdown:*\n"
        f"{line(by_final, STATUS_REGISTERED, '✅ Registered')}\n"
        f"{line(by_final, STATUS_OTP_SENT, '📨 OTP sent')}\n"
        f"{line(by_final, STATUS_NOT_FOUND, '❌ Not found')}\n"
        f"{line(by_final, STATUS_OTP_FAILED, '🚫 OTP failed')}\n"
        f"{line(by_final, STATUS_UNKNOWN, '⚠️ Unknown')}\n"
        f"{line(by_final, STATUS_ERROR, '⛔ Error')}\n\n"
        f"*Signup attempts:*\n"
        f"{line(by_signup, STATUS_OTP_SENT, '📨 OTP sent')}  •  "
        f"{line(by_signup, STATUS_REGISTERED, '✅ Phone in use').strip()}  •  "
        f"{line(by_signup, STATUS_OTP_FAILED, '🚫 Failed').strip()}\n\n"
        f"*Signin attempts:*\n"
        f"{line(by_signin, STATUS_REGISTERED, '✅ Account found')}  •  "
        f"{line(by_signin, STATUS_NOT_FOUND, '❌ No account').strip()}  •  "
        f"{line(by_signin, STATUS_UNKNOWN, '⚠️ Unknown').strip()}\n\n"
        f"*Per platform:*\n"
        + "\n".join(plat_lines[:30])
    )
    if len(plat_lines) > 30:
        summary += f"\n  …and {len(plat_lines) - 30} more"

    summary += (
        f"\n\n━━━━━━━━━━━━━━━━━━━━\n"
        f"*✅ SUCCESSFUL numbers* (registered or OTP sent) — `{len(success_by_number)}` number(s):\n"
        f"{_num_lines(success_by_number)}\n\n"
        f"*❌ FAILED numbers* (not found / OTP failed / error) — `{len(failed_by_number)}` number(s):\n"
        f"{_num_lines(failed_by_number)}"
    )
    return summary
