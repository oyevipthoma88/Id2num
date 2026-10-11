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

# Telethon for native fallback
from telethon import TelegramClient
from telethon.tl.functions.users import GetFullUserRequest

from config import (
    BOT_TOKEN, LOG_CHANNEL_ID, OWNER_USERNAME, SUPPORT_USERNAME,
    START_IMAGE_URL, TG_API_ID, TG_API_HASH, TG_PHONE,
    PRIORITY_API, FALLBACK_API, MAX_TRIES, RETRY_DELAY, REQUEST_TIMEOUT,
)

# ========== LOGGING ==========
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("telethon").setLevel(logging.WARNING)
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


# ========== PRIORITY API: aerosend.bond ==========
async def priority_lookup(query):
    """aerosend.bond API को सबसे पहले try करो"""
    q = query.lstrip("@")
    for attempt in range(MAX_TRIES):
        try:
            params = {k: v.format(query=q) for k, v in PRIORITY_API["params"].items()}
            logger.info(f"[Priority] Attempt {attempt+1}/{MAX_TRIES} | URL={PRIORITY_API['url']}")
            r = requests.get(PRIORITY_API["url"], params=params, timeout=REQUEST_TIMEOUT)
            logger.info(f"[Priority] HTTP {r.status_code} | {r.text[:150]}")
            data = r.json()
            if data.get("status") == "success":
                logger.info(f"[Priority] SUCCESS: {data}")
                return {
                    "tg_id": data.get("tg_id", q),
                    "mobile": data.get("mobile", "N/A"),
                    "country_code": data.get("country_code", "N/A"),
                    "country": data.get("country", "N/A"),
                    "username": "—",
                    "full_name": "—",
                }
            else:
                logger.warning(f"[Priority] API returned: {data}")
        except Exception as e:
            logger.warning(f"[Priority] Attempt {attempt+1} failed: {e}")
        await asyncio.sleep(RETRY_DELAY)
    return None


# ========== TELETHON FALLBACK ==========
async def telethon_lookup(query):
    """Telethon से native lookup (सिर्फ fallback के लिए)"""
    if not TG_API_ID or not TG_API_HASH:
        logger.warning("Telethon credentials missing — skipping")
        return None
    try:
        logger.info(f"Telethon lookup starting for query='{query}'")
        client = TelegramClient("bot_session", TG_API_ID, TG_API_HASH)
        await client.start(phone=TG_PHONE)
        
        # username या ID से entity निकालो
        entity = await client.get_entity(query)
        full = await client(GetFullUserRequest(entity))
        
        logger.info(f"Telethon success: id={entity.id}, username={getattr(entity, 'username', None)}")
        return {
            "tg_id": entity.id,
            "mobile": getattr(entity, "phone", None) or "Not public",
            "country_code": getattr(entity, "lang_code", "N/A"),
            "country": "N/A",
            "username": getattr(entity, "username", None) or "—",
            "full_name": getattr(entity, "first_name", "—"),
        }
    except Exception as e:
        logger.error(f"Telethon lookup failed: {type(e).__name__}: {e}")
        return None
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


async def unified_lookup(query):
    """पहले aerosend.bond (priority), फिर Telethon"""
    result = await priority_lookup(query)
    if result:
        return result
    logger.info("Priority API failed — trying Telethon fallback")
    return await telethon_lookup(query)


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
    await send_log(context, f"🟢 <b>NEW /start</b>\n🕒 {now_str()}\n\n{user_info(update)}")
    caption = (
        "👋 <b>Welcome to TG OSINT Bot</b>\n\n"
        "🔎 <b>Telegram ID</b> या <b>@username</b> से details निकालो।\n\n"
        "🛠️ <b>Features:</b>\n"
        "• ID → Number (aerosend.bond)\n"
        "• Username → Info\n"
        "• Telethon native fallback\n"
        "• Live logging\n\n"
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
            "🔎 <b>Send me a Telegram ID or @username</b>\n\n"
            "Examples:\n• <code>123456789</code>\n• <code>@durov</code>",
            parse_mode=ParseMode.HTML, reply_markup=back_kb())
    elif data == "help":
        await safe_edit(q,
            "ℹ️ <b>How to use</b>\n\n1️⃣ /start\n2️⃣ <b>Search 🔎</b>\n3️⃣ ID/@username\n4️⃣ Result",
            parse_mode=ParseMode.HTML, reply_markup=back_kb())
    elif data == "stats":
        await safe_edit(q,
            f"📊 <b>Bot Statistics</b>\n\n"
            f"🤖 Status: <b>Online</b>\n"
            f"🔌 Priority API: <b>aerosend.bond</b>\n"
            f"🧬 Telethon: <b>{'ON' if TG_API_ID else 'OFF'}</b>\n"
            f"🛡️ Version: <b>6.0</b>",
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
            "❌ Invalid input. Send ID or @username.",
            parse_mode=ParseMode.HTML, reply_markup=back_kb())
        return

    msg = await update.message.reply_text("⏳ <b>Searching...</b>", parse_mode=ParseMode.HTML)
    data = await unified_lookup(text)

    if not data:
        await msg.edit_text(
            f"❌ <b>No data found</b> for <code>{html.escape(text)}</code>",
            parse_mode=ParseMode.HTML, reply_markup=back_kb())
        return

    result = (
        f"✅ <b>Result Found</b>\n\n"
        f"🆔 <b>ID:</b> <code>{html.escape(str(data.get('tg_id', 'N/A')))}</code>\n"
        f"📱 <b>Mobile:</b> <code>{html.escape(str(data.get('mobile', 'N/A')))}</code>\n"
        f"🌍 <b>Country Code:</b> <code>{html.escape(str(data.get('country_code', 'N/A')))}</code>\n"
        f"🏴 <b>Country:</b> <code>{html.escape(str(data.get('country', 'N/A')))}</code>\n"
        f"🔗 <b>Username:</b> <code>{html.escape(str(data.get('username', '—')))}</code>\n"
        f"👤 <b>Name:</b> {html.escape(str(data.get('full_name', '—')))}"
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
