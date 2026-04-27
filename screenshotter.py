"""Headless-browser capture of register / login pages with the form filled
and submitted, returning PNG screenshots and the visible text.

Improvements over the original:
- Realistic browser fingerprint to reduce white-page anti-bot blocks
  (User-Agent, Accept-Language, viewport, navigator.webdriver patch).
- Long network-idle waits + scroll to trigger lazy-loaded auth widgets
  (the most common cause of the "white screen" issue).
- AI-assisted field analysis (when an OPENAI key is configured) — falls
  back to heuristic field detection when AI is unavailable.
- CAPTCHA / human-verification detection with a clear flag returned to
  the caller (and a best-effort AI-suggested solution for image/text
  CAPTCHAs).
- Hardened error handling — every step is wrapped, never crashes the bot.
"""

from __future__ import annotations

import asyncio
import io
import logging
import random
import re
import string
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

import ai_helper

logger = logging.getLogger(__name__)

LAUNCH_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
    "--no-zygote",
]
VIEWPORT = {"width": 1366, "height": 900}
NAV_TIMEOUT_MS = 45000
ACTION_TIMEOUT_MS = 15000
FORM_WAIT_MS = 12000
POST_SUBMIT_WAIT_MS = 6000
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

_FIRST = ["Alex", "Sam", "Jordan", "Taylor", "Casey", "Morgan", "Riley",
          "Jamie", "Robin", "Drew", "Avery", "Quinn", "Skyler", "Reese"]
_LAST = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia",
         "Miller", "Davis", "Lopez", "Wilson", "Anderson", "Thomas"]
_MAIL_DOMAINS = ["mailinator.com", "guerrillamail.com", "1secmail.com",
                 "yopmail.com", "trashmail.com"]

# Calling-code → (Country name, ISO-2). Sorted longest prefix first below.
_CC_TABLE_RAW = [
    ("1",   "United States",    "US"),
    ("7",   "Russia",           "RU"),
    ("20",  "Egypt",            "EG"),
    ("27",  "South Africa",     "ZA"),
    ("30",  "Greece",           "GR"),
    ("31",  "Netherlands",      "NL"),
    ("32",  "Belgium",          "BE"),
    ("33",  "France",           "FR"),
    ("34",  "Spain",            "ES"),
    ("36",  "Hungary",          "HU"),
    ("39",  "Italy",            "IT"),
    ("40",  "Romania",          "RO"),
    ("41",  "Switzerland",      "CH"),
    ("43",  "Austria",          "AT"),
    ("44",  "United Kingdom",   "GB"),
    ("45",  "Denmark",          "DK"),
    ("46",  "Sweden",           "SE"),
    ("47",  "Norway",           "NO"),
    ("48",  "Poland",           "PL"),
    ("49",  "Germany",          "DE"),
    ("51",  "Peru",             "PE"),
    ("52",  "Mexico",           "MX"),
    ("53",  "Cuba",             "CU"),
    ("54",  "Argentina",        "AR"),
    ("55",  "Brazil",           "BR"),
    ("56",  "Chile",            "CL"),
    ("57",  "Colombia",         "CO"),
    ("58",  "Venezuela",        "VE"),
    ("60",  "Malaysia",         "MY"),
    ("61",  "Australia",        "AU"),
    ("62",  "Indonesia",        "ID"),
    ("63",  "Philippines",      "PH"),
    ("64",  "New Zealand",      "NZ"),
    ("65",  "Singapore",        "SG"),
    ("66",  "Thailand",         "TH"),
    ("81",  "Japan",            "JP"),
    ("82",  "South Korea",      "KR"),
    ("84",  "Vietnam",          "VN"),
    ("86",  "China",            "CN"),
    ("90",  "Turkey",           "TR"),
    ("91",  "India",            "IN"),
    ("92",  "Pakistan",         "PK"),
    ("93",  "Afghanistan",      "AF"),
    ("94",  "Sri Lanka",        "LK"),
    ("95",  "Myanmar",          "MM"),
    ("98",  "Iran",             "IR"),
    ("212", "Morocco",          "MA"),
    ("213", "Algeria",          "DZ"),
    ("216", "Tunisia",          "TN"),
    ("218", "Libya",            "LY"),
    ("220", "Gambia",           "GM"),
    ("221", "Senegal",          "SN"),
    ("225", "Ivory Coast",      "CI"),
    ("233", "Ghana",            "GH"),
    ("234", "Nigeria",          "NG"),
    ("249", "Sudan",            "SD"),
    ("251", "Ethiopia",         "ET"),
    ("254", "Kenya",            "KE"),
    ("255", "Tanzania",         "TZ"),
    ("256", "Uganda",           "UG"),
    ("260", "Zambia",           "ZM"),
    ("263", "Zimbabwe",         "ZW"),
    ("351", "Portugal",         "PT"),
    ("352", "Luxembourg",       "LU"),
    ("353", "Ireland",          "IE"),
    ("354", "Iceland",          "IS"),
    ("358", "Finland",          "FI"),
    ("359", "Bulgaria",         "BG"),
    ("370", "Lithuania",        "LT"),
    ("371", "Latvia",           "LV"),
    ("372", "Estonia",          "EE"),
    ("375", "Belarus",          "BY"),
    ("380", "Ukraine",          "UA"),
    ("381", "Serbia",           "RS"),
    ("385", "Croatia",          "HR"),
    ("386", "Slovenia",         "SI"),
    ("387", "Bosnia",           "BA"),
    ("420", "Czechia",          "CZ"),
    ("421", "Slovakia",         "SK"),
    ("852", "Hong Kong",        "HK"),
    ("853", "Macau",            "MO"),
    ("855", "Cambodia",         "KH"),
    ("856", "Laos",             "LA"),
    ("880", "Bangladesh",       "BD"),
    ("886", "Taiwan",           "TW"),
    ("960", "Maldives",         "MV"),
    ("961", "Lebanon",          "LB"),
    ("962", "Jordan",           "JO"),
    ("963", "Syria",            "SY"),
    ("964", "Iraq",             "IQ"),
    ("965", "Kuwait",           "KW"),
    ("966", "Saudi Arabia",     "SA"),
    ("967", "Yemen",            "YE"),
    ("968", "Oman",             "OM"),
    ("970", "Palestine",        "PS"),
    ("971", "United Arab Emirates", "AE"),
    ("972", "Israel",           "IL"),
    ("973", "Bahrain",          "BH"),
    ("974", "Qatar",            "QA"),
    ("975", "Bhutan",           "BT"),
    ("976", "Mongolia",         "MN"),
    ("977", "Nepal",            "NP"),
    ("992", "Tajikistan",       "TJ"),
    ("993", "Turkmenistan",     "TM"),
    ("994", "Azerbaijan",       "AZ"),
    ("995", "Georgia",          "GE"),
    ("996", "Kyrgyzstan",       "KG"),
    ("998", "Uzbekistan",       "UZ"),
]
_CC_TABLE = sorted(_CC_TABLE_RAW, key=lambda x: -len(x[0]))


def _country_from_phone(number: str) -> dict:
    """Look up calling-code → country. Best-effort, longest prefix wins."""
    digits = "".join(c for c in (number or "") if c.isdigit())
    for code, name, iso in _CC_TABLE:
        if digits.startswith(code):
            return {"calling_code": code, "name": name, "iso2": iso}
    return {"calling_code": "", "name": "United States", "iso2": "US"}


def _random_data() -> dict:
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    first = random.choice(_FIRST)
    last = random.choice(_LAST)
    username = f"{first.lower()}{last.lower()}{suffix[:4]}"
    email = f"{username}@{random.choice(_MAIL_DOMAINS)}"
    pw = (
        "".join(random.choices(string.ascii_uppercase, k=2))
        + "".join(random.choices(string.ascii_lowercase, k=4))
        + "".join(random.choices(string.digits, k=3))
        + random.choice("!@#$%&*")
    )
    return {
        "first_name": first, "last_name": last, "full_name": f"{first} {last}",
        "username": username, "email": email, "password": pw,
        "dob": "1995-06-15", "country": "US", "zip": "10001",
    }


@dataclass
class CaptureResult:
    """Everything the caller might want to know about a capture attempt."""
    png: bytes
    text: str
    url: str
    blocked: bool
    captcha_present: bool
    captcha_kind: str | None
    captcha_solution: str | None
    summary: str
    error: str | None
    fields_total: int = 0
    fields_filled: int = 0
    submitted: bool = False
    form_found: bool = False


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
    d.text((40, 110), f"Site:    {platform}", font=f_med, fill=(220, 220, 230))
    d.text((40, 150), f"Number:  +{number}", font=f_med, fill=(220, 220, 230))
    d.text((40, 210), "Reason:", font=f_small, fill=(180, 180, 200))
    for i, chunk in enumerate(_wrap(reason, 80)[:10]):
        d.text((40, 240 + i * 26), chunk, font=f_small, fill=(255, 200, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _wrap(s: str, n: int) -> list[str]:
    s = (s or "").strip()
    return [s[i:i + n] for i in range(0, len(s), n)] or [""]


_CAPTCHA_PATTERNS = re.compile(
    r"(captcha|are you (a )?human|verify you are human|recaptcha|hcaptcha|"
    r"turnstile|press (and|&) hold|press and hold|are you a robot|"
    r"unusual (activity|traffic)|security check|cloudflare|"
    r"checking your browser|attention required|access denied|blocked)",
    re.IGNORECASE,
)


def _detect_blocked_or_captcha(text: str, title: str) -> tuple[bool, bool, str | None]:
    """Return (blocked, captcha_present, hint)."""
    blob = f"{title} {text}".lower()
    if "cloudflare" in blob or "attention required" in blob or "access denied" in blob:
        return True, False, f"Anti-bot wall: {title.strip()[:80] or blob[:80]}"
    m = _CAPTCHA_PATTERNS.search(blob)
    if m:
        return False, True, f"CAPTCHA / human verification: {m.group(0)}"
    return False, False, None


_FORM_SCAN_JS = r"""
(kind) => {
    function isVisible(el) {
        const r = el.getBoundingClientRect();
        const cs = window.getComputedStyle(el);
        return r.width > 0 && r.height > 0 &&
               cs.visibility !== 'hidden' && cs.display !== 'none';
    }
    function nearbyLabel(el) {
        // 1) <label for="id">
        if (el.id) {
            const lab = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
            if (lab) return (lab.innerText || '').trim();
        }
        // 2) wrapping <label>
        let p = el.closest('label');
        if (p) return (p.innerText || '').trim();
        // 3) preceding sibling text or label-like element
        let prev = el.previousElementSibling;
        for (let i = 0; i < 3 && prev; i++, prev = prev.previousElementSibling) {
            const t = (prev.innerText || '').trim();
            if (t && t.length < 80) return t;
        }
        // 4) parent's text (minus our own value)
        const par = el.parentElement;
        if (par) {
            const t = (par.innerText || '').trim();
            if (t && t.length < 120) return t;
        }
        return '';
    }
    function describeInput(el, fi, i) {
        el.setAttribute('data-pw-field-idx', fi + '-' + i);
        const tag = el.tagName.toLowerCase();
        const type = (el.type || '').toLowerCase();
        const obj = {
            fi, i, tag, type,
            name: (el.name || '').toLowerCase(),
            id: (el.id || '').toLowerCase(),
            placeholder: (el.placeholder || '').toLowerCase(),
            ariaLabel: (el.getAttribute('aria-label') || '').toLowerCase(),
            autocomplete: (el.autocomplete || '').toLowerCase(),
            label: (nearbyLabel(el) || '').slice(0, 120),
            required: !!el.required,
        };
        if (tag === 'select') {
            obj.options = Array.from(el.options || [])
                .slice(0, 60)
                .map(o => ({ value: o.value, text: (o.text || '').trim().slice(0, 60) }));
        }
        return obj;
    }
    function collectRadioGroups(scope) {
        // Group radios by name and treat each group as one "field".
        const radios = Array.from(scope.querySelectorAll('input[type=radio]'))
            .filter(isVisible);
        const groups = {};
        radios.forEach(r => {
            const n = (r.name || '').toLowerCase() || ('__' + r.id);
            if (!groups[n]) groups[n] = [];
            groups[n].push(r);
        });
        return groups;
    }
    const SIGNUP_KW = ['sign up','signup','register','create account','create an account','join'];
    const SIGNIN_KW = ['sign in','signin','log in','login','log-in','sign-in'];
    const NEG_KW    = ['subscribe','newsletter','search','filter','coupon','discount','review','enquire'];
    function score(text, action, kind) {
        text = (text || '').toLowerCase();
        action = (action || '').toLowerCase();
        let s = 0;
        const w = (kind === 'Signup') ? SIGNUP_KW : SIGNIN_KW;
        const o = (kind === 'Signup') ? SIGNIN_KW : SIGNUP_KW;
        for (const k of w) { if (text.includes(k)) s += 25; if (action.includes(k.replace(/\s+/g,''))) s += 25; }
        for (const k of o) { if (text.includes(k)) s += 5; }
        for (const k of NEG_KW) { if (text.includes(k)) s -= 80; if (action.includes(k)) s -= 80; }
        return s;
    }

    function buildForm(scope, fi, action, formText) {
        const baseInputs = Array.from(scope.querySelectorAll('input,select,textarea'))
            .filter(el => el.type !== 'hidden' &&
                          (el.type || '').toLowerCase() !== 'radio' &&
                          isVisible(el));
        const radioGroups = collectRadioGroups(scope);

        const inputs = [];
        let i = 0;
        for (const el of baseInputs) {
            inputs.push(describeInput(el, fi, i++));
        }
        // append one synthetic descriptor per radio group
        for (const name of Object.keys(radioGroups)) {
            const group = radioGroups[name];
            if (!group.length) continue;
            const first = group[0];
            first.setAttribute('data-pw-field-idx', fi + '-' + i);
            const labelTxt = nearbyLabel(first) || name;
            inputs.push({
                fi, i,
                tag: 'input', type: 'radio-group',
                name: name,
                id: (first.id || '').toLowerCase(),
                placeholder: '',
                ariaLabel: (first.getAttribute('aria-label') || '').toLowerCase(),
                autocomplete: '',
                label: (labelTxt || '').slice(0, 120),
                required: !!first.required,
                options: group.slice(0, 12).map((r, ri) => {
                    r.setAttribute('data-pw-radio-idx', fi + '-' + i + '-' + ri);
                    const lid = r.id;
                    let labText = '';
                    if (lid) {
                        const l = document.querySelector('label[for="' + CSS.escape(lid) + '"]');
                        if (l) labText = (l.innerText || '').trim();
                    }
                    if (!labText) {
                        const par = r.closest('label');
                        if (par) labText = (par.innerText || '').trim();
                    }
                    return { ri, value: r.value, text: (labText || r.value || '').slice(0, 60) };
                }),
            });
            i += 1;
        }
        return inputs;
    }

    const forms = Array.from(document.querySelectorAll('form')).filter(isVisible);
    const out = [];
    forms.forEach((f, fi) => {
        f.setAttribute('data-pw-form-idx', String(fi));
        const inputs = buildForm(f, fi, f.action || '', '');
        if (!inputs.length) return;
        const btn = Array.from(f.querySelectorAll('button, input[type=submit], [role=button]'))
            .map(b => (b.innerText || b.value || '').trim()).join(' ');
        const text = (f.innerText || '') + ' ' + btn;
        const hasPwd = inputs.some(e => (e.type || '').toLowerCase() === 'password');
        let s = score(text, f.action || '', kind);
        if (hasPwd) s += 60;
        s += Math.min(inputs.length, 6) * 3;
        out.push({
            idx: fi, score: s, hasPassword: hasPwd, inputCount: inputs.length,
            text: text.slice(0, 200), action: f.action || '',
            inputs: inputs,
        });
    });
    // Loose inputs not inside any form
    const loose = Array.from(document.querySelectorAll('input,select,textarea'))
        .filter(el => el.type !== 'hidden' && !el.closest('form') && isVisible(el));
    if (loose.length) {
        const fi = forms.length;
        // Wrap loose inputs in a synthetic scope so the helper can re-use logic
        const synthetic = document.body;
        // We can't easily reuse buildForm directly without a real form scope,
        // so describe each loose input manually.
        const inputs = [];
        let i = 0;
        for (const el of loose) {
            if ((el.type || '').toLowerCase() === 'radio') continue;
            inputs.push(describeInput(el, fi, i++));
        }
        const text = inputs.map(x => x.placeholder + ' ' + x.ariaLabel + ' ' + x.label).join(' ');
        const hasPwd = inputs.some(e => (e.type || '').toLowerCase() === 'password');
        let s = score(text + ' ' + document.title, '', kind);
        if (hasPwd) s += 60;
        s += Math.min(inputs.length, 6) * 3;
        out.push({
            idx: fi, score: s, hasPassword: hasPwd, inputCount: inputs.length,
            text: text.slice(0, 200), action: '(no form)',
            inputs: inputs,
        });
    }
    out.sort((a, b) => b.score - a.score);
    return out;
}
"""


def _classify_field(f: dict) -> str:
    ident = " ".join(
        (f.get(k) or "") for k in
        ("name", "id", "placeholder", "ariaLabel", "autocomplete", "label")
    ).lower()
    t = (f.get("type") or "").lower()
    tag = (f.get("tag") or "").lower()

    # Skip-list first (CAPTCHA, OTP, code)
    if any(k in ident for k in ("captcha", "otp", "verification code", "verif code")):
        return "skip"

    # Specific input types
    if t == "tel" or any(k in ident for k in ("phone", "mobile", "msisdn", "whatsapp", "cell")):
        return "phone"
    if t == "email" or "email" in ident or "e-mail" in ident or "mail" in ident:
        return "email"
    if t == "password" or "pass" in ident or "pwd" in ident:
        return "password"

    # Gender (radio group OR select)
    if t == "radio-group" or "gender" in ident or "sex" in ident:
        if "gender" in ident or "sex" in ident or t == "radio-group":
            return "gender"

    # Date / DOB (check specific month/day/year FIRST)
    if "month" in ident:
        return "dob_month"
    if "year" in ident and ("birth" in ident or "born" in ident or "dob" in ident):
        return "dob_year"
    if "day" in ident and ("birth" in ident or "dob" in ident):
        return "dob_day"
    if t == "date" or "birth" in ident or "dob" in ident or "birthday" in ident:
        return "dob"

    # Country
    if "country" in ident or "nationality" in ident:
        return "country"

    # Names
    if "first" in ident or "given" in ident or "fname" in ident or "forename" in ident:
        return "first"
    if "last" in ident or "surname" in ident or "family" in ident or "lname" in ident:
        return "last"
    if "fullname" in ident or "displayname" in ident or "full name" in ident or ident.strip() == "name":
        return "fullname"
    if "user" in ident or "login" in ident or "handle" in ident or "nick" in ident:
        return "username"

    # Address bits
    if "zip" in ident or "postal" in ident or "postcode" in ident:
        return "zip"
    if "city" in ident:
        return "city"

    # Generic SELECT — try to choose the first non-placeholder option
    if tag == "select":
        return "select_default"

    # Checkbox (terms / agree) — auto-check
    if t == "checkbox":
        return "checkbox"

    if t in ("text", "search"):
        return "text"
    return "skip"


def _value_for_field(kind: str, number: str, rd: dict, ai_hint: str | None = None) -> str:
    if ai_hint:
        h = ai_hint.lower()
        if "phone" in h or "mobile" in h:
            return f"+{number}"
        if "email" in h:
            return rd["email"]
        if "password" in h:
            return rd["password"]
        if "first" in h:
            return rd["first_name"]
        if "last" in h:
            return rd["last_name"]
        if "user" in h:
            return rd["username"]
        if "name" in h:
            return rd["full_name"]
    if kind == "phone":
        return f"+{number}"
    if kind == "email":
        return rd["email"]
    if kind == "password":
        return rd["password"]
    if kind == "first":
        return rd["first_name"]
    if kind == "last":
        return rd["last_name"]
    if kind == "username":
        return rd["username"]
    if kind == "fullname":
        return rd["full_name"]
    if kind == "dob":
        return rd["dob"]               # YYYY-MM-DD
    if kind == "dob_month":
        return "06"
    if kind == "dob_day":
        return "15"
    if kind == "dob_year":
        return "1995"
    if kind == "zip":
        return rd["zip"]
    if kind == "city":
        return "New York"
    if kind == "country":
        return "United States"
    if kind == "text":
        return rd["username"]
    return ""


def _pick_select_option(field: dict, kind: str, country: dict | None = None) -> str | None:
    """Pick the most appropriate <option> value for a select element."""
    options = field.get("options") or []
    if not options:
        return None
    country = country or {"calling_code": "1", "name": "United States", "iso2": "US"}

    def by_text(needles: list[str]) -> str | None:
        for o in options:
            txt = (o.get("text") or "").lower()
            if any(n in txt for n in needles):
                return o.get("value")
        return None

    def by_value(needles: list[str]) -> str | None:
        for o in options:
            v = (o.get("value") or "").lower()
            if any(n in v for n in needles):
                return o.get("value")
        return None

    # Detect a country-code dropdown (options like "+1", "+44 (UK)", "(91) India")
    looks_like_code = sum(
        1 for o in options
        if "+" in (o.get("text") or "") or
           re.match(r"^\(?\+?\d{1,4}\)?", (o.get("text") or "").strip())
    ) >= max(3, len(options) // 3)

    if kind == "gender":
        return by_text(["male", "m"]) or (options[1]["value"] if len(options) > 1 else options[0]["value"])
    if kind == "country" or kind == "country_code":
        cc = country.get("calling_code") or ""
        name = (country.get("name") or "").lower()
        iso = (country.get("iso2") or "").lower()
        if looks_like_code and cc:
            v = by_text([f"+{cc}", f"({cc})", f" {cc} "])
            if v is not None:
                return v
            v = by_value([f"+{cc}", cc])
            if v is not None:
                return v
        if name:
            v = by_text([name])
            if v is not None:
                return v
        if iso:
            v = by_value([iso])
            if v is not None:
                return v
        v = by_text(["united states", "usa", "us "])
        if v is not None:
            return v
    if kind == "dob_month":
        return by_text(["june", "jun", "06"]) or (options[6]["value"] if len(options) > 6 else None)
    if kind == "dob_day":
        return by_text([" 15", "15"]) or (options[15]["value"] if len(options) > 15 else None)
    if kind == "dob_year":
        return by_text(["1995"]) or (options[20]["value"] if len(options) > 20 else None)
    # Default: first non-empty, non-placeholder option
    for o in options:
        v = (o.get("value") or "").strip()
        t = (o.get("text") or "").strip().lower()
        if v and not any(p in t for p in ("select", "choose", "pick", "--", "please")):
            return v
    return options[0].get("value") if options else None


def _pick_radio_option(field: dict, kind: str) -> int | None:
    """Pick which radio button (by ri index) to click."""
    options = field.get("options") or []
    if not options:
        return None
    if kind == "gender":
        for o in options:
            t = (o.get("text") or o.get("value") or "").lower()
            if "male" in t and "female" not in t:
                return o.get("ri")
        return options[0].get("ri")
    return options[0].get("ri")


async def _try_solve_captcha(page, ai_solution: str | None = None) -> bool:
    """Best-effort: tick reCAPTCHA / hCaptcha / Turnstile checkboxes, fill
    image-CAPTCHA solution if the AI provided one. Returns True if anything
    was attempted successfully."""
    did = False
    # 1) Google reCAPTCHA v2 anchor checkbox
    try:
        rc = page.frame_locator('iframe[src*="recaptcha/api2/anchor"], iframe[title*="reCAPTCHA" i]').first
        cb = rc.locator('#recaptcha-anchor, .recaptcha-checkbox, .recaptcha-checkbox-border').first
        if await cb.count():
            await cb.click(timeout=4000, force=True)
            did = True
            logger.info("captcha: clicked reCAPTCHA checkbox")
    except Exception:
        pass
    # 2) hCaptcha checkbox
    try:
        hc = page.frame_locator('iframe[src*="hcaptcha.com"], iframe[title*="hCaptcha" i]').first
        cb = hc.locator('#checkbox, [role=checkbox]').first
        if await cb.count():
            await cb.click(timeout=4000, force=True)
            did = True
            logger.info("captcha: clicked hCaptcha checkbox")
    except Exception:
        pass
    # 3) Cloudflare Turnstile
    try:
        cf = page.frame_locator('iframe[src*="challenges.cloudflare.com"]').first
        cb = cf.locator('input[type=checkbox], label').first
        if await cb.count():
            await cb.click(timeout=4000, force=True)
            did = True
            logger.info("captcha: clicked Cloudflare Turnstile")
    except Exception:
        pass
    # 4) Plain "I am human" / "I am not a robot" buttons in main frame
    for sel in (
        'button:has-text("I am human")',
        'button:has-text("I\'m not a robot")',
        'button:has-text("Verify")',
        'label:has-text("I am human")',
    ):
        try:
            b = page.locator(sel).first
            if await b.count() and await b.is_visible():
                await b.click(timeout=3000, force=True)
                did = True
                logger.info(f"captcha: clicked '{sel}'")
                break
        except Exception:
            continue
    # 5) AI-suggested solution → fill into a captcha-looking input
    if ai_solution:
        for sel in (
            'input[name*="captcha" i]',
            'input[id*="captcha" i]',
            'input[placeholder*="captcha" i]',
            'input[aria-label*="captcha" i]',
            'input[name*="code" i]:not([type=hidden])',
        ):
            try:
                inp = page.locator(sel).first
                if await inp.count() and await inp.is_visible():
                    await inp.fill(ai_solution, timeout=ACTION_TIMEOUT_MS)
                    did = True
                    logger.info(f"captcha: filled solution into {sel}")
                    break
            except Exception:
                continue
    if did:
        try:
            await page.wait_for_timeout(2500)
        except Exception:
            pass
    return did


def _form_signature(form: dict) -> str:
    """Stable fingerprint of a form's input set, used to detect 'next page'."""
    parts = []
    for f in form.get("inputs", []):
        parts.append("|".join((
            (f.get("name") or ""),
            (f.get("id") or ""),
            (f.get("type") or ""),
            (f.get("placeholder") or ""),
            (f.get("label") or "")[:40],
        )))
    return "##".join(parts)


async def _fill_chosen_form(
    page, form: dict, number: str,
    ai_fields: list[dict] | None = None,
    country: dict | None = None,
) -> tuple[int, int, bool]:
    """Fill the chosen form, optionally guided by AI-detected fields. Returns
    (filled_count, total_fields, submitted)."""
    rd = _random_data()
    country = country or _country_from_phone(number)
    filled = 0
    inputs = form.get("inputs", [])
    total = len(inputs)
    # Use AI hints by INDEX (the AI sees fields in the same order)
    ai_by_idx = {}
    if ai_fields:
        for idx, ai in enumerate(ai_fields):
            ai_by_idx[idx] = ai

    for idx, f in enumerate(inputs):
        kind = _classify_field(f)
        ai_field = ai_by_idx.get(idx) or {}
        ai_label = (ai_field.get("label") or "").strip() if ai_field else ""
        ai_value = (ai_field.get("value_hint") or "").strip() if ai_field else ""
        sel = f'[data-pw-field-idx="{f["fi"]}-{f["i"]}"]'
        ftype = (f.get("type") or "").lower()
        ftag = (f.get("tag") or "").lower()

        try:
            # ── SELECT (dropdown) ────────────────────────────────────
            if ftag == "select":
                # Auto-detect a country-code dropdown by its options
                opts = f.get("options") or []
                code_like = sum(
                    1 for o in opts
                    if "+" in (o.get("text") or "") or
                       re.match(r"^\(?\+?\d{1,4}\)?", (o.get("text") or "").strip())
                ) >= max(3, len(opts) // 3)
                pick_kind = kind
                if code_like and kind not in ("country", "country_code"):
                    pick_kind = "country_code"
                target = _pick_select_option(f, pick_kind, country=country)
                if not target and ai_value:
                    target = ai_value
                if target:
                    await page.locator(sel).first.select_option(value=target, timeout=ACTION_TIMEOUT_MS)
                    filled += 1
                    continue
            # ── RADIO GROUP (gender etc) ─────────────────────────────
            if ftype == "radio-group":
                ri = _pick_radio_option(f, kind)
                if ri is not None:
                    rsel = f'[data-pw-radio-idx="{f["fi"]}-{f["i"]}-{ri}"]'
                    await page.locator(rsel).first.check(timeout=ACTION_TIMEOUT_MS, force=True)
                    filled += 1
                    continue
            # ── CHECKBOX (terms) ─────────────────────────────────────
            if ftype == "checkbox":
                lab = (f.get("label") or "").lower()
                if any(k in lab for k in ("terms", "agree", "privacy", "policy", "consent", "rule")):
                    await page.locator(sel).first.check(timeout=ACTION_TIMEOUT_MS, force=True)
                    filled += 1
                continue
            # ── DATE input ───────────────────────────────────────────
            if ftype == "date":
                await page.locator(sel).first.fill(rd["dob"], timeout=ACTION_TIMEOUT_MS)
                filled += 1
                continue
            # ── TEXT-LIKE inputs ─────────────────────────────────────
            if kind == "skip" and not ai_label and not ai_value:
                continue
            value = ai_value or _value_for_field(kind, number, rd, ai_label)
            if not value:
                continue
            await page.locator(sel).first.fill(value, timeout=ACTION_TIMEOUT_MS)
            filled += 1
        except Exception as e:
            logger.debug(f"fill skip {f.get('name') or f.get('id') or idx}: {e}")
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
    return filled, total, submitted


async def _scroll_through_page(page) -> None:
    """Encourage lazy-loaded content to render before screenshot."""
    try:
        for y in (300, 800, 1400, 2000):
            await page.evaluate(f"window.scrollTo(0, {y})")
            await page.wait_for_timeout(250)
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(200)
    except Exception:
        pass


async def _wait_for_real_render(page) -> None:
    """White-page protection — wait until the document body has meaningful
    content, the network is mostly idle, and lazy widgets have rendered."""
    # Step 1: DOM is parsed
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:
        pass
    # Step 2: full `load` event (CSS/images/fonts) — important for SPA shells
    try:
        await page.wait_for_load_state("load", timeout=15000)
    except Exception:
        pass
    # Step 3: page rendered enough text to be meaningful (kills white-screen)
    try:
        await page.wait_for_function(
            "document.body && document.body.innerText.trim().length > 30",
            timeout=12000,
        )
    except Exception:
        pass
    # Step 4: SPA hydration — wait for some interactive element OR a form input
    try:
        await page.wait_for_function(
            """
            () => {
                if (!document.body) return false;
                const inputs = document.querySelectorAll('input,select,textarea,button');
                return inputs.length >= 2;
            }
            """,
            timeout=10000,
        )
    except Exception:
        pass
    # Step 5: network mostly idle — give late XHR/JS a chance to finish
    try:
        await page.wait_for_load_state("networkidle", timeout=12000)
    except Exception:
        pass
    # Step 6: trigger lazy-loaded sections via scroll
    await _scroll_through_page(page)
    await page.wait_for_timeout(1500)


async def _wait_for_fillable_form(page, kind: str) -> bool:
    """Wait until at least one visible input field appears so we don't try
    to fill a form that hasn't rendered yet. Returns True if found."""
    selectors = [
        "form input:not([type=hidden])",
        "input[type=email]",
        "input[type=tel]",
        "input[type=password]",
        "input[name*=phone i]",
        "input[name*=mobile i]",
        "input[name*=email i]",
        "input[name*=user i]",
        "input[placeholder*=phone i]",
        "input[placeholder*=email i]",
        "input[placeholder*=user i]",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            await loc.wait_for(state="visible", timeout=FORM_WAIT_MS // len(selectors) + 500)
            return True
        except Exception:
            continue
    # Last-ditch: any form at all
    try:
        await page.locator("form").first.wait_for(state="attached", timeout=2000)
        return True
    except Exception:
        return False


async def _new_stealth_context(browser):
    context = await browser.new_context(
        viewport=VIEWPORT,
        user_agent=USER_AGENT,
        locale="en-US",
        timezone_id="America/New_York",
        ignore_https_errors=True,
        java_script_enabled=True,
        extra_http_headers={
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Sec-Ch-Ua": '"Chromium";v="131", "Google Chrome";v="131"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Upgrade-Insecure-Requests": "1",
        },
    )
    # Patch navigator.webdriver and plugins so the page sees a "real" browser.
    await context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
        window.chrome = { runtime: {} };
    """)
    return context


async def capture(
    browser,
    platform: str,
    number: str,
    url: str,
    kind: str,
    use_ai: bool = True,
) -> CaptureResult:
    """Capture a URL with form fill + submit. Always returns a CaptureResult,
    even on error (with a placeholder image)."""
    if not url:
        png = _placeholder_png(platform, number, kind, "no URL configured for this site")
        return CaptureResult(png, "", "", False, False, None, None,
                             "no URL configured", "missing url")

    context = None
    error: str | None = None
    final_url = url
    try:
        context = await _new_stealth_context(browser)
        page = await context.new_page()
        page.set_default_timeout(ACTION_TIMEOUT_MS)
        page.set_default_navigation_timeout(NAV_TIMEOUT_MS)

        # Try a forgiving navigation: 'load' first, fall back to 'domcontentloaded'.
        try:
            await page.goto(url, timeout=NAV_TIMEOUT_MS, wait_until="load")
        except Exception as e1:
            try:
                await page.goto(url, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
            except Exception as e2:
                error = f"navigation failed: {str(e2)[:140]}"
                logger.warning(f"{platform} {kind}: {error}")

        await _wait_for_real_render(page)
        # Wait a bit more specifically for a fillable form to appear.
        await _wait_for_fillable_form(page, kind)

        try:
            title = await page.title() or ""
        except Exception:
            title = ""
        try:
            text = await page.evaluate(
                "document.body ? document.body.innerText.slice(0, 4000) : ''"
            )
        except Exception:
            text = ""
        try:
            html_snip = await page.evaluate(
                "document.documentElement ? "
                "document.documentElement.outerHTML.slice(0, 4000) : ''"
            )
        except Exception:
            html_snip = ""

        blocked, captcha, hint = _detect_blocked_or_captcha(text, title)

        # Heuristic form scan
        try:
            forms = await page.evaluate(_FORM_SCAN_JS, kind)
        except Exception as e:
            logger.debug(f"form scan error: {e}")
            forms = []
        best = forms[0] if forms else None

        # AI vision pass — gives us field hints AND independent CAPTCHA detection
        ai_fields: list[dict] = []
        ai_summary = ""
        if use_ai and not blocked:
            try:
                screenshot_for_ai = await page.screenshot(full_page=False, timeout=ACTION_TIMEOUT_MS)
                ai = await ai_helper.analyze_page(
                    screenshot_for_ai, text, html_snip,
                    purpose=f"{kind} for {platform} with phone +{number}",
                )
                ai_summary = ai.get("summary", "")
                if ai.get("captcha_present"):
                    captcha = True
                    hint = (hint or ai.get("block_reason")
                            or f"CAPTCHA detected ({ai.get('captcha_kind')})")
                if ai.get("blocked"):
                    blocked = True
                    hint = hint or ai.get("block_reason") or "AI: page blocked"
                ai_fields = ai.get("fields") or []
            except Exception as e:
                logger.debug(f"AI analyze_page error: {e}")

        # Multi-step fill + submit (handles signup wizards across 1–3 pages)
        fields_filled = 0
        fields_total = 0
        submitted_form = False
        form_found = bool(best)
        country_ctx = _country_from_phone(number)
        seen_signatures: set[str] = set()
        MAX_STEPS = 3
        # If the page already shows a CAPTCHA, try to solve it first so we
        # can still attempt the signup/signin flow.
        if best and captcha and not blocked:
            try:
                solved = await _try_solve_captcha(page, ai_solution=None)
                if solved:
                    await page.wait_for_timeout(2000)
                    # Re-evaluate: maybe we passed the challenge
                    try:
                        text_after = await page.evaluate(
                            "document.body ? document.body.innerText.slice(0,3000) : ''"
                        )
                    except Exception:
                        text_after = ""
                    _b, _c, _h = _detect_blocked_or_captcha(text_after, title)
                    if not _c:
                        captcha = False
                        hint = None
            except Exception as e:
                logger.debug(f"initial captcha solve error: {e}")
        if best and not blocked and not captcha:
            for step in range(MAX_STEPS):
                # Re-scan from the live page on every step (the DOM has changed)
                try:
                    forms_now = await page.evaluate(_FORM_SCAN_JS, kind)
                except Exception as e:
                    logger.debug(f"form re-scan error step={step}: {e}")
                    forms_now = []
                if not forms_now:
                    break
                step_form = forms_now[0]
                sig = _form_signature(step_form)
                if not sig or sig in seen_signatures:
                    # Same form as last step → no progress, stop
                    break
                seen_signatures.add(sig)
                pre_url = page.url
                # AI hints: only for the first step (saves tokens)
                step_ai = ai_fields if step == 0 else []
                try:
                    sf, st, sub = await _fill_chosen_form(
                        page, step_form, number,
                        ai_fields=step_ai, country=country_ctx,
                    )
                except Exception as e:
                    logger.debug(f"fill form error step={step}: {e}")
                    sf, st, sub = 0, 0, False
                fields_filled += sf
                fields_total += st
                submitted_form = submitted_form or sub
                logger.info(
                    f"{platform} {kind} step{step+1}: filled={sf}/{st} submitted={sub}"
                )
                if not sub:
                    break
                # Wait for the page to react: URL change, result text, OR a brand new form
                try:
                    await page.wait_for_function(
                        """
                        (preUrl) => {
                            if (location.href !== preUrl) return true;
                            const t = (document.body && document.body.innerText || '').toLowerCase();
                            return /already|exists|registered|taken|verify|verification|sent|otp|code|invalid|incorrect|error|success|welcome|account created|check your (email|inbox|sms)/.test(t);
                        }
                        """,
                        arg=pre_url,
                        timeout=POST_SUBMIT_WAIT_MS,
                    )
                except Exception:
                    pass
                try:
                    await page.wait_for_load_state("networkidle", timeout=6000)
                except Exception:
                    pass
                await page.wait_for_timeout(1500)
                # If a CAPTCHA appeared between steps, try to solve before continuing
                try:
                    inter_text = await page.evaluate(
                        "document.body ? document.body.innerText.slice(0,2000) : ''"
                    )
                except Exception:
                    inter_text = ""
                _b, c_inter, _h = _detect_blocked_or_captcha(inter_text, title)
                if c_inter:
                    captcha = True
                    await _try_solve_captcha(page, ai_solution=None)
                    await page.wait_for_timeout(1500)
                # Stop early if a clear final-result keyword is showing
                low = (inter_text or "").lower()
                if any(k in low for k in (
                    "already", "exists", "registered", "account created",
                    "welcome", "check your email", "check your inbox", "check your sms",
                    "verification code sent", "otp sent",
                )):
                    break

        # Final screenshot
        try:
            png = await page.screenshot(full_page=False, timeout=ACTION_TIMEOUT_MS)
        except Exception as e:
            error = error or f"screenshot failed: {e}"
            png = _placeholder_png(platform, number, kind, error or "screenshot failed")

        try:
            final_url = page.url
        except Exception:
            pass
        try:
            text2 = await page.evaluate(
                "document.body ? document.body.innerText.slice(0, 4000) : ''"
            )
            if text2 and len(text2.strip()) > len(text.strip()):
                text = text2
        except Exception:
            pass
        # Re-evaluate captcha/block on final state too.
        b2, c2, h2 = _detect_blocked_or_captcha(text, title)
        blocked = blocked or b2
        captcha = captcha or c2
        hint = hint or h2

        # AI-suggested CAPTCHA solution (only when CAPTCHA present)
        captcha_solution = None
        if captcha and use_ai:
            try:
                ai2 = await ai_helper.analyze_page(
                    png, text, html_snip,
                    purpose=f"Solve CAPTCHA on {platform} ({kind})",
                )
                captcha_solution = ai2.get("captcha_solution")
            except Exception as e:
                logger.debug(f"AI captcha solution error: {e}")

        # White-page guard: if the page is essentially empty, prefer the
        # placeholder so the user gets a clear reason instead of a blank.
        if (not error and not blocked and not captcha
                and len((text or "").strip()) < 5
                and len(png) < 7000):
            png = _placeholder_png(
                platform, number, kind,
                "Page rendered blank — likely anti-bot block. "
                f"URL: {final_url}",
            )
            error = "page rendered blank"

        summary_bits = [s for s in (ai_summary, hint) if s]
        summary = " | ".join(summary_bits) or (title[:80] or "captured")

        return CaptureResult(
            png=png, text=text, url=final_url,
            blocked=blocked, captcha_present=captcha,
            captcha_kind=None, captcha_solution=captcha_solution,
            summary=summary, error=error,
            fields_total=fields_total, fields_filled=fields_filled,
            submitted=submitted_form, form_found=form_found,
        )
    except Exception as e:
        logger.error(f"capture {platform}/{number} {kind}: {e}")
        png = _placeholder_png(platform, number, kind, f"{type(e).__name__}: {e}")
        return CaptureResult(png, "", final_url, False, False, None, None,
                             f"capture error: {e}", str(e))
    finally:
        if context is not None:
            try:
                await context.close()
            except Exception:
                pass


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


async def capture_signup_and_signin(
    platform: str, number: str,
    signup_url: str, signin_url: str,
    timeout: float = 90.0,
    use_ai: bool = True,
) -> tuple[CaptureResult, CaptureResult]:
    """Capture (signup, signin) screenshots/results for one (platform, number)
    pair. Wall-clock-capped; on timeout returns placeholder results."""
    try:
        browser = await browser_pool.get()
    except Exception as e:
        logger.error(f"browser launch error: {e}")
        ph = _placeholder_png(platform, number, "Capture", f"browser launch failed: {e}")
        r = CaptureResult(ph, "", "", False, False, None, None,
                          "browser launch failed", str(e))
        return r, r

    async def _both():
        a = await capture(browser, platform, number, signup_url, "Signup", use_ai=use_ai)
        b = await capture(browser, platform, number, signin_url, "Signin", use_ai=use_ai)
        return a, b

    try:
        return await asyncio.wait_for(_both(), timeout=timeout)
    except asyncio.TimeoutError:
        ph = _placeholder_png(platform, number, "Capture", f"timed out after {timeout}s")
        r = CaptureResult(ph, "", "", False, False, None, None,
                          f"timed out after {timeout}s", "timeout")
        return r, r
    except Exception as e:
        ph = _placeholder_png(platform, number, "Capture", f"capture error: {e}")
        r = CaptureResult(ph, "", "", False, False, None, None,
                          f"capture error: {e}", str(e))
        return r, r
