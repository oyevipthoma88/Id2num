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

API_ENDPOINTS = [
    {
        "url": "https://aerosend.bond/tgtonum.php",
        "params": {"key": "crazy", "num": "{query}"},
        "parser": "aerosend",
    },
]

MAX_TRIES = 2
RETRY_DELAY = 1.0
REQUEST_TIMEOUT = 8
