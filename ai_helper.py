"""AI-powered helpers: form-field analysis from a page screenshot, CAPTCHA
detection + best-effort solution suggestion, and result interpretation.

Uses the OpenAI client wired against the Replit AI Integrations proxy when
the AI_INTEGRATIONS_OPENAI_* env vars are present, otherwise falls back to
a normal OpenAI client (OPENAI_API_KEY)."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_VISION_MODEL = "gpt-5-mini"
_TEXT_MODEL = "gpt-5-mini"


def _safe_json_loads(raw: str) -> dict | None:
    """Parse model output that should be JSON. Tolerates empty strings,
    leading/trailing prose, and ```json fences."""
    if not raw:
        return None
    s = raw.strip()
    # strip code fences
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:].lstrip()
    try:
        return json.loads(s)
    except Exception:
        pass
    # find first {...} block
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(s[start:end + 1])
        except Exception:
            return None
    return None

_client = None
_client_lock = asyncio.Lock()
_disabled_reason: str | None = None


async def _get_client():
    """Lazy-instantiate the AsyncOpenAI client. Caches the disabled reason
    so we don't spam logs if no key is configured."""
    global _client, _disabled_reason
    if _client is not None or _disabled_reason is not None:
        return _client
    async with _client_lock:
        if _client is not None or _disabled_reason is not None:
            return _client
        try:
            from openai import AsyncOpenAI
        except Exception as e:
            _disabled_reason = f"openai package not installed: {e}"
            logger.warning(_disabled_reason)
            return None

        base_url = os.environ.get("AI_INTEGRATIONS_OPENAI_BASE_URL")
        api_key = (
            os.environ.get("AI_INTEGRATIONS_OPENAI_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
        )
        if not api_key:
            _disabled_reason = "no OPENAI_API_KEY / AI_INTEGRATIONS_OPENAI_API_KEY set"
            logger.warning(_disabled_reason)
            return None
        try:
            kwargs: dict[str, Any] = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            _client = AsyncOpenAI(**kwargs)
            logger.info(f"AI helper ready (base_url={'replit-proxy' if base_url else 'openai'})")
        except Exception as e:
            _disabled_reason = f"openai client init failed: {e}"
            logger.warning(_disabled_reason)
            _client = None
        return _client


def is_enabled() -> bool:
    return os.environ.get("AI_INTEGRATIONS_OPENAI_API_KEY") is not None or \
           os.environ.get("OPENAI_API_KEY") is not None


def disabled_reason() -> str:
    return _disabled_reason or "AI not configured"


async def analyze_page(
    screenshot_png: bytes,
    visible_text: str,
    page_html_snippet: str,
    purpose: str,
) -> dict:
    """Analyze a page screenshot + DOM snippet and return:
    {
      "captcha_present": bool,
      "captcha_kind": "image" | "checkbox" | "puzzle" | "text" | null,
      "captcha_solution": str | null,
      "fields": [{"label": str, "type": "phone|email|name|password|text|...", "value_hint": str}],
      "submit_label": str | null,
      "blocked": bool,
      "block_reason": str | null,
      "summary": str
    }
    Returns a structured dict even when AI is disabled (with sensible defaults)
    so callers don't need to special-case the off path."""
    fallback = {
        "captcha_present": False,
        "captcha_kind": None,
        "captcha_solution": None,
        "fields": [],
        "submit_label": None,
        "blocked": False,
        "block_reason": None,
        "summary": "AI analysis unavailable",
    }
    client = await _get_client()
    if client is None:
        fallback["summary"] = f"AI off: {disabled_reason()}"
        return fallback

    b64 = base64.b64encode(screenshot_png).decode("ascii")
    sys_prompt = (
        "You are a web-form analyzer. The user is trying to detect whether a "
        "given phone number is registered on a website by visually inspecting "
        "the auth page after submission. You will be given a screenshot of "
        "the page, a small text snippet, and a small HTML snippet. Return a "
        "single compact JSON object — no markdown, no commentary."
    )
    user_prompt = (
        f"Purpose: {purpose}\n"
        f"Visible text (truncated):\n{visible_text[:1500]}\n\n"
        f"HTML snippet (truncated):\n{page_html_snippet[:1500]}\n\n"
        "Return JSON with these keys:\n"
        "  captcha_present (bool),\n"
        "  captcha_kind (image|checkbox|puzzle|text|null),\n"
        "  captcha_solution (best-guess string for image/text CAPTCHAs, else null),\n"
        "  fields: array, IN VISUAL ORDER, each item is "
        "{label, type, value_hint}. type ∈ "
        "{first_name, last_name, full_name, username, email, phone, password, "
        "gender, dob, dob_month, dob_day, dob_year, country, city, zip, "
        "checkbox_terms, otp, captcha, other}. "
        "value_hint is a SHORT example value to fill (e.g. for gender: 'Male'; "
        "for dob: '1995-06-15'; for phone: '+15551234567'). "
        "Include EVERY visible input/select/radio-group on the form — even "
        "hidden-looking ones. Do NOT skip gender, date-of-birth or country.\n"
        "  submit_label (string or null),\n"
        "  blocked (bool — true if anti-bot/cloudflare wall),\n"
        "  block_reason (string or null),\n"
        "  summary (one short sentence describing the page and how to sign up)."
    )

    try:
        resp = await client.chat.completions.create(
            model=_VISION_MODEL,
            response_format={"type": "json_object"},
            max_completion_tokens=2000,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": [
                    {"type": "text", "text": user_prompt},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/png;base64,{b64}",
                    }},
                ]},
            ],
        )
        raw = (resp.choices[0].message.content or "").strip()
        data = _safe_json_loads(raw) or {}
        # normalize
        out = {**fallback, **{k: v for k, v in data.items() if k in fallback}}
        if not isinstance(out.get("fields"), list):
            out["fields"] = []
        return out
    except Exception as e:
        logger.warning(f"analyze_page error: {e}")
        fallback["summary"] = f"AI analysis error: {str(e)[:120]}"
        return fallback


async def interpret_result_text(
    platform: str,
    number: str,
    visible_text: str,
    purpose: str,
) -> dict:
    """Ask the model to produce a short verdict (registered/not_found/...)
    based on the visible text after a signup/signin attempt. Returns:
    { 'verdict': 'registered'|'not_found'|'otp_sent'|'otp_failed'|'unknown'|'error',
      'reason': str }"""
    fallback = {"verdict": "unknown", "reason": "AI not configured"}
    client = await _get_client()
    if client is None:
        return fallback

    sys_prompt = (
        "Given the visible text from an auth page after a signup or signin "
        "attempt, return JSON {verdict, reason}. verdict ∈ "
        "{registered, not_found, otp_sent, otp_failed, unknown, error}. "
        "Be conservative — only say 'registered' if the page clearly "
        "implies the account exists (e.g. 'enter your password'). "
        "Use 'otp_sent' if a code was clearly sent. Use 'unknown' otherwise."
    )
    try:
        resp = await client.chat.completions.create(
            model=_TEXT_MODEL,
            response_format={"type": "json_object"},
            max_completion_tokens=800,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content":
                    f"Platform: {platform}\nNumber: +{number}\nPurpose: {purpose}\n\n"
                    f"Visible text:\n{visible_text[:2000]}"},
            ],
        )
        raw = (resp.choices[0].message.content or "").strip()
        data = _safe_json_loads(raw) or {}
        v = (data.get("verdict") or "unknown").lower()
        if v not in ("registered", "not_found", "otp_sent", "otp_failed", "unknown", "error"):
            v = "unknown"
        return {"verdict": v, "reason": (data.get("reason") or "")[:200]}
    except Exception as e:
        logger.warning(f"interpret_result_text error: {e}")
        return {"verdict": "unknown", "reason": f"AI error: {str(e)[:120]}"}
