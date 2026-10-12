import time, logging
from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGODB_URI, MONGODB_DB

logger = logging.getLogger("DB")
_client = None
_db = None


def _get_db():
    global _client, _db
    if _db is None:
        _client = AsyncIOMotorClient(MONGODB_URI)
        _db = _client[MONGODB_DB]
    return _db


async def init_db():
    db = _get_db()
    await db.users.create_index("user_id", unique=True)
    await db.coupons.create_index("code", unique=True)
    await db.payments.create_index("payment_id", unique=True)
    await db.settings.create_index("key", unique=True)
    await db.redemptions.create_index([("user_id", 1), ("code", 1)], unique=True)
    logger.info("MongoDB initialized")


# ---------- USERS ----------
async def create_user_if_new(user_id, username, first_name):
    db = _get_db()
    existing = await db.users.find_one({"user_id": user_id})
    if existing:
        await db.users.update_one({"user_id": user_id},
            {"$set": {"username": username, "first_name": first_name}})
        return False
    await db.users.insert_one({
        "user_id": user_id, "username": username, "first_name": first_name,
        "joined_at": int(time.time()), "referred_by": None,
        "referral_count": 0, "is_premium": False, "premium_until": 0,
        "premium_plan": None, "daily_used": 0, "last_reset": int(time.time()),
    })
    return True


async def set_referrer(user_id, referrer_id):
    if user_id == referrer_id:
        return False
    db = _get_db()
    u = await db.users.find_one({"user_id": user_id})
    if not u or u.get("referred_by"):
        return False
    ref = await db.users.find_one({"user_id": referrer_id})
    if not ref:
        return False
    await db.users.update_one({"user_id": user_id}, {"$set": {"referred_by": referrer_id}})
    await db.users.update_one({"user_id": referrer_id}, {"$inc": {"referral_count": 1}})
    return True


async def get_referral_count(user_id):
    db = _get_db()
    u = await db.users.find_one({"user_id": user_id})
    return (u.get("referral_count", 0) if u else 0)


async def is_premium(user_id):
    db = _get_db()
    u = await db.users.find_one({"user_id": user_id})
    if not u or not u.get("is_premium"):
        return False
    if u.get("premium_until", 0) == -1:  # lifetime
        return True
    return u.get("premium_until", 0) > int(time.time())


async def premium_until(user_id):
    db = _get_db()
    u = await db.users.find_one({"user_id": user_id})
    return (u.get("premium_until", 0) if u else 0)


async def add_premium(user_id, days, plan_name=None):
    """days = -1 means lifetime"""
    db = _get_db()
    now = int(time.time())
    u = await db.users.find_one({"user_id": user_id})
    if not u:
        await db.users.insert_one({
            "user_id": user_id, "username": None, "first_name": None,
            "joined_at": now, "referred_by": None, "referral_count": 0,
            "is_premium": True, "premium_until": (-1 if days == -1 else now + days*86400),
            "premium_plan": plan_name, "daily_used": 0, "last_reset": now,
        })
        return
    if days == -1:
        new_until = -1
    else:
        base = u.get("premium_until", 0)
        if base == -1:
            new_until = -1
        else:
            new_until = max(base, now) + days * 86400
    await db.users.update_one({"user_id": user_id},
        {"$set": {"is_premium": True, "premium_until": new_until,
                  "premium_plan": plan_name or u.get("premium_plan")}})


async def get_daily_used(user_id):
    db = _get_db()
    u = await db.users.find_one({"user_id": user_id})
    if not u:
        return 0
    if int(time.time()) - (u.get("last_reset", 0)) > 86400:
        await db.users.update_one({"user_id": user_id},
            {"$set": {"daily_used": 0, "last_reset": int(time.time())}})
        return 0
    return u.get("daily_used", 0)


async def inc_daily_used(user_id):
    db = _get_db()
    await db.users.update_one({"user_id": user_id}, {"$inc": {"daily_used": 1}})


# ---------- COUPONS ----------
async def create_coupon(code, days, max_uses, created_by):
    db = _get_db()
    try:
        await db.coupons.insert_one({
            "code": code.upper().strip(), "days": days, "max_uses": max_uses,
            "used": 0, "created_by": created_by, "created_at": int(time.time()),
        })
        return True
    except Exception:
        return False


async def redeem_coupon(user_id, code):
    db = _get_db()
    code = code.upper().strip()
    c = await db.coupons.find_one({"code": code})
    if not c:
        return None, "invalid"
    if c["used"] >= c["max_uses"]:
        return None, "exhausted"
    dup = await db.redemptions.find_one({"user_id": user_id, "code": code})
    if dup:
        return None, "already"
    await db.coupons.update_one({"code": code}, {"$inc": {"used": 1}})
    await db.redemptions.insert_one({
        "user_id": user_id, "code": code, "redeemed_at": int(time.time())})
    return c["days"], None


# ---------- SETTINGS (prices, QR) ----------
DEFAULT_PLANS = {
    "1day":   {"label": "1 Day",     "price": "₹10"},
    "7days":  {"label": "7 Days",    "price": "₹49"},
    "1month": {"label": "1 Month",   "price": "₹99"},
    "3months":{"label": "3 Months",  "price": "₹249"},
    "1year":  {"label": "1 Year",    "price": "₹699"},
    "lifetime":{"label": "Lifetime", "price": "₹1499"},
}
PLAN_DAYS = {"1day": 1, "7days": 7, "1month": 30, "3months": 90, "1year": 365, "lifetime": -1}


async def get_setting(key, default=None):
    db = _get_db()
    r = await db.settings.find_one({"key": key})
    return r["value"] if r else default


async def set_setting(key, value):
    db = _get_db()
    await db.settings.update_one({"key": key}, {"$set": {"value": str(value)}}, upsert=True)


async def get_plan_price(plan_key):
    val = await get_setting(f"price_{plan_key}")
    if val:
        return val
    return DEFAULT_PLANS.get(plan_key, {}).get("price", "N/A")


async def get_all_prices():
    prices = {}
    for k in DEFAULT_PLANS:
        prices[k] = await get_plan_price(k)
    return prices


async def get_qr_file_id():
    return await get_setting("qr_file_id", None)


async def get_qr_caption():
    return await get_setting("qr_caption", "Scan & Pay — फिर screenshot भेजो")


# ---------- PAYMENTS ----------
async def create_payment(user_id, username, plan_key, plan_days, price, ss_file_id, ss_chat_id, ss_msg_id):
    db = _get_db()
    pid = f"{user_id}_{int(time.time())}"
    await db.payments.insert_one({
        "payment_id": pid, "user_id": user_id, "username": username,
        "plan_key": plan_key, "plan_days": plan_days, "price": price,
        "ss_file_id": ss_file_id, "ss_chat_id": ss_chat_id, "ss_msg_id": ss_msg_id,
        "status": "pending", "created_at": int(time.time()),
    })
    return pid


async def get_payment(pid):
    db = _get_db()
    return await db.payments.find_one({"payment_id": pid})


async def update_payment_status(pid, status, reviewed_by=None):
    db = _get_db()
    await db.payments.update_one({"payment_id": pid},
        {"$set": {"status": status, "reviewed_by": reviewed_by,
                  "reviewed_at": int(time.time())}})


async def get_stats():
    db = _get_db()
    total = await db.users.count_documents({})
    prem = await db.users.count_documents({"is_premium": True, "premium_until": {"$ne": 0}})
    pending = await db.payments.count_documents({"status": "pending"})
    return {"total": total, "premium": prem, "pending": pending}
