import os
import logging
import re
import io
import asyncio
import pandas as pd
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from platform_checker import (
    PLATFORMS,
    check_platform,
    build_summary,
    make_result_card,
    STATUS_ERROR,
    STATUS_REGISTERED,
    STATUS_NOT_FOUND,
    STATUS_OTP_SENT,
    STATUS_OTP_FAILED,
    STATUS_UNKNOWN,
    STATUS_LABELS,
)
from screenshotter import capture_for, browser_pool
from telegram import InputMediaPhoto

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

PLATFORMS_PER_PAGE = 8
stop_flags: dict[int, bool] = {}


def normalize_phone(number: str) -> str:
    return re.sub(r'\D', '', number)


def get_user_platforms(context: ContextTypes.DEFAULT_TYPE) -> set:
    if "selected_platforms" not in context.user_data:
        context.user_data["selected_platforms"] = set(PLATFORMS)
    return context.user_data["selected_platforms"]


def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 Select Platforms", callback_data="menu_platforms")],
        [InlineKeyboardButton("🔢 Upload Numbers (File)", callback_data="menu_upload_nums")],
        [InlineKeyboardButton("✏️ Paste Numbers", callback_data="menu_paste")],
        [InlineKeyboardButton("📊 Stats", callback_data="menu_stats")],
    ])


def stop_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🛑 Stop Checking", callback_data="stop_check")
    ]])


def platforms_keyboard(page: int, selected: set) -> InlineKeyboardMarkup:
    start = page * PLATFORMS_PER_PAGE
    end = min(start + PLATFORMS_PER_PAGE, len(PLATFORMS))
    page_platforms = PLATFORMS[start:end]
    total_pages = (len(PLATFORMS) + PLATFORMS_PER_PAGE - 1) // PLATFORMS_PER_PAGE

    keyboard = []
    for plat in page_platforms:
        icon = "✅" if plat in selected else "⬜"
        keyboard.append([InlineKeyboardButton(
            f"{icon} {plat}", callback_data=f"toggle_{plat}"
        )])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"plat_page_{page - 1}"))
    nav.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop"))
    if end < len(PLATFORMS):
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"plat_page_{page + 1}"))
    keyboard.append(nav)

    keyboard.append([
        InlineKeyboardButton("✅ Select All", callback_data="plat_select_all"),
        InlineKeyboardButton("⬜ Clear All", callback_data="plat_clear_all"),
    ])
    keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="menu_main")])
    return InlineKeyboardMarkup(keyboard)


async def process_numbers(update: Update, context: ContextTypes.DEFAULT_TYPE, numbers: list[str]):
    user_id = update.effective_user.id
    selected = list(get_user_platforms(context))
    stop_flags[user_id] = False

    if not selected:
        await update.message.reply_text(
            "⚠️ No platforms selected!\n\nPlease select at least one platform.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📱 Select Platforms", callback_data="menu_platforms")
            ]])
        )
        return

    total_combos = len(numbers) * len(selected)
    progress_msg = await update.message.reply_text(
        f"🚀 *Starting checks (per platform)...*\n\n"
        f"📱 Platforms: `{len(selected)}`\n"
        f"📞 Numbers per platform: `{len(numbers)}`\n"
        f"📸 Total checks: `{total_combos}`\n\n"
        f"_All numbers are checked on one platform before moving to the next._",
        parse_mode="Markdown",
        reply_markup=stop_keyboard()
    )

    completed = 0
    stopped = False
    PER_CHECK_TIMEOUT = 30
    all_results: list[dict] = []

    for plat_idx, plat in enumerate(selected, 1):
        await asyncio.sleep(0)
        if stop_flags.get(user_id):
            stopped = True
            break

        header_msg = await update.message.reply_text(
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📱 *Platform {plat_idx}/{len(selected)}:* `{plat}`\n"
            f"🔍 Trying signup → signin for {len(numbers)} number(s)...",
            parse_mode="Markdown"
        )

        plat_done = 0
        plat_registered = 0
        plat_not_found = 0
        plat_otp = 0
        plat_other = 0

        for num_idx, number in enumerate(numbers, 1):
            await asyncio.sleep(0)
            if stop_flags.get(user_id):
                stopped = True
                break

            try:
                await progress_msg.edit_text(
                    f"🔄 *Live Progress*\n\n"
                    f"📱 Platform: *{plat}*  ({plat_idx}/{len(selected)})\n"
                    f"📞 Number: `+{number}`  ({num_idx}/{len(numbers)})\n\n"
                    f"📊 *This platform:*  `{plat_done}/{len(numbers)}` done\n"
                    f"  ✅ Registered: `{plat_registered}`\n"
                    f"  ❌ Not found: `{plat_not_found}`\n"
                    f"  📨 OTP: `{plat_otp}`  •  ⚠️ Other: `{plat_other}`\n\n"
                    f"📈 *Overall:* `{completed}/{total_combos}` checks done\n\n"
                    f"⏳ Trying signup then signin (max {PER_CHECK_TIMEOUT}s)...",
                    parse_mode="Markdown",
                    reply_markup=stop_keyboard()
                )
            except Exception:
                pass

            timed_out = False
            result: dict | None = None
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
                    result = {
                        "platform": plat, "number": number,
                        "signup_status": STATUS_ERROR,
                        "signup_msg": f"Signup timed out after {PER_CHECK_TIMEOUT}s",
                        "signin_status": STATUS_ERROR,
                        "signin_msg": f"Signin timed out after {PER_CHECK_TIMEOUT}s",
                        "final_status": STATUS_ERROR,
                        "url": "",
                        "card": make_result_card(
                            platform=plat, number=number, final_status=STATUS_ERROR,
                            signup_status=STATUS_ERROR, signup_msg=f"Timed out after {PER_CHECK_TIMEOUT}s",
                            signin_status=STATUS_ERROR, signin_msg=f"Timed out after {PER_CHECK_TIMEOUT}s",
                            url="",
                        ),
                    }
            except Exception as e:
                logger.error(f"Error on {plat}/{number}: {e}")
                result = {
                    "platform": plat, "number": number,
                    "signup_status": STATUS_ERROR, "signup_msg": f"Exception: {str(e)[:80]}",
                    "signin_status": STATUS_ERROR, "signin_msg": f"Exception: {str(e)[:80]}",
                    "final_status": STATUS_ERROR, "url": "",
                    "card": make_result_card(
                        platform=plat, number=number, final_status=STATUS_ERROR,
                        signup_status=STATUS_ERROR, signup_msg=f"Exception: {str(e)[:80]}",
                        signin_status=STATUS_ERROR, signin_msg=f"Exception: {str(e)[:80]}",
                        url="",
                    ),
                }

            all_results.append(result)
            fs = result["final_status"]
            if fs == STATUS_REGISTERED: plat_registered += 1
            elif fs == STATUS_NOT_FOUND: plat_not_found += 1
            elif fs == STATUS_OTP_SENT: plat_otp += 1
            else: plat_other += 1

            caption = (
                f"📱 *{plat}* — `+{number}`  ({num_idx}/{len(numbers)})\n"
                f"🏁 *Verdict:* {STATUS_LABELS.get(fs, '⚠️')}\n"
                f"📝 *Signup:* {STATUS_LABELS.get(result['signup_status'], '⚠️')} — _{result['signup_msg'][:140]}_\n"
                f"🔑 *Signin:* {STATUS_LABELS.get(result['signin_status'], '⚠️')} — _{result['signin_msg'][:140]}_"
                + ("\n⏱ Timed out" if timed_out else "")
            )
            try:
                await update.message.reply_photo(
                    photo=io.BytesIO(result["card"]),
                    caption=caption[:1020],
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"send card error: {e}")
                await update.message.reply_text(caption[:4000], parse_mode="Markdown")

            try:
                signup_png, signin_png = await capture_for(plat, number, timeout=40.0)
                await update.message.reply_media_group(media=[
                    InputMediaPhoto(
                        media=io.BytesIO(signup_png),
                        caption=(f"📝 *Signup page* — {plat} +{number}\n"
                                 f"Final state after submitting random data + the phone."),
                        parse_mode="Markdown",
                    ),
                    InputMediaPhoto(
                        media=io.BytesIO(signin_png),
                        caption=(f"🔑 *Signin page* — {plat} +{number}\n"
                                 f"Final state after attempting login with the phone."),
                        parse_mode="Markdown",
                    ),
                ])
                result["signup_screenshot_bytes"] = len(signup_png)
                result["signin_screenshot_bytes"] = len(signin_png)
            except Exception as e:
                logger.error(f"screenshot send error {plat}/{number}: {e}")
                try:
                    await update.message.reply_text(
                        f"⚠️ Could not capture page screenshots for *{plat}* +{number}: `{str(e)[:120]}`",
                        parse_mode="Markdown"
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
                parse_mode="Markdown"
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
        InlineKeyboardButton("✏️ Check More Numbers", callback_data="menu_paste"),
        InlineKeyboardButton("🏠 Main Menu", callback_data="menu_main")
    ]])

    summary_text = build_summary(all_results)
    header = "🛑 *Stopped by user* — partial summary\n\n" if stopped else "✅ *All done!*\n\n"
    full = header + summary_text
    try:
        if len(full) <= 4000:
            await update.message.reply_text(full, parse_mode="Markdown", reply_markup=back_keyboard)
        else:
            await update.message.reply_text(header + "Summary attached as file.", parse_mode="Markdown")
            await update.message.reply_document(
                document=io.BytesIO(summary_text.encode("utf-8")),
                filename="summary.txt",
                reply_markup=back_keyboard
            )
    except Exception as e:
        logger.error(f"summary send error: {e}")
        await update.message.reply_text(
            f"{header}Done. Total: {len(all_results)} checks.",
            parse_mode="Markdown",
            reply_markup=back_keyboard
        )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    get_user_platforms(context)
    await update.message.reply_text(
        "👋 *Phone Number Platform Checker*\n\n"
        "Paste or upload phone numbers. I'll check each one across your selected platforms "
        "and send a result card for every check.\n\n"
        "Choose an option below:",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard()
    )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id
    selected = get_user_platforms(context)

    if data == "stop_check":
        stop_flags[user_id] = True
        await query.edit_message_text(
            "🛑 *Stop signal sent!*\n\nFinishing current check, then stopping...",
            parse_mode="Markdown"
        )
        return

    if data == "menu_main":
        await query.edit_message_text(
            "👋 *Phone Number Platform Checker*\n\nChoose an option below:",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )

    elif data == "menu_platforms":
        page = context.user_data.get("plat_page", 0)
        await query.edit_message_text(
            f"📱 *Select Platforms*\n\n"
            f"Toggle which platforms to check.\n"
            f"Selected: *{len(selected)}/{len(PLATFORMS)}*",
            parse_mode="Markdown",
            reply_markup=platforms_keyboard(page, selected)
        )

    elif data.startswith("plat_page_"):
        page = int(data.split("_")[-1])
        context.user_data["plat_page"] = page
        await query.edit_message_text(
            f"📱 *Select Platforms*\n\n"
            f"Toggle which platforms to check.\n"
            f"Selected: *{len(selected)}/{len(PLATFORMS)}*",
            parse_mode="Markdown",
            reply_markup=platforms_keyboard(page, selected)
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
            f"📱 *Select Platforms*\n\n"
            f"Toggle which platforms to check.\n"
            f"Selected: *{len(selected)}/{len(PLATFORMS)}*",
            parse_mode="Markdown",
            reply_markup=platforms_keyboard(page, selected)
        )

    elif data == "plat_select_all":
        context.user_data["selected_platforms"] = set(PLATFORMS)
        page = context.user_data.get("plat_page", 0)
        await query.edit_message_text(
            f"📱 *Select Platforms*\n\nSelected: *{len(PLATFORMS)}/{len(PLATFORMS)}*",
            parse_mode="Markdown",
            reply_markup=platforms_keyboard(page, context.user_data["selected_platforms"])
        )

    elif data == "plat_clear_all":
        context.user_data["selected_platforms"] = set()
        page = context.user_data.get("plat_page", 0)
        await query.edit_message_text(
            f"📱 *Select Platforms*\n\nSelected: *0/{len(PLATFORMS)}*",
            parse_mode="Markdown",
            reply_markup=platforms_keyboard(page, set())
        )

    elif data == "menu_upload_nums":
        context.user_data["mode"] = "upload_nums"
        await query.edit_message_text(
            "🔢 *Upload Numbers File*\n\n"
            "Send a CSV, Excel, or TXT file with phone numbers — one per row.\n\n"
            "```\n971501234567\n96612345678\n12025551234\n```\n\n"
            "📎 Send your file now:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Main Menu", callback_data="menu_main")
            ]])
        )

    elif data == "menu_paste":
        context.user_data["mode"] = "paste"
        await query.edit_message_text(
            "✏️ *Paste Numbers*\n\n"
            "Send phone numbers, one per line:\n\n"
            "```\n+971501234567\n+96612345678\n+12025551234\n```",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Main Menu", callback_data="menu_main")
            ]])
        )

    elif data == "menu_stats":
        from platform_checker import PLATFORM_CHECKERS, GENERIC_PLATFORM_URLS
        await query.edit_message_text(
            f"📊 *Statistics*\n\n"
            f"📱 Total platforms: `{len(PLATFORMS)}`\n"
            f"🔬 Deep checkers (form automation): `{len(PLATFORM_CHECKERS)}`\n"
            f"🌐 Generic site checkers: `{len(GENERIC_PLATFORM_URLS)}`\n"
            f"✅ Your active selection: `{len(selected)}`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Main Menu", callback_data="menu_main")
            ]])
        )

    elif data == "noop":
        pass


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    filename = doc.file_name.lower()
    is_txt   = filename.endswith(".txt")
    is_csv   = filename.endswith(".csv")
    is_excel = filename.endswith(".xlsx") or filename.endswith(".xls")

    if not (is_csv or is_excel or is_txt):
        await update.message.reply_text(
            "❌ Please send a CSV, Excel (.xlsx/.xls), or TXT file.",
            reply_markup=main_menu_keyboard()
        )
        return

    msg = await update.message.reply_text("⏳ Reading file...")
    file = await doc.get_file()
    file_bytes = await file.download_as_bytearray()
    data_io = io.BytesIO(bytes(file_bytes))

    try:
        numbers = []
        if is_txt:
            content = file_bytes.decode("utf-8", errors="ignore")
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

        await msg.edit_text(f"✅ Found *{len(numbers)}* number(s). Starting...", parse_mode="Markdown")
        await process_numbers(update, context, numbers)

    except Exception as e:
        logger.error(f"File error: {e}")
        await msg.edit_text(f"❌ Error reading file: {str(e)}")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    numbers = []
    for line in text.splitlines():
        n = normalize_phone(line.strip())
        if len(n) >= 7:
            numbers.append(n)

    numbers = list(dict.fromkeys(numbers))
    if not numbers:
        await update.message.reply_text(
            "I couldn't find any valid phone numbers.\n\nSend numbers one per line.",
            reply_markup=main_menu_keyboard()
        )
        return

    await process_numbers(update, context, numbers)


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
    app.add_handler(CallbackQueryHandler(callback_handler, block=False))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document, block=False))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text, block=False))

    logger.info("Bot started...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
