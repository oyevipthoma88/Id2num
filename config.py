import os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
LOG_CHANNEL_ID = os.environ.get("LOG_CHANNEL_ID", "")
OWNER_ID = int(os.environ.get("OWNER_ID", "0") or "0")
OWNER_USERNAME = os.environ.get("OWNER_USERNAME", "")
SUPPORT_LINK = os.environ.get("SUPPORT_LINK", "")
BOT_USERNAME = os.environ.get("BOT_USERNAME", "")
START_IMAGE_URL = os.environ.get("START_IMAGE_URL", "")
GITHUB_URL = os.environ.get("GITHUB_URL", "")
OWNER_CONTACT = os.environ.get("OWNER_CONTACT", "")

# Referral + limit
REFERRALS_REQUIRED = int(os.environ.get("REFERRALS_REQUIRED", "3"))
FREE_SEARCHES_PER_DAY = int(os.environ.get("FREE_SEARCHES_PER_DAY", "5"))
DEFAULT_PREMIUM_PRICE = os.environ.get("DEFAULT_PREMIUM_PRICE", "₹99 / 30 days")

# DB
DATABASE_PATH = os.environ.get("DATABASE_PATH", "bot.db")

# API
API_URL = "https://aerosend.bond/tgtonum.php"
API_KEY = "crazy"
MAX_TRIES = 3
RETRY_DELAY = 1.5
REQUEST_TIMEOUT = 10
