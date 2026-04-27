# Phone Number Platform Checker — Telegram Bot

## Overview
A Python Telegram bot that takes phone numbers, tries `signup` and `signin`
on a configurable list of websites, and reports a verdict per number/site
along with screenshots of the actual pages.

## Stack
- **Language / runtime**: Python 3.11
- **Bot framework**: `python-telegram-bot` 22.x
- **Headless browser**: Playwright (Chromium)
- **AI helper**: OpenAI (gpt-5-mini) via the Replit AI Integrations proxy
- **Misc**: pandas + openpyxl (file uploads), Pillow (result-card images),
  beautifulsoup4 + httpx (legacy HTTP fallbacks)

## Files
- `bot.py` — Telegram entry point. Menus for site selection, *site management
  (add/remove/list/reset)*, number paste/upload, live progress, summary.
- `sites.py` — JSON-backed dynamic site store (`sites.json`). Each site has
  `name`, `signup_url`, `signin_url`, `field_count`, `notes`.
- `screenshotter.py` — Playwright capture with anti-blank-page hardening
  (realistic UA, network-idle, scroll, `webdriver` patch), AI-assisted form
  filling, CAPTCHA / anti-bot detection.
- `ai_helper.py` — OpenAI client wrapped against the Replit AI Integrations
  proxy. Two entry points: `analyze_page()` (vision: fields + CAPTCHA) and
  `interpret_result_text()` (verdict from visible text).
- `platform_checker.py` — Glue: per-site `check_platform()`, result-card
  rendering, run summary.

## Key Commands
- `python bot.py` — run the bot (managed by the `Telegram Bot` workflow).
- `python -m playwright install chromium` — re-install browser binaries
  if the cache is wiped.

## Required Secrets
- `TELEGRAM_BOT_TOKEN` — from @BotFather.
- `AI_INTEGRATIONS_OPENAI_API_KEY` + `AI_INTEGRATIONS_OPENAI_BASE_URL` —
  provisioned via the Replit AI integration; used for vision/text calls.

## Workflow
- `Telegram Bot` (console) — long-polls Telegram. The two TS artifact
  workflows (`api-server`, `mockup-sandbox`) are unrelated leftovers from
  the original template and can stay running idle without affecting the bot.

## Recent Changes
- **Smarter signup-form filling (2026-04-27)**: form scanner now also collects `<label>` text near each input, the full list of `<select>` options, and groups radio buttons (e.g. gender) into one synthetic field with all choices. Classifier now recognises gender, dob (date input or 3 separate Month/Day/Year selects), country/nationality, city, and terms checkboxes. Filler uses `select_option()` for dropdowns, `check()` for radios/checkboxes, and a real `YYYY-MM-DD` for date inputs. AI prompt updated to return per-field {label, type, value_hint} in visual order, including gender and date-of-birth.
- **Multi-page signups + country-aware fills (2026-04-27)**: capture loop now fills + submits up to 3 sequential forms (handles signup wizards like Apple/Microsoft that ask for email → password → name → birthday across separate pages). Phone number is mapped to a country (~110 calling codes built-in: US/UK/IN/RU/CN/etc.); country `<select>`s and country-CODE selects (`+1`, `+44 …`) are picked automatically to match. Added `_try_solve_captcha()` that ticks reCAPTCHA / hCaptcha / Cloudflare Turnstile checkboxes and clicks "I am human" buttons; image-/text-CAPTCHA solutions from the AI are auto-typed into captcha inputs. Captcha is attempted once before fill and again between every page step.
