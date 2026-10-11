import os

# Telegram Bot Token (Heroku Config Vars / .env से लोड होगा)
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# API endpoint (aerosend.bond)
API_URL = "https://aerosend.bond/tgtonum.php"
API_KEY = "crazy"  # Hardcoded key from original script

# Retry settings
MAX_TRIES = 5
RETRY_DELAY = 1.5
REQUEST_TIMEOUT = 10
