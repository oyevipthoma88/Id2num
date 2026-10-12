import os

# ---------- All from Heroku Config Vars ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
LOG_CHANNEL_ID = os.environ.get("LOG_CHANNEL_ID", "")
OWNER_ID = int(os.environ.get("OWNER_ID", "0") or "0")
OWNER_USERNAME = os.environ.get("OWNER_USERNAME", "")

# Support = Channel = URL (एक ही variable)
SUPPORT_LINK = os.environ.get("SUPPORT_LINK", "")   # e.g., @YourChannel or https://t.me/YourChannel

BOT_USERNAME = os.environ.get("BOT_USERNAME", "")
START_IMAGE_URL = os.environ.get("START_IMAGE_URL", "")
GITHUB_URL = os.environ.get("GITHUB_URL", "")
MAX_SEARCHES_PER_DAY = int(os.environ.get("MAX_SEARCHES_PER_DAY", "10"))

# ---------- API (internal) ----------
API_URL = "https://aerosend.bond/tgtonum.php"
API_KEY = "crazy"
MAX_TRIES = 3
RETRY_DELAY = 1.5
REQUEST_TIMEOUT = 10
