#!/usr/bin/env python3
import logging, asyncio, html, re, time, requests
from datetime import datetime
from collections import defaultdict
from telegram import (InlineKeyboardButton, InlineKeyboardMarkup, Update, CopyTextButton)
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.error import BadRequest, TelegramError
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler,
                          ContextTypes, MessageHandler, filters)
from config import (BOT_TOKEN, LOG_CHANNEL_ID, OWNER_ID, OWNER_USERNAME, SUPPORT_LINK,
                    BOT_USERNAME, START_IMAGE_URL, GITHUB_URL, OWNER_CONTACT,
                    REFERRALS_REQUIRED, FREE_SEARCHES_PER_DAY, DEFAULT_PREMIUM_PRICE,
                    API_URL, API_KEY, MAX_TRIES, RETRY_DELAY, REQUEST_TIMEOUT)
import database as db

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
for lib in ("httpx", "telegram", "telegram.ext", "DB"): logging.getLogger(lib).setLevel(logging.WARNING)
logger = logging.getLogger("TG_OSINT")

# ========== SAFE BUTTON (style fallback) ==========
def btn(text, **kw):
    try:
        return InlineKeyboardButton(text, **kw)
    except TypeError:
        kw.pop("style", None)
        return InlineKeyboardButton(text, **kw)

# ========== LINK HELPERS ==========
def _norm_link(raw):
    if not raw: return None, "", "—"
    raw = raw.strip()
    if raw.startswith("http"):
        disp = "@" + raw.rstrip("/").split("/")[-1]
        return raw, raw, disp
    if raw.startswith("-"):
        return int(raw), f"https://t.me/{raw}", raw
    if raw.startswith("@"):
        return raw, f"https://t.me/{raw.lstrip('@')}", raw
    return f"@{raw}", f"https://t.me/{raw}", f"@{raw}"

SUPPORT_CHAT_ID, SUPPORT_URL, SUPPORT_DISPLAY = _norm_link(SUPPORT_LINK)

# ========== HELPERS ==========
def now_str(): return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

async def send_log(context, text):
    if not LOG_CHANNEL_ID: return
    try:
        await context.bot.send_message(LOG_CHANNEL_ID, text,
            parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception as e: logger.warning(f"log failed: {e}")

def user_info(update):
    u = update.effective_user
    if not u: return "<i>unknown</i>"
    un = f"@{html.escape(u.username)}" if u.username else "—"
    return f"🆔 <code>{u.id}</code>\n👤 {html.escape(u.full_name)}\n🔗 {un}"

def bot_signature():
    lines = []
    if SUPPORT_URL and SUPPORT_DISPLAY != "—":
        lines.append(f'📢 <a href="{SUPPORT_URL}">{html.escape(SUPPORT_DISPLAY)}</a>')
    if BOT_USERNAME:
        lines.append(f'🤖 <a href="https://t.me/{BOT_USERNAME.lstrip("@")}">{html.escape(BOT_USERNAME)}</a>')
    if not lines: return ""
    return "\n\n<blockquote>" + "  •  ".join(lines) + "</blockquote>"

async def smart_edit(q, text, photo=None, **kwargs):
    """Edit message smartly — handles photo vs text transition (UI break fix)."""
    msg = q.message
    has_photo = bool(getattr(msg, "photo", None))
    if photo:
        if has_photo:
            try:
                await q.edit_message_caption(caption=text, **kwargs); return
            except BadRequest as e:
                if "not modified" in str(e).lower(): return
            except Exception: pass
        else:
            try: await msg.delete()
            except Exception: pass
            try:
                await msg.chat.send_photo(photo=photo, caption=text, **kwargs); return
            except Exception: pass
    else:
        if has_photo:
            try: await msg.delete()
            except Exception: pass
            try:
                await msg.chat.send_message(text, **kwargs); return
            except Exception: pass
    try:
        await q.edit_message_text(text, **kwargs)
    except BadRequest as e:
        if "not modified" in str(e).lower(): return
        try: await msg.delete()
        except Exception: pass
        try: await msg.chat.send_message(text, **kwargs)
        except Exception as e2: logger.error(f"smart_edit fatal: {e2}")
    except Exception as e:
        logger.warning(f"smart_edit: {e}")

# ========== FORCE JOIN ==========
_membership_cache = {}
CACHE_TTL = 60

async def is_member(context, user_id):
    if not SUPPORT_CHAT_ID: return True
    if OWNER_ID and user_id == OWNER_ID: return True
    now = time.time()
    cached = _membership_cache.get(user_id)
    if cached and (now - cached[1]) < CACHE_TTL: return cached[0]
    for attempt in range(2):
        try:
            m = await context.bot.get_chat_member(SUPPORT_CHAT_ID, user_id)
            ok = m.status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR,
                              ChatMemberStatus.OWNER, ChatMemberStatus.RESTRICTED)
            _membership_cache[user_id] = (ok, now)
            return ok
        except BadRequest as e:
            err = str(e).lower()
            if "user not found" in err or "participant" in err:
                _membership_cache[user_id] = (False, now); return False
            if "chat not found" in err or "chat admin" in err:
                logger.error(f"⚠️ Support channel issue (bot admin?): {e}")
                return True
        except TelegramError as e: logger.warning(f"TG error: {e}")
        if attempt < 1: await asyncio.sleep(0.8)
    return True

def join_kb():
    b = []
    if SUPPORT_URL:
        b.append([btn("📢 Join Channel", url=SUPPORT_URL, style="primary")])
    b.append([btn("✅ Verify", callback_data="verify", style="success")])
    return InlineKeyboardMarkup(b)

def join_text():
    return ("🔒 <b>Access Restricted</b>\n\n<blockquote>"
            "इस bot को use करने के लिए पहले हमारे official channel को join करना ज़रूरी है।\n\n"
            f"📢 <b>Channel:</b> {html.escape(SUPPORT_DISPLAY)}</blockquote>\n\n"
            "👇 नीचे से <b>Join Channel</b> दबाओ, फिर <b>Verify ✅</b> दबाओ।" + bot_signature())

# ========== REFERRAL ==========
def referral_link(user_id):
    if not BOT_USERNAME: return ""
    return f"https://t.me/{BOT_USERNAME.lstrip('@')}?start=ref_{user_id}"

def referral_progress(user_id):
    cnt = db.get_referral_count(user_id)
    return cnt, REFERRALS_REQUIRED, min(cnt, REFERRALS_REQUIRED)

async def require_join(update, context):
    u = update.effective_user
    if not u: return False
    if await is_member(context, u.id): return True
    try:
        if update.callback_query:
            await smart_edit(update.callback_query, join_text(), parse_mode=ParseMode.HTML, reply_markup=join_kb())
        elif update.message:
            await update.message.reply_text(join_text(), parse_mode=ParseMode.HTML, reply_markup=join_kb())
    except Exception as e: logger.error(f"require_join: {e}")
    return False

# ========== SEARCH (API) ==========
async def lookup_tg_id(tg_id):
    q = tg_id.lstrip("@")
    last_err = None
    for i in range(MAX_TRIES):
        try:
            r = requests.get(API_URL, params={"key": API_KEY, "num": q}, timeout=REQUEST_TIMEOUT).json()
            logger.info(f"[API] {i+1}: {r}")
            if r.get("status") == "success":
                return {"ok": True, "data": {
                    "tg_id": r.get("tg_id", q), "mobile": r.get("mobile", "N/A"),
                    "country_code": r.get("country_code", "N/A"), "country": r.get("country", "N/A")}}
            last_err = r.get("error", "No data found")
        except Exception as e:
            last_err = str(e); logger.warning(f"[API] {i+1}: {e}")
        if i < MAX_TRIES - 1: await asyncio.sleep(RETRY_DELAY)
    return {"ok": False, "error": last_err or "Unknown"}

# ========== ACCESS CONTROL ==========
def can_search(user_id):
    if OWNER_ID and user_id == OWNER_ID: return True, "owner"
    if db.is_premium(user_id): return True, "premium"
    cnt = db.get_referral_count(user_id)
    if cnt >= REFERRALS_REQUIRED: return True, "referral"
    return False, "gate"

def get_remaining(user_id):
    if OWNER_ID and user_id == OWNER_ID: return -1
    if db.is_premium(user_id): return -1
    used = db.get_daily_used(user_id)
    return max(0, FREE_SEARCHES_PER_DAY - used)

def record_search(user_id):
    if (OWNER_ID and user_id == OWNER_ID) or db.is_premium(user_id): return
    db.inc_daily_used(user_id)

def reset_str(user_id):
    with db._conn() as c:
        r = c.execute("SELECT last_reset FROM users WHERE user_id=?", (user_id,)).fetchone()
    if not r or not r["last_reset"]: return "now"
    delta = (r["last_reset"] + 86400) - int(time.time())
    if delta <= 0: return "now"
    return f"{delta//3600}h {(delta%3600)//60}m"

# ========== KEYBOARDS ==========
def main_menu_kb(user_id=None):
    kb = [
        [btn("Search 🔎", callback_data="search", style="success")],
        [btn("🎁 Refer & Unlock", callback_data="referral", style="primary"),
         btn("💎 Premium", callback_data="premium", style="primary")],
        [btn("📊 Stats", callback_data="stats", style="primary"),
         btn("ℹ️ Help", callback_data="help", style="primary")],
        [btn("👑 Owner", callback_data="owner", style="primary"),
         btn("💬 Support", callback_data="support", style="primary")],
        [btn("📂 Source Code", callback_data="source", style="primary"),
         btn("👤 Profile", callback_data="profile", style="primary")],
        [btn("🔴 Close", callback_data="close", style="danger")],
    ]
    if user_id and OWNER_ID and user_id == OWNER_ID:
        kb.insert(0, [btn("🛠️ Owner Panel", callback_data="owner_panel", style="danger")])
    return InlineKeyboardMarkup(kb)

def back_kb():
    return InlineKeyboardMarkup([[btn("🔙 Back to Menu", callback_data="menu", style="danger")]])

def referral_gate_kb():
    return InlineKeyboardMarkup([
        [btn("📋 Copy Referral Link", callback_data="copy_ref", style="success")],
        [btn("🔄 Check Progress", callback_data="check_ref", style="primary"),
         btn("💎 Get Premium", callback_data="premium", style="primary")],
        [btn("🔙 Menu", callback_data="menu", style="danger")],
    ])

def result_kb(copy_text):
    kb = []
    if copy_text:
        kb.append([btn("📋 Copy Result", copy_text=CopyTextButton(text=copy_text), style="primary")])
    kb.append([btn("Search 🔎", callback_data="search", style="success"),
               btn("🔙 Menu", callback_data="menu", style="danger")])
    return InlineKeyboardMarkup(kb)

def no_data_kb():
    return InlineKeyboardMarkup([
        [btn("🔄 Retry Search", callback_data="retry", style="success")],
        [btn("🔍 New Query", callback_data="search", style="primary"),
         btn("🔙 Menu", callback_data="menu", style="danger")]])

def close_kb():
    return InlineKeyboardMarkup([[btn("✅ Yes", callback_data="menu", style="success"),
                                  btn("❌ No", callback_data="noop", style="danger")]])

def source_kb():
    b = []
    if GITHUB_URL: b.append([btn("🌐 Open Repository", url=GITHUB_URL, style="success")])
    b.append([btn("👤 My Profile", callback_data="profile", style="primary")])
    b.append([btn("🔙 Menu", callback_data="menu", style="danger")])
    return InlineKeyboardMarkup(b)

def premium_kb(is_active):
    b = []
    if not is_active:
        if OWNER_CONTACT:
            url = f"https://t.me/{OWNER_CONTACT.lstrip('@')}"
            b.append([btn("📞 Contact Owner", url=url, style="success")])
        b.append([btn("🎟️ Redeem Code", callback_data="redeem", style="primary")])
    b.append([btn("🔙 Menu", callback_data="menu", style="danger")])
    return InlineKeyboardMarkup(b)

def owner_panel_kb():
    return InlineKeyboardMarkup([
        [btn("📊 Stats", callback_data="op_stats", style="primary")],
        [btn("💰 Set Price", callback_data="op_price", style="primary"),
         btn("🎁 Gift Premium", callback_data="op_gift", style="primary")],
        [btn("🎟️ Create Coupon", callback_data="op_coupon", style="primary")],
        [btn("🔙 Menu", callback_data="menu", style="danger")],
    ])

# ========== COMMANDS ==========
async def start(update, context):
    user = update.effective_user
    await send_log(context, f"🟢 <b>/start</b>\n🕒 {now_str()}\n\n{user_info(update)}")

    # Referral parsing
    args = context.args or []
    referrer = None
    if args and args[0].startswith("ref_"):
        try: referrer = int(args[0][4:])
        except Exception: pass

    is_new = db.create_user_if_new(user.id, user.username, user.first_name)
    if is_new and referrer and referrer != user.id:
        if db.set_referrer(user.id, referrer):
            await send_log(context, f"🎁 <b>REFERRAL</b> {user.id} referred by {referrer}")
            try:
                await context.bot.send_message(
                    chat_id=referrer,
                    text=f"🎉 <b>New Referral!</b>\n\n<blockquote>Aapka ek naya referral aaya hai. Progress check karne ke liye <b>Refer & Unlock</b> button dabao.</blockquote>",
                    parse_mode=ParseMode.HTML)
            except Exception: pass

    if not await require_join(update, context): return

    allowed, reason = can_search(user.id)
    caption = (
        "👋 <b>Welcome to TG OSINT Bot</b>\n\n<blockquote>"
        "🔎 <b>Telegram ID</b> या <b>@username</b> भेजो और details निकालो।\n"
        "सब कुछ real-time और anonymous।</blockquote>\n\n"
        "🛠️ <b>Features:</b>\n<blockquote>"
        "• ID → Mobile Number\n"
        "• Username → Profile Info\n"
        "• Copy Result with Channel Link\n"
        "• Premium & Referral Unlock</blockquote>\n\n"
    )
    if reason == "owner":
        caption += "👑 <b>Welcome, Owner!</b>\n\n"
    elif reason == "premium":
        caption += "💎 <b>Premium Active</b> — unlimited searches!\n\n"
    elif reason == "gate":
        cnt, req, _ = referral_progress(user.id)
        caption += f"🔒 <b>Search Locked</b> — {cnt}/{req} referrals\n\n"
    caption += "👇 नीचे से option चुनो:" + bot_signature()

    if START_IMAGE_URL:
        try:
            await update.message.reply_photo(photo=START_IMAGE_URL, caption=caption,
                parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(user.id))
            return
        except Exception as e: logger.warning(f"img: {e}")
    await update.message.reply_text(caption, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(user.id))

async def help_cmd(update, context):
    if not await require_join(update, context): return
    text = ("ℹ️ <b>How to use</b>\n\n<blockquote>"
            "<b>Step 1:</b> /start भेजो\n"
            "<b>Step 2:</b> <b>Search 🔎</b> दबाओ\n"
            "<b>Step 3:</b> ID (जैसे <code>123456789</code>) या @username भेजो\n"
            "<b>Step 4:</b> Result का इंतज़ार करो\n"
            f"<b>Step 5:</b> Free user के लिए {REFERRALS_REQUIRED} referrals ज़रूरी</blockquote>\n\n"
            f"📊 <b>Free Limit:</b> <code>{FREE_SEARCHES_PER_DAY} searches/24hrs</code>\n"
            "💎 <b>Premium:</b> Unlimited searches\n"
            "👑 <b>Owner:</b> Unlimited (always)\n\n"
            "⚠️ केवल consent के साथ use करो।" + bot_signature())
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=back_kb())

async def cancel_cmd(update, context):
    context.user_data.clear()
    await update.message.reply_text("✅ Action cancelled.", reply_markup=main_menu_kb(update.effective_user.id))

async def post_init(app):
    db.init_db()
    logger.info("DB ready")
    if SUPPORT_CHAT_ID:
        try:
            chat = await app.bot.get_chat(SUPPORT_CHAT_ID)
            me = await app.bot.get_me()
            m = await app.bot.get_chat_member(SUPPORT_CHAT_ID, me.id)
            if m.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
                logger.info(f"✅ Bot admin in support: {chat.title}")
            else:
                logger.error("❌ Bot NOT admin in support channel!")
        except Exception as e: logger.error(f"⚠️ Support check: {e}")

# ========== SEARCH UI ==========
async def show_search_prompt(q_or_msg, user_id, is_edit=True, context=None):
    remaining = get_remaining(user_id)
    if remaining == -1:
        limit = "👑 <b>Unlimited</b>" if (OWNER_ID and user_id == OWNER_ID) else "💎 <b>Unlimited</b>"
    else:
        limit = f"📊 <b>Remaining:</b> <code>{remaining}/{FREE_SEARCHES_PER_DAY}</code>"
    text = ("🔎 <b>Send ID or @username</b>\n\n<blockquote>"
            "<b>Examples:</b>\n• <code>123456789</code> — numeric ID\n• <code>@durov</code> — username</blockquote>\n\n"
            + limit)
    if is_edit and q_or_msg:
        await smart_edit(q_or_msg, text, parse_mode=ParseMode.HTML, reply_markup=back_kb())
    return text

async def show_referral_gate(q_or_msg, user, is_edit=True):
    cnt, req, _ = referral_progress(user.id)
    link = referral_link(user.id)
    text = ("🎁 <b>Unlock Search Access</b>\n\n<blockquote>"
            f"Search unlock करने के लिए <b>{req} users</b> को refer करना ज़रूरी है।\n\n"
            f"📊 <b>Progress:</b> <code>{cnt}/{req}</code>\n"
            f"🔗 <b>Your Link:</b>\n<code>{link}</code>\n\n"
            "जब users आपके link से bot start करेंगे, तो automatically search unlock हो जाएगा।\n"
            "या <b>💎 Premium</b> लेकर instant unlock करो।</blockquote>"
            + bot_signature())
    if is_edit and q_or_msg:
        await smart_edit(q_or_msg, text, parse_mode=ParseMode.HTML, reply_markup=referral_gate_kb())
    return text

async def show_premium_screen(q, user, is_edit=True):
    active = db.is_premium(user.id)
    price = db.get_setting("premium_price", DEFAULT_PREMIUM_PRICE)
    if active:
        until = db.premium_until(user.id)
        dt = datetime.utcfromtimestamp(until).strftime("%Y-%m-%d %H:%M UTC")
        text = ("💎 <b>Premium Active</b>\n\n<blockquote>"
                f"✅ <b>Status:</b> Active\n"
                f"📅 <b>Valid till:</b> <code>{dt}</code>\n\n"
                "🎉 आपको unlimited searches मिल रहे हैं।</blockquote>" + bot_signature())
    else:
        text = ("💎 <b>Premium Access</b>\n\n<blockquote>"
                "अगर आप <b>Premium</b> लेते हो तो:\n"
                "• ♾️ Unlimited searches\n"
                "• 🚫 No referral requirement\n"
                "• ⚡ Priority support\n\n"
                f"💰 <b>Price:</b> <code>{html.escape(str(price))}</code>\n\n"
                "💡 या नीचे <b>Redeem Code</b> दबाकर code use करो।</blockquote>"
                + bot_signature())
    if is_edit:
        await smart_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=premium_kb(active))
    return text

# ========== BUTTON HANDLER ==========
async def button_handler(update, context):
    q = update.callback_query
    try: await q.answer()
    except Exception: pass
    data = q.data if isinstance(q.data, str) else ""
    user = update.effective_user
    if not user: return

    # Verify — always allowed
    if data == "verify":
        _membership_cache.pop(user.id, None)
        if await is_member(context, user.id):
            await smart_edit(q,
                "✅ <b>Verification Successful</b>\n\n<blockquote>Access unlocked! अब bot use कर सकते हो।</blockquote>"
                + bot_signature(), parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(user.id))
            await send_log(context, f"✅ VERIFIED {user.id}")
        else:
            try: await q.answer("❌ पहले channel join करो!", show_alert=True)
            except Exception: pass
        return

    if data == "noop":
        return

    if not await require_join(update, context): return

    await send_log(context, f"🔘 {data} | {user.id}")

    if data == "search":
        allowed, reason = can_search(user.id)
        if not allowed:
            await show_referral_gate(q, user, is_edit=True)
            return
        await show_search_prompt(q, user.id, is_edit=True)

    elif data == "referral":
        await show_referral_gate(q, user, is_edit=True)

    elif data == "copy_ref":
        link = referral_link(user.id)
        await q.answer(f"Copy: {link}", show_alert=True)

    elif data == "check_ref":
        cnt, req, _ = referral_progress(user.id)
        if cnt >= req:
            await q.answer(f"✅ Unlocked! {cnt}/{req}", show_alert=True)
            await smart_edit(q, "🎉 <b>Search Unlocked!</b>\n\n<blockquote>अब आप search कर सकते हो।</blockquote>"
                            + bot_signature(), parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(user.id))
        else:
            await q.answer(f"📊 Progress: {cnt}/{req}. थोड़ा और refer करो!", show_alert=True)

    elif data == "premium":
        await show_premium_screen(q, user, is_edit=True)

    elif data == "redeem":
        context.user_data["awaiting"] = "redeem_code"
        await smart_edit(q,
            "🎟️ <b>Redeem Code</b>\n\n<blockquote>अपना coupon code भेजो (case-insensitive)।\n\nCancel करने के लिए /cancel भेजो।</blockquote>",
            parse_mode=ParseMode.HTML, reply_markup=back_kb())

    elif data == "retry":
        allowed, reason = can_search(user.id)
        if not allowed:
            await show_referral_gate(q, user, is_edit=True); return
        await show_search_prompt(q, user.id, is_edit=True)

    elif data == "help":
        text = ("ℹ️ <b>How to use</b>\n\n<blockquote>"
                "1️⃣ /start\n2️⃣ <b>Search 🔎</b>\n3️⃣ ID/@username\n4️⃣ Result\n\n"
                f"Free: {REFERRALS_REQUIRED} referrals required + {FREE_SEARCHES_PER_DAY}/day\n"
                "Premium: unlimited</blockquote>" + bot_signature())
        await smart_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=back_kb())

    elif data == "stats":
        is_owner = bool(OWNER_ID and user.id == OWNER_ID)
        rem = get_remaining(user.id)
        lim = "♾️ Unlimited" if rem == -1 else f"{rem}/{FREE_SEARCHES_PER_DAY}"
        cnt, req, _ = referral_progress(user.id)
        prem = db.is_premium(user.id)
        st = db.get_stats()
        text = ("📊 <b>Bot Statistics</b>\n\n<blockquote>"
                "🤖 <b>Status:</b> Online\n⚡ <b>Mode:</b> Long Polling\n"
                f"📡 <b>Your Remaining:</b> <code>{lim}</code>\n"
                f"🎁 <b>Your Referrals:</b> <code>{cnt}/{req}</code>\n"
                f"💎 <b>Premium:</b> {'✅ Yes' if prem else '❌ No'}\n"
                f"👑 <b>Owner:</b> {'Yes' if is_owner else 'No'}\n"
                f"👥 <b>Total Users:</b> <code>{st['total']}</code>\n"
                f"💎 <b>Premium Users:</b> <code>{st['premium']}</code>\n"
                "🛡️ <b>Version:</b> 13.0</blockquote>" + bot_signature())
        await smart_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=back_kb())

    elif data == "owner":
        owner = (f'<a href="https://t.me/{OWNER_USERNAME.lstrip("@")}">{html.escape(OWNER_USERNAME)}</a>'
                 if OWNER_USERNAME else "—")
        text = ("👑 <b>Owner Panel</b>\n\n<blockquote>"
                f"👤 <b>Owner:</b> {owner}\n🛠️ <b>Role:</b> Developer\n📅 <b>Status:</b> Active"
                "</blockquote>\n\n💡 query के लिए message करो।" + bot_signature())
        await smart_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=back_kb(), disable_web_page_preview=True)

    elif data == "support":
        text = ("💬 <b>Support Center</b>\n\n<blockquote>"
                f'📢 <b>Channel:</b> <a href="{SUPPORT_URL}">{html.escape(SUPPORT_DISPLAY)}</a>\n'
                "⏰ <b>Response:</b> 24 hours\n📝 Details के साथ message करो</blockquote>" + bot_signature())
        await smart_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=back_kb(), disable_web_page_preview=True)

    elif data == "source":
        text = ("📂 <b>Source Code</b>\n\n<blockquote>"
                "🛠️ <b>Language:</b> Python 3.11\n📦 <b>Framework:</b> python-telegram-bot 22.8\n"
                "📜 <b>License:</b> Open Source</blockquote>" + bot_signature())
        await smart_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=source_kb(), disable_web_page_preview=True)

    elif data == "profile":
        un = f"@{html.escape(user.username)}" if user.username else "<i>Not set</i>"
        is_owner = bool(OWNER_ID and user.id == OWNER_ID)
        prem = db.is_premium(user.id)
        rem = get_remaining(user.id)
        rem_s = "♾️ Unlimited" if rem == -1 else f"{rem}/{FREE_SEARCHES_PER_DAY}"
        cnt, req, _ = referral_progress(user.id)
        text = ("👤 <b>Your Profile</b>\n\n<blockquote>"
                f"🆔 <b>User ID:</b> <code>{user.id}</code>\n"
                f"👤 <b>Name:</b> {html.escape(user.full_name)}\n"
                f"🔗 <b>Username:</b> {un}\n"
                f"🌐 <b>Language:</b> <code>{html.escape(user.language_code or '—')}</code>\n"
                f"💎 <b>Premium:</b> {'✅ Yes' if prem else '❌ No'}\n"
                f"👑 <b>Owner:</b> {'Yes' if is_owner else 'No'}\n"
                f"🎁 <b>Referrals:</b> <code>{cnt}/{req}</code>\n"
                f"📊 <b>Remaining:</b> <code>{rem_s}</code></blockquote>\n\n"
                f"📅 <b>Session:</b> <code>{now_str()}</code>" + bot_signature())
        await smart_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=back_kb())

    elif data == "menu":
        text = ("👋 <b>TG OSINT Bot</b>\n\n<blockquote>🔎 Main menu — option चुनो</blockquote>" + bot_signature())
        await smart_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(user.id))

    elif data == "close":
        await smart_edit(q, "❌ <b>Close Menu</b>\n\n<blockquote>मेनू बंद करें?</blockquote>",
                        parse_mode=ParseMode.HTML, reply_markup=close_kb())

    # ========== OWNER PANEL ==========
    elif data.startswith("op_"):
        if not (OWNER_ID and user.id == OWNER_ID):
            await q.answer("❌ Owner only!", show_alert=True); return

        if data == "op_stats":
            st = db.get_stats()
            price = db.get_setting("premium_price", DEFAULT_PREMIUM_PRICE)
            text = ("📊 <b>Owner Dashboard</b>\n\n<blockquote>"
                    f"👥 <b>Total Users:</b> <code>{st['total']}</code>\n"
                    f"💎 <b>Premium Users:</b> <code>{st['premium']}</code>\n"
                    f"🎟️ <b>Coupons Created:</b> <code>{st['coupons']}</code>\n"
                    f"💰 <b>Premium Price:</b> <code>{html.escape(str(price))}</code>\n"
                    f"🔒 <b>Referrals Required:</b> <code>{REFERRALS_REQUIRED}</code>\n"
                    f"📊 <b>Free Daily Limit:</b> <code>{FREE_SEARCHES_PER_DAY}</code></blockquote>"
                    + bot_signature())
            await smart_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=owner_panel_kb())

        elif data == "op_price":
            context.user_data["awaiting"] = "owner_set_price"
            await smart_edit(q, "💰 <b>Set Premium Price</b>\n\n<blockquote>नई price भेजो (जैसे <code>₹199 / 30 days</code>)।\nCancel: /cancel</blockquote>",
                            parse_mode=ParseMode.HTML, reply_markup=owner_panel_kb())

        elif data == "op_gift":
            context.user_data["awaiting"] = "owner_gift"
            await smart_edit(q, "🎁 <b>Gift Premium</b>\n\n<blockquote>Format: <code>user_id days</code>\nExample: <code>8098146730 30</code>\n\nCancel: /cancel</blockquote>",
                            parse_mode=ParseMode.HTML, reply_markup=owner_panel_kb())

        elif data == "op_coupon":
            context.user_data["awaiting"] = "owner_coupon"
            await smart_edit(q, "🎟️ <b>Create Coupon</b>\n\n<blockquote>Format: <code>CODE days max_uses</code>\nExample: <code>WELCOME30 30 100</code>\n\nCancel: /cancel</blockquote>",
                            parse_mode=ParseMode.HTML, reply_markup=owner_panel_kb())

    elif data == "owner_panel":
        if OWNER_ID and user.id == OWNER_ID:
            await smart_edit(q, "🛠️ <b>Owner Panel</b>\n\n<blockquote>Choose action:</blockquote>",
                            parse_mode=ParseMode.HTML, reply_markup=owner_panel_kb())

# ========== TEXT HANDLER ==========
async def handle_text(update, context):
    user = update.effective_user
    text = update.message.text.strip()
    awaiting = context.user_data.get("awaiting")

    await send_log(context, f"📥 <b>INPUT</b>\n🕒 {now_str()}\n\n{user_info(update)}\n\n💬 <code>{html.escape(text)}</code>")

    if not await require_join(update, context): return

    # ---- Pending actions (owner panel + redeem) ----
    if awaiting == "redeem_code":
        context.user_data.pop("awaiting", None)
        days, err = db.redeem_coupon(user.id, text)
        if err == "invalid":
            await update.message.reply_text("❌ Invalid code.", reply_markup=back_kb()); return
        if err == "exhausted":
            await update.message.reply_text("❌ Code exhausted.", reply_markup=back_kb()); return
        if err == "already":
            await update.message.reply_text("❌ आप ये code पहले use कर चुके हो.", reply_markup=back_kb()); return
        db.add_premium(user.id, days)
        until = db.premium_until(user.id)
        dt = datetime.utcfromtimestamp(until).strftime("%Y-%m-%d")
        await update.message.reply_text(
            f"✅ <b>Code Redeemed!</b>\n\n<blockquote>💎 <b>Premium Active</b>\n📅 Valid till: <code>{dt}</code>\n🎉 {days} days premium added!</blockquote>"
            + bot_signature(), parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(user.id))
        await send_log(context, f"🎟️ Redeem: {user.id} used code {text} → +{days}d")
        return

    if awaiting == "owner_set_price" and OWNER_ID and user.id == OWNER_ID:
        context.user_data.pop("awaiting", None)
        db.set_setting("premium_price", text)
        await update.message.reply_text(f"✅ Price set to: <code>{html.escape(text)}</code>",
                                        parse_mode=ParseMode.HTML, reply_markup=owner_panel_kb()); return

    if awaiting == "owner_gift" and OWNER_ID and user.id == OWNER_ID:
        context.user_data.pop("awaiting", None)
        parts = text.split()
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
            await update.message.reply_text("❌ Format: <code>user_id days</code>", parse_mode=ParseMode.HTML, reply_markup=owner_panel_kb()); return
        target, days = int(parts[0]), int(parts[1])
        db.add_premium(target, days)
        until = db.premium_until(target)
        dt = datetime.utcfromtimestamp(until).strftime("%Y-%m-%d")
        await update.message.reply_text(f"✅ Gifted <code>{days}</code> days to <code>{target}</code>\nValid till: {dt}",
                                        parse_mode=ParseMode.HTML, reply_markup=owner_panel_kb())
        try:
            await context.bot.send_message(target,
                f"🎁 <b>Premium Gifted!</b>\n\n<blockquote>👑 Owner ने आपको <b>{days} days Premium</b> gift किया है!\n📅 Valid till: <code>{dt}</code></blockquote>",
                parse_mode=ParseMode.HTML)
        except Exception: pass
        return

    if awaiting == "owner_coupon" and OWNER_ID and user.id == OWNER_ID:
        context.user_data.pop("awaiting", None)
        parts = text.split()
        if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
            await update.message.reply_text("❌ Format: <code>CODE days max_uses</code>", parse_mode=ParseMode.HTML, reply_markup=owner_panel_kb()); return
        code, days, mx = parts[0].upper(), int(parts[1]), int(parts[2])
        ok = db.create_coupon(code, days, mx, user.id)
        if ok:
            await update.message.reply_text(
                f"✅ <b>Coupon Created</b>\n\n<blockquote>🎟️ Code: <code>{code}</code>\n📅 Days: <code>{days}</code>\n🔢 Max uses: <code>{mx}</code></blockquote>",
                parse_mode=ParseMode.HTML, reply_markup=owner_panel_kb())
        else:
            await update.message.reply_text("❌ Code already exists.", reply_markup=owner_panel_kb())
        return

    # ---- Default: search query ----
    is_id = text.isdigit()
    is_username = bool(re.match(r'^@?[A-Za-z][A-Za-z0-9_]{3,31}$', text))
    if not (is_id or is_username):
        await update.message.reply_text(
            "❌ <b>Invalid Input</b>\n\n<blockquote>Numeric ID या @username भेजो।\n\n"
            "• <code>123456789</code>\n• <code>@durov</code></blockquote>" + bot_signature(),
            parse_mode=ParseMode.HTML, reply_markup=back_kb()); return

    allowed, reason = can_search(user.id)
    if not allowed:
        await show_referral_gate(update.message, user, is_edit=False) if False else None
        await update.message.reply_text(await show_referral_gate(None, user, is_edit=False),
                                        parse_mode=ParseMode.HTML, reply_markup=referral_gate_kb())
        return

    remaining = get_remaining(user.id)
    if remaining == 0:
        await update.message.reply_text(
            f"⏰ <b>Daily Limit Reached</b>\n\n<blockquote>आपने {FREE_SEARCHES_PER_DAY} searches की limit पूरी कर ली।\n\n"
            f"🔓 Reset in: <code>{reset_str(user.id)}</code></blockquote>\n\n💡 Premium लेकर unlimited पाओ।" + bot_signature(),
            parse_mode=ParseMode.HTML); return

    msg = await update.message.reply_text("⏳ <b>Searching...</b>\n\n<blockquote>Data fetch हो रहा है...</blockquote>",
                                          parse_mode=ParseMode.HTML)
    result = await lookup_tg_id(text)

    if not result.get("ok"):
        err = result.get("error", "No data found")
        await msg.edit_text(
            f"❌ <b>No Data Found</b>\n\n<blockquote>🔎 <b>Query:</b> <code>{html.escape(text)}</code>\n"
            f"⚠️ <b>Reason:</b> <i>{html.escape(str(err))}</i>\n\n"
            "💡 Database dynamic है — 5-10 मिनट बाद Retry करो।</blockquote>" + bot_signature(),
            parse_mode=ParseMode.HTML, reply_markup=no_data_kb())
        await send_log(context, f"📤 NO DATA: {text} | {user.id}")
        return

    data = result["data"]
    record_search(user.id)
    new_rem = get_remaining(user.id)
    rem_line = ("👑 <b>Unlimited</b>" if (OWNER_ID and user.id == OWNER_ID)
                else ("💎 <b>Unlimited</b>" if db.is_premium(user.id)
                      else f"📊 <b>Remaining:</b> <code>{new_rem}/{FREE_SEARCHES_PER_DAY}</code>"))

    # Copy text — includes channel + bot
    copy_lines = [
        f"🔎 Telegram ID: {data.get('tg_id', 'N/A')}",
        f"📱 Mobile: {data.get('mobile', 'N/A')}",
        f"🌍 Country Code: {data.get('country_code', 'N/A')}",
        f"🏴 Country: {data.get('country', 'N/A')}",
        "",
    ]
    if SUPPORT_DISPLAY and SUPPORT_DISPLAY != "—":
        copy_lines.append(f"📢 Channel: {SUPPORT_DISPLAY}")
    if BOT_USERNAME:
        copy_lines.append(f"🤖 Bot: {BOT_USERNAME}")
    copy_text = "\n".join(copy_lines)

    result_text = ("✅ <b>Result Found</b>\n\n<blockquote>"
        f"🆔 <b>Telegram ID:</b> <code>{html.escape(str(data.get('tg_id', 'N/A')))}</code>\n"
        f"📱 <b>Mobile:</b> <code>{html.escape(str(data.get('mobile', 'N/A')))}</code>\n"
        f"🌍 <b>Country Code:</b> <code>{html.escape(str(data.get('country_code', 'N/A')))}</code>\n"
        f"🏴 <b>Country:</b> <code>{html.escape(str(data.get('country', 'N/A')))}</code>"
        f"</blockquote>\n\n{rem_line}\n🔒 <i>Data fetched securely</i>" + bot_signature())
    await msg.edit_text(result_text, parse_mode=ParseMode.HTML, reply_markup=result_kb(copy_text))
    await send_log(context, f"📤 SUCCESS: {text} → {data.get('mobile')} | user {user.id}")

# ========== ERROR HANDLER ==========
async def error_handler(update, context):
    logger.error("Exception:", exc_info=context.error)
    err = str(context.error)
    if "Query is too old" in err or "query ID is invalid" in err: return
    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(update.effective_chat.id,
                "⚠️ <b>Error</b>\n\n<blockquote>कुछ गड़बड़ हो गई। बाद में try करो।</blockquote>",
                parse_mode=ParseMode.HTML)
        except Exception: pass

# ========== MAIN ==========
def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN missing!"); return
    app = (Application.builder().token(BOT_TOKEN).post_init(post_init).build())
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CallbackQueryHandler(button_handler,
        pattern="^(search|retry|help|stats|owner|support|source|profile|menu|close|noop|verify|referral|copy_ref|check_ref|premium|redeem|owner_panel|op_stats|op_price|op_gift|op_coupon)$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)
    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
