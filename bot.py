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
    START_IMAGE_URL, API_ENDPOINTS, MAX_TRIES, RETRY_DELAY, REQUEST_TIMEOUT,
)

# ========== DETAILED LOGGING SETUP ==========
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),  # Heroku logs में दिखेगा
    ]
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logger = logging.getLogger("TG_OSINT_BOT")


# ========== LOG HELPERS ==========
async def send_log(context, text):
    if not LOG_CHANNEL_ID:
        return
    try:
        await context.bot.send_message(
            chat_id=LOG_CHANNEL_ID, text=text,
            parse_mode=ParseMode.HTML, disable_web_page_preview=True)
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


# ========== API LOOKUP — DETAILED LOGGING ==========
def _parse_response(endpoint, data):
    parser = endpoint.get("parser", "generic")
    logger.info(f"Parsing with parser={parser}, raw data={data}")

    if parser == "callmebot":
        # Callmebot response: {"status": "success", "phone": "+91..."}
        if data.get("status") == "success" or data.get("phone"):
            return {
                "tg_id": data.get("id", "N/A"),
                "mobile": data.get("phone", "N/A"),
                "country_code": data.get("country_code", "N/A"),
                "country": data.get("country", "N/A"),
            }
        return None

    if parser == "callmebot_id":
        if data.get("status") == "success" or data.get("phone"):
            return {
                "tg_id": data.get("id", "N/A"),
                "mobile": data.get("phone", "N/A"),
                "country_code": data.get("country_code", "N/A"),
                "country": data.get("country", "N/A"),
            }
        return None

    # Generic fallback
    if data.get("success") or data.get("status") in ("ok", "success"):
        return {
            "tg_id": data.get("tg_id") or data.get("id"),
            "mobile": data.get("mobile") or data.get("phone"),
            "country_code": data.get("country_code") or data.get("cc"),
            "country": data.get("country"),
        }
    return None


def _is_valid_url(url):
    return "example.com" not in url and url.startswith("http")


async def lookup_tg(query):
    """ID या username — दोनों accept करता है"""
    q = query.lstrip("@")
    logger.info(f"Starting lookup for query='{q}'")

    for ep_idx, endpoint in enumerate(API_ENDPOINTS):
        if not _is_valid_url(endpoint["url"]):
            logger.warning(f"[{ep_idx}] Skipping invalid URL: {endpoint['url']}")
            continue

        for attempt in range(MAX_TRIES):
            try:
                params = {k: v.format(query=q)
                          for k, v in endpoint["params"].items()}
                logger.info(f"[{ep_idx}] Attempt {attempt+1}/{MAX_TRIES} | URL={endpoint['url']} | params={params}")

                resp = requests.get(endpoint["url"], params=params,
                                    timeout=REQUEST_TIMEOUT)
                logger.info(f"[{ep_idx}] HTTP {resp.status_code} | len={len(resp.text)}")

                data = resp.json()
                logger.info(f"[{ep_idx}] JSON response: {data}")

                parsed = _parse_response(endpoint, data)
                if parsed:
                    logger.info(f"[{ep_idx}] ✅ SUCCESS — parsed={parsed}")
                    return parsed
                else:
                    logger.warning(f"[{ep_idx}] Parser returned None (status={data.get('status')})")

            except requests.exceptions.Timeout:
                logger.warning(f"[{ep_idx}] Attempt {attempt+1} TIMEOUT after {REQUEST_TIMEOUT}s")
            except requests.exceptions.ConnectionError as e:
                logger.warning(f"[{ep_idx}] Attempt {attempt+1} CONNECTION ERROR: {e}")
            except requests.exceptions.RequestException as e:
                logger.warning(f"[{ep_idx}] Attempt {attempt+1} REQUEST ERROR: {e}")
            except Exception as e:
                logger.error(f"[{ep_idx}] Attempt {attempt+1} UNEXPECTED: {e}")

            await asyncio.sleep(RETRY_DELAY)

    logger.error(f"❌ ALL APIs FAILED for query='{q}'")
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
    logger.info(f"/start from user={update.effective_user.id}")
    await send_log(context,
                   f"🟢 <b>NEW /start</b>\n🕒 {now_str()}\n\n{user_info(update)}")

    caption = (
        "👋 <b>Welcome to TG OSINT Bot</b>\n\n"
        "🔎 <b>Telegram ID</b> या <b>@username</b> से details निकालो।\n\n"
        "🛠️ <b>Features:</b>\n"
        "• ID → Number\n"
        "• Username → Info\n"
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
            caption, parse_mode=ParseMode.HTML,
            reply_markup=main_menu_kb())


async def help_cmd(update, context):
    await update.message.reply_text(
        "ℹ️ <b>How to use</b>\n\n"
        "1️⃣ /start भेजो\n"
        "2️⃣ <b>Search 🔎</b> दबाओ\n"
        "3️⃣ ID (जैसे <code>123456789</code>) या username (जैसे <code>@durov</code>) भेजो\n"
        "4️⃣ Result wait करो\n\n"
        "⚠️ केवल consent के साथ use करो।",
        parse_mode=ParseMode.HTML, reply_markup=back_kb())


# ========== BUTTON HANDLER ==========
async def button_handler(update, context):
    q = update.callback_query
    await q.answer()
    data = q.data
    logger.info(f"Button pressed: {data} by user={update.effective_user.id}")

    await send_log(context,
                   f"🔘 <b>Button:</b> <code>{html.escape(data)}</code>\n"
                   f"🕒 {now_str()}\n\n{user_info(update)}")

    if data == "search":
        await safe_edit(q,
            "🔎 <b>Send me a Telegram ID or @username</b>\n\n"
            "Examples:\n"
            "• <code>123456789</code> (ID)\n"
            "• <code>@durov</code> (username)",
            parse_mode=ParseMode.HTML, reply_markup=back_kb())
    elif data == "help":
        await safe_edit(q,
            "ℹ️ <b>How to use</b>\n\n"
            "1️⃣ /start\n2️⃣ <b>Search 🔎</b>\n"
            "3️⃣ ID या username भेजो\n4️⃣ Result\n\n"
            "⚠️ केवल consent के साथ use करो।",
            parse_mode=ParseMode.HTML, reply_markup=back_kb())
    elif data == "stats":
        active = sum(1 for e in API_ENDPOINTS if _is_valid_url(e["url"]))
        await safe_edit(q,
            f"📊 <b>Bot Statistics</b>\n\n"
            f"🤖 Status: <b>Online</b>\n"
            f"🔌 APIs: <b>{active} active</b>\n"
            f"⚡ Mode: <b>Long Polling</b>\n"
            f"🛡️ Version: <b>4.0</b>",
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
    logger.info(f"Text received: '{text}' from user={update.effective_user.id}")

    await send_log(context,
                   f"📥 <b>USER INPUT</b>\n🕒 {now_str()}\n\n{user_info(update)}\n\n"
                   f"💬 <b>Text:</b> <code>{html.escape(text)}</code>")

    is_id = text.isdigit()
    is_username = bool(re.match(r'^@?[A-Za-z][A-Za-z0-9_]{3,31}$', text))

    if not (is_id or is_username):
        reply = ("❌ <b>Invalid input</b>\n\n"
                 "कृपया numeric ID या @username भेजो।\n"
                 "Example: <code>123456789</code> या <code>@durov</code>")
        await update.message.reply_text(reply, parse_mode=ParseMode.HTML,
                                       reply_markup=back_kb())
        return

    msg = await update.message.reply_text("⏳ <b>Searching...</b>",
                                          parse_mode=ParseMode.HTML)
    data = await lookup_tg(text)

    if not data:
        reply = (f"❌ <b>No data found</b> for <code>{html.escape(text)}</code>\n\n"
                 "ID/username invalid हो सकता है या API ने result नहीं दिया।")
        await msg.edit_text(reply, parse_mode=ParseMode.HTML, reply_markup=back_kb())
        await send_log(context,
                       f"📤 <b>BOT:</b> No data\n🕒 {now_str()}\n\n🔎 {html.escape(text)}")
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
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⚠️ कुछ गड़बड़ हो गई। थोड़ी देर बाद try करो।")
        except Exception:
            pass
    await send_log(context,
                   f"🔴 <b>ERROR</b>\n🕒 {now_str()}\n\n"
                   f"<code>{html.escape(str(context.error))}</code>")


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
