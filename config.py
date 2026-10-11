import os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
LOG_CHANNEL_ID = os.environ.get("LOG_CHANNEL_ID", "")
OWNER_USERNAME = os.environ.get("OWNER_USERNAME", "@PokiePy")
SUPPORT_USERNAME = os.environ.get("SUPPORT_USERNAME", "@PokiePy")
START_IMAGE_URL = os.environ.get("START_IMAGE_URL",
    "https://i.ibb.co/3YvGkx7/telegram-osint.jpg")

# ---------- Telegram ID → Number API (original file जैसी) ----------
API_URL = "https://aerosend.bond/tgtonum.php"
API_KEY = "crazy"

MAX_TRIES = 3
RETRY_DELAY = 1.5
REQUEST_TIMEOUT = 10
