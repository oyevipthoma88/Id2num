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
    BOT_TOKEN, LOG_CHANNEL_ID, OWNER_USERNAME, SUPPORT_USERNAME,
    START_IMAGE_URL, API_URL, API_KEY,
    MAX_TRIES, RETRY_DELAY, REQUEST_TIMEOUT,
)

# ========== LOGGING ==========
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logger = logging.getLogger("TG_OSINT")


# ========== HELPERS ==========
async def send_log(context, text):
    if not LOG_CHANNEL_ID:
        return
    try:
        await context.bot.send_message(
            chat_id=LOG_CHANNEL_ID, text=text,
            parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception as e:
        logger.warning(f"Log send failed: {e}")


def user_info(update):
    u = update.effective_user
    if not u:
        return "<i>unknown</i>"
    uname = f"@{html.escape(u.username)}" if u.username else "—"
    return f"🆔 <code>{u.id}</code>\n👤 {html.escape(u.full_name)}\n🔗 {uname}"


def now_str():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")


async def safe_edit(query, text, **kwargs):
    try:
        await query.edit_message_text(text, **kwargs)
    except Exception:
        try:
            await query.message.delete()
        except Exception:
            pass
        try:
            await query.message.chat.send_message(text, **kwargs)
        except Exception as e:
            logger.error(f"safe_edit send fallback failed: {e}")


# ========== API LOOKUP — बिल्कुल original file जैसा ==========
async def lookup_tg_id(tg_id):
    """aerosend.bond API से ID → Number lookup"""
    q = tg_id.lstrip("@")
    for attempt in range(MAX_TRIES):
        try:
            logger.info(f"[API] Attempt {attempt+1}/{MAX_TRIES} | query='{q}'")
            r = requests.get(
                API_URL,
                params={"key": API_KEY, "num": q},
                timeout=REQUEST_TIMEOUT,
            ).json()
            logger.info(f"[API] Response: {r}")

            if r.get("status") == "success":
                logger.info(f"[API] ✅ SUCCESS")
                return {
                    "tg_id": r.get("tg_id", q),
                    "mobile": r.get("mobile", "N/A"),
                    "country_code": r.get("country_code", "N/A"),
                    "country": r.get("country", "N/A"),
                }
            else:
                logger.warning(f"[API] Failed: {r.get('error', 'unknown')}")
        except Exception as e:
            logger.warning(f"[API] Attempt {attempt+1} error: {e}")

        if attempt < MAX_TRIES - 1:
            await asyncio.sleep(RETRY_DELAY)

    logger.error(f"❌ All attempts failed for '{q}'")
    return None


# ========== KEYBOARDS ==========
def main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Search 🔎", callback_data="search", style="success")],
        [
            InlineKeyboardButton("📊 Stats", callback_data="stats", style="primary"),
            InlineKeyboardButton("ℹ️ Help", callback_data="help", style="primary"),
        ],
        [
            InlineKeyboardButton("👑 Owner", callback_data="owner", style="primary"),
            InlineKeyboardButton("💬 Support", callback_data="support", style="primary"),
        ],
        [InlineKeyboardButton("🔴 Close", callback_data="close", style="danger")],
    ])


def back_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Menu", callback_data="menu", style="danger")],
    ])


def result_kb():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Search 🔎", callback_data="search", style="success"),
            InlineKeyboardButton("🔙 Menu", callback_data="menu", style="danger"),
        ],
    ])


def close_kb():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Yes", callback_data="menu", style="success"),
            InlineKeyboardButton("❌ No", callback_data="noop", style="danger"),
        ],
    ])


# ========== COMMANDS ==========
async def start(update, context):
    await send_log(context,
                   f"🟢 <b>NEW /start</b>\n🕒 {now_str()}\n\n{user_info(update)}")
    caption = (
        "👋 <b>Welcome to TG OSINT Bot</b>\n\n"
        "🔎 <b>Telegram ID</b> या <b>@username</b> भेजो।\n\n"
        "🛠️ <b>Features:</b>\n"
        "• ID → Number lookup\n"
        "• Username → Info lookup\n"
        "• Live logging channel\n\n"
        "👇 नीचे से option चुनो:"
    )
    try:
        await update.message.reply_photo(
            photo=START_IMAGE_URL, caption=caption,
            parse_mode=ParseMode.HTML, reply_markup=main_menu_kb())
    except Exception as e:
        logger.warning(f"Image failed: {e}")
        await update.message.reply_text(
            caption, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb())


async def help_cmd(update, context):
    await update.message.reply_text(
        "ℹ️ <b>How to use</b>\n\n"
        "1️⃣ /start भेजो\n"
        "2️⃣ <b>Search 🔎</b> दबाओ\n"
        "3️⃣ ID (जैसे <code>123456789</code>) या @username (जैसे <code>@durov</code>) भेजो\n"
        "4️⃣ Result wait करो\n\n"
        "⚠️ केवल consent के साथ use करो।",
        parse_mode=ParseMode.HTML, reply_markup=back_kb())


# ========== BUTTON HANDLER ==========
async def button_handler(update, context):
    q = update.callback_query
    await q.answer()
    data = q.data
    await send_log(context,
                   f"🔘 <b>Button:</b> <code>{data}</code>\n🕒 {now_str()}\n\n{user_info(update)}")

    if data == "search":
        await safe_edit(q,
            "🔎 <b>Send ID or @username</b>\n\n"
            "Examples:\n• <code>123456789</code>\n• <code>@durov</code>",
            parse_mode=ParseMode.HTML, reply_markup=back_kb())
    elif data == "help":
        await safe_edit(q,
            "ℹ️ <b>How to use</b>\n\n"
            "1️⃣ /start\n2️⃣ <b>Search 🔎</b>\n"
            "3️⃣ ID/@username भेजो\n4️⃣ Result",
            parse_mode=ParseMode.HTML, reply_markup=back_kb())
    elif data == "stats":
        await safe_edit(q,
            f"📊 <b>Bot Statistics</b>\n\n"
            f"🤖 Status: <b>Online</b>\n"
            f"🔌 API: <b>aerosend.bond</b>\n"
            f"⚡ Mode: <b>Long Polling</b>\n"
            f"🛡️ Version: <b>7.0</b>",
            parse_mode=ParseMode.HTML, reply_markup=back_kb())
    elif data == "owner":
        owner = (f'👤 <b>Owner:</b> <a href="https://t.me/{OWNER_USERNAME.lstrip("@")}">'
                 f'{html.escape(OWNER_USERNAME)}</a>'
                 if OWNER_USERNAME else "👤 <b>Owner:</b> —")
        await safe_edit(q, f"{owner}\n\n🛠️ Developed with ❤️",
                        parse_mode=ParseMode.HTML, reply_markup=back_kb(),
                        disable_web_page_preview=True)
    elif data == "support":
        sup = (f'💬 <b>Support:</b> <a href="https://t.me/{SUPPORT_USERNAME.lstrip("@")}">'
               f'{html.escape(SUPPORT_USERNAME)}</a>'
               if SUPPORT_USERNAME else "💬 <b>Support:</b> —")
        await safe_edit(q, f"{sup}\n\n⏰ Response within 24 hours",
                        parse_mode=ParseMode.HTML, reply_markup=back_kb(),
                        disable_web_page_preview=True)
    elif data == "menu":
        await safe_edit(q, "👋 <b>TG OSINT Bot</b>\n\nOption चुनो:",
                        parse_mode=ParseMode.HTML, reply_markup=main_menu_kb())
    elif data == "close":
        await safe_edit(q, "❌ <b>Close bot?</b>",
                        parse_mode=ParseMode.HTML, reply_markup=close_kb())
    elif data == "noop":
        await q.answer("Okay!", show_alert=False)


# ========== TEXT HANDLER ==========
async def handle_text(update, context):
    text = update.message.text.strip()
    await send_log(context,
                   f"📥 <b>USER INPUT</b>\n🕒 {now_str()}\n\n{user_info(update)}\n\n"
                   f"💬 <code>{html.escape(text)}</code>")

    is_id = text.isdigit()
    is_username = bool(re.match(r'^@?[A-Za-z][A-Za-z0-9_]{3,31}$', text))

    if not (is_id or is_username):
        await update.message.reply_text(
            "❌ Invalid input. Send numeric ID or @username.",
            parse_mode=ParseMode.HTML, reply_markup=back_kb())
        return

    msg = await update.message.reply_text("⏳ <b>Searching...</b>",
                                          parse_mode=ParseMode.HTML)
    data = await lookup_tg_id(text)

    if not data:
        await msg.edit_text(
            f"❌ <b>No data found</b> for <code>{html.escape(text)}</code>\n\n"
            "ID/username invalid हो सकता है या API ने result नहीं दिया।",
            parse_mode=ParseMode.HTML, reply_markup=back_kb())
        await send_log(context,
                       f"📤 <b>NO DATA</b>\n🕒 {now_str()}\n\n"
                       f"{user_info(update)}\n\n🔎 {html.escape(text)}")
        return

    result = (
        f"✅ <b>Result Found</b>\n\n"
        f"🆔 <b>Telegram ID:</b> <code>{html.escape(str(data.get('tg_id', 'N/A')))}</code>\n"
        f"📱 <b>Mobile:</b> <code>{html.escape(str(data.get('mobile', 'N/A')))}</code>\n"
        f"🌍 <b>Country Code:</b> <code>{html.escape(str(data.get('country_code', 'N/A')))}</code>\n"
        f"🏴 <b>Country:</b> <code>{html.escape(str(data.get('country', 'N/A')))}</code>"
    )
    await msg.edit_text(result, parse_mode=ParseMode.HTML, reply_markup=result_kb())
    await send_log(context,
                   f"📤 <b>SUCCESS</b>\n🕒 {now_str()}\n\n{user_info(update)}\n\n"
                   f"🔎 <code>{html.escape(text)}</code>\n"
                   f"📱 <code>{html.escape(str(data.get('mobile', 'N/A')))}</code>")


# ========== ERROR HANDLER ==========
async def error_handler(update, context):
    logger.error("Exception:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⚠️ कुछ गड़बड़ हो गई। थोड़ी देर बाद try करो।")
        except Exception:
            pass


# ========== MAIN ==========
def main():
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("BOT_TOKEN not set!")
        return
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(
        button_handler,
        pattern="^(search|help|stats|owner|support|menu|close|noop)$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)
    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
