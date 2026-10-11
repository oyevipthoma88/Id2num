import os

# ---------- Telegram Bot ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# ---------- Log Channel ----------
LOG_CHANNEL_ID = os.environ.get("LOG_CHANNEL_ID", "")

# ---------- Owner & Support ----------
OWNER_ID = os.environ.get("OWNER_ID", "")
OWNER_USERNAME = os.environ.get("OWNER_USERNAME", "@PokiePy")
SUPPORT_USERNAME = os.environ.get("SUPPORT_USERNAME", "@PokiePy")

# ---------- Start Image ----------
# /start command pe ye photo bhejenge (public image URL)
START_IMAGE_URL = os.environ.get(
    "START_IMAGE_URL",
    "https://i.ibb.co/3YvGkx7/telegram-osint.jpg"   # apni image URL daal
)

# ---------- API Endpoints ----------
# Note: sirf working APIs rakho. Fake example.com URLs mat daalo.
API_ENDPOINTS = [
    # 1. Primary working API
    {
        "url": "https://aerosend.bond/tgtonum.php",
        "params": {"key": "crazy", "num": "{query}"},
        "parser": "aerosend",
        "accepts": ["id"],       # numeric ID hi chalegi
    },
    # NOTE: Neeche apni real API daal sakte ho jab mile.
    # Format:
    # {
    #     "url": "https://your-real-api.com/lookup",
    #     "params": {"username": "{query}"},
    #     "parser": "generic",
    #     "accepts": ["id", "username"],
    # },
]

# ---------- Retry Settings ----------
MAX_TRIES = 2                # fake URLs na hone se ab retry count kam
RETRY_DELAY = 1.0
REQUEST_TIMEOUT = 8
