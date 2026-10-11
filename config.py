import os

# ---------- Telegram Bot ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# ---------- Log Channel ----------
# Channel ID जहाँ हर user input + bot response log होगा
# Example: -1001234567890  (channel का numeric ID, @username नहीं)
LOG_CHANNEL_ID = os.environ.get("LOG_CHANNEL_ID", "")

# ---------- Owner & Support ----------
OWNER_ID = os.environ.get("OWNER_ID", "")          # तुम्हारा Telegram numeric ID
OWNER_USERNAME = os.environ.get("OWNER_USERNAME", "@PokiePy")
SUPPORT_USERNAME = os.environ.get("SUPPORT_USERNAME", "@PokiePy")

# ---------- API Endpoints (Multiple / Fallback) ----------
API_ENDPOINTS = [
    {
        "url": "https://aerosend.bond/tgtonum.php",
        "params": {"key": "crazy", "num": "{tg_id}"},
        "parser": "aerosend",
    },
    # Fallback API (agar available हो तो)
    # {
    #     "url": "https://api.example.com/tg2num",
    #     "params": {"id": "{tg_id}"},
    #     "parser": "generic",
    # },
]

# ---------- Retry Settings ----------
MAX_TRIES = 3
RETRY_DELAY = 1.5
REQUEST_TIMEOUT = 10
