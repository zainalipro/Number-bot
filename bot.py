"""Telegram entry point for the Phone Number Platform Checker.

Improvements vs. the original:
- Site list is fully dynamic — managed from a new "Manage Sites" menu
  (add / remove / list / reset). No more hardcoded PLATFORMS list.
- Screenshots are taken with hardened anti-blank-page logic (see
  screenshotter.py) and analyzed by AI to fill forms and detect CAPTCHAs.
- Per-check verdict is enriched with CAPTCHA / anti-bot block info.
- All long-running work is wrapped in error-handling that never crashes
  the bot loop — every failure is reported to the user with context.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import re

import pandas as pd
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import ai_helper
import sites
from platform_checker import (
    STATUS_CAPTCHA,
    STATUS_BLOCKED,
    STATUS_ERROR,
    STATUS_LABELS,
    STATUS_NOT_FOUND,
    STATUS_OTP_SENT,
    STATUS_REGISTERED,
    build_summary,
    check_platform,
    get_platforms,
    make_result_card,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

PLATFORMS_PER_PAGE = 8
PER_CHECK_TIMEOUT = 150  # capturing 2 pages with full network-idle waits

stop_flags: dict[int, bool] = {}


# ───────────────────────────── helpers ─────────────────────────────

def normalize_phone(number: str) -> str:
    return re.sub(r"\D", "", number)


def get_user_platforms(context: ContextTypes.DEFAULT_TYPE) -> set[str]:
    all_names = set(get_platforms())
    if "selected_platforms" not in context.user_data:
        context.user_data["selected_platforms"] = set(all_names)
    else:
        # Drop any names that no longer exist (sites can be removed).
        context.user_data["selected_platforms"] &= all_names
    return context.user_data["selected_platforms"]


# ───────────────────────────── keyboards ─────────────────────────────

def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 Select Sites", callback_data="menu_platforms")],
        [InlineKeyboardButton("⚙️ Manage Sites", callback_data="menu_manage")],
        [InlineKeyboardButton("🔢 Upload Numbers (File)", callback_data="menu_upload_nums")],
        [InlineKeyboardButton("✏️ Paste Numbers", callback_data="menu_paste")],
        [InlineKeyboardButton("📊 Stats", callback_data="menu_stats")],
    ])


def stop_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🛑 Stop Checking", callback_data="stop_check")
    ]])


def back_to_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🏠 Main Menu", callback_data="menu_main")
    ]])


def manage_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Site", callback_data="manage_add")],
        [InlineKeyboardButton("➖ Remove Site", callback_data="manage_remove")],
        [InlineKeyboardButton("📋 List Sites", callback_data="manage_list")],
        [InlineKeyboardButton("♻️ Reset to Defaults", callback_data="manage_reset_confirm")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="menu_main")],
    ])


def platforms_keyboard(page: int, selected: set[str]) -> InlineKeyboardMarkup:
    names = get_platforms()
    if not names:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add a site first", callback_data="menu_manage")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="menu_main")],
        ])
    start = page * PLATFORMS_PER_PAGE
    end = min(start + PLATFORMS_PER_PAGE, len(names))
    page_items = names[start:end]
    total_pages = max(1, (len(names) + PLATFORMS_PER_PAGE - 1) // PLATFORMS_PER_PAGE)

    keyboard = []
    for plat in page_items:
        icon = "✅" if plat in selected else "⬜"
        keyboard.append([
            InlineKeyboardButton(f"{icon} {plat}", callback_data=f"toggle_{plat}"),
            InlineKeyboardButton("✏️", callback_data=f"platedit_{plat}"),
            InlineKeyboardButton("🗑", callback_data=f"platrm_{plat}"),
        ])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"plat_page_{page - 1}"))
    nav.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop"))
    if end < len(names):
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"plat_page_{page + 1}"))
    keyboard.append(nav)
    keyboard.append([
        InlineKeyboardButton("✅ Select All", callback_data="plat_select_all"),
        InlineKeyboardButton("⬜ Clear All", callback_data="plat_clear_all"),
    ])
    keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="menu_main")])
    return InlineKeyboardMarkup(keyboard)


def remove_sites_keyboard() -> InlineKeyboardMarkup:
    keyboard = []
    for s in sites.list_sites():
        keyboard.append([InlineKeyboardButton(
            f"🗑 {s['name']}", callback_data=f"remove_{s['name']}",
        )])
    keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="menu_main")])
    return InlineKeyboardMarkup(keyboard)


def edit_site_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Edit Name",        callback_data="editfld_name")],
        [InlineKeyboardButton("🔗 Edit Signup URL",  callback_data="editfld_signup")],
        [InlineKeyboardButton("🔑 Edit Signin URL",  callback_data="editfld_signin")],
        [InlineKeyboardButton("🔢 Edit Field Count", callback_data="editfld_count")],
        [InlineKeyboardButton("✅ Done", callback_data="editdone")],
    ])


def _site_summary_text(s) -> str:
    return (
        f"✏️ *Editing:* `{s['name']}`\n\n"
        f"🔗 *Signup URL:*  `{s.get('signup_url', '') or '—'}`\n"
        f"🔑 *Signin URL:*  `{s.get('signin_url', '') or '—'}`\n"
        f"🔢 *Field count:* `{s.get('field_count', 1)}`\n"
        f"📝 *Notes:* `{s.get('notes', '') or '—'}`\n\n"
        f"Pick a field to change, or tap *Done* when finished."
    )


# ───────────────────────────── number processing ─────────────────────────────

async def process_numbers(update: Update, context: ContextTypes.DEFAULT_TYPE, numbers: list[str]):
    user_id = update.effective_user.id
    raw_selected = get_user_platforms(context)
    stop_flags[user_id] = False

    # Only test sites the user picked AND that are actually usable
    # (still configured + at least one of signup/signin URL set).
    available: list[str] = []
    skipped: list[str] = []
    for name in sorted(raw_selected):
        s = sites.get_site(name)
        if not s:
            continue
        if not (s.get("signup_url") or s.get("signin_url")):
            skipped.append(name)
            continue
        available.append(name)
    selected = available

    if not selected:
        msg = "⚠️ No usable sites selected!\n\nPick at least one site that has a Signup or Signin URL."
        if skipped:
            msg += "\n\nSkipped (no URLs configured): " + ", ".join(f"`{x}`" for x in skipped)
        await update.message.reply_text(
            msg, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📱 Select Sites", callback_data="menu_platforms"),
                InlineKeyboardButton("⚙️ Manage Sites", callback_data="menu_manage"),
            ]]),
        )
        return

    if skipped:
        try:
            await update.message.reply_text(
                "ℹ️ Skipped (no URLs configured): " + ", ".join(f"`{x}`" for x in skipped),
                parse_mode="Markdown",
            )
        except Exception:
            pass

    total_combos = len(numbers) * len(selected)
    progress_msg = await update.message.reply_text(
        f"🚀 *Starting checks (per site)...*\n\n"
        f"📱 Sites: `{len(selected)}`\n"
        f"📞 Numbers per site: `{len(numbers)}`\n"
        f"📸 Total checks: `{total_combos}`\n\n"
        f"_All numbers are checked on one site before moving to the next._",
        parse_mode="Markdown",
        reply_markup=stop_keyboard(),
    )

    completed = 0
    stopped = False
    all_results: list[dict] = []

    for plat_idx, plat in enumerate(selected, 1):
        await asyncio.sleep(0)
        if stop_flags.get(user_id):
            stopped = True
            break

        header_msg = await update.message.reply_text(
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📱 *Site {plat_idx}/{len(selected)}:* `{plat}`\n"
            f"🔍 Trying signup → signin for {len(numbers)} number(s)...",
            parse_mode="Markdown",
        )

        plat_done = 0
        plat_registered = 0
        plat_not_found = 0
        plat_otp = 0
        plat_other = 0
        plat_fields_filled = 0
        plat_fields_total = 0
        plat_submits = 0

        for num_idx, number in enumerate(numbers, 1):
            await asyncio.sleep(0)
            if stop_flags.get(user_id):
                stopped = True
                break

            try:
                await progress_msg.edit_text(
                    f"🔄 *Live Progress*\n\n"
                    f"📱 Site: *{plat}*  ({plat_idx}/{len(selected)})\n"
                    f"📞 Number: `+{number}`  ({num_idx}/{len(numbers)})\n\n"
                    f"📊 *This site:*  `{plat_done}/{len(numbers)}` done\n"
                    f"  ✅ Registered: `{plat_registered}`\n"
                    f"  ❌ Not found: `{plat_not_found}`\n"
                    f"  📨 OTP: `{plat_otp}`  •  ⚠️ Other: `{plat_other}`\n"
                    f"  ✍️ Fields filled so far: `{plat_fields_filled}/{plat_fields_total}`"
                    f"  •  📤 Submits: `{plat_submits}`\n\n"
                    f"📈 *Overall:* `{completed}/{total_combos}` checks done\n\n"
                    f"⏳ Loading page → waiting for form → filling → reading result "
                    f"(max {PER_CHECK_TIMEOUT}s)...",
                    parse_mode="Markdown",
                    reply_markup=stop_keyboard(),
                )
            except Exception:
                pass

            timed_out = False
            result: dict | None = None
            check_task = None
            try:
                check_task = asyncio.create_task(check_platform(plat, number))
                try:
                    result = await asyncio.wait_for(check_task, timeout=PER_CHECK_TIMEOUT)
                except asyncio.TimeoutError:
                    timed_out = True
                    check_task.cancel()
                    try:
                        await check_task
                    except Exception:
                        pass
                    msg_t = f"Timed out after {PER_CHECK_TIMEOUT}s"
                    result = {
                        "platform": plat, "number": number,
                        "signup_status": STATUS_ERROR, "signup_msg": msg_t,
                        "signin_status": STATUS_ERROR, "signin_msg": msg_t,
                        "final_status": STATUS_ERROR,
                        "url": "", "signup_png": b"", "signin_png": b"",
                        "captcha_present": False, "blocked": False,
                        "card": make_result_card(
                            plat, number, STATUS_ERROR,
                            STATUS_ERROR, msg_t, STATUS_ERROR, msg_t, "",
                        ),
                    }
            except Exception as e:
                logger.error(f"Error on {plat}/{number}: {e}")
                em = f"Exception: {str(e)[:120]}"
                result = {
                    "platform": plat, "number": number,
                    "signup_status": STATUS_ERROR, "signup_msg": em,
                    "signin_status": STATUS_ERROR, "signin_msg": em,
                    "final_status": STATUS_ERROR,
                    "url": "", "signup_png": b"", "signin_png": b"",
                    "captcha_present": False, "blocked": False,
                    "card": make_result_card(
                        plat, number, STATUS_ERROR,
                        STATUS_ERROR, em, STATUS_ERROR, em, "",
                    ),
                }

            all_results.append(result)
            fs = result["final_status"]
            if fs == STATUS_REGISTERED:
                plat_registered += 1
            elif fs == STATUS_NOT_FOUND:
                plat_not_found += 1
            elif fs == STATUS_OTP_SENT:
                plat_otp += 1
            else:
                plat_other += 1
            plat_fields_filled += int(result.get("signup_fields_filled", 0)) + int(result.get("signin_fields_filled", 0))
            plat_fields_total += int(result.get("signup_fields_total", 0)) + int(result.get("signin_fields_total", 0))
            if result.get("signup_submitted"):
                plat_submits += 1
            if result.get("signin_submitted"):
                plat_submits += 1

            warning = ""
            if result.get("captcha_present"):
                warning = "\n🤖 _CAPTCHA / human verification detected on this site._"
            elif result.get("blocked"):
                warning = "\n🚧 _Anti-bot wall detected — site rejected the visit._"

            su_f = result.get("signup_fields_filled", 0)
            su_t = result.get("signup_fields_total", 0)
            su_s = result.get("signup_submitted", False)
            si_f = result.get("signin_fields_filled", 0)
            si_t = result.get("signin_fields_total", 0)
            si_s = result.get("signin_submitted", False)

            def _fc(found, f, t, sub):
                if not found:
                    return "no form found"
                tag = f"{f}/{t} fields filled"
                tag += " • submitted ✅" if sub else " • not submitted ⚠️"
                return tag

            su_line = _fc(result.get("signup_form_found", False), su_f, su_t, su_s)
            si_line = _fc(result.get("signin_form_found", False), si_f, si_t, si_s)

            caption = (
                f"📱 *{plat}* — `+{number}`  ({num_idx}/{len(numbers)})\n"
                f"🏁 *Verdict:* {STATUS_LABELS.get(fs, '⚠️')}\n"
                f"📝 *Signup:* {STATUS_LABELS.get(result['signup_status'], '⚠️')} "
                f"({su_line})\n   _{result['signup_msg'][:140]}_\n"
                f"🔑 *Signin:* {STATUS_LABELS.get(result['signin_status'], '⚠️')} "
                f"({si_line})\n   _{result['signin_msg'][:140]}_"
                + warning
                + ("\n⏱ _Timed out_" if timed_out else "")
            )
            try:
                await update.message.reply_photo(
                    photo=io.BytesIO(result["card"]),
                    caption=caption[:1020],
                    parse_mode="Markdown",
                )
            except Exception as e:
                logger.error(f"send card error: {e}")
                await update.message.reply_text(caption[:4000], parse_mode="Markdown")

            # Send the actual page screenshots captured during the check.
            try:
                signup_png = result.get("signup_png") or b""
                signin_png = result.get("signin_png") or b""
                media = []
                if signup_png:
                    media.append(InputMediaPhoto(
                        media=io.BytesIO(signup_png),
                        caption=(f"📝 *Signup page* — {plat} +{number}\n"
                                 f"_Final state after submitting random data + the phone._"),
                        parse_mode="Markdown",
                    ))
                if signin_png:
                    media.append(InputMediaPhoto(
                        media=io.BytesIO(signin_png),
                        caption=(f"🔑 *Signin page* — {plat} +{number}\n"
                                 f"_Final state after attempting login with the phone._"),
                        parse_mode="Markdown",
                    ))
                if len(media) == 2:
                    await update.message.reply_media_group(media=media)
                elif len(media) == 1:
                    await update.message.reply_photo(
                        photo=media[0].media, caption=media[0].caption,
                        parse_mode="Markdown",
                    )
            except Exception as e:
                logger.error(f"screenshot send error {plat}/{number}: {e}")
                try:
                    await update.message.reply_text(
                        f"⚠️ Could not send page screenshots for *{plat}* +{number}: `{str(e)[:120]}`",
                        parse_mode="Markdown",
                    )
                except Exception:
                    pass

            completed += 1
            plat_done += 1

        try:
            await update.message.reply_text(
                f"📊 *{plat}* — finished\n"
                f"`{plat_done}/{len(numbers)}` numbers checked  •  "
                f"✅ `{plat_registered}`  ❌ `{plat_not_found}`  📨 `{plat_otp}`  ⚠️ `{plat_other}`",
                parse_mode="Markdown",
            )
        except Exception:
            pass

        try:
            await header_msg.delete()
        except Exception:
            pass

    stop_flags.pop(user_id, None)

    try:
        await progress_msg.delete()
    except Exception:
        pass

    back_keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✏️ Check More", callback_data="menu_paste"),
        InlineKeyboardButton("🏠 Main Menu", callback_data="menu_main"),
    ]])

    summary_text = build_summary(all_results)
    header = "🛑 *Stopped by user* — partial summary\n\n" if stopped else "✅ *All done!*\n\n"
    full = header + summary_text
    try:
        if len(full) <= 4000:
            await update.message.reply_text(full, parse_mode="Markdown",
                                            reply_markup=back_keyboard)
        else:
            await update.message.reply_text(header + "Summary attached as file.",
                                            parse_mode="Markdown")
            await update.message.reply_document(
                document=io.BytesIO(summary_text.encode("utf-8")),
                filename="summary.txt",
                reply_markup=back_keyboard,
            )
    except Exception as e:
        logger.error(f"summary send error: {e}")
        await update.message.reply_text(
            f"{header}Done. Total: {len(all_results)} checks.",
            parse_mode="Markdown",
            reply_markup=back_keyboard,
        )


# ───────────────────────────── handlers ─────────────────────────────

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    get_user_platforms(context)
    ai_state = "🟢 ON" if ai_helper.is_enabled() else "🔴 OFF"
    await update.message.reply_text(
        "👋 *Phone Number Platform Checker*\n\n"
        "Paste or upload phone numbers and I'll try signup → signin on each site you "
        "selected, then send a result card and the actual page screenshots.\n\n"
        f"🌐 Sites configured: `{len(get_platforms())}`\n"
        f"🤖 AI form-filling & CAPTCHA detection: *{ai_state}*\n\n"
        "Choose an option below:",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id
    selected = get_user_platforms(context)
    names = get_platforms()

    # ── stop ────────────────────────────────────────────────────────
    if data == "stop_check":
        stop_flags[user_id] = True
        await query.edit_message_text(
            "🛑 *Stop signal sent!*\n\nFinishing current check, then stopping...",
            parse_mode="Markdown",
        )
        return

    # ── main menu ──────────────────────────────────────────────────
    if data == "menu_main":
        context.user_data.pop("mode", None)
        context.user_data.pop("add_site_state", None)
        context.user_data.pop("add_site_data", None)
        await query.edit_message_text(
            "👋 *Phone Number Platform Checker*\n\nChoose an option below:",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(),
        )

    # ── platforms select ───────────────────────────────────────────
    elif data == "menu_platforms":
        page = context.user_data.get("plat_page", 0)
        await query.edit_message_text(
            f"📱 *Select Sites*\n\n"
            f"Toggle which sites to check.\n"
            f"Selected: *{len(selected)}/{len(names)}*",
            parse_mode="Markdown",
            reply_markup=platforms_keyboard(page, selected),
        )

    elif data.startswith("plat_page_"):
        page = int(data.split("_")[-1])
        context.user_data["plat_page"] = page
        await query.edit_message_text(
            f"📱 *Select Sites*\n\nSelected: *{len(selected)}/{len(names)}*",
            parse_mode="Markdown",
            reply_markup=platforms_keyboard(page, selected),
        )

    elif data.startswith("toggle_"):
        plat = data[len("toggle_"):]
        if plat in selected:
            selected.discard(plat)
        else:
            selected.add(plat)
        context.user_data["selected_platforms"] = selected
        page = context.user_data.get("plat_page", 0)
        await query.edit_message_text(
            f"📱 *Select Sites*\n\nSelected: *{len(selected)}/{len(names)}*",
            parse_mode="Markdown",
            reply_markup=platforms_keyboard(page, selected),
        )

    elif data == "plat_select_all":
        context.user_data["selected_platforms"] = set(names)
        page = context.user_data.get("plat_page", 0)
        await query.edit_message_text(
            f"📱 *Select Sites*\n\nSelected: *{len(names)}/{len(names)}*",
            parse_mode="Markdown",
            reply_markup=platforms_keyboard(page, context.user_data["selected_platforms"]),
        )

    elif data == "plat_clear_all":
        context.user_data["selected_platforms"] = set()
        page = context.user_data.get("plat_page", 0)
        await query.edit_message_text(
            f"📱 *Select Sites*\n\nSelected: *0/{len(names)}*",
            parse_mode="Markdown",
            reply_markup=platforms_keyboard(page, set()),
        )

    # ── manage sites ──────────────────────────────────────────────
    elif data == "menu_manage":
        context.user_data.pop("add_site_state", None)
        await query.edit_message_text(
            f"⚙️ *Manage Sites*\n\n"
            f"Currently configured: `{len(names)}` site(s).\n\n"
            f"Add new sites (with custom signup/signin URLs and field count), "
            f"remove existing ones, or reset to the built-in defaults.",
            parse_mode="Markdown",
            reply_markup=manage_menu_keyboard(),
        )

    elif data == "manage_list":
        lines = [f"📋 *Sites* (`{len(names)}`)\n"]
        for s in sites.list_sites():
            lines.append(
                f"• *{s['name']}*  — fields: `{s.get('field_count', 1)}`"
                + (f"\n   ↪ Signup: `{s.get('signup_url', '')[:80]}`" if s.get("signup_url") else "")
                + (f"\n   ↪ Signin: `{s.get('signin_url', '')[:80]}`" if s.get("signin_url") else "")
            )
        text = "\n".join(lines)
        if len(text) > 3800:
            text = text[:3800] + "\n…"
        await query.edit_message_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⚙️ Manage Sites", callback_data="menu_manage"),
                InlineKeyboardButton("🏠 Main Menu", callback_data="menu_main"),
            ]]),
        )

    elif data == "manage_remove":
        if not names:
            await query.edit_message_text(
                "📋 No sites to remove.",
                reply_markup=manage_menu_keyboard(),
            )
            return
        await query.edit_message_text(
            "➖ *Remove a Site*\n\nTap the site you want to remove:",
            parse_mode="Markdown",
            reply_markup=remove_sites_keyboard(),
        )

    elif data.startswith("remove_"):
        name = data[len("remove_"):]
        ok, msg = sites.remove_site(name)
        sel = context.user_data.get("selected_platforms")
        if isinstance(sel, set):
            sel.discard(name)
        await query.edit_message_text(
            f"{'✅' if ok else '⚠️'} {msg}",
            reply_markup=manage_menu_keyboard(),
        )

    # ── inline remove button on the Select Sites screen ──────────
    elif data.startswith("platrm_"):
        name = data[len("platrm_"):]
        ok, msg = sites.remove_site(name)
        sel = context.user_data.get("selected_platforms")
        if isinstance(sel, set):
            sel.discard(name)
        names_after = get_platforms()
        page = context.user_data.get("plat_page", 0)
        total_pages = max(1, (len(names_after) + PLATFORMS_PER_PAGE - 1) // PLATFORMS_PER_PAGE)
        if page >= total_pages:
            page = max(0, total_pages - 1)
            context.user_data["plat_page"] = page
        try:
            await query.answer(("✅ " if ok else "⚠️ ") + msg, show_alert=False)
        except Exception:
            pass
        await query.edit_message_text(
            f"📱 *Select Sites*\n\nSelected: *{len(selected & set(names_after))}/{len(names_after)}*",
            parse_mode="Markdown",
            reply_markup=platforms_keyboard(page, selected),
        )

    # ── inline edit button on the Select Sites screen ────────────
    elif data.startswith("platedit_"):
        name = data[len("platedit_"):]
        s = sites.get_site(name)
        if not s:
            try:
                await query.answer(f"⚠️ '{name}' no longer exists", show_alert=True)
            except Exception:
                pass
            await query.edit_message_text(
                f"📱 *Select Sites*\n\nSelected: *{len(selected)}/{len(names)}*",
                parse_mode="Markdown",
                reply_markup=platforms_keyboard(context.user_data.get("plat_page", 0), selected),
            )
            return
        context.user_data["mode"] = "edit_site"
        context.user_data["edit_site_name"] = s["name"]
        context.user_data.pop("edit_site_field", None)
        await query.edit_message_text(
            _site_summary_text(s),
            parse_mode="Markdown",
            reply_markup=edit_site_keyboard(),
        )

    elif data.startswith("editfld_"):
        field = data[len("editfld_"):]
        site_name = context.user_data.get("edit_site_name")
        s = sites.get_site(site_name) if site_name else None
        if not s:
            await query.edit_message_text(
                "⚠️ This site no longer exists.",
                reply_markup=manage_menu_keyboard(),
            )
            return
        context.user_data["edit_site_field"] = field
        prompts = {
            "name":   "Send the *new name* for this site.",
            "signup": "Send the *new Signup URL* (or `-` to clear).",
            "signin": "Send the *new Signin URL* (or `-` to clear).",
            "count":  "Send the *new field count* (1–20).",
        }
        prompt = prompts.get(field, "Send the new value.")
        await query.edit_message_text(
            f"✏️ *Editing:* `{s['name']}`\n\n{prompt}\n\nSend /cancel to abort.",
            parse_mode="Markdown",
        )

    elif data == "editdone":
        context.user_data.pop("mode", None)
        context.user_data.pop("edit_site_name", None)
        context.user_data.pop("edit_site_field", None)
        page = context.user_data.get("plat_page", 0)
        await query.edit_message_text(
            f"📱 *Select Sites*\n\nSelected: *{len(selected & set(get_platforms()))}/{len(get_platforms())}*",
            parse_mode="Markdown",
            reply_markup=platforms_keyboard(page, selected),
        )

    elif data == "manage_add":
        context.user_data["add_site_state"] = "name"
        context.user_data["add_site_data"] = {}
        context.user_data["mode"] = "add_site"
        await query.edit_message_text(
            "➕ *Add a New Site* — step 1/4\n\n"
            "Send the *site name* (e.g. `Discord`).\n\n"
            "Send /cancel any time to abort.",
            parse_mode="Markdown",
            reply_markup=back_to_main_keyboard(),
        )

    elif data == "manage_reset_confirm":
        await query.edit_message_text(
            "♻️ *Reset to Defaults?*\n\n"
            "This will replace your current site list with the built-in defaults. "
            "Your custom sites will be lost.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Yes, reset", callback_data="manage_reset_yes")],
                [InlineKeyboardButton("❌ Cancel", callback_data="menu_manage")],
            ]),
        )

    elif data == "manage_reset_yes":
        sites.reset_to_defaults()
        context.user_data["selected_platforms"] = set(get_platforms())
        await query.edit_message_text(
            "♻️ Sites reset to defaults.",
            reply_markup=manage_menu_keyboard(),
        )

    # ── number input modes ────────────────────────────────────────
    elif data == "menu_upload_nums":
        context.user_data["mode"] = "upload_nums"
        await query.edit_message_text(
            "🔢 *Upload Numbers File*\n\n"
            "Send a CSV, Excel, or TXT file with phone numbers — one per row.\n\n"
            "```\n971501234567\n96612345678\n12025551234\n```\n\n"
            "📎 Send your file now:",
            parse_mode="Markdown",
            reply_markup=back_to_main_keyboard(),
        )

    elif data == "menu_paste":
        context.user_data["mode"] = "paste"
        await query.edit_message_text(
            "✏️ *Paste Numbers*\n\n"
            "Send phone numbers, one per line:\n\n"
            "```\n+971501234567\n+96612345678\n+12025551234\n```",
            parse_mode="Markdown",
            reply_markup=back_to_main_keyboard(),
        )

    elif data == "menu_stats":
        ai_state = "🟢 ON" if ai_helper.is_enabled() else "🔴 OFF"
        await query.edit_message_text(
            f"📊 *Statistics*\n\n"
            f"📱 Total sites: `{len(names)}`\n"
            f"✅ Your active selection: `{len(selected)}`\n"
            f"🤖 AI helper: *{ai_state}*\n",
            parse_mode="Markdown",
            reply_markup=back_to_main_keyboard(),
        )

    elif data == "noop":
        pass


# ── add-site multi-step input ────────────────────────────────────

async def _handle_add_site_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    state = context.user_data.get("add_site_state")
    data = context.user_data.setdefault("add_site_data", {})

    if text.lower().strip() in ("/cancel", "cancel"):
        context.user_data.pop("add_site_state", None)
        context.user_data.pop("add_site_data", None)
        context.user_data.pop("mode", None)
        await update.message.reply_text(
            "❌ Cancelled.", reply_markup=manage_menu_keyboard(),
        )
        return

    if state == "name":
        if sites.get_site(text):
            await update.message.reply_text(
                f"⚠️ A site named *{text}* already exists. Send a different name (or /cancel).",
                parse_mode="Markdown",
            )
            return
        data["name"] = text
        context.user_data["add_site_state"] = "signup_url"
        await update.message.reply_text(
            "Step 2/4 — send the *Signup URL* (or `-` to skip).",
            parse_mode="Markdown",
        )

    elif state == "signup_url":
        data["signup_url"] = "" if text == "-" else text
        context.user_data["add_site_state"] = "signin_url"
        await update.message.reply_text(
            "Step 3/4 — send the *Signin / Login URL* (or `-` to skip).",
            parse_mode="Markdown",
        )

    elif state == "signin_url":
        data["signin_url"] = "" if text == "-" else text
        if not (data.get("signup_url") or data.get("signin_url")):
            await update.message.reply_text(
                "⚠️ I need at least one URL (signup or signin). Please send the signup URL now:",
            )
            context.user_data["add_site_state"] = "signup_url"
            return
        context.user_data["add_site_state"] = "field_count"
        await update.message.reply_text(
            "Step 4/4 — how many *form fields* does the signup page have? "
            "Send a number (1–10). Send `1` if unsure.",
            parse_mode="Markdown",
        )

    elif state == "field_count":
        try:
            n = max(1, min(20, int(text)))
        except ValueError:
            await update.message.reply_text("⚠️ Please send a number (e.g. 3).")
            return
        data["field_count"] = n
        ok, msg = sites.add_site(data)
        context.user_data.pop("add_site_state", None)
        context.user_data.pop("add_site_data", None)
        context.user_data.pop("mode", None)
        if ok:
            sel = context.user_data.get("selected_platforms")
            if isinstance(sel, set):
                sel.add(data["name"])
            await update.message.reply_text(
                f"✅ {msg}\n\nThe site is now selectable from *Select Sites*.",
                parse_mode="Markdown",
                reply_markup=manage_menu_keyboard(),
            )
        else:
            await update.message.reply_text(
                f"❌ {msg}",
                reply_markup=manage_menu_keyboard(),
            )


# ── edit-site input ──────────────────────────────────────────────

async def _handle_edit_site_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    site_name = context.user_data.get("edit_site_name")
    field = context.user_data.get("edit_site_field")
    s = sites.get_site(site_name) if site_name else None
    if not s or not field:
        context.user_data.pop("mode", None)
        context.user_data.pop("edit_site_name", None)
        context.user_data.pop("edit_site_field", None)
        await update.message.reply_text(
            "⚠️ Edit session lost. Open the site again from *Select Sites*.",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(),
        )
        return

    updates: dict = {}
    if field == "name":
        new_name = text.strip()
        if not new_name:
            await update.message.reply_text("⚠️ Name cannot be empty.")
            return
        if new_name.lower() != s["name"].lower() and sites.get_site(new_name):
            await update.message.reply_text(
                f"⚠️ A site named *{new_name}* already exists.",
                parse_mode="Markdown",
            )
            return
        updates["name"] = new_name
    elif field == "signup":
        updates["signup_url"] = "" if text.strip() == "-" else text.strip()
    elif field == "signin":
        updates["signin_url"] = "" if text.strip() == "-" else text.strip()
    elif field == "count":
        try:
            updates["field_count"] = max(1, min(20, int(text.strip())))
        except ValueError:
            await update.message.reply_text("⚠️ Please send a number (e.g. 3).")
            return
    else:
        await update.message.reply_text("⚠️ Unknown field.")
        return

    ok, msg = sites.update_site(site_name, updates)
    if not ok:
        await update.message.reply_text(f"❌ {msg}")
        return

    # Track the (possibly renamed) site
    new_name = updates.get("name", s["name"])
    context.user_data["edit_site_name"] = new_name
    context.user_data.pop("edit_site_field", None)

    # Keep selection consistent if the site was renamed
    if "name" in updates and updates["name"] != s["name"]:
        sel = context.user_data.get("selected_platforms")
        if isinstance(sel, set) and s["name"] in sel:
            sel.discard(s["name"])
            sel.add(new_name)

    refreshed = sites.get_site(new_name) or s
    await update.message.reply_text(
        f"✅ Saved.\n\n{_site_summary_text(refreshed)}",
        parse_mode="Markdown",
        reply_markup=edit_site_keyboard(),
    )


# ── document + text handlers ─────────────────────────────────────

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    filename = (doc.file_name or "").lower()
    is_txt = filename.endswith(".txt")
    is_csv = filename.endswith(".csv")
    is_excel = filename.endswith(".xlsx") or filename.endswith(".xls")

    if not (is_csv or is_excel or is_txt):
        await update.message.reply_text(
            "❌ Please send a CSV, Excel (.xlsx/.xls), or TXT file.",
            reply_markup=main_menu_keyboard(),
        )
        return

    msg = await update.message.reply_text("⏳ Reading file...")
    try:
        file = await doc.get_file()
        file_bytes = await file.download_as_bytearray()
        data_io = io.BytesIO(bytes(file_bytes))

        numbers: list[str] = []
        if is_txt:
            content = bytes(file_bytes).decode("utf-8", errors="ignore")
            for line in content.splitlines():
                n = normalize_phone(line.strip())
                if len(n) >= 7:
                    numbers.append(n)
        elif is_csv:
            df = pd.read_csv(data_io, dtype=str, header=None)
            for val in df.iloc[:, 0]:
                n = normalize_phone(str(val))
                if len(n) >= 7:
                    numbers.append(n)
        else:
            df = pd.read_excel(data_io, dtype=str, header=None)
            for val in df.iloc[:, 0]:
                n = normalize_phone(str(val))
                if len(n) >= 7:
                    numbers.append(n)

        numbers = list(dict.fromkeys(numbers))
        if not numbers:
            await msg.edit_text("❌ No valid phone numbers found in the file.")
            return

        await msg.edit_text(
            f"✅ Found *{len(numbers)}* number(s). Starting...",
            parse_mode="Markdown",
        )
        await process_numbers(update, context, numbers)
    except Exception as e:
        logger.error(f"File error: {e}")
        await msg.edit_text(f"❌ Error reading file: {str(e)[:200]}")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    # If the user is in the middle of adding a site, route input there.
    if context.user_data.get("mode") == "add_site" and context.user_data.get("add_site_state"):
        await _handle_add_site_input(update, context, text)
        return

    # If the user is in the middle of editing a site, route input there.
    if context.user_data.get("mode") == "edit_site" and context.user_data.get("edit_site_field"):
        await _handle_edit_site_input(update, context, text)
        return

    numbers: list[str] = []
    for line in text.splitlines():
        n = normalize_phone(line.strip())
        if len(n) >= 7:
            numbers.append(n)
    numbers = list(dict.fromkeys(numbers))
    if not numbers:
        await update.message.reply_text(
            "I couldn't find any valid phone numbers.\n\nSend numbers one per line, "
            "or use /start to open the menu.",
            reply_markup=main_menu_keyboard(),
        )
        return
    await process_numbers(update, context, numbers)


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("add_site_state", None)
    context.user_data.pop("add_site_data", None)
    context.user_data.pop("mode", None)
    await update.message.reply_text("❌ Cancelled.", reply_markup=main_menu_keyboard())


async def error_handler(update, context):
    logger.error(f"Unhandled error: {context.error}", exc_info=context.error)


# ───────────────────────────── main ─────────────────────────────

def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN not set")

    app = (
        Application.builder()
        .token(token)
        .concurrent_updates(True)
        .build()
    )
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CallbackQueryHandler(callback_handler, block=False))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document, block=False))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text, block=False))
    app.add_error_handler(error_handler)

    logger.info(
        "Bot starting... sites=%d  AI=%s",
        len(get_platforms()),
        "on" if ai_helper.is_enabled() else "off",
    )
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
