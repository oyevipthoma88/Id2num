import os

# ---------- Telegram Bot ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
LOG_CHANNEL_ID = os.environ.get("LOG_CHANNEL_ID", "")
OWNER_USERNAME = os.environ.get("OWNER_USERNAME", "@PokiePy")
SUPPORT_USERNAME = os.environ.get("SUPPORT_USERNAME", "@PokiePy")
START_IMAGE_URL = os.environ.get("START_IMAGE_URL",
    "https://i.ibb.co/3YvGkx7/telegram-osint.jpg")

# ---------- Hody-Telepro Credentials ----------
# https://my.telegram.org/auth से लो (throwaway account)
TG_API_ID = int(os.environ.get("TG_API_ID", "0"))
TG_API_HASH = os.environ.get("TG_API_HASH", "")
TG_PHONE = os.environ.get("TG_PHONE", "")   # +919876543210

# ---------- Fallback HTTP API (working एक) ----------
FALLBACK_API = {
    "url": "https://aerosend.bond/tgtonum.php",
    "params": {"key": "crazy", "num": "{query}"},
}

MAX_TRIES = 2
RETRY_DELAY = 1.0
REQUEST_TIMEOUT = 10
