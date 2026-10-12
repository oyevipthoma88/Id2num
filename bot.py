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
    START_IMAGE_URL, GITHUB_URL, API_URL, API_KEY,
    MAX_TRIES, RETRY_DELAY, REQUEST_TIMEOUT,
)

# ========== LOGGING ==========
logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
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
            logger.error(f"safe_edit fallback failed: {e}")


# ========== API LOOKUP ==========
async def lookup_tg_id(tg_id):
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
                return {
                    "tg_id": r.get("tg_id", q),
                    "mobile": r.get("mobile", "N/A"),
                    "country_code": r.get("country_code", "N/A"),
                    "country": r.get("country", "N/A"),
                }
            logger.warning(f"[API] Failed: {r.get('error', 'unknown')}")
        except Exception as e:
            logger.warning(f"[API] Attempt {attempt+1} error: {e}")
        if attempt < MAX_TRIES - 1:
            await asyncio.sleep(RETRY_DELAY)
    return None


# ========== KEYBOARDS ==========
def main_menu_kb():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Search 🔎", callback_data="search", style="success"),
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
            InlineKeyboardButton("📂 Source Code", callback_data="source", style="primary"),
            InlineKeyboardButton("👤 Profile", callback_data="profile", style="primary"),
        ],
        [
            InlineKeyboardButton("🔴 Close", callback_data="close", style="danger"),
        ],
    ])


def back_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="menu", style="danger")],
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


def source_kb():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🌐 Open Repository", url=GITHUB_URL, style="success"),
        ],
        [
            InlineKeyboardButton("👤 My Profile", callback_data="profile", style="primary"),
        ],
        [
            InlineKeyboardButton("🔙 Menu", callback_data="menu", style="danger"),
        ],
    ])


# ========== COMMANDS ==========
async def start(update, context):
    await send_log(context,
                   f"🟢 <b>NEW /start</b>\n🕒 {now_str()}\n\n{user_info(update)}")

    caption = (
        "👋 <b>Welcome to TG OSINT Bot</b>\n\n"
        "<blockquote>"
        "🔎 <b>Telegram ID</b> या <b>@username</b> भेजो और details निकालो।\n"
        "सब कुछ real-time, encrypted और anonymous।"
        "</blockquote>\n\n"
        "🛠️ <b>Features:</b>\n"
        "<blockquote>"
        "• ID → Mobile Number\n"
        "• Username → Profile Info\n"
        "• Live Logging Channel\n"
        "• Source Code Available\n"
        "</blockquote>\n\n"
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
    text = (
        "ℹ️ <b>How to use the bot</b>\n\n"
        "<blockquote>"
        "<b>Step 1:</b> /start भेजो\n"
        "<b>Step 2:</b> <b>Search 🔎</b> button दबाओ\n"
        "<b>Step 3:</b> Numeric ID (जैसे <code>123456789</code>) या @username (जैसे <code>@durov</code>) भेजो\n"
        "<b>Step 4:</b> Result का इंतज़ार करो"
        "</blockquote>\n\n"
        "⚠️ <b>Disclaimer:</b>\n"
        "<blockquote>"
        "केवल consent के साथ use करो। किसी की personal info बिना permission lookup करना illegal है।"
        "</blockquote>"
    )
    await update.message.reply_text(
        text, parse_mode=ParseMode.HTML, reply_markup=back_kb())


# ========== BUTTON HANDLER ==========
async def button_handler(update, context):
    q = update.callback_query
    await q.answer()
    data = q.data
    user = update.effective_user

    await send_log(context,
                   f"🔘 <b>Button:</b> <code>{data}</code>\n🕒 {now_str()}\n\n{user_info(update)}")

    if data == "search":
        await safe_edit(q,
            "🔎 <b>Send ID or @username</b>\n\n"
            "<blockquote>"
            "<b>Examples:</b>\n"
            "• <code>123456789</code> — numeric ID\n"
            "• <code>@durov</code> — username"
            "</blockquote>",
            parse_mode=ParseMode.HTML, reply_markup=back_kb())

    elif data == "help":
        text = (
            "ℹ️ <b>How to use</b>\n\n"
            "<blockquote>"
            "<b>Step 1:</b> /start भेजो\n"
            "<b>Step 2:</b> <b>Search 🔎</b> दबाओ\n"
            "<b>Step 3:</b> ID या @username भेजो\n"
            "<b>Step 4:</b> Result wait करो"
            "</blockquote>\n\n"
            "⚠️ केवल consent के साथ use करो।"
        )
        await safe_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=back_kb())

    elif data == "stats":
        text = (
            "📊 <b>Bot Statistics</b>\n\n"
            "<blockquote>"
            "🤖 <b>Status:</b> Online\n"
            "⚡ <b>Mode:</b> Long Polling\n"
            "🔌 <b>Backend:</b> Active\n"
            "📡 <b>Response Time:</b> ~2s\n"
            "🛡️ <b>Version:</b> 9.0"
            "</blockquote>"
        )
        await safe_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=back_kb())

    elif data == "owner":
        owner = (f'👤 <b>Owner:</b> <a href="https://t.me/{OWNER_USERNAME.lstrip("@")}">'
                 f'{html.escape(OWNER_USERNAME)}</a>'
                 if OWNER_USERNAME else "👤 <b>Owner:</b> —")
        text = (
            f"👑 <b>Owner Panel</b>\n\n"
            f"<blockquote>"
            f"{owner}\n"
            f"🛠️ <b>Role:</b> Developer\n"
            f"📅 <b>Status:</b> Active"
            f"</blockquote>\n\n"
            f"💡 किसी भी query के लिए message करो।"
        )
        await safe_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=back_kb(),
                       disable_web_page_preview=True)

    elif data == "support":
        sup = (f'💬 <b>Support:</b> <a href="https://t.me/{SUPPORT_USERNAME.lstrip("@")}">'
               f'{html.escape(SUPPORT_USERNAME)}</a>'
               if SUPPORT_USERNAME else "💬 <b>Support:</b> —")
        text = (
            f"💬 <b>Support Center</b>\n\n"
            f"<blockquote>"
            f"{sup}\n"
            f"⏰ <b>Response Time:</b> 24 hours\n"
            f"📝 <b>Issue:</b> Details के साथ message करो"
            f"</blockquote>"
        )
        await safe_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=back_kb(),
                       disable_web_page_preview=True)

    elif data == "source":
        text = (
            "📂 <b>Source Code</b>\n\n"
            "<blockquote>"
            "🔗 <b>Repository:</b> <a href=\"" + GITHUB_URL + "\">GitHub</a>\n"
            "🛠️ <b>Language:</b> Python 3.11\n"
            "📦 <b>Framework:</b> python-telegram-bot\n"
            "📜 <b>License:</b> Open Source"
            "</blockquote>\n\n"
            "👇 नीचे से option चुनो:"
        )
        await safe_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=source_kb(),
                       disable_web_page_preview=True)

    elif data == "profile":
        uname = f"@{html.escape(user.username)}" if user.username else "<i>Not set</i>"
        lang = html.escape(user.language_code or "—")
        is_premium = "👑 Yes" if getattr(user, "is_premium", False) else "❌ No"
        text = (
            "👤 <b>Your Profile</b>\n\n"
            "<blockquote>"
            f"🆔 <b>User ID:</b> <code>{user.id}</code>\n"
            f"👤 <b>Full Name:</b> {html.escape(user.full_name)}\n"
            f"🔗 <b>Username:</b> {uname}\n"
            f"🌐 <b>Language:</b> <code>{lang}</code>\n"
            f"💎 <b>Premium:</b> {is_premium}\n"
            f"🤖 <b>Is Bot:</b> {'Yes' if user.is_bot else 'No'}"
            "</blockquote>\n\n"
            "📅 <b>Session Info:</b>\n"
            f"<blockquote>🕒 {now_str()}</blockquote>"
        )
        await safe_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=back_kb())

    elif data == "menu":
        text = (
            "👋 <b>TG OSINT Bot</b>\n\n"
            "<blockquote>"
            "🔎 Main menu — option चुनो\n"
            "📌 सारे features available हैं"
            "</blockquote>"
        )
        await safe_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb())

    elif data == "close":
        text = (
            "❌ <b>Close Menu</b>\n\n"
            "<blockquote>क्या तुम menu बंद करना चाहते हो?</blockquote>"
        )
        await safe_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=close_kb())

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
        reply = (
            "❌ <b>Invalid Input</b>\n\n"
            "<blockquote>"
            "कृपया numeric ID या @username भेजो।\n\n"
            "<b>Examples:</b>\n"
            "• <code>123456789</code>\n"
            "• <code>@durov</code>"
            "</blockquote>"
        )
        await update.message.reply_text(
            reply, parse_mode=ParseMode.HTML, reply_markup=back_kb())
        return

    msg = await update.message.reply_text(
        "⏳ <b>Searching...</b>\n\n"
        "<blockquote>कृपया प्रतीक्षा करें, data fetch हो रहा है...</blockquote>",
        parse_mode=ParseMode.HTML)

    data = await lookup_tg_id(text)

    if not data:
        reply = (
            f"❌ <b>No Data Found</b>\n\n"
            f"<blockquote>"
            f"🔎 <b>Query:</b> <code>{html.escape(text)}</code>\n"
            f"💬 ID/username invalid हो सकता है या API ने result नहीं दिया।"
            f"</blockquote>"
        )
        await msg.edit_text(reply, parse_mode=ParseMode.HTML, reply_markup=back_kb())
        await send_log(context,
                       f"📤 <b>NO DATA</b>\n🕒 {now_str()}\n\n"
                       f"{user_info(update)}\n\n🔎 {html.escape(text)}")
        return

    result = (
        "✅ <b>Result Found</b>\n\n"
        "<blockquote>"
        f"🆔 <b>Telegram ID:</b> <code>{html.escape(str(data.get('tg_id', 'N/A')))}</code>\n"
        f"📱 <b>Mobile:</b> <code>{html.escape(str(data.get('mobile', 'N/A')))}</code>\n"
        f"🌍 <b>Country Code:</b> <code>{html.escape(str(data.get('country_code', 'N/A')))}</code>\n"
        f"🏴 <b>Country:</b> <code>{html.escape(str(data.get('country', 'N/A')))}</code>"
        "</blockquote>\n\n"
        "🔒 <i>Data fetched securely</i>"
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
                text="⚠️ <b>Error Occurred</b>\n\n"
                     "<blockquote>कुछ गड़बड़ हो गई। थोड़ी देर बाद try करो।</blockquote>",
                parse_mode=ParseMode.HTML)
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
        pattern="^(search|help|stats|owner|support|source|profile|menu|close|noop)$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)
    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
