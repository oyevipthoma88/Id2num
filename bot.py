#!/usr/bin/env python3
import logging, asyncio, html, re, time, requests, traceback
from datetime import datetime
from telegram import (InlineKeyboardButton, InlineKeyboardMarkup, Update, CopyTextButton)
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.error import BadRequest, TelegramError
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler,
                          ContextTypes, MessageHandler, filters)
from config import (BOT_TOKEN, LOG_CHANNEL_ID, OWNER_ID, OWNER_USERNAME, OWNER_CONTACT,
                    TG_SCRAPE_URL, SCRAPE_TIMEOUT, SCRAPE_UA,
                    SUPPORT_LINK, BOT_USERNAME, START_IMAGE_URL, GITHUB_URL,
                    REFERRALS_REQUIRED, FREE_SEARCHES_PER_DAY,
                    API_URL, API_KEY, MAX_TRIES, RETRY_DELAY, REQUEST_TIMEOUT)
import database as db

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
for lib in ("httpx", "telegram", "motor", "pymongo", "DB"): logging.getLogger(lib).setLevel(logging.WARNING)
logger = logging.getLogger("TG_OSINT")

def btn(text, **kw):
    try: return InlineKeyboardButton(text, **kw)
    except (TypeError, ValueError):
        kw.pop("style", None)
        return InlineKeyboardButton(text, **kw)

def _norm_link(raw):
    if not raw: return None, "", "—"
    raw = raw.strip()
    if raw.startswith("http"):
        return raw, raw, "@" + raw.rstrip("/").split("/")[-1]
    if raw.startswith("-"):
        # Private channel — numeric ID
        chat_id = int(raw)
        short = str(abs(chat_id))[3:] if len(str(abs(chat_id))) > 3 else str(abs(chat_id))
        return chat_id, f"https://t.me/c/{short}", "Private Channel"
    if raw.startswith("@"):
        return raw, f"https://t.me/{raw.lstrip('@')}", raw
    return f"@{raw}", f"https://t.me/{raw}", f"@{raw}"

SUPPORT_CHAT_ID, SUPPORT_URL, SUPPORT_DISPLAY = _norm_link(SUPPORT_LINK)

def now_str(): return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

async def send_log(context, text):
    if not LOG_CHANNEL_ID: return
    try:
        await context.bot.send_message(
            LOG_CHANNEL_ID, text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True)
    except Exception as e:
        logger.warning(f"log: {e}")

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

async def smart_edit(q, text, **kwargs):
    msg = q.message
    has_photo = bool(getattr(msg, "photo", None))
    if has_photo:
        if len(text) <= 1024:
            try:
                await q.edit_message_caption(caption=text, **kwargs); return
            except BadRequest as e:
                if "not modified" in str(e).lower(): return
            except Exception: pass
        try: await msg.delete()
        except Exception: pass
        try: await msg.chat.send_message(text, **kwargs); return
        except Exception as e: logger.warning(f"send after delete: {e}")
    try: await q.edit_message_text(text, **kwargs)
    except BadRequest as e:
        err = str(e).lower()
        if "not modified" in err: return
        if "message to edit not found" in err: return
        try: await msg.delete()
        except Exception: pass
        try: await msg.chat.send_message(text, **kwargs)
        except Exception as e2: logger.error(f"smart_edit fatal: {e2}")
    except Exception as e: logger.warning(f"smart_edit: {e}")

# ===== FORCE JOIN =====
_member_cache = {}
CACHE_TTL = 300

async def is_member(context, user_id):
    if not SUPPORT_CHAT_ID: return True
    if OWNER_ID and user_id == OWNER_ID: return True
    now = time.time()
    c = _member_cache.get(user_id)
    if c and (now - c[1]) < CACHE_TTL: return c[0]
    try:
        m = await context.bot.get_chat_member(SUPPORT_CHAT_ID, user_id)
        ok = m.status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR,
                          ChatMemberStatus.OWNER, ChatMemberStatus.RESTRICTED)
        _member_cache[user_id] = (ok, now)
        return ok
    except BadRequest as e:
        err = str(e).lower()
        if "user not found" in err or "participant" in err:
            _member_cache[user_id] = (False, now)
            return False
        if "chat not found" in err or "chat admin" in err:
            logger.error(f"⚠️ Support channel issue (bot admin?): {e}")
            return True
        logger.warning(f"Member check: {e}")
        return True
    except TelegramError as e:
        logger.warning(f"TG error: {e}")
        return True

def join_kb():
    b = []
    if SUPPORT_URL: b.append([btn("📢 Join Channel", url=SUPPORT_URL, style="primary")])
    b.append([btn("✅ Verify", callback_data="verify", style="success")])
    return InlineKeyboardMarkup(b)

def join_text():
    return ("🔒 <b>Access Restricted</b>\n\n<blockquote>"
            "इस bot को use करने के लिए पहले हमारे official channel को join करना ज़रूरी है।\n\n"
            f"📢 <b>Channel:</b> {html.escape(SUPPORT_DISPLAY)}</blockquote>\n\n"
            "👇 नीचे से Join दबाओ, फिर Verify ✅ दबाओ।" + bot_signature())

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

# ===== REFERRAL =====
def referral_link(user_id):
    if not BOT_USERNAME: return ""
    username = BOT_USERNAME.lstrip("@")
    return f"https://t.me/{username}?start=ref_{user_id}"

async def referral_progress(user_id):
    cnt = await db.get_referral_count(user_id)
    return cnt, REFERRALS_REQUIRED

# ===== API LOOKUP =====
async def lookup_tg_id(tg_id):
    q = tg_id.lstrip("@"); last_err = None
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



# ===== USERNAME PROFILE SCRAPER =====
def _scrape_meta(html, prop, attr="property"):
    """Extract meta tag content (og: or twitter:)"""
    pattern = rf'<meta[^>]+{attr}=["\'](?:og:|twitter:)?{prop}["\'][^>]+content=["\']([^"\']*)["\']'
    m = re.search(pattern, html, re.IGNORECASE)
    return m.group(1).strip() if m else None


async def scrape_username(username):
    """t.me/username से profile data निकालो"""
    u = username.lstrip("@").strip()
    if not u:
        return None
    try:
        url = TG_SCRAPE_URL.format(username=u)
        r = requests.get(url, timeout=SCRAPE_TIMEOUT,
                         headers={"User-Agent": SCRAPE_UA})
        r.raise_for_status()
        html = r.text

        def og(prop):
            m = re.search(
                rf'<meta[^>]+property=["\']og:{prop}["\'][^>]+content=["\']([^"\']*)["\']',
                html, re.IGNORECASE)
            return m.group(1).strip() if m else None

        def tw(prop):
            m = re.search(
                rf'<meta[^>]+name=["\']twitter:{prop}["\'][^>]+content=["\']([^"\']*)["\']',
                html, re.IGNORECASE)
            return m.group(1).strip() if m else None

        return {
            "username": u,
            "display": og("title") or tw("title"),
            "bio": og("description") or tw("description"),
            "avatar_url": og("image") or tw("image"),
            "profile_url": url,
        }
    except Exception as e:
        logger.warning(f"scrape_username failed: {e}")
        return None


# ===== ACCESS =====
async def can_search(user_id):
    if OWNER_ID and user_id == OWNER_ID: return True, "owner"
    if await db.is_premium(user_id): return True, "premium"
    cnt = await db.get_referral_count(user_id)
    if cnt >= REFERRALS_REQUIRED: return True, "referral"
    return False, "gate"

async def get_remaining(user_id):
    if OWNER_ID and user_id == OWNER_ID: return -1
    if await db.is_premium(user_id): return -1
    used = await db.get_daily_used(user_id)
    return max(0, FREE_SEARCHES_PER_DAY - used)

async def record_search(user_id):
    if (OWNER_ID and user_id == OWNER_ID) or await db.is_premium(user_id): return
    await db.inc_daily_used(user_id)

async def reset_str(user_id):
    u = await db._get_db().users.find_one({"user_id": user_id})
    if not u or not u.get("last_reset"):
        return "24h"
    delta = (u["last_reset"] + 86400) - int(time.time())
    if delta <= 0:
        return "now"
    return f"{delta // 3600}h {(delta % 3600) // 60}m"

# ===== KEYBOARDS =====
def main_menu_kb(user_id=None):
    kb = [
        [btn("Search 🔎", callback_data="search", style="success")],
        [btn("🎁 Refer & Unlock", callback_data="referral", style="primary"),
         btn("💎 Premium", callback_data="premium", style="primary")],
        [btn("📊 Stats", callback_data="stats", style="primary"),
         btn("ℹ️ Help", callback_data="help", style="primary")],
        [btn("👑 Owner", callback_data="owner", style="primary"),
         btn("💬 Support", callback_data="support", style="primary")],
        [btn("📂 Source", callback_data="source", style="primary"),
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
        [btn("🔙 Menu", callback_data="menu", style="danger")]])

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

async def premium_kb(is_active):
    b = []
    if not is_active:
        b.append([btn("🎟️ Redeem Code", callback_data="redeem", style="primary")])
    b.append([btn("🔙 Menu", callback_data="menu", style="danger")])
    return InlineKeyboardMarkup(b)

async def plans_kb():
    prices = await db.get_all_prices()
    rows = []
    for key, meta in db.DEFAULT_PLANS.items():
        label = meta["label"]
        price = prices.get(key, "—")
        rows.append([btn(f"💎 {label} — {price}", callback_data=f"plan_{key}", style="primary")])
    rows.append([btn("🔙 Back", callback_data="premium", style="danger")])
    return InlineKeyboardMarkup(rows)

def ss_upload_kb(plan_key):
    return InlineKeyboardMarkup([
        [btn("❌ Cancel", callback_data="premium", style="danger")]])

async def owner_panel_kb():
    return InlineKeyboardMarkup([
        [btn("📊 Stats", callback_data="op_stats", style="primary"),
         btn("💰 Set Prices", callback_data="op_prices", style="primary")],
        [btn("📷 Set QR", callback_data="op_qr", style="primary"),
         btn("🎁 Gift Premium", callback_data="op_gift", style="primary")],
        [btn("🎟️ Create Coupon", callback_data="op_coupon", style="primary")],
        [btn("🔙 Menu", callback_data="menu", style="danger")]])

async def owner_prices_kb():
    rows = []
    for key, meta in db.DEFAULT_PLANS.items():
        rows.append([btn(f"✏️ {meta['label']}", callback_data=f"op_setprice_{key}", style="primary")])
    rows.append([btn("🔙 Panel", callback_data="owner_panel", style="danger")])
    return InlineKeyboardMarkup(rows)

def approval_kb(payment_id):
    return InlineKeyboardMarkup([
        [btn("✅ Approve", callback_data=f"approve_{payment_id}", style="success"),
         btn("❌ Decline", callback_data=f"decline_{payment_id}", style="danger")]])

# ===== SCREENS =====
async def show_search_prompt(q, user_id, is_edit=True):
    remaining = await get_remaining(user_id)
    if remaining == -1:
        limit = "👑 <b>Unlimited</b>" if (OWNER_ID and user_id == OWNER_ID) else "💎 <b>Unlimited</b>"
    else:
        limit = f"📊 <b>Remaining:</b> <code>{remaining}/{FREE_SEARCHES_PER_DAY}</code>"
    text = ("🔎 <b>Send ID or @username</b>\n\n<blockquote>"
            "<b>Examples:</b>\n• <code>123456789</code>\n• <code>@durov</code></blockquote>\n\n" + limit)
    if is_edit and q:
        await smart_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=back_kb())
    return text

async def show_referral_gate(q, user, is_edit=True):
    cnt, req = await referral_progress(user.id)
    link = referral_link(user.id)
    text = ("🎁 <b>Unlock Search Access</b>\n\n<blockquote>"
            f"Search unlock करने के लिए <b>{req} users</b> को refer करो।\n\n"
            f"📊 <b>Progress:</b> <code>{cnt}/{req}</code>\n"
            f"🔗 <b>Your Link:</b>\n<code>{link}</code></blockquote>"
            + bot_signature())
    if is_edit and q:
        await smart_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=referral_gate_kb())
    return text

async def show_premium_screen(q, user, is_edit=True):
    active = await db.is_premium(user.id)
    if active:
        until = await db.premium_until(user.id)
        if until == -1:
            valid = "♾️ Lifetime"
        else:
            valid = datetime.utcfromtimestamp(until).strftime("%Y-%m-%d %H:%M UTC")
        text = ("💎 <b>Premium Active</b>\n\n<blockquote>"
                f"✅ <b>Status:</b> Active\n"
                f"📅 <b>Valid till:</b> <code>{valid}</code>\n\n"
                "🎉 आपको unlimited searches मिल रहे हैं।</blockquote>" + bot_signature())
        kb = await premium_kb(True)
    else:
        prices = await db.get_all_prices()
        lines = "\n".join([f"• <b>{meta['label']}:</b> <code>{prices[k]}</code>"
                           for k, meta in db.DEFAULT_PLANS.items()])
        text = ("💎 <b>Premium Plans</b>\n\n<blockquote>"
                "💎 <b>Unlock Premium</b> to get:\n"
                "• ♾️ Unlimited searches\n"
                "• 🚫 No referral requirement\n"
                "• ⚡ Priority support\n\n"
                f"💰 <b>Prices:</b>\n{lines}\n\n"
                "👇 नीचे से plan चुनो:</blockquote>" + bot_signature())
        kb = await plans_kb()
    if is_edit and q:
        await smart_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=kb)
    return text

# ===== COMMANDS =====
async def start(update, context):
    user = update.effective_user
    if not user:
        return

    # Referral parsing — multiple formats support
    args = context.args or []
    referrer = None
    if args:
        arg = args[0].strip()
        if arg.startswith("ref_"):
            try:
                referrer = int(arg[4:])
            except Exception:
                pass
        elif arg.isdigit():
            try:
                referrer = int(arg)
            except Exception:
                pass

    is_new = await db.create_user_if_new(user.id, user.username, user.first_name)

    # Referral process — only for NEW users
    if is_new and referrer and referrer != user.id:
        success = await db.set_referrer(user.id, referrer)
        if success:
            # Log
            await send_log(context,
                f"🎁 <b>REFERRAL</b>\n🕒 {now_str()}\n\n"
                f"👤 New: <code>{user.id}</code> ({html.escape(user.full_name)})\n"
                f"🔗 Referrer: <code>{referrer}</code>")
            # Notify referrer
            try:
                ref_cnt = await db.get_referral_count(referrer)
                if ref_cnt >= REFERRALS_REQUIRED:
                    msg = (f"🎉 <b>Search Unlocked!</b>\n\n<blockquote>"
                           f"आपने <code>{ref_cnt}/{REFERRALS_REQUIRED}</code> referrals पूरे कर लिए।\n"
                           f"अब आप search कर सकते हो!</blockquote>")
                else:
                    msg = (f"🎉 <b>New Referral!</b>\n\n<blockquote>"
                           f"👤 <b>New User:</b> {html.escape(user.full_name)}\n"
                           f"📊 <b>Progress:</b> <code>{ref_cnt}/{REFERRALS_REQUIRED}</code>\n"
                           f"और refer करने पर unlock होगा।</blockquote>")
                await context.bot.send_message(referrer, msg,
                    parse_mode=ParseMode.HTML, disable_web_page_preview=True)
            except Exception as e:
                logger.warning(f"referrer notify failed: {e}")

    await send_log(context, f"🟢 /start\n🕒 {now_str()}\n\n{user_info(update)}")

    if not await require_join(update, context): return
    allowed, reason = await can_search(user.id)
    caption = ("👋 <b>Welcome to TG OSINT Bot</b>\n\n<blockquote>"
               "🔎 ID / @username भेजो, details निकालो।</blockquote>\n\n"
               "🛠️ <b>Features:</b>\n<blockquote>"
               "• ID → Mobile Number\n• Username → Info\n"
               "• Referral Unlock\n• Premium Plans</blockquote>\n\n")
    if reason == "owner": caption += "👑 <b>Welcome, Owner!</b>\n\n"
    elif reason == "premium": caption += "💎 <b>Premium Active</b>\n\n"
    elif reason == "gate":
        cnt, req = await referral_progress(user.id)
        caption += f"🔒 <b>Search Locked</b> — {cnt}/{req} referrals\n\n"
    caption += "👇 नीचे से option चुनो:" + bot_signature()
    if START_IMAGE_URL:
        try:
            await update.message.reply_photo(photo=START_IMAGE_URL, caption=caption,
                parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(user.id)); return
        except Exception as e: logger.warning(f"img: {e}")
    await update.message.reply_text(caption, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(user.id))

async def help_cmd(update, context):
    if not await require_join(update, context): return
    text = ("ℹ️ <b>How to use</b>\n\n<blockquote>"
            "1️⃣ /start\n2️⃣ <b>Search 🔎</b>\n3️⃣ ID/@username\n4️⃣ Result\n\n"
            f"Free: {REFERRALS_REQUIRED} referrals + {FREE_SEARCHES_PER_DAY}/day\n"
            "Premium: unlimited</blockquote>" + bot_signature())
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=back_kb())

async def cancel_cmd(update, context):
    context.user_data.clear()
    await update.message.reply_text("✅ Cancelled.", reply_markup=main_menu_kb(update.effective_user.id))

async def post_init(app):
    # MongoDB validate
    try:
        mongo = db._get_db()
        await mongo.command("ping")
        logger.info("✅ MongoDB connected")
        await db.init_db()
    except Exception as e:
        logger.error(f"❌ MongoDB failed: {e}")
        raise

    # Support channel validate (startup पर)
    if SUPPORT_CHAT_ID:
        try:
            chat = await app.bot.get_chat(SUPPORT_CHAT_ID)
            me = await app.bot.get_me()
            m = await app.bot.get_chat_member(SUPPORT_CHAT_ID, me.id)
            if m.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
                logger.info(f"✅ Bot admin in support: {chat.title}")
            else:
                logger.error("❌ Bot NOT admin in support channel — force join will fail!")
        except Exception as e:
            logger.error(f"⚠️ Support check: {e}")

async def post_shutdown(app):
    await db.close_db()

# ===== PLAN SELECTION → QR =====
async def show_plan_qr(q, user, plan_key):
    plan = db.DEFAULT_PLANS.get(plan_key)
    if not plan: return
    price = await db.get_plan_price(plan_key)
    qr_file_id = await db.get_qr_file_id()
    caption_text = await db.get_qr_caption()
    text = ("💳 <b>Payment Details</b>\n\n<blockquote>"
            f"📦 <b>Plan:</b> {plan['label']}\n"
            f"💰 <b>Amount:</b> <code>{price}</code>\n\n"
            f"1️⃣ नीचे QR scan करो\n"
            f"2️⃣ Payment करो\n"
            f"3️⃣ Screenshot भेजो\n\n"
            f"{caption_text}</blockquote>" + bot_signature())
    # Save plan in user_data-like context via callback (approximate)
    if qr_file_id:
        try:
            await q.message.delete()
        except Exception: pass
        try:
            await q.message.chat.send_photo(photo=qr_file_id, caption=text,
                parse_mode=ParseMode.HTML, reply_markup=ss_upload_kb(plan_key))
            return
        except Exception as e: logger.warning(f"qr send: {e}")
    await smart_edit(q, text + "\n\n⚠️ <i>QR not set by owner yet</i>",
                     parse_mode=ParseMode.HTML, reply_markup=ss_upload_kb(plan_key))

# ===== BUTTON HANDLER =====
async def button_handler(update, context):
    q = update.callback_query
    try: await q.answer()
    except Exception: pass
    data = q.data if isinstance(q.data, str) else ""
    user = update.effective_user
    if not user: return

    if data == "verify":
        _member_cache.pop(user.id, None)
        if await is_member(context, user.id):
            await smart_edit(q,
                "✅ <b>Verification Successful</b>\n\n<blockquote>Access unlocked!</blockquote>"
                + bot_signature(), parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(user.id))
            await send_log(context, f"✅ VERIFIED {user.id}")
        else:
            try: await q.answer("❌ पहले channel join करो!", show_alert=True)
            except Exception: pass
        return

    if data == "noop": return
    if not await require_join(update, context): return
    await send_log(context, f"🔘 {data} | {user.id}")

    if data == "search":
        allowed, reason = await can_search(user.id)
        if not allowed:
            await show_referral_gate(q, user, is_edit=True); return
        await show_search_prompt(q, user.id, is_edit=True)

    elif data == "referral":
        await show_referral_gate(q, user, is_edit=True)

    elif data == "copy_ref":
        link = referral_link(user.id)
        await q.answer(f"Link: {link}", show_alert=True)

    elif data == "check_ref":
        cnt, req = await referral_progress(user.id)
        if cnt >= req:
            await q.answer(f"✅ Unlocked! {cnt}/{req}", show_alert=True)
            await smart_edit(q, "🎉 <b>Search Unlocked!</b>" + bot_signature(),
                            parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(user.id))
        else:
            await q.answer(f"📊 {cnt}/{req}. और refer करो!", show_alert=True)

    elif data == "premium":
        await show_premium_screen(q, user, is_edit=True)

    elif data.startswith("plan_"):
        plan_key = data[5:]
        await db.set_pending_plan(user.id, plan_key)  # ✅ DB में save
        await show_plan_qr(q, user, plan_key)

    elif data == "redeem":
        context.user_data["awaiting"] = "redeem_code"
        await smart_edit(q, "🎟️ <b>Redeem Code</b>\n\n<blockquote>Code भेजो (case-insensitive). Cancel: /cancel</blockquote>",
                        parse_mode=ParseMode.HTML, reply_markup=back_kb())

    elif data == "retry":
        allowed, _ = await can_search(user.id)
        if not allowed: await show_referral_gate(q, user, is_edit=True); return
        await show_search_prompt(q, user.id, is_edit=True)

    elif data == "help":
        text = ("ℹ️ <b>How to use</b>\n\n<blockquote>1️⃣ /start\n2️⃣ <b>Search 🔎</b>\n"
                "3️⃣ ID/@username\n4️⃣ Result\n\n"
                f"Free: {REFERRALS_REQUIRED} referrals + {FREE_SEARCHES_PER_DAY}/day\n"
                "Premium: unlimited</blockquote>" + bot_signature())
        await smart_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=back_kb())

    elif data == "stats":
        is_owner = bool(OWNER_ID and user.id == OWNER_ID)
        rem = await get_remaining(user.id)
        lim = "♾️ Unlimited" if rem == -1 else f"{rem}/{FREE_SEARCHES_PER_DAY}"
        cnt, req = await referral_progress(user.id)
        prem = await db.is_premium(user.id)

        # Common lines — user's own data
        lines = [
            f"📡 <b>Remaining Searches:</b> <code>{lim}</code>",
            f"🎁 <b>Your Referrals:</b> <code>{cnt}/{req}</code>",
            f"💎 <b>Premium:</b> {'✅ Active' if prem else '❌ Inactive'}",
        ]

        # Premium expiry info
        if prem:
            until = await db.premium_until(user.id)
            if until == -1:
                lines.append("📅 <b>Valid Till:</b> <code>Lifetime</code>")
            elif until:
                dt = datetime.utcfromtimestamp(until).strftime("%Y-%m-%d")
                lines.append(f"📅 <b>Valid Till:</b> <code>{dt}</code>")

        # Owner को extra data
        if is_owner:
            st = await db.get_stats()
            lines.append("")
            lines.append("👑 <b>Owner View:</b>")
            lines.append(f"👥 <b>Total Users:</b> <code>{st['total']}</code>")
            lines.append(f"💎 <b>Premium Users:</b> <code>{st['premium']}</code>")
            lines.append(f"⏳ <b>Pending Payments:</b> <code>{st['pending']}</code>")

        text = ("📊 <b>Your Statistics</b>\n\n<blockquote>"
                + "\n".join(lines)
                + "</blockquote>" + bot_signature())
        await smart_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=back_kb())

    elif data == "owner":
        owner = (f'<a href="https://t.me/{OWNER_USERNAME.lstrip("@")}">{html.escape(OWNER_USERNAME)}</a>'
                 if OWNER_USERNAME else "—")
        text = ("👑 <b>Owner Panel</b>\n\n<blockquote>"
                f"👤 <b>Owner:</b> {owner}\n🛠️ <b>Role:</b> Developer</blockquote>\n\n"
                "💡 query के लिए message करो।" + bot_signature())
        await smart_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=back_kb(), disable_web_page_preview=True)

    elif data == "support":
        text = ("💬 <b>Support Center</b>\n\n<blockquote>"
                f'📢 <a href="{SUPPORT_URL}">{html.escape(SUPPORT_DISPLAY)}</a>\n'
                "⏰ 24 hours\n📝 Details के साथ message करो</blockquote>" + bot_signature())
        await smart_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=back_kb(), disable_web_page_preview=True)

    elif data == "source":
        text = ("📂 <b>Source Code</b>\n\n<blockquote>"
                "🛠️ Python 3.11\n📦 python-telegram-bot 22.8\n"
                "📜 Open Source</blockquote>" + bot_signature())
        await smart_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=source_kb(), disable_web_page_preview=True)

    elif data == "profile":
        un = f"@{html.escape(user.username)}" if user.username else "<i>Not set</i>"
        is_owner = bool(OWNER_ID and user.id == OWNER_ID)
        prem = await db.is_premium(user.id)
        rem = await get_remaining(user.id)
        rem_s = "♾️" if rem == -1 else f"{rem}/{FREE_SEARCHES_PER_DAY}"
        cnt, req = await referral_progress(user.id)
        text = ("👤 <b>Your Profile</b>\n\n<blockquote>"
                f"🆔 <code>{user.id}</code>\n"
                f"👤 {html.escape(user.full_name)}\n"
                f"🔗 {un}\n"
                f"💎 Premium: {'✅' if prem else '❌'}\n"
                f"👑 Owner: {'Yes' if is_owner else 'No'}\n"
                f"🎁 Referrals: <code>{cnt}/{req}</code>\n"
                f"📊 Remaining: <code>{rem_s}</code></blockquote>" + bot_signature())
        await smart_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=back_kb())

    elif data == "menu":
        text = ("👋 <b>TG OSINT Bot</b>\n\n<blockquote>🔎 Main menu</blockquote>" + bot_signature())
        await smart_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(user.id))

    elif data == "close":
        await smart_edit(q, "❌ <b>Close Menu</b>\n\n<blockquote>मेनू बंद करें?</blockquote>",
                        parse_mode=ParseMode.HTML, reply_markup=close_kb())

    # ===== APPROVAL (Owner only) =====
    elif data.startswith("approve_") or data.startswith("decline_"):
        if not (OWNER_ID and user.id == OWNER_ID):
            await q.answer("❌ Owner only!", show_alert=True); return
        action, pid = data.split("_", 1)
        payment = await db.get_payment(pid)
        if not payment:
            await q.answer("❌ Payment not found!", show_alert=True); return
        if payment["status"] != "pending":
            await q.answer(f"⚠️ Already {payment['status']}!", show_alert=True); return
        if action == "approve":
            ok = await db.update_payment_status(pid, "approved", user.id)
            if not ok:
                await q.answer("⚠️ Already processed!", show_alert=True); return
            await db.add_premium(payment["user_id"], payment["plan_days"], payment["plan_key"])
            new_text = (f"✅ <b>Payment Approved</b>\n\n<blockquote>"
                        f"👤 User: <code>{payment['user_id']}</code>\n"
                        f"💎 Plan: {db.DEFAULT_PLANS.get(payment['plan_key'], {}).get('label', payment['plan_key'])}\n"
                        f"💰 Amount: {payment['price']}</blockquote>\n\n"
                        f"✅ Reviewed by: <code>{user.id}</code>")
            try:
                await q.message.edit_caption(caption=new_text, parse_mode=ParseMode.HTML)
            except Exception:
                try: await q.message.edit_text(new_text, parse_mode=ParseMode.HTML)
                except Exception: pass
            try:
                await context.bot.send_message(payment["user_id"],
                    f"🎉 <b>Payment Approved!</b>\n\n<blockquote>"
                    f"💎 <b>Premium Activated</b>\n"
                    f"📦 Plan: {db.DEFAULT_PLANS.get(payment['plan_key'], {}).get('label', payment['plan_key'])}\n"
                    f"🎉 अब आपको unlimited searches मिलेंगे!</blockquote>" + bot_signature(),
                    parse_mode=ParseMode.HTML)
            except Exception: pass
            await send_log(context, f"✅ APPROVED {pid} → user {payment['user_id']} by {user.id}")
            await q.answer("✅ Approved & Premium activated!", show_alert=True)
        else:
            ok = await db.update_payment_status(pid, "declined", user.id)
            if not ok:
                await q.answer("⚠️ Already processed!", show_alert=True); return
            new_text = (f"❌ <b>Payment Declined</b>\n\n<blockquote>"
                        f"👤 User: <code>{payment['user_id']}</code>\n"
                        f"💎 Plan: {payment['plan_key']}</blockquote>")
            try: await q.message.edit_caption(caption=new_text, parse_mode=ParseMode.HTML)
            except Exception:
                try: await q.message.edit_text(new_text, parse_mode=ParseMode.HTML)
                except Exception: pass
            try:
                await context.bot.send_message(payment["user_id"],
                    "❌ <b>Payment Declined</b>\n\n<blockquote>"
                    "आपका payment screenshot accept नहीं हुआ। Support से contact करो।</blockquote>" + bot_signature(),
                    parse_mode=ParseMode.HTML)
            except Exception: pass
            await send_log(context, f"❌ DECLINED {pid} → user {payment['user_id']} by {user.id}")
            await q.answer("❌ Declined.", show_alert=True)

    # ===== OWNER PANEL =====
    elif data == "owner_panel":
        if not (OWNER_ID and user.id == OWNER_ID):
            await q.answer("❌ Owner only!", show_alert=True); return
        await smart_edit(q, "🛠️ <b>Owner Panel</b>\n\n<blockquote>Choose action:</blockquote>",
                        parse_mode=ParseMode.HTML, reply_markup=await owner_panel_kb())

    elif data == "op_stats":
        if not (OWNER_ID and user.id == OWNER_ID):
            await q.answer("❌ Owner only!", show_alert=True); return
        st = await db.get_stats()
        prices = await db.get_all_prices()
        price_lines = "\n".join([f"• {db.DEFAULT_PLANS[k]['label']}: <code>{prices[k]}</code>"
                                 for k in db.DEFAULT_PLANS])
        qr_status = "✅ Set" if await db.get_qr_file_id() else "❌ Not set"
        text = ("📊 <b>Owner Dashboard</b>\n\n<blockquote>"
                f"👥 <b>Total Users:</b> <code>{st['total']}</code>\n"
                f"💎 <b>Premium Users:</b> <code>{st['premium']}</code>\n"
                f"⏳ <b>Pending Payments:</b> <code>{st['pending']}</code>\n\n"
                f"📷 <b>QR Status:</b> {qr_status}\n\n"
                f"💰 <b>Prices:</b>\n{price_lines}</blockquote>" + bot_signature())
        await smart_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=await owner_panel_kb())

    elif data == "op_prices":
        if not (OWNER_ID and user.id == OWNER_ID): return
        await smart_edit(q, "💰 <b>Set Prices</b>\n\n<blockquote>किस plan की price set करनी है?</blockquote>",
                        parse_mode=ParseMode.HTML, reply_markup=await owner_prices_kb())

    elif data.startswith("op_setprice_"):
        if not (OWNER_ID and user.id == OWNER_ID): return
        plan_key = data[len("op_setprice_"):]
        context.user_data["awaiting"] = f"setprice_{plan_key}"
        label = db.DEFAULT_PLANS.get(plan_key, {}).get("label", plan_key)
        await smart_edit(q, f"💰 <b>Set Price — {label}</b>\n\n<blockquote>नई price भेजो (जैसे <code>₹199</code>)।\nCancel: /cancel</blockquote>",
                        parse_mode=ParseMode.HTML, reply_markup=await owner_prices_kb())

    elif data == "op_qr":
        if not (OWNER_ID and user.id == OWNER_ID): return
        context.user_data["awaiting"] = "owner_set_qr"
        await smart_edit(q, "📷 <b>Set QR Code</b>\n\n<blockquote>"
            "अपना payment QR का <b>photo</b> भेजो।\nBot उसे store करेगा और users को दिखाएगा।\n\nCancel: /cancel</blockquote>",
            parse_mode=ParseMode.HTML, reply_markup=await owner_panel_kb())

    elif data == "op_gift":
        if not (OWNER_ID and user.id == OWNER_ID): return
        context.user_data["awaiting"] = "owner_gift"
        await smart_edit(q, "🎁 <b>Gift Premium</b>\n\n<blockquote>"
            "Format: <code>user_id plan_key</code>\n"
            "Plan keys: <code>1day, 7days, 1month, 3months, 1year, lifetime</code>\n"
            "Example: <code>8098146730 1month</code>\n\nCancel: /cancel</blockquote>",
            parse_mode=ParseMode.HTML, reply_markup=await owner_panel_kb())

    elif data == "op_coupon":
        if not (OWNER_ID and user.id == OWNER_ID): return
        context.user_data["awaiting"] = "owner_coupon"
        await smart_edit(q, "🎟️ <b>Create Coupon</b>\n\n<blockquote>"
            "Format: <code>CODE days max_uses</code>\n"
            "Example: <code>WELCOME30 30 100</code>\n\nCancel: /cancel</blockquote>",
            parse_mode=ParseMode.HTML, reply_markup=await owner_panel_kb())

# ===== PHOTO HANDLER (SS Upload) =====
async def handle_photo(update, context):
    user = update.effective_user
    text = update.message.caption or ""
    awaiting = context.user_data.get("awaiting")

    # Owner QR upload
    if awaiting == "owner_set_qr" and OWNER_ID and user.id == OWNER_ID:
        context.user_data.pop("awaiting", None)
        photo = update.message.photo[-1]
        await db.set_setting("qr_file_id", photo.file_id)
        await update.message.reply_text("✅ <b>QR saved!</b> Users को payment के time दिखेगा।",
                                        parse_mode=ParseMode.HTML, reply_markup=await owner_panel_kb())
        return

    # Force join check
    if not await require_join(update, context):
        return

    # User SS upload — DB से pending plan लो (restart-safe)
    plan_key = await db.get_pending_plan(user.id)
    if not plan_key:
        await update.message.reply_text(
            "⚠️ पहले <b>Premium</b> → plan select करो।", parse_mode=ParseMode.HTML,
            reply_markup=main_menu_kb(user.id))
        return

    photo = update.message.photo[-1]
    price = await db.get_plan_price(plan_key)
    plan_days = db.PLAN_DAYS.get(plan_key, 0)
    plan_label = db.DEFAULT_PLANS.get(plan_key, {}).get("label", plan_key)

    pid = await db.create_payment(user.id, user.username, plan_key, plan_days, price,
                                   photo.file_id, update.message.chat_id, update.message.message_id)

    # Send to owner DM
    owner_text = (f"🔔 <b>New Payment Request</b>\n\n<blockquote>"
                  f"🆔 <b>Payment ID:</b> <code>{pid}</code>\n"
                  f"👤 <b>User:</b> <code>{user.id}</code>\n"
                  f"🔗 <b>Username:</b> @{html.escape(user.username or '—')}\n"
                  f"👤 <b>Name:</b> {html.escape(user.full_name)}\n\n"
                  f"💎 <b>Plan:</b> {plan_label}\n"
                  f"📅 <b>Days:</b> <code>{plan_days}</code>\n"
                  f"💰 <b>Amount:</b> <code>{price}</code></blockquote>")
    if OWNER_ID:
        try:
            await context.bot.send_photo(OWNER_ID, photo=photo.file_id,
                caption=owner_text, parse_mode=ParseMode.HTML,
                reply_markup=approval_kb(pid))
        except Exception as e: logger.error(f"owner DM: {e}")

    # Send to log channel
    if LOG_CHANNEL_ID:
        try:
            await context.bot.send_photo(LOG_CHANNEL_ID, photo=photo.file_id,
                caption=owner_text, parse_mode=ParseMode.HTML,
                reply_markup=approval_kb(pid))
        except Exception as e: logger.error(f"log channel: {e}")

    await update.message.reply_text(
        "✅ <b>Payment Proof Received!</b>\n\n<blockquote>"
        "आपका screenshot owner को भेज दिया गया है।\n"
        "Verification के बाद Premium activate हो जाएगा।\n\n"
        "⏰ Expected time: 5-30 minutes</blockquote>" + bot_signature(),
        parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(user.id))
    await db.clear_pending_plan(user.id)
    await send_log(context, f"💳 SS Uploaded: {pid} | user {user.id} | {plan_label} | {price}")


# ===== TEXT HANDLER =====
async def handle_text(update, context):
    user = update.effective_user
    text = update.message.text.strip()
    awaiting = context.user_data.get("awaiting")

    await send_log(context, f"📥 INPUT\n🕒 {now_str()}\n\n{user_info(update)}\n\n💬 <code>{html.escape(text)}</code>")

    # Redeem
    if awaiting == "redeem_code":
        context.user_data.pop("awaiting", None)
        days, err = await db.redeem_coupon(user.id, text)
        if err == "invalid": await update.message.reply_text("❌ Invalid code.", reply_markup=back_kb()); return
        if err == "exhausted": await update.message.reply_text("❌ Code exhausted.", reply_markup=back_kb()); return
        if err == "already": await update.message.reply_text("❌ Already used.", reply_markup=back_kb()); return
        await db.add_premium(user.id, days, "redeem")
        until = await db.premium_until(user.id)
        dt = "Lifetime" if until == -1 else datetime.utcfromtimestamp(until).strftime("%Y-%m-%d")
        await update.message.reply_text(
            f"✅ <b>Code Redeemed!</b>\n\n<blockquote>💎 Premium Active\n📅 Valid: <code>{dt}</code>\n🎉 +{days} days</blockquote>"
            + bot_signature(), parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(user.id))
        return

    # Owner: set price
    if awaiting and awaiting.startswith("setprice_") and OWNER_ID and user.id == OWNER_ID:
        plan_key = awaiting[len("setprice_"):]
        context.user_data.pop("awaiting", None)
        await db.set_setting(f"price_{plan_key}", text)
        label = db.DEFAULT_PLANS.get(plan_key, {}).get("label", plan_key)
        await update.message.reply_text(
            f"✅ <b>Price set for {label}:</b> <code>{html.escape(text)}</code>",
            parse_mode=ParseMode.HTML, reply_markup=await owner_prices_kb())
        return

    # Owner: gift premium
    if awaiting == "owner_gift" and OWNER_ID and user.id == OWNER_ID:
        context.user_data.pop("awaiting", None)
        parts = text.split()
        if len(parts) != 2 or not parts[0].isdigit() or parts[1] not in db.PLAN_DAYS:
            await update.message.reply_text("❌ Format: <code>user_id plan_key</code>",
                                            parse_mode=ParseMode.HTML, reply_markup=await owner_panel_kb()); return
        target, plan_key = int(parts[0]), parts[1]
        days = db.PLAN_DAYS[plan_key]
        await db.add_premium(target, days, plan_key)
        until = await db.premium_until(target)
        dt = "Lifetime" if until == -1 else datetime.utcfromtimestamp(until).strftime("%Y-%m-%d")
        await update.message.reply_text(
            f"✅ Gifted <b>{db.DEFAULT_PLANS[plan_key]['label']}</b> to <code>{target}</code>\nValid: {dt}",
            parse_mode=ParseMode.HTML, reply_markup=await owner_panel_kb())
        try:
            await context.bot.send_message(target,
                f"🎁 <b>Premium Gifted!</b>\n\n<blockquote>Owner ने आपको <b>{db.DEFAULT_PLANS[plan_key]['label']}</b> Premium gift किया!\n📅 {dt}</blockquote>",
                parse_mode=ParseMode.HTML)
        except Exception: pass
        return

    # Owner: create coupon
    if awaiting == "owner_coupon" and OWNER_ID and user.id == OWNER_ID:
        context.user_data.pop("awaiting", None)
        parts = text.split()
        if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
            await update.message.reply_text("❌ Format: <code>CODE days max_uses</code>",
                                            parse_mode=ParseMode.HTML, reply_markup=await owner_panel_kb()); return
        code, days, mx = parts[0].upper(), int(parts[1]), int(parts[2])
        ok = await db.create_coupon(code, days, mx, user.id)
        if ok:
            await update.message.reply_text(
                f"✅ <b>Coupon Created</b>\n\n<blockquote>🎟️ <code>{code}</code>\n📅 {days} days\n🔢 Max: {mx}</blockquote>",
                parse_mode=ParseMode.HTML, reply_markup=await owner_panel_kb())
        else:
            await update.message.reply_text("❌ Code already exists.", reply_markup=await owner_panel_kb())
        return

    if not await require_join(update, context): return

    # Normal search
    is_id = text.isdigit()
    is_username = bool(re.match(r'^@?[A-Za-z][A-Za-z0-9_]{3,31}$', text))
    if not (is_id or is_username):
        await update.message.reply_text(
            "❌ <b>Invalid</b>\n\n<blockquote>ID या @username भेजो।</blockquote>" + bot_signature(),
            parse_mode=ParseMode.HTML, reply_markup=back_kb()); return

    allowed, reason = await can_search(user.id)
    if not allowed:
        gate_text = await show_referral_gate(None, user, is_edit=False)
        await update.message.reply_text(gate_text,
                                        parse_mode=ParseMode.HTML,
                                        reply_markup=referral_gate_kb())
        return

    remaining = await get_remaining(user.id)
    if remaining == 0:
        await update.message.reply_text(
            f"⏰ <b>Daily Limit Reached</b>\n\n<blockquote>{FREE_SEARCHES_PER_DAY} searches पूरे।\nPremium लेकर unlimited पाओ।</blockquote>"
            + bot_signature(), parse_mode=ParseMode.HTML); return

    msg = await update.message.reply_text("⏳ <b>Searching...</b>\n\n<blockquote>Data fetch हो रहा है...</blockquote>",
                                          parse_mode=ParseMode.HTML)
    result = await lookup_tg_id(text)
    if not result.get("ok"):
        err = result.get("error", "No data found")
        await msg.edit_text(
            f"❌ <b>No Data Found</b>\n\n<blockquote>🔎 <code>{html.escape(text)}</code>\n"
            f"⚠️ <i>{html.escape(str(err))}</i>\n\n💡 5-10 मिनट बाद Retry करो।</blockquote>" + bot_signature(),
            parse_mode=ParseMode.HTML, reply_markup=no_data_kb()); return

    data = result["data"]
    await record_search(user.id)
    new_rem = await get_remaining(user.id)
    rem_line = ("👑 <b>Unlimited</b>" if (OWNER_ID and user.id == OWNER_ID)
                else ("💎 <b>Unlimited</b>" if await db.is_premium(user.id)
                      else f"📊 <b>Remaining:</b> <code>{new_rem}/{FREE_SEARCHES_PER_DAY}</code>"))
    copy_lines = [f"🔎 Telegram ID: {data.get('tg_id')}", f"📱 Mobile: {data.get('mobile')}",
                  f"🌍 Country Code: {data.get('country_code')}", f"🏴 Country: {data.get('country')}", ""]
    if SUPPORT_DISPLAY and SUPPORT_DISPLAY != "—": copy_lines.append(f"📢 Channel: {SUPPORT_DISPLAY}")
    if BOT_USERNAME: copy_lines.append(f"🤖 Bot: {BOT_USERNAME}")
    copy_text = "\n".join(copy_lines)
    result_text = ("✅ <b>Result Found</b>\n\n<blockquote>"
        f"🆔 <b>ID:</b> <code>{html.escape(str(data.get('tg_id')))}</code>\n"
        f"📱 <b>Mobile:</b> <code>{html.escape(str(data.get('mobile')))}</code>\n"
        f"🌍 <b>Country Code:</b> <code>{html.escape(str(data.get('country_code')))}</code>\n"
        f"🏴 <b>Country:</b> <code>{html.escape(str(data.get('country')))}</code>"
        f"</blockquote>\n\n{rem_line}\n🔒 <i>Secure</i>" + bot_signature())
    await msg.edit_text(result_text, parse_mode=ParseMode.HTML, reply_markup=result_kb(copy_text))


async def error_handler(update, context):
    tb = "".join(traceback.format_exception(None, context.error, context.error.__traceback__))
    logger.error(f"Exception:\n{tb}")
    err = str(context.error)
    if "Query is too old" in err or "query ID is invalid" in err: return
    if "Message to edit not found" in err or "message is not modified" in err: return
    if "Message can't be edited" in err: return
    # Log channel
    try:
        await send_log(context,
            f"🔴 <b>ERROR</b>\n🕒 {now_str()}\n\n<code>{html.escape(err[:500])}</code>")
    except Exception: pass
    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(update.effective_chat.id,
                "⚠️ <b>Error</b>\n\n<blockquote>कुछ गड़बड़ हो गई।</blockquote>",
                parse_mode=ParseMode.HTML)
        except Exception: pass


def main():
    if not BOT_TOKEN: logger.error("BOT_TOKEN missing!"); return
    app = (Application.builder()
           .token(BOT_TOKEN)
           .post_init(post_init)
           .post_shutdown(post_shutdown)
           .build())
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CallbackQueryHandler(button_handler,
        pattern="^(search|retry|help|stats|owner|support|source|profile|menu|close|noop|verify|"
                "referral|copy_ref|check_ref|premium|redeem|owner_panel|op_stats|op_prices|op_qr|"
                "op_gift|op_coupon|plan_.*|op_setprice_.*|approve_.*|decline_.*)$"))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)
    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

# ===== PHOTO HANDLER (SS Upload) =====
async def handle_photo(update, context):
    user = update.effective_user
    if not user:
        return
    text = update.message.caption or ""
    awaiting = context.user_data.get("awaiting")

    # Owner QR upload
    if awaiting == "owner_set_qr" and OWNER_ID and user.id == OWNER_ID:
        context.user_data.pop("awaiting", None)
        photo = update.message.photo[-1]
        await db.set_setting("qr_file_id", photo.file_id)
        await update.message.reply_text(
            "✅ <b>QR saved!</b> Users को payment के time दिखेगा।",
            parse_mode=ParseMode.HTML, reply_markup=await owner_panel_kb())
        return

    # Force join check
    if not await require_join(update, context):
        return

    # User SS upload — DB से pending plan लो
    plan_key = await db.get_pending_plan(user.id)
    if not plan_key:
        await update.message.reply_text(
            "⚠️ पहले <b>Premium</b> → plan select करो।",
            parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(user.id))
        return

    photo = update.message.photo[-1]
    price = await db.get_plan_price(plan_key)
    plan_days = db.PLAN_DAYS.get(plan_key, 0)
    plan_label = db.DEFAULT_PLANS.get(plan_key, {}).get("label", plan_key)

    pid = await db.create_payment(
        user.id, user.username, plan_key, plan_days, price,
        photo.file_id, update.message.chat_id, update.message.message_id)

    owner_text = (
        f"🔔 <b>New Payment Request</b>\n\n<blockquote>"
        f"🆔 <b>Payment ID:</b> <code>{pid}</code>\n"
        f"👤 <b>User:</b> <code>{user.id}</code>\n"
        f"🔗 <b>Username:</b> @{html.escape(user.username or '—')}\n"
        f"👤 <b>Name:</b> {html.escape(user.full_name)}\n\n"
        f"💎 <b>Plan:</b> {plan_label}\n"
        f"📅 <b>Days:</b> <code>{plan_days}</code>\n"
        f"💰 <b>Amount:</b> <code>{price}</code></blockquote>")

    if OWNER_ID:
        try:
            await context.bot.send_photo(OWNER_ID, photo=photo.file_id,
                caption=owner_text, parse_mode=ParseMode.HTML,
                reply_markup=approval_kb(pid))
        except Exception as e:
            logger.error(f"owner DM: {e}")

    if LOG_CHANNEL_ID:
        try:
            await context.bot.send_photo(LOG_CHANNEL_ID, photo=photo.file_id,
                caption=owner_text, parse_mode=ParseMode.HTML,
                reply_markup=approval_kb(pid))
        except Exception as e:
            logger.error(f"log channel: {e}")

    await update.message.reply_text(
        "✅ <b>Payment Proof Received!</b>\n\n<blockquote>"
        "आपका screenshot owner को भेज दिया गया है।\n"
        "Verification के बाद Premium activate हो जाएगा।\n\n"
        "⏰ Expected time: 5-30 minutes</blockquote>" + bot_signature(),
        parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(user.id))
    await db.clear_pending_plan(user.id)
    await send_log(context, f"💳 SS Uploaded: {pid} | user {user.id} | {plan_label} | {price}")


# ===== TEXT HANDLER =====
async def handle_text(update, context):
    user = update.effective_user
    if not user:
        return
    text = update.message.text.strip()
    awaiting = context.user_data.get("awaiting")

    await send_log(context,
                   f"📥 INPUT\n🕒 {now_str()}\n\n{user_info(update)}\n\n"
                   f"💬 <code>{html.escape(text)}</code>")

    # Redeem
    if awaiting == "redeem_code":
        context.user_data.pop("awaiting", None)
        days, err = await db.redeem_coupon(user.id, text)
        if err == "invalid":
            await update.message.reply_text("❌ Invalid code.", reply_markup=back_kb()); return
        if err == "exhausted":
            await update.message.reply_text("❌ Code exhausted.", reply_markup=back_kb()); return
        if err == "already":
            await update.message.reply_text("❌ Already used.", reply_markup=back_kb()); return
        await db.add_premium(user.id, days, "redeem")
        until = await db.premium_until(user.id)
        dt = "Lifetime" if until == -1 else datetime.utcfromtimestamp(until).strftime("%Y-%m-%d")
        await update.message.reply_text(
            f"✅ <b>Code Redeemed!</b>\n\n<blockquote>💎 Premium Active\n"
            f"📅 Valid: <code>{dt}</code>\n🎉 +{days} days</blockquote>" + bot_signature(),
            parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(user.id))
        return

    # Owner: set price
    if awaiting and awaiting.startswith("setprice_") and OWNER_ID and user.id == OWNER_ID:
        plan_key = awaiting[len("setprice_"):]
        context.user_data.pop("awaiting", None)
        await db.set_setting(f"price_{plan_key}", text)
        label = db.DEFAULT_PLANS.get(plan_key, {}).get("label", plan_key)
        await update.message.reply_text(
            f"✅ <b>Price set for {label}:</b> <code>{html.escape(text)}</code>",
            parse_mode=ParseMode.HTML, reply_markup=await owner_prices_kb())
        return

    # Owner: gift premium
    if awaiting == "owner_gift" and OWNER_ID and user.id == OWNER_ID:
        context.user_data.pop("awaiting", None)
        parts = text.split()
        if len(parts) != 2 or not parts[0].isdigit() or parts[1] not in db.PLAN_DAYS:
            await update.message.reply_text(
                "❌ Format: <code>user_id plan_key</code>",
                parse_mode=ParseMode.HTML, reply_markup=await owner_panel_kb()); return
        target, plan_key = int(parts[0]), parts[1]
        days = db.PLAN_DAYS[plan_key]
        await db.add_premium(target, days, plan_key)
        until = await db.premium_until(target)
        dt = "Lifetime" if until == -1 else datetime.utcfromtimestamp(until).strftime("%Y-%m-%d")
        await update.message.reply_text(
            f"✅ Gifted <b>{db.DEFAULT_PLANS[plan_key]['label']}</b> to <code>{target}</code>\nValid: {dt}",
            parse_mode=ParseMode.HTML, reply_markup=await owner_panel_kb())
        try:
            await context.bot.send_message(target,
                f"🎁 <b>Premium Gifted!</b>\n\n<blockquote>Owner ने आपको "
                f"<b>{db.DEFAULT_PLANS[plan_key]['label']}</b> Premium gift किया!\n📅 {dt}</blockquote>",
                parse_mode=ParseMode.HTML)
        except Exception:
            pass
        return

    # Owner: create coupon
    if awaiting == "owner_coupon" and OWNER_ID and user.id == OWNER_ID:
        context.user_data.pop("awaiting", None)
        parts = text.split()
        if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
            await update.message.reply_text(
                "❌ Format: <code>CODE days max_uses</code>",
                parse_mode=ParseMode.HTML, reply_markup=await owner_panel_kb()); return
        code, days, mx = parts[0].upper(), int(parts[1]), int(parts[2])
        ok = await db.create_coupon(code, days, mx, user.id)
        if ok:
            await update.message.reply_text(
                f"✅ <b>Coupon Created</b>\n\n<blockquote>🎟️ <code>{code}</code>\n"
                f"📅 {days} days\n🔢 Max: {mx}</blockquote>",
                parse_mode=ParseMode.HTML, reply_markup=await owner_panel_kb())
        else:
            await update.message.reply_text("❌ Code already exists.", reply_markup=await owner_panel_kb())
        return

    if not await require_join(update, context):
        return

    # Normal search
    is_id = text.isdigit()
    is_username = bool(re.match(r'^@?[A-Za-z][A-Za-z0-9_]{3,31}$', text))
    if not (is_id or is_username):
        await update.message.reply_text(
            "❌ <b>Invalid</b>\n\n<blockquote>ID या @username भेजो।</blockquote>" + bot_signature(),
            parse_mode=ParseMode.HTML, reply_markup=back_kb()); return

    allowed, reason = await can_search(user.id)
    if not allowed:
        gate_text = await show_referral_gate(None, user, is_edit=False)
        await update.message.reply_text(gate_text,
                                        parse_mode=ParseMode.HTML,
                                        reply_markup=referral_gate_kb())
        return

    remaining = await get_remaining(user.id)
    if remaining == 0:
        await update.message.reply_text(
            f"⏰ <b>Daily Limit Reached</b>\n\n<blockquote>{FREE_SEARCHES_PER_DAY} searches पूरे।\n"
            f"Premium लेकर unlimited पाओ।</blockquote>" + bot_signature(),
            parse_mode=ParseMode.HTML); return

    msg = await update.message.reply_text(
        "⏳ <b>Searching...</b>\n\n<blockquote>Data fetch हो रहा है...</blockquote>",
        parse_mode=ParseMode.HTML)
    result = await lookup_tg_id(text)
    if not result.get("ok"):
        err = result.get("error", "No data found")
        await msg.edit_text(
            f"❌ <b>No Data Found</b>\n\n<blockquote>🔎 <code>{html.escape(text)}</code>\n"
            f"⚠️ <i>{html.escape(str(err))}</i>\n\n💡 5-10 मिनट बाद Retry करो।</blockquote>"
            + bot_signature(), parse_mode=ParseMode.HTML, reply_markup=no_data_kb()); return

    data = result["data"]

    # अगर username है तो profile scrape भी करो
    profile = None
    if not text.isdigit():
        profile = await scrape_username(text)

    await record_search(user.id)
    new_rem = await get_remaining(user.id)
    rem_line = ("👑 <b>Unlimited</b>" if (OWNER_ID and user.id == OWNER_ID)
                else ("💎 <b>Unlimited</b>" if await db.is_premium(user.id)
                      else f"📊 <b>Remaining:</b> <code>{new_rem}/{FREE_SEARCHES_PER_DAY}</code>"))

    # Copy text बनाओ
    copy_lines = []
    if profile:
        if profile.get("display"):
            copy_lines.append(f"👤 Display Name: {profile['display']}")
        if profile.get("username"):
            copy_lines.append(f"🔗 Username: @{profile['username']}")
        if profile.get("bio"):
            copy_lines.append(f"📝 Bio: {profile['bio']}")
        if profile.get("profile_url"):
            copy_lines.append(f"🌐 Profile: {profile['profile_url']}")
        copy_lines.append("")

    if data.get("mobile") and data.get("mobile") != "N/A":
        copy_lines.append(f"📱 Mobile: {data.get('mobile')}")
    if data.get("country_code") and data.get("country_code") != "N/A":
        copy_lines.append(f"🌍 Country Code: {data.get('country_code')}")
    if data.get("country") and data.get("country") != "N/A":
        copy_lines.append(f"🏴 Country: {data.get('country')}")

    if SUPPORT_DISPLAY and SUPPORT_DISPLAY != "—":
        copy_lines.append("")
        copy_lines.append(f"📢 Channel: {SUPPORT_DISPLAY}")
    if BOT_USERNAME:
        copy_lines.append(f"🤖 Bot: {BOT_USERNAME}")
    copy_text = "\n".join(copy_lines)

    # Result display
    result_lines = []
    if profile:
        result_lines.append("👤 <b>Telegram Profile</b>")
        if profile.get("display"):
            result_lines.append(f"👤 <b>Name:</b> {html.escape(profile['display'])}")
        if profile.get("username"):
            result_lines.append(f"🔗 <b>Username:</b> @{html.escape(profile['username'])}")
        if profile.get("bio"):
            bio_short = profile["bio"][:200] + ("..." if len(profile["bio"]) > 200 else "")
            result_lines.append(f"📝 <b>Bio:</b> <i>{html.escape(bio_short)}</i>")
        if profile.get("avatar_url"):
            result_lines.append(f"🖼️ <a href=\"{html.escape(profile['avatar_url'])}\">Profile Picture</a>")
        if profile.get("profile_url"):
            result_lines.append(f"🌐 <a href=\"{html.escape(profile['profile_url'])}\">Open Profile</a>")
        result_lines.append("")

    result_lines.append("📱 <b>Phone Info</b>")
    if data.get("mobile") and data.get("mobile") != "N/A":
        result_lines.append(f"📱 <b>Mobile:</b> <code>{html.escape(str(data.get('mobile')))}</code>")
    if data.get("country_code") and data.get("country_code") != "N/A":
        result_lines.append(f"🌍 <b>Country Code:</b> <code>{html.escape(str(data.get('country_code')))}</code>")
    if data.get("country") and data.get("country") != "N/A":
        result_lines.append(f"🏴 <b>Country:</b> <code>{html.escape(str(data.get('country')))}</code>")

    result_text = ("✅ <b>Result Found</b>\n\n<blockquote>"
                   + "\n".join(result_lines)
                   + f"</blockquote>\n\n{rem_line}\n🔒 <i>Secure</i>" + bot_signature())

    # अगर profile pic है तो photo के साथ भेजो
    if profile and profile.get("avatar_url"):
        try:
            await msg.delete()
            await update.message.reply_photo(
                photo=profile["avatar_url"],
                caption=result_text,
                parse_mode=ParseMode.HTML,
                reply_markup=result_kb(copy_text))
            return
        except Exception as e:
            logger.warning(f"avatar send failed: {e}")

    await msg.edit_text(result_text, parse_mode=ParseMode.HTML,
                        reply_markup=result_kb(copy_text))


# ===== ERROR HANDLER =====
async def error_handler(update, context):
    tb = "".join(traceback.format_exception(None, context.error, context.error.__traceback__))
    logger.error(f"Exception:\n{tb}")
    err = str(context.error)
    if "Query is too old" in err or "query ID is invalid" in err:
        return
    if "Message to edit not found" in err or "message is not modified" in err:
        return
    if "Message can't be edited" in err:
        return
    try:
        await send_log(context,
            f"🔴 <b>ERROR</b>\n🕒 {now_str()}\n\n<code>{html.escape(err[:500])}</code>")
    except Exception:
        pass
    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(update.effective_chat.id,
                "⚠️ <b>Error</b>\n\n<blockquote>कुछ गड़बड़ हो गई।</blockquote>",
                parse_mode=ParseMode.HTML)
        except Exception:
            pass


# ===== MAIN =====
def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN missing!")
        return
    app = (Application.builder()
           .token(BOT_TOKEN)
           .post_init(post_init)
           .post_shutdown(post_shutdown)
           .build())
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CallbackQueryHandler(button_handler,
        pattern="^(search|retry|help|stats|owner|support|source|profile|menu|close|noop|verify|"
                "referral|copy_ref|check_ref|premium|redeem|owner_panel|op_stats|op_prices|op_qr|"
                "op_gift|op_coupon|plan_.*|op_setprice_.*|approve_.*|decline_.*)$"))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)
    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

# ===== PHOTO HANDLER (SS Upload) =====
async def handle_photo(update, context):
    user = update.effective_user
    if not user:
        return
    text = update.message.caption or ""
    awaiting = context.user_data.get("awaiting")

    # Owner QR upload
    if awaiting == "owner_set_qr" and OWNER_ID and user.id == OWNER_ID:
        context.user_data.pop("awaiting", None)
        photo = update.message.photo[-1]
        await db.set_setting("qr_file_id", photo.file_id)
        await update.message.reply_text(
            "✅ <b>QR saved!</b> Users को payment के time दिखेगा।",
            parse_mode=ParseMode.HTML, reply_markup=await owner_panel_kb())
        return

    # Force join check
    if not await require_join(update, context):
        return

    # User SS upload — DB से pending plan लो
    plan_key = await db.get_pending_plan(user.id)
    if not plan_key:
        await update.message.reply_text(
            "⚠️ पहले <b>Premium</b> → plan select करो।",
            parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(user.id))
        return

    photo = update.message.photo[-1]
    price = await db.get_plan_price(plan_key)
    plan_days = db.PLAN_DAYS.get(plan_key, 0)
    plan_label = db.DEFAULT_PLANS.get(plan_key, {}).get("label", plan_key)

    pid = await db.create_payment(
        user.id, user.username, plan_key, plan_days, price,
        photo.file_id, update.message.chat_id, update.message.message_id)

    owner_text = (
        f"🔔 <b>New Payment Request</b>\n\n<blockquote>"
        f"🆔 <b>Payment ID:</b> <code>{pid}</code>\n"
        f"👤 <b>User:</b> <code>{user.id}</code>\n"
        f"🔗 <b>Username:</b> @{html.escape(user.username or '—')}\n"
        f"👤 <b>Name:</b> {html.escape(user.full_name)}\n\n"
        f"💎 <b>Plan:</b> {plan_label}\n"
        f"📅 <b>Days:</b> <code>{plan_days}</code>\n"
        f"💰 <b>Amount:</b> <code>{price}</code></blockquote>")

    if OWNER_ID:
        try:
            await context.bot.send_photo(OWNER_ID, photo=photo.file_id,
                caption=owner_text, parse_mode=ParseMode.HTML,
                reply_markup=approval_kb(pid))
        except Exception as e:
            logger.error(f"owner DM: {e}")

    if LOG_CHANNEL_ID:
        try:
            await context.bot.send_photo(LOG_CHANNEL_ID, photo=photo.file_id,
                caption=owner_text, parse_mode=ParseMode.HTML,
                reply_markup=approval_kb(pid))
        except Exception as e:
            logger.error(f"log channel: {e}")

    await update.message.reply_text(
        "✅ <b>Payment Proof Received!</b>\n\n<blockquote>"
        "आपका screenshot owner को भेज दिया गया है।\n"
        "Verification के बाद Premium activate हो जाएगा।\n\n"
        "⏰ Expected time: 5-30 minutes</blockquote>" + bot_signature(),
        parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(user.id))
    await db.clear_pending_plan(user.id)
    await send_log(context, f"💳 SS Uploaded: {pid} | user {user.id} | {plan_label} | {price}")


# ===== TEXT HANDLER =====
async def handle_text(update, context):
    user = update.effective_user
    if not user:
        return
    text = update.message.text.strip()
    awaiting = context.user_data.get("awaiting")

    await send_log(context,
                   f"📥 INPUT\n🕒 {now_str()}\n\n{user_info(update)}\n\n"
                   f"💬 <code>{html.escape(text)}</code>")

    # Redeem
    if awaiting == "redeem_code":
        context.user_data.pop("awaiting", None)
        days, err = await db.redeem_coupon(user.id, text)
        if err == "invalid":
            await update.message.reply_text("❌ Invalid code.", reply_markup=back_kb()); return
        if err == "exhausted":
            await update.message.reply_text("❌ Code exhausted.", reply_markup=back_kb()); return
        if err == "already":
            await update.message.reply_text("❌ Already used.", reply_markup=back_kb()); return
        await db.add_premium(user.id, days, "redeem")
        until = await db.premium_until(user.id)
        dt = "Lifetime" if until == -1 else datetime.utcfromtimestamp(until).strftime("%Y-%m-%d")
        await update.message.reply_text(
            f"✅ <b>Code Redeemed!</b>\n\n<blockquote>💎 Premium Active\n"
            f"📅 Valid: <code>{dt}</code>\n🎉 +{days} days</blockquote>" + bot_signature(),
            parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(user.id))
        return

    # Owner: set price
    if awaiting and awaiting.startswith("setprice_") and OWNER_ID and user.id == OWNER_ID:
        plan_key = awaiting[len("setprice_"):]
        context.user_data.pop("awaiting", None)
        await db.set_setting(f"price_{plan_key}", text)
        label = db.DEFAULT_PLANS.get(plan_key, {}).get("label", plan_key)
        await update.message.reply_text(
            f"✅ <b>Price set for {label}:</b> <code>{html.escape(text)}</code>",
            parse_mode=ParseMode.HTML, reply_markup=await owner_prices_kb())
        return

    # Owner: gift premium
    if awaiting == "owner_gift" and OWNER_ID and user.id == OWNER_ID:
        context.user_data.pop("awaiting", None)
        parts = text.split()
        if len(parts) != 2 or not parts[0].isdigit() or parts[1] not in db.PLAN_DAYS:
            await update.message.reply_text(
                "❌ Format: <code>user_id plan_key</code>",
                parse_mode=ParseMode.HTML, reply_markup=await owner_panel_kb()); return
        target, plan_key = int(parts[0]), parts[1]
        days = db.PLAN_DAYS[plan_key]
        await db.add_premium(target, days, plan_key)
        until = await db.premium_until(target)
        dt = "Lifetime" if until == -1 else datetime.utcfromtimestamp(until).strftime("%Y-%m-%d")
        await update.message.reply_text(
            f"✅ Gifted <b>{db.DEFAULT_PLANS[plan_key]['label']}</b> to <code>{target}</code>\nValid: {dt}",
            parse_mode=ParseMode.HTML, reply_markup=await owner_panel_kb())
        try:
            await context.bot.send_message(target,
                f"🎁 <b>Premium Gifted!</b>\n\n<blockquote>Owner ने आपको "
                f"<b>{db.DEFAULT_PLANS[plan_key]['label']}</b> Premium gift किया!\n📅 {dt}</blockquote>",
                parse_mode=ParseMode.HTML)
        except Exception:
            pass
        return

    # Owner: create coupon
    if awaiting == "owner_coupon" and OWNER_ID and user.id == OWNER_ID:
        context.user_data.pop("awaiting", None)
        parts = text.split()
        if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
            await update.message.reply_text(
                "❌ Format: <code>CODE days max_uses</code>",
                parse_mode=ParseMode.HTML, reply_markup=await owner_panel_kb()); return
        code, days, mx = parts[0].upper(), int(parts[1]), int(parts[2])
        ok = await db.create_coupon(code, days, mx, user.id)
        if ok:
            await update.message.reply_text(
                f"✅ <b>Coupon Created</b>\n\n<blockquote>🎟️ <code>{code}</code>\n"
                f"📅 {days} days\n🔢 Max: {mx}</blockquote>",
                parse_mode=ParseMode.HTML, reply_markup=await owner_panel_kb())
        else:
            await update.message.reply_text("❌ Code already exists.", reply_markup=await owner_panel_kb())
        return

    if not await require_join(update, context):
        return

    # Normal search
    is_id = text.isdigit()
    is_username = bool(re.match(r'^@?[A-Za-z][A-Za-z0-9_]{3,31}$', text))
    if not (is_id or is_username):
        await update.message.reply_text(
            "❌ <b>Invalid</b>\n\n<blockquote>ID या @username भेजो।</blockquote>" + bot_signature(),
            parse_mode=ParseMode.HTML, reply_markup=back_kb()); return

    allowed, reason = await can_search(user.id)
    if not allowed:
        gate_text = await show_referral_gate(None, user, is_edit=False)
        await update.message.reply_text(gate_text,
                                        parse_mode=ParseMode.HTML,
                                        reply_markup=referral_gate_kb())
        return

    remaining = await get_remaining(user.id)
    if remaining == 0:
        await update.message.reply_text(
            f"⏰ <b>Daily Limit Reached</b>\n\n<blockquote>{FREE_SEARCHES_PER_DAY} searches पूरे।\n"
            f"Premium लेकर unlimited पाओ।</blockquote>" + bot_signature(),
            parse_mode=ParseMode.HTML); return

    msg = await update.message.reply_text(
        "⏳ <b>Searching...</b>\n\n<blockquote>Data fetch हो रहा है...</blockquote>",
        parse_mode=ParseMode.HTML)
    result = await lookup_tg_id(text)
    if not result.get("ok"):
        err = result.get("error", "No data found")
        await msg.edit_text(
            f"❌ <b>No Data Found</b>\n\n<blockquote>🔎 <code>{html.escape(text)}</code>\n"
            f"⚠️ <i>{html.escape(str(err))}</i>\n\n💡 5-10 मिनट बाद Retry करो।</blockquote>"
            + bot_signature(), parse_mode=ParseMode.HTML, reply_markup=no_data_kb()); return

    data = result["data"]

    # अगर username है तो profile scrape भी करो
    profile = None
    if not text.isdigit():
        profile = await scrape_username(text)

    await record_search(user.id)
    new_rem = await get_remaining(user.id)
    rem_line = ("👑 <b>Unlimited</b>" if (OWNER_ID and user.id == OWNER_ID)
                else ("💎 <b>Unlimited</b>" if await db.is_premium(user.id)
                      else f"📊 <b>Remaining:</b> <code>{new_rem}/{FREE_SEARCHES_PER_DAY}</code>"))

    # Copy text बनाओ
    copy_lines = []
    if profile:
        if profile.get("display"):
            copy_lines.append(f"👤 Display Name: {profile['display']}")
        if profile.get("username"):
            copy_lines.append(f"🔗 Username: @{profile['username']}")
        if profile.get("bio"):
            copy_lines.append(f"📝 Bio: {profile['bio']}")
        if profile.get("profile_url"):
            copy_lines.append(f"🌐 Profile: {profile['profile_url']}")
        copy_lines.append("")

    if data.get("mobile") and data.get("mobile") != "N/A":
        copy_lines.append(f"📱 Mobile: {data.get('mobile')}")
    if data.get("country_code") and data.get("country_code") != "N/A":
        copy_lines.append(f"🌍 Country Code: {data.get('country_code')}")
    if data.get("country") and data.get("country") != "N/A":
        copy_lines.append(f"🏴 Country: {data.get('country')}")

    if SUPPORT_DISPLAY and SUPPORT_DISPLAY != "—":
        copy_lines.append("")
        copy_lines.append(f"📢 Channel: {SUPPORT_DISPLAY}")
    if BOT_USERNAME:
        copy_lines.append(f"🤖 Bot: {BOT_USERNAME}")
    copy_text = "\n".join(copy_lines)

    # Result display
    result_lines = []
    if profile:
        result_lines.append("👤 <b>Telegram Profile</b>")
        if profile.get("display"):
            result_lines.append(f"👤 <b>Name:</b> {html.escape(profile['display'])}")
        if profile.get("username"):
            result_lines.append(f"🔗 <b>Username:</b> @{html.escape(profile['username'])}")
        if profile.get("bio"):
            bio_short = profile["bio"][:200] + ("..." if len(profile["bio"]) > 200 else "")
            result_lines.append(f"📝 <b>Bio:</b> <i>{html.escape(bio_short)}</i>")
        if profile.get("avatar_url"):
            result_lines.append(f"🖼️ <a href=\"{html.escape(profile['avatar_url'])}\">Profile Picture</a>")
        if profile.get("profile_url"):
            result_lines.append(f"🌐 <a href=\"{html.escape(profile['profile_url'])}\">Open Profile</a>")
        result_lines.append("")

    result_lines.append("📱 <b>Phone Info</b>")
    if data.get("mobile") and data.get("mobile") != "N/A":
        result_lines.append(f"📱 <b>Mobile:</b> <code>{html.escape(str(data.get('mobile')))}</code>")
    if data.get("country_code") and data.get("country_code") != "N/A":
        result_lines.append(f"🌍 <b>Country Code:</b> <code>{html.escape(str(data.get('country_code')))}</code>")
    if data.get("country") and data.get("country") != "N/A":
        result_lines.append(f"🏴 <b>Country:</b> <code>{html.escape(str(data.get('country')))}</code>")

    result_text = ("✅ <b>Result Found</b>\n\n<blockquote>"
                   + "\n".join(result_lines)
                   + f"</blockquote>\n\n{rem_line}\n🔒 <i>Secure</i>" + bot_signature())

    # अगर profile pic है तो photo के साथ भेजो
    if profile and profile.get("avatar_url"):
        try:
            await msg.delete()
            await update.message.reply_photo(
                photo=profile["avatar_url"],
                caption=result_text,
                parse_mode=ParseMode.HTML,
                reply_markup=result_kb(copy_text))
            return
        except Exception as e:
            logger.warning(f"avatar send failed: {e}")

    await msg.edit_text(result_text, parse_mode=ParseMode.HTML,
                        reply_markup=result_kb(copy_text))


# ===== ERROR HANDLER =====
async def error_handler(update, context):
    tb = "".join(traceback.format_exception(None, context.error, context.error.__traceback__))
    logger.error(f"Exception:\n{tb}")
    err = str(context.error)
    if "Query is too old" in err or "query ID is invalid" in err:
        return
    if "Message to edit not found" in err or "message is not modified" in err:
        return
    if "Message can't be edited" in err:
        return
    try:
        await send_log(context,
            f"🔴 <b>ERROR</b>\n🕒 {now_str()}\n\n<code>{html.escape(err[:500])}</code>")
    except Exception:
        pass
    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(update.effective_chat.id,
                "⚠️ <b>Error</b>\n\n<blockquote>कुछ गड़बड़ हो गई।</blockquote>",
                parse_mode=ParseMode.HTML)
        except Exception:
            pass


# ===== MAIN =====
def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN missing!")
        return
    app = (Application.builder()
           .token(BOT_TOKEN)
           .post_init(post_init)
           .post_shutdown(post_shutdown)
           .build())
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CallbackQueryHandler(button_handler,
        pattern="^(search|retry|help|stats|owner|support|source|profile|menu|close|noop|verify|"
                "referral|copy_ref|check_ref|premium|redeem|owner_panel|op_stats|op_prices|op_qr|"
                "op_gift|op_coupon|plan_.*|op_setprice_.*|approve_.*|decline_.*)$"))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)
    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()


# ==================================================
#        PARALLEL LOOKUP ENGINE (Multi-source)
# ==================================================
async def _source_aerosend(query):
    """Source 1: aerosend.bond API"""
    q = query.lstrip("@")
    try:
        r = requests.get(
            API_URL,
            params={"key": API_KEY, "num": q},
            timeout=REQUEST_TIMEOUT,
        ).json()
        if r.get("status") == "success":
            return {"source": "aerosend", "ok": True, "data": {
                "tg_id": r.get("tg_id", q),
                "mobile": r.get("mobile", "N/A"),
                "country_code": r.get("country_code", "N/A"),
                "country": r.get("country", "N/A"),
            }}
    except Exception as e:
        logger.warning(f"[aerosend] {e}")
    return {"source": "aerosend", "ok": False}


async def _source_tgme(query):
    """Source 2: t.me/username HTML scraper"""
    u = query.lstrip("@")
    if not u or u.isdigit():
        return {"source": "tgme", "ok": False}
    try:
        url = f"https://t.me/{u}"
        r = requests.get(url, timeout=REQUEST_TIMEOUT, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0 Safari/537.36"
        })
        r.raise_for_status()
        html_text = r.text

        def og(prop):
            m = re.search(
                rf'<meta[^>]+property=["\']og:{prop}["\'][^>]+content=["\']([^"\']*)["\']',
                html_text, re.IGNORECASE)
            return m.group(1).strip() if m else None

        def tw(prop):
            m = re.search(
                rf'<meta[^>]+name=["\']twitter:{prop}["\'][^>]+content=["\']([^"\']*)["\']',
                html_text, re.IGNORECASE)
            return m.group(1).strip() if m else None

        display = og("title") or tw("title")
        bio = og("description") or tw("description")
        avatar = og("image") or tw("image")

        if display or bio:
            return {"source": "tgme", "ok": True, "data": {
                "username": u,
                "display": display,
                "bio": bio,
                "avatar_url": avatar,
                "profile_url": url,
            }}
    except Exception as e:
        logger.warning(f"[tgme] {e}")
    return {"source": "tgme", "ok": False}


async def _source_channel_viewer(query):
    """Source 3: telegram-channel-viewer lib (no API key)"""
    u = query.lstrip("@")
    if not u:
        return {"source": "viewer", "ok": False}
    try:
        from telegram_channel_viewer import TelegramChannelViewer
        viewer = TelegramChannelViewer()
        info = viewer.get_channel_info(u) if not u.isdigit() else viewer.get_user_info(u)
        if info:
            return {"source": "viewer", "ok": True, "data": info}
    except Exception as e:
        logger.warning(f"[viewer] {e}")
    return {"source": "viewer", "ok": False}


async def parallel_lookup(query):
    """सारे sources parallel चलाओ, results merge करो"""
    tasks = []
    if PARALLEL_SOURCES.get("aerosend"):
        tasks.append(_source_aerosend(query))
    if PARALLEL_SOURCES.get("tgme_scraper"):
        tasks.append(_source_tgme(query))
    if PARALLEL_SOURCES.get("channel_viewer"):
        tasks.append(_source_channel_viewer(query))

    if not tasks:
        tasks.append(_source_aerosend(query))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    merged = {"ok": False, "sources": {}, "data": {}}
    for r in results:
        if isinstance(r, Exception):
            logger.warning(f"parallel source exception: {r}")
            continue
        merged["sources"][r["source"]] = r.get("ok", False)
        if r.get("ok") and r.get("data"):
            merged["ok"] = True
            merged["data"].update(r["data"])

    logger.info(f"[parallel] sources={merged['sources']} ok={merged['ok']}")
    return merged
