import sqlite3, time, logging
from config import DATABASE_PATH

logger = logging.getLogger("DB")

def _conn():
    c = sqlite3.connect(DATABASE_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT, first_name TEXT,
            joined_at INTEGER, referred_by INTEGER,
            referral_count INTEGER DEFAULT 0,
            is_premium INTEGER DEFAULT 0,
            premium_until INTEGER DEFAULT 0,
            daily_used INTEGER DEFAULT 0,
            last_reset INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS coupons (
            code TEXT PRIMARY KEY, days INTEGER, max_uses INTEGER,
            used INTEGER DEFAULT 0, created_by INTEGER, created_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS redemptions (
            user_id INTEGER, code TEXT, redeemed_at INTEGER,
            PRIMARY KEY (user_id, code)
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY, value TEXT
        );
        """)
    logger.info("DB initialized")

def create_user_if_new(user_id, username, first_name):
    with _conn() as c:
        row = c.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,)).fetchone()
        if row:
            c.execute("UPDATE users SET username=?, first_name=? WHERE user_id=?",
                      (username, first_name, user_id))
            return False
        c.execute("INSERT INTO users (user_id,username,first_name,joined_at,last_reset) VALUES (?,?,?,?,?)",
                  (user_id, username, first_name, int(time.time()), int(time.time())))
        return True

def set_referrer(user_id, referrer_id):
    if user_id == referrer_id: return False
    with _conn() as c:
        row = c.execute("SELECT referred_by FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not row or row["referred_by"]: return False
        ref = c.execute("SELECT 1 FROM users WHERE user_id=?", (referrer_id,)).fetchone()
        if not ref: return False
        c.execute("UPDATE users SET referred_by=? WHERE user_id=?", (referrer_id, user_id))
        c.execute("UPDATE users SET referral_count=referral_count+1 WHERE user_id=?", (referrer_id,))
        return True

def get_referral_count(user_id):
    with _conn() as c:
        r = c.execute("SELECT referral_count FROM users WHERE user_id=?", (user_id,)).fetchone()
        return r["referral_count"] if r else 0

def is_premium(user_id):
    with _conn() as c:
        r = c.execute("SELECT is_premium,premium_until FROM users WHERE user_id=?", (user_id,)).fetchone()
        return bool(r and r["is_premium"] == 1 and r["premium_until"] > int(time.time()))

def premium_until(user_id):
    with _conn() as c:
        r = c.execute("SELECT premium_until FROM users WHERE user_id=?", (user_id,)).fetchone()
        return r["premium_until"] if r else 0

def add_premium(user_id, days):
    now = int(time.time())
    with _conn() as c:
        r = c.execute("SELECT premium_until FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not r:
            c.execute("INSERT INTO users (user_id,is_premium,premium_until,joined_at,last_reset) VALUES (?,?,?,?,?)",
                      (user_id, 1, now + days*86400, now, now))
        else:
            base = r["premium_until"] if r["premium_until"] > now else now
            c.execute("UPDATE users SET is_premium=1, premium_until=? WHERE user_id=?",
                      (base + days*86400, user_id))

def get_daily_used(user_id):
    with _conn() as c:
        r = c.execute("SELECT daily_used,last_reset FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not r: return 0
        if int(time.time()) - (r["last_reset"] or 0) > 86400:
            c.execute("UPDATE users SET daily_used=0,last_reset=? WHERE user_id=?", (int(time.time()), user_id))
            return 0
        return r["daily_used"] or 0

def inc_daily_used(user_id):
    with _conn() as c:
        c.execute("UPDATE users SET daily_used=daily_used+1 WHERE user_id=?", (user_id,))

def create_coupon(code, days, max_uses, created_by):
    with _conn() as c:
        try:
            c.execute("INSERT INTO coupons (code,days,max_uses,created_by,created_at) VALUES (?,?,?,?,?)",
                      (code.upper().strip(), days, max_uses, created_by, int(time.time())))
            return True
        except sqlite3.IntegrityError:
            return False

def redeem_coupon(user_id, code):
    code = code.upper().strip()
    with _conn() as c:
        r = c.execute("SELECT * FROM coupons WHERE code=?", (code,)).fetchone()
        if not r: return None, "invalid"
        if r["used"] >= r["max_uses"]: return None, "exhausted"
        dup = c.execute("SELECT 1 FROM redemptions WHERE user_id=? AND code=?", (user_id, code)).fetchone()
        if dup: return None, "already"
        c.execute("UPDATE coupons SET used=used+1 WHERE code=?", (code,))
        c.execute("INSERT INTO redemptions (user_id,code,redeemed_at) VALUES (?,?,?)",
                  (user_id, code, int(time.time())))
        return r["days"], None

def get_setting(key, default=None):
    with _conn() as c:
        r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default

def set_setting(key, value):
    with _conn() as c:
        c.execute("INSERT INTO settings (key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (key, str(value)))

def get_stats():
    with _conn() as c:
        total = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        prem = c.execute("SELECT COUNT(*) FROM users WHERE is_premium=1 AND premium_until>?",
                         (int(time.time()),)).fetchone()[0]
        cps = c.execute("SELECT COUNT(*) FROM coupons").fetchone()[0]
        return {"total": total, "premium": prem, "coupons": cps}
