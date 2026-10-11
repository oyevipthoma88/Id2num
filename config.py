import os

# ---------- Telegram Bot ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# ---------- Log Channel ----------
LOG_CHANNEL_ID = os.environ.get("LOG_CHANNEL_ID", "")

# ---------- Owner & Support ----------
OWNER_ID = os.environ.get("OWNER_ID", "")
OWNER_USERNAME = os.environ.get("OWNER_USERNAME", "@PokiePy")
SUPPORT_USERNAME = os.environ.get("SUPPORT_USERNAME", "@PokiePy")

# ---------- Free API Endpoints (Fallback chain) ----------
API_ENDPOINTS = [
    # 1. Primary: aerosend.bond (working)
    {
        "url": "https://aerosend.bond/tgtonum.php",
        "params": {"key": "crazy", "num": "{tg_id}"},
        "parser": "aerosend",
    },
    # 2. SmartUserInfo (self-hosted) — apna server chala ke use karo
    # {
    #     "url": "http://localhost:8000/info",
    #     "params": {"username": "{tg_id}"},
    #     "parser": "smartuserinfo",
    # },
    # 3. tgden (free REST search) — replace URL with actual endpoint
    # {
    #     "url": "https://tgden.example.com/search",
    #     "params": {"q": "{tg_id}"},
    #     "parser": "tgden",
    # },
]

# ---------- Retry Settings ----------
MAX_TRIES = 3
RETRY_DELAY = 1.5
REQUEST_TIMEOUT = 10
