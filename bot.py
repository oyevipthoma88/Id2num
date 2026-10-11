#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import asyncio
import requests
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import (
    BOT_TOKEN,
    API_URL,
    API_KEY,
    MAX_TRIES,
    RETRY_DELAY,
    REQUEST_TIMEOUT,
)

# ---------- Logging ----------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ---------- API Call ----------
def lookup_tg_id(tg_id: str):
    """Call aerosend.bond API to resolve Telegram ID to mobile number."""
    for attempt in range(MAX_TRIES):
        try:
            r = requests.get(
                API_URL,
                params={"key": API_KEY, "num": tg_id},
                timeout=REQUEST_TIMEOUT,
            ).json()
            if r.get("status") == "success":
                return r
        except requests.exceptions.RequestException as e:
            logger.warning(f"API attempt {attempt + 1} failed: {e}")
        except Exception as e:
            logger.warning(f"Unexpected error: {e}")
        asyncio.run(asyncio.sleep(RETRY_DELAY))
    return None


# ---------- /start Command ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send welcome message with inline buttons."""
    keyboard = [
        [InlineKeyboardButton("🔍 Lookup Telegram ID", callback_data="lookup")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "👋 Welcome to *TG OSINT Bot*\n\n"
        "I can look up a Telegram ID and try to resolve it to a mobile number.\n\n"
        "Choose an option below:",
        reply_markup=reply_markup,
        parse_mode="Markdown",
    )


# ---------- Inline Button Handler ----------
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline button presses."""
    query = update.callback_query
    await query.answer()

    if query.data == "lookup":
        await query.edit_message_text(
            "📝 Please send me a *numeric Telegram ID*.\n\n"
            "Example: `123456789`",
            parse_mode="Markdown",
        )
    elif query.data == "help":
        await query.edit_message_text(
            "ℹ️ *How to use:*\n\n"
            "1. Press /start\n"
            "2. Click *Lookup Telegram ID*\n"
            "3. Send a numeric Telegram ID\n"
            "4. Wait for the result\n\n"
            "⚠️ *Disclaimer:* Only use with explicit consent. "
            "Unauthorized lookup may be illegal.",
            parse_mode="Markdown",
        )


# ---------- Message Handler (for ID input) ----------
async def handle_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle numeric Telegram ID input and perform lookup."""
    text = update.message.text.strip()

    if not text.isdigit():
        await update.message.reply_text(
            "❌ *Invalid input.* Please send a numeric Telegram ID.",
            parse_mode="Markdown",
        )
        return

    msg = await update.message.reply_text("⏳ Looking up... Please wait.")

    data = lookup_tg_id(text)

    if not data:
        await msg.edit_text(
            "❌ *No data found* for this ID.\n"
            "The ID may be invalid or the API returned no result.",
            parse_mode="Markdown",
        )
        return

    # Build result message
    result = (
        f"✅ *Result Found*\n\n"
        f"🆔 *Telegram ID:* `{data.get('tg_id', 'N/A')}`\n"
        f"📱 *Mobile:* `{data.get('mobile', 'N/A')}`\n"
        f"🌍 *Country Code:* `{data.get('country_code', 'N/A')}`\n"
        f"🏴 *Country:* `{data.get('country', 'N/A')}`\n"
    )

    # Add back button
    keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await msg.edit_text(result, parse_mode="Markdown", reply_markup=reply_markup)


# ---------- Back to Menu Handler ----------
async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'Back to Menu' button."""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("🔍 Lookup Telegram ID", callback_data="lookup")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "👋 *TG OSINT Bot*\n\nChoose an option below:",
        reply_markup=reply_markup,
        parse_mode="Markdown",
    )


# ---------- Main ----------
def main() -> None:
    """Start the bot."""
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("BOT_TOKEN is not set! Please set it in config.py or environment.")
        return

    application = Application.builder().token(BOT_TOKEN).build()

    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler, pattern="^(lookup|help)$"))
    application.add_handler(CallbackQueryHandler(back_to_menu, pattern="^menu$"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_id))

    logger.info("Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
