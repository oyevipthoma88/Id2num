import os
import logging

logger = logging.getLogger("config")

# ---------- Required (Heroku Config Vars) ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
MONGODB_URI = os.environ.get("MONGODB_URI", "")

# ---------- Defaults ----------
MONGODB_DB = os.environ.get("MONGODB_DB", "tg_osint_bot")
LOG_CHANNEL_ID = os.environ.get("LOG_CHANNEL_ID", "")
OWNER_ID = int(os.environ.get("OWNER_ID", "0") or "0")
OWNER_USERNAME = os.environ.get("OWNER_USERNAME", "@PokiePy")
OWNER_CONTACT = os.environ.get("OWNER_CONTACT", "@PokiePy")
SUPPORT_LINK = os.environ.get("SUPPORT_LINK", "@PokiePy")
BOT_USERNAME = os.environ.get("BOT_USERNAME", "")
START_IMAGE_URL = os.environ.get("START_IMAGE_URL", "https://i.ibb.co/3YvGkx7/telegram-osint.jpg")
GITHUB_URL = os.environ.get("GITHUB_URL", "https://github.com/oyevipthoma88/Id2num")

REFERRALS_REQUIRED = int(os.environ.get("REFERRALS_REQUIRED", "3"))
FREE_SEARCHES_PER_DAY = int(os.environ.get("FREE_SEARCHES_PER_DAY", "5"))

API_URL = "https://aerosend.bond/tgtonum.php"
API_KEY = "crazy"
MAX_TRIES = 3
RETRY_DELAY = 1.5
REQUEST_TIMEOUT = 10

if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN not set")
if not MONGODB_URI:
    logger.error("❌ MONGODB_URI not set")
