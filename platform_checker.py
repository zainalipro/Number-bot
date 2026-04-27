"""Per-site signup + signin verification. Now site-list is dynamic (loaded
from sites.py) and every check goes through the AI-enhanced screenshotter
in screenshotter.py. We do NOT keep hardcoded per-platform HTTP recipes
anymore — they were brittle and made it impossible to add/remove sites
at runtime.

The public surface (`check_platform`, `make_result_card`, `build_summary`,
plus the STATUS_* constants) is preserved so bot.py keeps working with
minor updates only."""

from __future__ import annotations

import io
import logging
import time
from typing import Any

from PIL import Image, ImageDraw, ImageFont

import ai_helper
import sites
from screenshotter import browser_pool, capture_signup_and_signin

logger = logging.getLogger(__name__)


STATUS_REGISTERED = "registered"
STATUS_NOT_FOUND = "not_found"
STATUS_UNKNOWN = "unknown"
STATUS_ERROR = "error"
STATUS_OTP_SENT = "otp_sent"
STATUS_OTP_FAILED = "otp_failed"
STATUS_CAPTCHA = "captcha"
STATUS_BLOCKED = "blocked"

STATUS_LABELS = {
    STATUS_REGISTERED: "✅ REGISTERED",
    STATUS_NOT_FOUND:  "❌ NOT FOUND",
    STATUS_UNKNOWN:    "⚠️ UNKNOWN",
    STATUS_ERROR:      "⛔ ERROR",
    STATUS_OTP_SENT:   "📨 OTP SENT",
    STATUS_OTP_FAILED: "🚫 OTP FAILED",
    STATUS_CAPTCHA:    "🤖 CAPTCHA",
    STATUS_BLOCKED:    "🚧 BLOCKED",
}

PLATFORM_COLORS = {
    STATUS_REGISTERED: (39, 174, 96),
    STATUS_NOT_FOUND:  (231, 76, 60),
    STATUS_UNKNOWN:    (243, 156, 18),
    STATUS_ERROR:      (127, 140, 141),
    STATUS_OTP_SENT:   (52, 152, 219),
    STATUS_OTP_FAILED: (155, 89, 182),
    STATUS_CAPTCHA:    (230, 126, 34),
    STATUS_BLOCKED:    (192, 57, 43),
}


def get_platforms() -> list[str]:
    """Live list of site names from sites.py (replaces the old PLATFORMS const)."""
    return sites.site_names()


# Backwards-compat module-level alias used by older code paths.
def __getattr__(name):  # pragma: no cover
    if name == "PLATFORMS":
        return get_platforms()
    raise AttributeError(name)


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
    platform: str, number: str, final_status: str,
    signup_status: str, signup_msg: str,
    signin_status: str, signin_msg: str,
    url: str = "",
) -> bytes:
    W, H = 980, 460
    bg = (18, 18, 24)
    accent = PLATFORM_COLORS.get(final_status, (127, 140, 141))
    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)
    draw.rectangle([(0, 0), (8, H)], fill=accent)
    draw.rectangle([(0, 0), (W, H)], outline=(40, 40, 52), width=2)

    f_big, f_med, f_small, f_xs, f_mono = _load_fonts()
    draw.text((28, 20), f"🌐  {platform}", font=f_big, fill=(255, 255, 255))

    final_label = STATUS_LABELS.get(final_status, "⚠️ UNKNOWN")
    draw.rectangle([(W - 250, 18), (W - 20, 58)], fill=accent)
    draw.text((W - 240, 28), final_label, font=f_small, fill=(255, 255, 255))

    draw.line([(20, 70), (W - 20, 70)], fill=(50, 50, 65), width=1)
    draw.text((20, 84), "📞  Number:", font=f_small, fill=(150, 150, 180))
    draw.text((150, 82), f"+{number}", font=f_mono, fill=(100, 220, 255))

    def _section(title, status, msg, y):
        sec = PLATFORM_COLORS.get(status, (127, 140, 141))
        draw.rectangle([(20, y), (W - 20, y + 110)], fill=(28, 28, 38), outline=(50, 50, 65), width=1)
        draw.rectangle([(20, y), (24, y + 110)], fill=sec)
        draw.text((40, y + 8), title, font=f_med, fill=(220, 220, 220))
        sl = STATUS_LABELS.get(status, "⚠️ UNKNOWN")
        draw.rectangle([(W - 230, y + 6), (W - 30, y + 38)], fill=sec)
        draw.text((W - 222, y + 12), sl, font=f_xs, fill=(255, 255, 255))
        l1 = (msg or "")[:95]
        l2 = (msg or "")[95:190]
        draw.text((40, y + 44), l1, font=f_small, fill=(230, 230, 230))
        if l2:
            draw.text((40, y + 70), l2, font=f_small, fill=(200, 200, 200))

    _section("📝  SIGNUP attempt", signup_status, signup_msg, 118)
    _section("🔑  SIGNIN attempt", signin_status, signin_msg, 240)

    if url:
        draw.text((20, 372), "🔗", font=f_small, fill=(150, 150, 180))
        draw.text((46, 372), url[:110], font=f_small, fill=(100, 160, 255))

    ts = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    draw.text((20, 430), f"🕐  {ts}", font=f_xs, fill=(90, 90, 110))

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _verdict_from(signup: str, signin: str, captcha: bool, blocked: bool) -> str:
    if blocked:
        return STATUS_BLOCKED
    if captcha:
        return STATUS_CAPTCHA
    # signin is the strongest signal — if it says "registered" we trust it
    if signin == STATUS_REGISTERED:
        return STATUS_REGISTERED
    if signup == STATUS_REGISTERED:
        return STATUS_REGISTERED
    if signin == STATUS_NOT_FOUND and signup in (STATUS_NOT_FOUND, STATUS_OTP_SENT, STATUS_UNKNOWN):
        return STATUS_NOT_FOUND
    if signup == STATUS_OTP_SENT:
        return STATUS_OTP_SENT
    if signin == STATUS_NOT_FOUND:
        return STATUS_NOT_FOUND
    if signup == STATUS_ERROR and signin == STATUS_ERROR:
        return STATUS_ERROR
    return STATUS_UNKNOWN


async def check_platform(platform_name: str, number: str) -> dict[str, Any]:
    """Run signup + signin checks for a (site, number) pair. Returns a dict
    with the same shape bot.py already expects, plus screenshot bytes."""
    site = sites.get_site(platform_name)
    if not site:
        msg = f"Site '{platform_name}' not configured. Add it from the bot menu."
        return {
            "platform": platform_name, "number": number,
            "signup_status": STATUS_ERROR, "signup_msg": msg,
            "signin_status": STATUS_ERROR, "signin_msg": msg,
            "final_status": STATUS_ERROR,
            "url": "", "signup_png": b"", "signin_png": b"",
            "captcha_present": False, "blocked": False,
            "card": make_result_card(platform_name, number, STATUS_ERROR,
                                     STATUS_ERROR, msg, STATUS_ERROR, msg, ""),
        }

    signup_url = site.get("signup_url") or ""
    signin_url = site.get("signin_url") or ""
    use_ai = ai_helper.is_enabled()

    signup_cap, signin_cap = await capture_signup_and_signin(
        platform_name, number, signup_url, signin_url,
        timeout=120.0, use_ai=use_ai,
    )

    # Interpret final results
    if use_ai and not signup_cap.error:
        try:
            ai_signup = await ai_helper.interpret_result_text(
                platform_name, number, signup_cap.text, "signup")
            signup_status = _ai_to_status(ai_signup["verdict"])
            signup_msg = ai_signup["reason"][:200] or signup_cap.summary
        except Exception as e:
            signup_status = _heuristic_status(signup_cap.text, signup_cap.error)
            signup_msg = signup_cap.summary or str(e)
    else:
        signup_status = _heuristic_status(signup_cap.text, signup_cap.error)
        signup_msg = signup_cap.summary or signup_cap.error or "no AI"

    if use_ai and not signin_cap.error:
        try:
            ai_signin = await ai_helper.interpret_result_text(
                platform_name, number, signin_cap.text, "signin")
            signin_status = _ai_to_status(ai_signin["verdict"])
            signin_msg = ai_signin["reason"][:200] or signin_cap.summary
        except Exception as e:
            signin_status = _heuristic_status(signin_cap.text, signin_cap.error)
            signin_msg = signin_cap.summary or str(e)
    else:
        signin_status = _heuristic_status(signin_cap.text, signin_cap.error)
        signin_msg = signin_cap.summary or signin_cap.error or "no AI"

    captcha = signup_cap.captcha_present or signin_cap.captcha_present
    blocked = signup_cap.blocked or signin_cap.blocked

    if captcha:
        sol_bits = []
        if signup_cap.captcha_solution:
            sol_bits.append(f"signup→{signup_cap.captcha_solution[:60]}")
        if signin_cap.captcha_solution:
            sol_bits.append(f"signin→{signin_cap.captcha_solution[:60]}")
        if sol_bits:
            note = " | AI suggestion: " + ", ".join(sol_bits)
            signup_msg = (signup_msg + note)[:240]
            signin_msg = (signin_msg + note)[:240]

    final_status = _verdict_from(signup_status, signin_status, captcha, blocked)

    card = make_result_card(
        platform_name, number, final_status,
        signup_status, signup_msg,
        signin_status, signin_msg,
        signin_cap.url or signup_cap.url or signup_url or signin_url,
    )

    return {
        "platform": platform_name, "number": number,
        "signup_status": signup_status, "signup_msg": signup_msg,
        "signin_status": signin_status, "signin_msg": signin_msg,
        "final_status": final_status,
        "url": signin_cap.url or signup_cap.url or signup_url or signin_url,
        "signup_png": signup_cap.png, "signin_png": signin_cap.png,
        "captcha_present": captcha, "blocked": blocked,
        "card": card,
        "signup_form_found": signup_cap.form_found,
        "signup_fields_total": signup_cap.fields_total,
        "signup_fields_filled": signup_cap.fields_filled,
        "signup_submitted": signup_cap.submitted,
        "signin_form_found": signin_cap.form_found,
        "signin_fields_total": signin_cap.fields_total,
        "signin_fields_filled": signin_cap.fields_filled,
        "signin_submitted": signin_cap.submitted,
    }


def _ai_to_status(verdict: str) -> str:
    return {
        "registered": STATUS_REGISTERED,
        "not_found":  STATUS_NOT_FOUND,
        "otp_sent":   STATUS_OTP_SENT,
        "otp_failed": STATUS_OTP_FAILED,
        "unknown":    STATUS_UNKNOWN,
        "error":      STATUS_ERROR,
    }.get(verdict, STATUS_UNKNOWN)


def _heuristic_status(text: str, error: str | None) -> str:
    if error:
        return STATUS_ERROR
    t = (text or "").lower()
    if any(k in t for k in ["enter your password", "enter password", "wrong password",
                            "incorrect password", "two-factor", "2-step",
                            "verification code"]):
        return STATUS_REGISTERED
    if any(k in t for k in ["no account", "couldn't find", "not registered",
                            "doesn't exist", "user not found", "create one",
                            "we cannot find", "create account"]):
        return STATUS_NOT_FOUND
    if any(k in t for k in ["code sent", "we sent a code", "verification sent",
                            "check your phone", "sms"]):
        return STATUS_OTP_SENT
    if "captcha" in t or "are you human" in t:
        return STATUS_CAPTCHA
    return STATUS_UNKNOWN


def build_summary(results: list[dict]) -> str:
    if not results:
        return "No checks completed."
    by_status: dict[str, int] = {}
    by_platform: dict[str, dict[str, int]] = {}
    for r in results:
        fs = r.get("final_status") or STATUS_UNKNOWN
        by_status[fs] = by_status.get(fs, 0) + 1
        plat = r.get("platform") or "?"
        if plat not in by_platform:
            by_platform[plat] = {}
        by_platform[plat][fs] = by_platform[plat].get(fs, 0) + 1

    lines = [f"📊 *Run summary*  •  total checks: `{len(results)}`", ""]
    for s in (STATUS_REGISTERED, STATUS_NOT_FOUND, STATUS_OTP_SENT, STATUS_OTP_FAILED,
              STATUS_CAPTCHA, STATUS_BLOCKED, STATUS_UNKNOWN, STATUS_ERROR):
        if by_status.get(s):
            lines.append(f"{STATUS_LABELS[s]}  `{by_status[s]}`")
    lines.append("")
    lines.append("*Per-site breakdown:*")
    for plat in sorted(by_platform):
        bits = []
        for s in (STATUS_REGISTERED, STATUS_NOT_FOUND, STATUS_OTP_SENT,
                  STATUS_OTP_FAILED, STATUS_CAPTCHA, STATUS_BLOCKED,
                  STATUS_UNKNOWN, STATUS_ERROR):
            if by_platform[plat].get(s):
                bits.append(f"{STATUS_LABELS[s].split()[0]}{by_platform[plat][s]}")
        lines.append(f"• `{plat}` — " + "  ".join(bits))
    return "\n".join(lines)
