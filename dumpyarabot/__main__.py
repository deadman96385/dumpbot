import logging
import os
import sys
import re

# Load settings early
from dumpyarabot.config import settings # noqa F401

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Import handlers after logger is configured
from dumpyarabot.handlers import (
    accept_command,
    cancel_dump,
    dump,
    handle_callback_query,
    handle_request_message,
    reject_command,
    restart,
)

# Use the logger configured in __init__
logger = logging.getLogger("rich")

if __name__ == "__main__":
    logger.info("Starting DumpyaraBot (Minimal Version)...")
    try:
        req_chat_id = settings.REQUEST_CHAT_ID
        rev_chat_id = settings.REVIEW_CHAT_ID
        logger.info(f"Request Chat ID: {req_chat_id}")
        logger.info(f"Review Chat ID: {rev_chat_id}")
    except Exception as e:
        logger.critical(f"Failed loading chat IDs from settings: {e}", exc_info=True)
        sys.exit("Error: Missing required chat ID configuration in .env file.")

    application = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).build()

    # Initialize bot_data structures
    application.bot_data.setdefault("restart", False)
    application.bot_data.setdefault("pending_reviews", {}) # {req_id: PendingReview dict}
    application.bot_data.setdefault("review_options", {}) # {req_id: AcceptOptionsState dict}

    # --- Handler Registration ---
    request_chat_filter = filters.Chat(chat_id=settings.REQUEST_CHAT_ID)
    review_chat_filter = filters.Chat(chat_id=settings.REVIEW_CHAT_ID)

    # Order: Commands > Specific Messages > Callbacks
    application.add_handler(CommandHandler("reject", reject_command, filters=review_chat_filter))
    application.add_handler(CommandHandler("accept", accept_command, filters=review_chat_filter))
    application.add_handler(CommandHandler("dump", dump, filters=review_chat_filter))
    application.add_handler(CommandHandler("cancel", cancel_dump, filters=review_chat_filter))
    application.add_handler(CommandHandler("restart", restart, filters=review_chat_filter))

    application.add_handler(MessageHandler(
        request_chat_filter & filters.Regex(re.compile(r'^#request\s+', re.IGNORECASE)) & filters.TEXT & ~filters.COMMAND,
        handle_request_message
    ))

    application.add_handler(CallbackQueryHandler(handle_callback_query))

    logger.info("Bot handlers registered. Starting polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

    if application.bot_data.get("restart", False):
        logger.info("Restart flag is set. Executing restart...")
        try:
            os.execl(sys.executable, sys.executable, *sys.argv)
        except Exception as e:
             logger.critical(f"Failed to execute restart: {e}", exc_info=True)
             sys.exit(1)
    else:
        logger.info("Polling stopped.")
        sys.exit(0)