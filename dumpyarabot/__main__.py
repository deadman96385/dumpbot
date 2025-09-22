import os
import sys

from telegram.ext import (ApplicationBuilder, CallbackQueryHandler,
                          CommandHandler, MessageHandler, filters)

from dumpyarabot.handlers import cancel_dump, dump
from dumpyarabot.moderated_handlers import (accept_command,
                                            handle_callback_query,
                                            handle_request_message,
                                            reject_command)

from .config import settings

if __name__ == "__main__":
    application = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).build()
    application.bot_data["restart"] = False

    # Existing handlers
    dump_handler = CommandHandler("dump", dump)
    cancel_dump_handler = CommandHandler("cancel", cancel_dump)

    # Moderated request system handlers
    accept_handler = CommandHandler("accept", accept_command)
    reject_handler = CommandHandler("reject", reject_command)
    request_message_handler = MessageHandler(
        filters.TEXT & filters.Regex(r"#request"), handle_request_message
    )
    callback_handler = CallbackQueryHandler(handle_callback_query)

    # TODO: Fix the restart handler implementation
    # restart_handler = CommandHandler("restart", restart)

    # Add all handlers
    application.add_handler(dump_handler)
    application.add_handler(cancel_dump_handler)
    application.add_handler(accept_handler)
    application.add_handler(reject_handler)
    application.add_handler(request_message_handler)
    application.add_handler(callback_handler)
    # application.add_handler(restart_handler)

    application.run_polling()

    if application.bot_data["restart"]:
        os.execl(sys.executable, sys.executable, *sys.argv)
