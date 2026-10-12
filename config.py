import os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
LOG_CHANNEL_ID = os.environ.get("LOG_CHANNEL_ID", "")
OWNER_ID = int(os.environ.get("OWNER_ID", "0") or "0")
OWNER_USERNAME = os.environ.get("OWNER_USERNAME", "")
OWNER_CONTACT = os.environ.get("OWNER_CONTACT", "")
SUPPORT_LINK = os.environ.get("SUPPORT_LINK", "")
BOT_USERNAME = os.environ.get("BOT_USERNAME", "")
START_IMAGE_URL = os.environ.get("START_IMAGE_URL", "")
GITHUB_URL = os.environ.get("GITHUB_URL", "")

# MongoDB
MONGODB_URI = os.environ.get("MONGODB_URI", "")
MONGODB_DB = os.environ.get("MONGODB_DB", "tg_osint_bot")

# Referral + Free limit
REFERRALS_REQUIRED = int(os.environ.get("REFERRALS_REQUIRED", "3"))
FREE_SEARCHES_PER_DAY = int(os.environ.get("FREE_SEARCHES_PER_DAY", "5"))

# API
API_URL = "https://aerosend.bond/tgtonum.php"
API_KEY = "crazy"
MAX_TRIES = 3
RETRY_DELAY = 1.5
REQUEST_TIMEOUT = 10
