#!/usr/bin/env python3
import logging
import asyncio
import html
import re
import requests
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters,
)

from config import (
    BOT_TOKEN, LOG_CHANNEL_ID, OWNER_ID, OWNER_USERNAME,
    SUPPORT_USERNAME, API_ENDPOINTS, MAX_TRIES, RETRY_DELAY, REQUEST_TIMEOUT,
)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


# ========== LOG TO CHANNEL ==========
async def send_log(context, text):
    if not LOG_CHANNEL_ID:
        return
    try:
        await context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=text,
                                       parse_mode=ParseMode.HTML,
                                       disable_web_page_preview=True)
    except Exception as e:
        logger.warning(f"Log channel send failed: {e}")


def user_info(update):
    u = update.effective_user
    if not u:
        return "<i>unknown</i>"
    uname = f"@{html.escape(u.username)}" if u.username else "—"
    return f"🆔 <code>{u.id}</code>\n👤 {html.escape(u.full_name)}\n🔗 {uname}"


def now_str():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")


# ========== API LOOKUP ==========
def _parse_response(endpoint, data):
    parser = endpoint.get("parser", "aerosend")
    if parser == "aerosend":
        return data if data.get("status") == "success" else None
    if parser == "smartuserinfo":
        if data.get("success"):
            return {"tg_id": data.get("id"), "mobile": data.get("phone", "N/A"),
                    "country_code": data.get("dc_location", "N/A"),
                    "country": data.get("dc_location", "N/A")}
        return None
    if parser == "tguserdetails":
        if data.get("success") or data.get("id"):
            return {"tg_id": data.get("id"), "mobile": data.get("phone", "N/A"),
                    "country_code": data.get("country_code", "N/A"),
                    "country": data.get("country", "N/A")}
        return None
    if parser == "generic":
        if data.get("success") or data.get("status") in ("ok", "success"):
            return {"tg_id": data.get("tg_id") or data.get("id"),
                    "mobile": data.get("mobile") or data.get("phone"),
                    "country_code": data.get("country_code") or data.get("cc"),
                    "country": data.get("country")}
        return None
    return None


async def lookup_tg_id(query):
    """query = numeric ID या @username"""
    # Normalize
    if query.startswith("@"):
        query = query[1:]
    for endpoint in API_ENDPOINTS:
        for attempt in range(MAX_TRIES):
            try:
                params = {k: v.format(tg_id=query) for k, v in endpoint["params"].items()}
                r = requests.get(endpoint["url"], params=params, timeout=REQUEST_TIMEOUT).json()
                parsed = _parse_response(endpoint, r)
                if parsed:
                    return parsed
            except Exception as e:
                logger.warning(f"[{endpoint['url']}] attempt {attempt+1}: {e}")
            await asyncio.sleep(RETRY_DELAY)
    return None


# ========== COLORFUL KEYBOARDS ==========
def main_menu_kb():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔍 ID Lookup", callback_data="lookup", style="success"),
            InlineKeyboardButton("👤 Username Lookup", callback_data="usernamelookup", style="primary"),
        ],
        [
            InlineKeyboardButton("📊 Stats", callback_data="stats", style="primary"),
            InlineKeyboardButton("ℹ️ Help", callback_data="help", style="primary"),
        ],
        [
            InlineKeyboardButton("👑 Owner", callback_data="owner", style="primary"),
            InlineKeyboardButton("💬 Support", callback_data="support", style="primary"),
        ],
        [
            InlineKeyboardButton("🔴 Close Menu", callback_data="close", style="danger"),
        ],
    ])


def back_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="menu", style="danger")],
    ])


def result_kb():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔍 New Lookup", callback_data="lookup", style="success"),
            InlineKeyboardButton("🔙 Menu", callback_data="menu", style="danger"),
        ],
    ])


def close_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes, Close", callback_data="menu", style="success"),
         InlineKeyboardButton("❌ No", callback_data="noop", style="danger")],
    ])


# ========== COMMANDS ==========
async def start(update, context):
    await send_log(context, f"🟢 <b>NEW /start</b>\n🕒 {now_str()}\n\n{user_info(update)}")
    await update.message.reply_text(
        "👋 <b>Welcome to TG OSINT Bot</b>\n\n"
        "🔎 Telegram ID या @username से details निकालो।\n"
        "नीचे से option चुनो:",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_kb(),
    )


async def help_cmd(update, context):
    await update.message.reply_text(
        "ℹ️ <b>How to use</b>\n\n"
        "1️⃣ /start भेजो\n"
        "2️⃣ <b>ID Lookup</b> या <b>Username Lookup</b> दबाओ\n"
        "3️⃣ Numeric ID (जैसे <code>123456789</code>) या @username (जैसे <code>@durov</code>) भेजो\n"
        "4️⃣ Result का wait करो\n\n"
        "⚠️ <b>Disclaimer:</b> केवल consent के साथ use करो।",
        parse_mode=ParseMode.HTML,
        reply_markup=back_kb(),
    )


# ========== BUTTON HANDLER ==========
async def button_handler(update, context):
    q = update.callback_query
    await q.answer()
    data = q.data

    await send_log(context,
                   f"🔘 <b>Button:</b> <code>{html.escape(data)}</code>\n🕒 {now_str()}\n\n{user_info(update)}")

    if data == "lookup":
        await q.edit_message_text(
            "📝 <b>Send me a numeric Telegram ID</b>\n\nExample: <code>123456789</code>",
            parse_mode=ParseMode.HTML, reply_markup=back_kb())

    elif data == "usernamelookup":
        await q.edit_message_text(
            "📝 <b>Send me a Telegram username</b>\n\nExample: <code>@durov</code> or <code>durov</code>",
            parse_mode=ParseMode.HTML, reply_markup=back_kb())

    elif data == "help":
        await q.edit_message_text(
            "ℹ️ <b>How to use</b>\n\n"
            "1️⃣ /start भेजो\n2️⃣ <b>ID Lookup</b> या <b>Username Lookup</b> दबाओ\n"
            "3️⃣ ID या username भेजो\n4️⃣ Result wait करो\n\n"
            "⚠️ केवल consent के साथ use करो।",
            parse_mode=ParseMode.HTML, reply_markup=back_kb())

    elif data == "stats":
        await q.edit_message_text(
            "📊 <b>Bot Statistics</b>\n\n"
            "🤖 Status: <b>Online</b>\n"
            f"🔌 APIs: <b>{len(API_ENDPOINTS)} active</b>\n"
            "⚡ Mode: <b>Long Polling</b>\n"
            "🛡️ Version: <b>3.0</b>",
            parse_mode=ParseMode.HTML, reply_markup=back_kb())

    elif data == "owner":
        owner = f'👤 <b>Owner:</b> <a href="https://t.me/{OWNER_USERNAME.lstrip("@")}">{html.escape(OWNER_USERNAME)}</a>' if OWNER_USERNAME else "👤 <b>Owner:</b> —"
        await q.edit_message_text(f"{owner}\n\n🛠️ Bot developed with ❤️",
                                  parse_mode=ParseMode.HTML, reply_markup=back_kb(),
                                  disable_web_page_preview=True)

    elif data == "support":
        sup = f'💬 <b>Support:</b> <a href="https://t.me/{SUPPORT_USERNAME.lstrip("@")}">{html.escape(SUPPORT_USERNAME)}</a>' if SUPPORT_USERNAME else "💬 <b>Support:</b> —"
        await q.edit_message_text(f"{sup}\n\n⏰ Response time: 24 hours के अंदर",
                                  parse_mode=ParseMode.HTML, reply_markup=back_kb(),
                                  disable_web_page_preview=True)

    elif data == "menu":
        await q.edit_message_text("👋 <b>TG OSINT Bot</b>\n\nOption चुनो:",
                                  parse_mode=ParseMode.HTML, reply_markup=main_menu_kb())

    elif data == "close":
        await q.edit_message_text("❌ <b>Close bot?</b>", parse_mode=ParseMode.HTML,
                                  reply_markup=close_kb())

    elif data == "noop":
        await q.answer("Okay!", show_alert=False)


# ========== TEXT HANDLER (ID + Username दोनों) ==========
async def handle_text(update, context):
    text = update.message.text.strip()

    await send_log(context,
                   f"📥 <b>USER INPUT</b>\n🕒 {now_str()}\n\n{user_info(update)}\n\n"
                   f"💬 <b>Text:</b> <code>{html.escape(text)}</code>")

    # ID या Username validate करो
    is_id = text.isdigit()
    is_username = bool(re.match(r'^@?[A-Za-z][A-Za-z0-9_]{3,31}$', text))

    if not (is_id or is_username):
        reply = ("❌ <b>Invalid input</b>\n\n"
                 "कृपया numeric ID या @username भेजो।\n"
                 "Example: <code>123456789</code> or <code>@durov</code>")
        await update.message.reply_text(reply, parse_mode=ParseMode.HTML, reply_markup=back_kb())
        await send_log(context, f"📤 <b>BOT:</b> Invalid input\n🕒 {now_str()}\n\n💬 {html.escape(reply)}")
        return

    msg = await update.message.reply_text("⏳ <b>Looking up...</b>", parse_mode=ParseMode.HTML)
    data = await lookup_tg_id(text)

    if not data:
        reply = (f"❌ <b>No data found</b> for <code>{html.escape(text)}</code>\n\n"
                 "ID/username invalid हो सकता है या API ने result नहीं दिया।")
        await msg.edit_text(reply, parse_mode=ParseMode.HTML, reply_markup=back_kb())
        await send_log(context, f"📤 <b>BOT:</b> No data\n🕒 {now_str()}\n\n🔎 {html.escape(text)}")
        return

    result = (
        f"✅ <b>Result Found</b>\n\n"
        f"🆔 <b>Telegram ID:</b> <code>{html.escape(str(data.get('tg_id', 'N/A')))}</code>\n"
        f"📱 <b>Mobile:</b> <code>{html.escape(str(data.get('mobile', 'N/A')))}</code>\n"
        f"🌍 <b>Country Code:</b> <code>{html.escape(str(data.get('country_code', 'N/A')))}</code>\n"
        f"🏴 <b>Country:</b> <code>{html.escape(str(data.get('country', 'N/A')))}</code>\n"
    )
    await msg.edit_text(result, parse_mode=ParseMode.HTML, reply_markup=result_kb())
    await send_log(context,
                   f"📤 <b>BOT: SUCCESS</b>\n🕒 {now_str()}\n\n{user_info(update)}\n\n"
                   f"🔎 <b>Query:</b> <code>{html.escape(text)}</code>\n"
                   f"📱 <b>Mobile:</b> <code>{html.escape(str(data.get('mobile', 'N/A')))}</code>")


# ========== ERROR HANDLER ==========
async def error_handler(update, context):
    logger.error("Exception:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(chat_id=update.effective_chat.id,
                                           text="⚠️ कुछ गड़बड़ हो गई। थोड़ी देर बाद try करो।")
        except Exception:
            pass
    await send_log(context, f"🔴 <b>ERROR</b>\n🕒 {now_str()}\n\n<code>{html.escape(str(context.error))}</code>")


# ========== MAIN ==========
def main():
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("BOT_TOKEN not set!")
        return
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(button_handler,
                                         pattern="^(lookup|usernamelookup|help|stats|owner|support|menu|close|noop)$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)
    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
