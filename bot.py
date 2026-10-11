#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import asyncio
import html
import requests
from datetime import datetime

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import (
    BOT_TOKEN,
    LOG_CHANNEL_ID,
    OWNER_ID,
    OWNER_USERNAME,
    SUPPORT_USERNAME,
    API_ENDPOINTS,
    MAX_TRIES,
    RETRY_DELAY,
    REQUEST_TIMEOUT,
)

# ---------- Logging ----------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)   # token leak रोकने के लिए
logger = logging.getLogger(__name__)


# ==================================================
#                HELPER: LOG TO CHANNEL
# ==================================================
async def send_log(context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """Log channel पर detailed message भेजो."""
    if not LOG_CHANNEL_ID:
        return
    try:
        await context.bot.send_message(
            chat_id=LOG_CHANNEL_ID,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.warning(f"Log channel send failed: {e}")


def user_info(update: Update) -> str:
    """User की पूरी details HTML format में."""
    u = update.effective_user
    if not u:
        return "<i>unknown user</i>"
    uname = f"@{html.escape(u.username)}" if u.username else "—"
    return (
        f"🆔 <code>{u.id}</code>\n"
        f"👤 {html.escape(u.full_name)}\n"
        f"🔗 {uname}\n"
        f"🌐 {html.escape(u.language_code or '—')}"
    )


def now_str() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")


# ==================================================
#                API LOOKUP (Multiple fallback)
# ==================================================
def _parse_response(endpoint: dict, data: dict) -> dict | None:
    """Different APIs का response normalize करो."""
    parser = endpoint.get("parser", "aerosend")

    if parser == "aerosend":
        if data.get("status") == "success":
            return data
        return None

    if parser == "smartuserinfo":
        if data.get("success") or data.get("status") == "ok":
            return {
                "tg_id": data.get("id") or data.get("user_id"),
                "mobile": data.get("phone", "N/A"),
                "country_code": data.get("dc_location", "N/A"),
                "country": data.get("dc_location", "N/A"),
            }
        return None

    if parser == "tgden":
        if data.get("results"):
            item = data["results"][0]
            return {
                "tg_id": item.get("id", "N/A"),
                "mobile": item.get("phone", "N/A"),
                "country_code": item.get("country_code", "N/A"),
                "country": item.get("country", "N/A"),
            }
        return None

    if parser == "generic":
        if data.get("success") or data.get("status") in ("ok", "success"):
            return {
                "tg_id": data.get("tg_id") or data.get("id"),
                "mobile": data.get("mobile") or data.get("phone"),
                "country_code": data.get("country_code") or data.get("cc"),
                "country": data.get("country"),
            }
        return None

    return None


async def lookup_tg_id(tg_id: str) -> dict | None:
    """हर endpoint try करो, पहला success return करो."""
    for endpoint in API_ENDPOINTS:
        for attempt in range(MAX_TRIES):
            try:
                params = {
                    k: v.format(tg_id=tg_id)
                    for k, v in endpoint["params"].items()
                }
                r = requests.get(
                    endpoint["url"],
                    params=params,
                    timeout=REQUEST_TIMEOUT,
                ).json()
                parsed = _parse_response(endpoint, r)
                if parsed:
                    return parsed
            except requests.exceptions.RequestException as e:
                logger.warning(
                    f"[{endpoint['url']}] attempt {attempt+1} failed: {e}"
                )
            except Exception as e:
                logger.warning(f"[{endpoint['url']}] parse error: {e}")
            await asyncio.sleep(RETRY_DELAY)
    return None


# ==================================================
#                   KEYBOARDS
# ==================================================
def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔍 Lookup Telegram ID",
                callback_data="lookup",
                         # 🟢 green
            ),
        ],
        [
            InlineKeyboardButton("ℹ️ Help", callback_data="help"),
            InlineKeyboardButton("📊 Stats", callback_data="stats"),
        ],
        [
            InlineKeyboardButton("👤 Owner", callback_data="owner"),
            InlineKeyboardButton("💬 Support", callback_data="support"),
        ],
    ])


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔙 Back to Menu", callback_data="menu"),
        ],
    ])


def lookup_result_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔍 New Lookup", callback_data="lookup"),
            InlineKeyboardButton("🔙 Menu", callback_data="menu"),
        ],
    ])


# ==================================================
#                  COMMANDS
# ==================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Log user input
    await send_log(
        context,
        f"🟢 <b>NEW /start</b>\n"
        f"🕒 {now_str()}\n\n"
        f"{user_info(update)}",
    )

    await update.message.reply_text(
        "👋 <b>Welcome to TG OSINT Bot</b>\n\n"
        "🔎 मैं Telegram ID से mobile number resolve करने की कोशिश करता हूँ।\n"
        "नीचे से option चुनो:",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_kb(),
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "ℹ️ <b>How to use</b>\n\n"
        "1️⃣ /start भेजो\n"
        "2️⃣ <b>Lookup Telegram ID</b> button दबाओ\n"
        "3️⃣ Numeric Telegram ID भेजो (जैसे <code>123456789</code>)\n"
        "4️⃣ Result का wait करो\n\n"
        "⚠️ <b>Disclaimer:</b> केवल consent के साथ use करो।",
        parse_mode=ParseMode.HTML,
        reply_markup=back_kb(),
    )


# ==================================================
#              CALLBACK BUTTONS
# ==================================================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    data = q.data

    # Log button press
    await send_log(
        context,
        f"🔘 <b>Button Pressed:</b> <code>{html.escape(data)}</code>\n"
        f"🕒 {now_str()}\n\n"
        f"{user_info(update)}",
    )

    if data == "lookup":
        await q.edit_message_text(
            "📝 <b>Send me a numeric Telegram ID</b>\n\n"
            "Example: <code>123456789</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb(),
        )

    elif data == "help":
        await q.edit_message_text(
            "ℹ️ <b>How to use</b>\n\n"
            "1️⃣ /start भेजो\n"
            "2️⃣ <b>Lookup Telegram ID</b> दबाओ\n"
            "3️⃣ Numeric ID भेजो\n"
            "4️⃣ Result wait करो\n\n"
            "⚠️ केवल consent के साथ use करो।",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb(),
        )

    elif data == "stats":
        await q.edit_message_text(
            "📊 <b>Bot Statistics</b>\n\n"
            "🤖 Status: <b>Online</b>\n"
            "🔌 APIs: <b>1 active</b>\n"
            "⚡ Mode: <b>Long Polling</b>\n"
            "🛡️ Version: <b>2.0</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb(),
        )

    elif data == "owner":
        owner_line = (
            f'👤 <b>Owner:</b> <a href="https://t.me/{OWNER_USERNAME.lstrip("@")}">'
            f"{html.escape(OWNER_USERNAME)}</a>"
            if OWNER_USERNAME else "👤 <b>Owner:</b> —"
        )
        await q.edit_message_text(
            f"{owner_line}\n\n"
            "🛠️ Bot developed with ❤️\n"
            "📩 किसी भी query के लिए message करो।",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb(),
            disable_web_page_preview=True,
        )

    elif data == "support":
        support_line = (
            f'💬 <b>Support:</b> <a href="https://t.me/{SUPPORT_USERNAME.lstrip("@")}">'
            f"{html.escape(SUPPORT_USERNAME)}</a>"
            if SUPPORT_USERNAME else "💬 <b>Support:</b> —"
        )
        await q.edit_message_text(
            f"{support_line}\n\n"
            "⏰ Response time: 24 hours के अंदर\n"
            "📝 Issue का details भेजो।",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb(),
            disable_web_page_preview=True,
        )

    elif data == "menu":
        await q.edit_message_text(
            "👋 <b>TG OSINT Bot</b>\n\nOption चुनो:",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_kb(),
        )


# ==================================================
#              TEXT MESSAGE HANDLER
# ==================================================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip()

    # Log user input
    await send_log(
        context,
        f"📥 <b>USER INPUT</b>\n"
        f"🕒 {now_str()}\n\n"
        f"{user_info(update)}\n\n"
        f"💬 <b>Text:</b> <code>{html.escape(text)}</code>",
    )

    if not text.isdigit():
        reply = (
            "❌ <b>Invalid input</b>\n\n"
            "कृपया केवल <b>numeric Telegram ID</b> भेजो।\n"
            "Example: <code>123456789</code>"
        )
        await update.message.reply_text(
            reply,
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb(),
        )
        # Log bot response
        await send_log(
            context,
            f"📤 <b>BOT RESPONSE</b> (invalid input)\n"
            f"🕒 {now_str()}\n\n"
            f"{user_info(update)}\n\n"
            f"💬 {html.escape(reply)}",
        )
        return

    msg = await update.message.reply_text("⏳ <b>Looking up...</b>", parse_mode=ParseMode.HTML)
    data = await lookup_tg_id(text)

    if not data:
        reply = (
            f"❌ <b>No data found</b> for ID <code>{html.escape(text)}</code>\n\n"
            "ID invalid हो सकती है या API ने result नहीं दिया।"
        )
        await msg.edit_text(reply, parse_mode=ParseMode.HTML, reply_markup=back_kb())
        await send_log(
            context,
            f"📤 <b>BOT RESPONSE</b> (no data)\n"
            f"🕒 {now_str()}\n\n"
            f"{user_info(update)}\n\n"
            f"🔎 <b>Queried ID:</b> <code>{html.escape(text)}</code>\n\n"
            f"💬 {html.escape(reply)}",
        )
        return

    result = (
        f"✅ <b>Result Found</b>\n\n"
        f"🆔 <b>Telegram ID:</b> <code>{html.escape(str(data.get('tg_id', 'N/A')))}</code>\n"
        f"📱 <b>Mobile:</b> <code>{html.escape(str(data.get('mobile', 'N/A')))}</code>\n"
        f"🌍 <b>Country Code:</b> <code>{html.escape(str(data.get('country_code', 'N/A')))}</code>\n"
        f"🏴 <b>Country:</b> <code>{html.escape(str(data.get('country', 'N/A')))}</code>\n"
    )
    await msg.edit_text(
        result,
        parse_mode=ParseMode.HTML,
        reply_markup=lookup_result_kb(),
    )

    # Log full response
    await send_log(
        context,
        f"📤 <b>BOT RESPONSE</b> (success)\n"
        f"🕒 {now_str()}\n\n"
        f"{user_info(update)}\n\n"
        f"🔎 <b>Queried ID:</b> <code>{html.escape(text)}</code>\n"
        f"📱 <b>Mobile:</b> <code>{html.escape(str(data.get('mobile', 'N/A')))}</code>\n"
        f"🌍 <b>Country:</b> <code>{html.escape(str(data.get('country', 'N/A')))}</code>",
    )


# ==================================================
#              ERROR HANDLER
# ==================================================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling update:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⚠️ कुछ गड़बड़ हो गई। थोड़ी देर बाद try करो।",
            )
        except Exception:
            pass
    # Log error to channel
    await send_log(
        context,
        f"🔴 <b>ERROR</b>\n"
        f"🕒 {now_str()}\n\n"
        f"<code>{html.escape(str(context.error))}</code>",
    )


# ==================================================
#                    MAIN
# ==================================================
def main() -> None:
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("BOT_TOKEN not set!")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(
        CallbackQueryHandler(
            button_handler,
            pattern="^(lookup|help|stats|owner|support|menu)$",
        )
    )
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
    )
    app.add_error_handler(error_handler)

    logger.info("Bot is starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
