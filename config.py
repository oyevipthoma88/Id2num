import os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
LOG_CHANNEL_ID = os.environ.get("LOG_CHANNEL_ID", "")
OWNER_ID = os.environ.get("OWNER_ID", "")
OWNER_USERNAME = os.environ.get("OWNER_USERNAME", "@PokiePy")
SUPPORT_USERNAME = os.environ.get("SUPPORT_USERNAME", "@PokiePy")

START_IMAGE_URL = os.environ.get(
    "START_IMAGE_URL",
    "https://i.ibb.co/3YvGkx7/telegram-osint.jpg"
)

# ---------- API Endpoints (Fallback chain — पहली fail हो तो दूसरी try) ----------
API_ENDPOINTS = [
    # 1. नई reliable API — Callmebot (username से phone number)
    {
        "url": "https://api.callmebot.com/telegram/getPhoneNumber.php",
        "params": {"username": "{query}"},
        "parser": "callmebot",
    },
    # 2. Fallback — telegram-phone-number-checker style
    {
        "url": "https://api.callmebot.com/telegram/getPhoneNumber.php",
        "params": {"id": "{query}"},
        "parser": "callmebot_id",
    },
]

MAX_TRIES = 2
RETRY_DELAY = 1.0
REQUEST_TIMEOUT = 10
