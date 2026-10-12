#!/usr/bin/env python3
import logging, asyncio, html, re, time, requests
from datetime import datetime
from collections import defaultdict
from telegram import (InlineKeyboardButton, InlineKeyboardMarkup, Update, CopyTextButton)
from telegram.constants import ParseMode
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler,
                          ContextTypes, MessageHandler, filters)
from config import (BOT_TOKEN, LOG_CHANNEL_ID, OWNER_ID, OWNER_USERNAME,
                    SUPPORT_LINK, BOT_USERNAME, START_IMAGE_URL, GITHUB_URL,
                    MAX_SEARCHES_PER_DAY, API_URL, API_KEY,
                    MAX_TRIES, RETRY_DELAY, REQUEST_TIMEOUT)

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logger = logging.getLogger("TG_OSINT")

user_searches = defaultdict(list)

def get_remaining(user_id):
    if OWNER_ID and user_id == OWNER_ID: return -1
    now = time.time()
    user_searches[user_id] = [t for t in user_searches[user_id] if t > now - 86400]
    return max(0, MAX_SEARCHES_PER_DAY - len(user_searches[user_id]))

def record_search(user_id):
    if OWNER_ID and user_id == OWNER_ID: return
    user_searches[user_id].append(time.time())

def next_reset_str(user_id):
    if not user_searches[user_id]: return "now"
    oldest = min(user_searches[user_id])
    delta = datetime.utcfromtimestamp(oldest + 86400) - datetime.utcnow()
    total = int(delta.total_seconds())
    return f"{total // 3600}h {(total % 3600) // 60}m"

async def send_log(context, text):
    if not LOG_CHANNEL_ID: return
    try:
        await context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=text,
            parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception as e: logger.warning(f"Log failed: {e}")

def user_info(update):
    u = update.effective_user
    if not u: return "<i>unknown</i>"
    uname = f"@{html.escape(u.username)}" if u.username else "—"
    return f"🆔 <code>{u.id}</code>\n👤 {html.escape(u.full_name)}\n🔗 {uname}"

def now_str(): return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

def support_url():
    if not SUPPORT_LINK: return ""
    if SUPPORT_LINK.startswith("http"): return SUPPORT_LINK
    return f"https://t.me/{SUPPORT_LINK.lstrip('@')}"

def support_display():
    if not SUPPORT_LINK: return "—"
    if SUPPORT_LINK.startswith("http"):
        return "@" + SUPPORT_LINK.rstrip("/").split("/")[-1]
    return SUPPORT_LINK if SUPPORT_LINK.startswith("@") else f"@{SUPPORT_LINK}"

def bot_signature():
    lines = []
    if SUPPORT_LINK:
        lines.append(f'📢 <a href="{support_url()}">{html.escape(support_display())}</a>')
    if BOT_USERNAME:
        lines.append(f'🤖 <a href="https://t.me/{BOT_USERNAME.lstrip("@")}">{html.escape(BOT_USERNAME)}</a>')
    if not lines: return ""
    return "\n\n<blockquote>" + "  •  ".join(lines) + "</blockquote>"

async def safe_edit(query, text, **kwargs):
    try:
        await query.edit_message_text(text, **kwargs)
    except Exception:
        try: await query.message.delete()
        except Exception: pass
        try: await query.message.chat.send_message(text, **kwargs)
        except Exception as e: logger.error(f"safe_edit fallback failed: {e}")

async def is_member(context, user_id):
    if not SUPPORT_LINK: return True
    try:
        chat_id = SUPPORT_LINK if SUPPORT_LINK.startswith("@") else f"@{SUPPORT_LINK.rstrip('/').split('/')[-1]}"
        m = await context.bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        return m.status in ("member", "administrator", "creator")
    except Exception as e:
        logger.warning(f"Membership check failed: {e}"); return True

def join_kb():
    buttons = []
    if SUPPORT_LINK:
        buttons.append([InlineKeyboardButton("📢 Join Channel", url=support_url(), style="primary")])
    buttons.append([InlineKeyboardButton("✅ Verify", callback_data="verify", style="success")])
    return InlineKeyboardMarkup(buttons)

def join_text():
    return ("🔒 <b>Access Restricted</b>\n\n<blockquote>"
            "इस bot को use करने के लिए पहले हमारे official channel को join करना ज़रूरी है।\n\n"
            f"📢 <b>Channel:</b> {html.escape(support_display())}"
            "</blockquote>\n\n👇 नीचे से join करो, फिर <b>Verify ✅</b> दबाओ।")

async def lookup_tg_id(tg_id):
    q = tg_id.lstrip("@")
    last_error = None
    for attempt in range(MAX_TRIES):
        try:
            logger.info(f"[API] Attempt {attempt+1}/{MAX_TRIES} | query='{q}'")
            r = requests.get(API_URL, params={"key": API_KEY, "num": q},
                             timeout=REQUEST_TIMEOUT).json()
            logger.info(f"[API] Response: {r}")
            if r.get("status") == "success":
                return {"ok": True, "data": {
                    "tg_id": r.get("tg_id", q), "mobile": r.get("mobile", "N/A"),
                    "country_code": r.get("country_code", "N/A"),
                    "country": r.get("country", "N/A")}}
            last_error = r.get("error", "No data found")
        except Exception as e:
            logger.warning(f"[API] Attempt {attempt+1} error: {e}")
            last_error = str(e)
        if attempt < MAX_TRIES - 1: await asyncio.sleep(RETRY_DELAY)
    return {"ok": False, "error": last_error or "Unknown error"}

def main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Search 🔎", callback_data="search", style="success")],
        [InlineKeyboardButton("📊 Stats", callback_data="stats", style="primary"),
         InlineKeyboardButton("ℹ️ Help", callback_data="help", style="primary")],
        [InlineKeyboardButton("👑 Owner", callback_data="owner", style="primary"),
         InlineKeyboardButton("💬 Support", callback_data="support", style="primary")],
        [InlineKeyboardButton("📂 Source Code", callback_data="source", style="primary"),
         InlineKeyboardButton("👤 Profile", callback_data="profile", style="primary")],
        [InlineKeyboardButton("🔴 Close", callback_data="close", style="danger")],
    ])

def back_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data="menu", style="danger")]])

def result_kb(copy_text):
    kb = []
    if copy_text:
        kb.append([InlineKeyboardButton("📋 Copy Result",
            copy_text=CopyTextButton(text=copy_text), style="primary")])
    kb.append([InlineKeyboardButton("Search 🔎", callback_data="search", style="success"),
               InlineKeyboardButton("🔙 Menu", callback_data="menu", style="danger")])
    return InlineKeyboardMarkup(kb)

def no_data_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Retry Search", callback_data="retry", style="success")],
        [InlineKeyboardButton("🔍 New Query", callback_data="search", style="primary"),
         InlineKeyboardButton("🔙 Menu", callback_data="menu", style="danger")]])

def close_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ Yes", callback_data="menu", style="success"),
                                  InlineKeyboardButton("❌ No", callback_data="noop", style="danger")]])

def source_kb():
    buttons = []
    if GITHUB_URL:
        buttons.append([InlineKeyboardButton("🌐 Open Repository", url=GITHUB_URL, style="success")])
    buttons.append([InlineKeyboardButton("👤 My Profile", callback_data="profile", style="primary")])
    buttons.append([InlineKeyboardButton("🔙 Menu", callback_data="menu", style="danger")])
    return InlineKeyboardMarkup(buttons)

async def start(update, context):
    user = update.effective_user
    await send_log(context, f"🟢 <b>NEW /start</b>\n🕒 {now_str()}\n\n{user_info(update)}")
    if not await is_member(context, user.id):
        await update.message.reply_text(join_text(), parse_mode=ParseMode.HTML, reply_markup=join_kb())
        return
    caption = ("👋 <b>Welcome to TG OSINT Bot</b>\n\n<blockquote>"
               "🔎 <b>Telegram ID</b> या <b>@username</b> भेजो और details निकालो।\n"
               "सब कुछ real-time और anonymous।</blockquote>\n\n"
               "🛠️ <b>Features:</b>\n<blockquote>"
               "• ID → Mobile Number\n• Username → Profile Info\n"
               "• Live Logging Channel\n• Copy Result Instantly</blockquote>\n\n"
               "👇 नीचे से option चुनो:" + bot_signature())
    if START_IMAGE_URL:
        try:
            await update.message.reply_photo(photo=START_IMAGE_URL, caption=caption,
                parse_mode=ParseMode.HTML, reply_markup=main_menu_kb()); return
        except Exception as e: logger.warning(f"Image failed: {e}")
    await update.message.reply_text(caption, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb())

async def help_cmd(update, context):
    user = update.effective_user
    if not await is_member(context, user.id):
        await update.message.reply_text(join_text(), parse_mode=ParseMode.HTML, reply_markup=join_kb()); return
    text = ("ℹ️ <b>How to use the bot</b>\n\n<blockquote>"
            "<b>Step 1:</b> /start भेजो\n<b>Step 2:</b> <b>Search 🔎</b> दबाओ\n"
            "<b>Step 3:</b> ID (जैसे <code>123456789</code>) या @username भेजो\n"
            "<b>Step 4:</b> Result का इंतज़ार करो\n<b>Step 5:</b> <b>Copy Result</b> दबाकर copy करो"
            "</blockquote>\n\n"
            f"📊 <b>Daily Limit:</b> <code>{MAX_SEARCHES_PER_DAY} searches / 24hrs</code>\n"
            "👑 <i>Owner has unlimited access</i>\n\n"
            "💡 <b>Tip:</b> अगर 'No Data' आए तो बाद में दोबारा try करो।\n\n"
            "⚠️ <b>Disclaimer:</b>\n<blockquote>केवल consent के साथ use करो।</blockquote>"
            + bot_signature())
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=back_kb())

async def button_handler(update, context):
    q = update.callback_query; await q.answer()
    data = q.data; user = update.effective_user

    if data == "verify":
        if await is_member(context, user.id):
            text = ("✅ <b>Verification Successful</b>\n\n<blockquote>"
                    "आपका access unlock हो गया है।\nअब bot के सारे features use कर सकते हो।"
                    "</blockquote>\n\n👇 Menu खोल रहे हैं..." + bot_signature())
            await safe_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb())
            await send_log(context, f"✅ <b>VERIFIED</b>\n🕒 {now_str()}\n\n{user_info(update)}")
        else:
            await q.answer("❌ पहले channel join करो!", show_alert=True)
        return

    if not await is_member(context, user.id):
        await safe_edit(q, join_text(), parse_mode=ParseMode.HTML, reply_markup=join_kb()); return

    await send_log(context, f"🔘 <b>Button:</b> <code>{data}</code>\n🕒 {now_str()}\n\n{user_info(update)}")

    if data == "search":
        remaining = get_remaining(user.id)
        limit_line = "👑 <b>Unlimited</b> (Owner)" if remaining == -1 else f"📊 <b>Remaining:</b> <code>{remaining}/{MAX_SEARCHES_PER_DAY}</code>"
        await safe_edit(q, "🔎 <b>Send ID or @username</b>\n\n<blockquote>"
            "<b>Examples:</b>\n• <code>123456789</code> — numeric ID\n• <code>@durov</code> — username"
            "</blockquote>\n\n" + limit_line, parse_mode=ParseMode.HTML, reply_markup=back_kb())

    elif data == "retry":
        await safe_edit(q, "🔄 <b>Retry Search</b>\n\n<blockquote>"
            "अपना ID/username दोबारा भेजो।\nDatabase हर कुछ देर में update होता है।"
            "</blockquote>", parse_mode=ParseMode.HTML, reply_markup=back_kb())

    elif data == "help":
        text = ("ℹ️ <b>How to use</b>\n\n<blockquote>1️⃣ /start भेजो\n2️⃣ <b>Search 🔎</b> दबाओ\n"
                "3️⃣ ID या @username भेजो\n4️⃣ Result wait करो</blockquote>\n\n"
                f"📊 <b>Limit:</b> <code>{MAX_SEARCHES_PER_DAY}/24hrs</code>" + bot_signature())
        await safe_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=back_kb())

    elif data == "stats":
        remaining = get_remaining(user.id)
        is_owner = (OWNER_ID and user.id == OWNER_ID)
        limit_text = "♾️ Unlimited" if is_owner else f"{remaining}/{MAX_SEARCHES_PER_DAY}"
        text = ("📊 <b>Bot Statistics</b>\n\n<blockquote>"
                "🤖 <b>Status:</b> Online\n⚡ <b>Mode:</b> Long Polling\n🔌 <b>Backend:</b> Active\n"
                f"📡 <b>Your Remaining:</b> <code>{limit_text}</code>\n"
                f"👑 <b>Owner:</b> {'Yes' if is_owner else 'No'}\n"
                "🛡️ <b>Version:</b> 11.0</blockquote>" + bot_signature())
        await safe_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=back_kb())

    elif data == "owner":
        owner = (f'<a href="https://t.me/{OWNER_USERNAME.lstrip("@")}">{html.escape(OWNER_USERNAME)}</a>'
                 if OWNER_USERNAME else "—")
        text = ("👑 <b>Owner Panel</b>\n\n<blockquote>"
                f"👤 <b>Owner:</b> {owner}\n🛠️ <b>Role:</b> Developer\n📅 <b>Status:</b> Active"
                "</blockquote>\n\n💡 किसी भी query के लिए message करो।" + bot_signature())
        await safe_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=back_kb(), disable_web_page_preview=True)

    elif data == "support":
        text = ("💬 <b>Support Center</b>\n\n<blockquote>"
                f'📢 <b>Channel:</b> <a href="{support_url()}">{html.escape(support_display())}</a>\n'
                "⏰ <b>Response Time:</b> 24 hours\n📝 <b>Issue:</b> Details के साथ message करो"
                "</blockquote>" + bot_signature())
        await safe_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=back_kb(), disable_web_page_preview=True)

    elif data == "source":
        text = ("📂 <b>Source Code</b>\n\n<blockquote>"
                "🛠️ <b>Language:</b> Python 3.11\n📦 <b>Framework:</b> python-telegram-bot\n"
                "📜 <b>License:</b> Open Source</blockquote>\n\n👇 नीचे से option चुनो:" + bot_signature())
        await safe_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=source_kb(), disable_web_page_preview=True)

    elif data == "profile":
        uname = f"@{html.escape(user.username)}" if user.username else "<i>Not set</i>"
        lang = html.escape(user.language_code or "—")
        is_premium = "👑 Yes" if getattr(user, "is_premium", False) else "❌ No"
        is_owner = (OWNER_ID and user.id == OWNER_ID)
        remaining = get_remaining(user.id)
        remaining_str = "♾️ Unlimited" if remaining == -1 else f"{remaining}/{MAX_SEARCHES_PER_DAY}"
        text = ("👤 <b>Your Profile</b>\n\n<blockquote>"
                f"🆔 <b>User ID:</b> <code>{user.id}</code>\n"
                f"👤 <b>Full Name:</b> {html.escape(user.full_name)}\n"
                f"🔗 <b>Username:</b> {uname}\n🌐 <b>Language:</b> <code>{lang}</code>\n"
                f"💎 <b>Premium:</b> {is_premium}\n👑 <b>Owner:</b> {'Yes' if is_owner else 'No'}\n"
                f"📊 <b>Remaining Searches:</b> <code>{remaining_str}</code>"
                f"</blockquote>\n\n📅 <b>Session:</b> <code>{now_str()}</code>" + bot_signature())
        await safe_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=back_kb())

    elif data == "menu":
        text = ("👋 <b>TG OSINT Bot</b>\n\n<blockquote>🔎 Main menu — option चुनो</blockquote>"
                + bot_signature())
        await safe_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb())

    elif data == "close":
        await safe_edit(q, "❌ <b>Close Menu</b>\n\n<blockquote>क्या तुम menu बंद करना चाहते हो?</blockquote>",
                        parse_mode=ParseMode.HTML, reply_markup=close_kb())

    elif data == "noop":
        await q.answer("Okay!", show_alert=False)

async def handle_text(update, context):
    user = update.effective_user
    text = update.message.text.strip()
    await send_log(context, f"📥 <b>USER INPUT</b>\n🕒 {now_str()}\n\n{user_info(update)}\n\n💬 <code>{html.escape(text)}</code>")

    if not await is_member(context, user.id):
        await update.message.reply_text(join_text(), parse_mode=ParseMode.HTML, reply_markup=join_kb()); return

    is_id = text.isdigit()
    is_username = bool(re.match(r'^@?[A-Za-z][A-Za-z0-9_]{3,31}$', text))
    if not (is_id or is_username):
        reply = ("❌ <b>Invalid Input</b>\n\n<blockquote>"
                 "कृपया numeric ID या @username भेजो।\n\n<b>Examples:</b>\n"
                 "• <code>123456789</code>\n• <code>@durov</code></blockquote>" + bot_signature())
        await update.message.reply_text(reply, parse_mode=ParseMode.HTML, reply_markup=back_kb()); return

    remaining = get_remaining(user.id)
    if remaining == 0:
        reset = next_reset_str(user.id)
        text_limit = ("⏰ <b>Daily Limit Reached</b>\n\n<blockquote>"
                      f"आपने <code>{MAX_SEARCHES_PER_DAY}</code> searches की limit पूरी कर ली है।\n\n"
                      f"🔓 <b>Reset in:</b> <code>{reset}</code></blockquote>\n\n"
                      "💡 Owner को unlimited access है।" + bot_signature())
        await update.message.reply_text(text_limit, parse_mode=ParseMode.HTML); return

    msg = await update.message.reply_text("⏳ <b>Searching...</b>\n\n"
        "<blockquote>कृपया प्रतीक्षा करें, data fetch हो रहा है...</blockquote>",
        parse_mode=ParseMode.HTML)

    result = await lookup_tg_id(text)

    if not result.get("ok"):
        error = result.get("error", "No data found")
        reply = ("❌ <b>No Data Found</b>\n\n<blockquote>"
                 f"🔎 <b>Query:</b> <code>{html.escape(text)}</code>\n"
                 f"⚠️ <b>Reason:</b> <i>{html.escape(str(error))}</i>\n\n"
                 "💡 <b>Tip:</b> Database dynamic है — 5-10 मिनट बाद <b>Retry</b> करके देखो। "
                 "कई बार data बाद में update होता है।</blockquote>" + bot_signature())
        await msg.edit_text(reply, parse_mode=ParseMode.HTML, reply_markup=no_data_kb())
        await send_log(context, f"📤 <b>NO DATA</b>\n🕒 {now_str()}\n\n{user_info(update)}\n\n"
            f"🔎 <code>{html.escape(text)}</code>\n⚠️ {html.escape(str(error))}")
        return

    data = result["data"]
    record_search(user.id)
    new_remaining = get_remaining(user.id)

    copy_text = (f"Telegram ID: {data.get('tg_id', 'N/A')}\nMobile: {data.get('mobile', 'N/A')}\n"
                 f"Country Code: {data.get('country_code', 'N/A')}\nCountry: {data.get('country', 'N/A')}")
    remaining_line = "👑 <b>Unlimited</b>" if new_remaining == -1 else f"📊 <b>Remaining:</b> <code>{new_remaining}/{MAX_SEARCHES_PER_DAY}</code>"

    result_text = ("✅ <b>Result Found</b>\n\n<blockquote>"
        f"🆔 <b>Telegram ID:</b> <code>{html.escape(str(data.get('tg_id', 'N/A')))}</code>\n"
        f"📱 <b>Mobile:</b> <code>{html.escape(str(data.get('mobile', 'N/A')))}</code>\n"
        f"🌍 <b>Country Code:</b> <code>{html.escape(str(data.get('country_code', 'N/A')))}</code>\n"
        f"🏴 <b>Country:</b> <code>{html.escape(str(data.get('country', 'N/A')))}</code>"
        f"</blockquote>\n\n{remaining_line}\n🔒 <i>Data fetched securely</i>" + bot_signature())
    await msg.edit_text(result_text, parse_mode=ParseMode.HTML, reply_markup=result_kb(copy_text))
    await send_log(context, f"📤 <b>SUCCESS</b>\n🕒 {now_str()}\n\n{user_info(update)}\n\n"
        f"🔎 <code>{html.escape(text)}</code>\n📱 <code>{html.escape(str(data.get('mobile', 'N/A')))}</code>")

async def error_handler(update, context):
    logger.error("Exception:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(chat_id=update.effective_chat.id,
                text="⚠️ <b>Error</b>\n\n<blockquote>कुछ गड़बड़ हो गई। बाद में try करो।</blockquote>",
                parse_mode=ParseMode.HTML)
        except Exception: pass

def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set!"); return
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(button_handler,
        pattern="^(search|retry|help|stats|owner|support|source|profile|menu|close|noop|verify)$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)
    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
