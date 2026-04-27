"""Site configuration store. Sites are persisted as JSON so the user can
add/remove them at runtime from the Telegram bot."""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import TypedDict

logger = logging.getLogger(__name__)

SITES_FILE = os.environ.get("SITES_FILE", "sites.json")
_lock = threading.Lock()


class Site(TypedDict, total=False):
    name: str
    signup_url: str
    signin_url: str
    field_count: int
    notes: str


DEFAULT_SITES: list[Site] = [
    {"name": "WhatsApp",  "signup_url": "https://www.whatsapp.com/",
     "signin_url": "https://web.whatsapp.com/", "field_count": 1, "notes": "Phone-only"},
    {"name": "Telegram",  "signup_url": "https://my.telegram.org/auth",
     "signin_url": "https://web.telegram.org/", "field_count": 1, "notes": "Phone-only"},
    {"name": "Facebook",  "signup_url": "https://www.facebook.com/r.php",
     "signin_url": "https://www.facebook.com/login/", "field_count": 4, "notes": ""},
    {"name": "Instagram", "signup_url": "https://www.instagram.com/accounts/emailsignup/",
     "signin_url": "https://www.instagram.com/accounts/login/", "field_count": 4, "notes": ""},
    {"name": "Google",    "signup_url": "https://accounts.google.com/signup",
     "signin_url": "https://accounts.google.com/signin", "field_count": 1, "notes": ""},
    {"name": "Microsoft", "signup_url": "https://signup.live.com/signup",
     "signin_url": "https://login.live.com/", "field_count": 1, "notes": ""},
    {"name": "Apple",     "signup_url": "https://appleid.apple.com/account",
     "signin_url": "https://appleid.apple.com/sign-in", "field_count": 1, "notes": ""},
    {"name": "Amazon",    "signup_url": "https://www.amazon.com/ap/register",
     "signin_url": "https://www.amazon.com/ap/signin", "field_count": 1, "notes": ""},
    {"name": "TikTok",    "signup_url": "https://www.tiktok.com/signup/phone-or-email/phone",
     "signin_url": "https://www.tiktok.com/login/phone-or-email/phone", "field_count": 1, "notes": ""},
    {"name": "Snapchat",  "signup_url": "https://accounts.snapchat.com/accounts/signup",
     "signin_url": "https://accounts.snapchat.com/accounts/login", "field_count": 1, "notes": ""},
    {"name": "GitHub",    "signup_url": "https://github.com/signup",
     "signin_url": "https://github.com/login", "field_count": 2, "notes": ""},
    {"name": "Uber",      "signup_url": "https://auth.uber.com/v2/",
     "signin_url": "https://auth.uber.com/v2/", "field_count": 1, "notes": ""},
    {"name": "Booking",   "signup_url": "https://account.booking.com/register",
     "signin_url": "https://account.booking.com/sign-in", "field_count": 1, "notes": ""},
    {"name": "LINE",      "signup_url": "https://account.line.biz/signup",
     "signin_url": "https://account.line.biz/login", "field_count": 1, "notes": ""},
    {"name": "Viber",     "signup_url": "https://www.viber.com/",
     "signin_url": "https://www.viber.com/", "field_count": 1, "notes": "App-based"},
    {"name": "Samsung",   "signup_url": "https://account.samsung.com/membership/intro",
     "signin_url": "https://account.samsung.com/", "field_count": 1, "notes": ""},
    {"name": "Huawei",    "signup_url": "https://id.huawei.com/CAS/portal/userRegister/regbyphone.html",
     "signin_url": "https://id.huawei.com/", "field_count": 1, "notes": ""},
    {"name": "Tinder",    "signup_url": "https://tinder.com/",
     "signin_url": "https://tinder.com/", "field_count": 1, "notes": ""},
    {"name": "OK.ru",     "signup_url": "https://ok.ru/dk?st.cmd=anonymRegistrationEnterPhone",
     "signin_url": "https://ok.ru/", "field_count": 1, "notes": ""},
]


def _load_raw() -> dict:
    if not os.path.exists(SITES_FILE):
        data = {"sites": DEFAULT_SITES}
        _save_raw(data)
        return data
    try:
        with open(SITES_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if "sites" not in data or not isinstance(data["sites"], list):
            raise ValueError("missing sites array")
        return data
    except Exception as e:
        logger.error(f"sites file unreadable ({e}) — recreating with defaults")
        data = {"sites": DEFAULT_SITES}
        _save_raw(data)
        return data


def _save_raw(data: dict) -> None:
    tmp = SITES_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, SITES_FILE)


def list_sites() -> list[Site]:
    with _lock:
        return list(_load_raw()["sites"])


def site_names() -> list[str]:
    return [s["name"] for s in list_sites()]


def get_site(name: str) -> Site | None:
    key = (name or "").strip().lower()
    for s in list_sites():
        if s["name"].lower() == key:
            return s
    return None


def add_site(site: Site) -> tuple[bool, str]:
    name = (site.get("name") or "").strip()
    if not name:
        return False, "Site name is required"
    if not (site.get("signup_url") or site.get("signin_url")):
        return False, "At least one of signup_url or signin_url is required"
    with _lock:
        data = _load_raw()
        for s in data["sites"]:
            if s["name"].lower() == name.lower():
                return False, f"Site '{name}' already exists"
        clean: Site = {
            "name": name,
            "signup_url": (site.get("signup_url") or "").strip(),
            "signin_url": (site.get("signin_url") or "").strip(),
            "field_count": int(site.get("field_count") or 1),
            "notes": (site.get("notes") or "").strip(),
        }
        data["sites"].append(clean)
        _save_raw(data)
        return True, f"Added site '{name}'"


def update_site(name: str, updates: Site) -> tuple[bool, str]:
    key = (name or "").strip().lower()
    with _lock:
        data = _load_raw()
        for s in data["sites"]:
            if s["name"].lower() == key:
                for k, v in updates.items():
                    if k == "field_count":
                        try:
                            s[k] = int(v)
                        except Exception:
                            pass
                    elif k in ("name", "signup_url", "signin_url", "notes"):
                        s[k] = (v or "").strip()
                _save_raw(data)
                return True, f"Updated '{s['name']}'"
        return False, f"Site '{name}' not found"


def remove_site(name: str) -> tuple[bool, str]:
    key = (name or "").strip().lower()
    with _lock:
        data = _load_raw()
        before = len(data["sites"])
        data["sites"] = [s for s in data["sites"] if s["name"].lower() != key]
        if len(data["sites"]) == before:
            return False, f"Site '{name}' not found"
        _save_raw(data)
        return True, f"Removed '{name}'"


def reset_to_defaults() -> None:
    with _lock:
        _save_raw({"sites": list(DEFAULT_SITES)})
