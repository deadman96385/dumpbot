from typing import Optional

from pydantic import ValidationError
from rich.console import Console
from telegram import Chat, Message, Update
from telegram.ext import ContextTypes

from dumpyarabot import schemas, utils
from dumpyarabot.config import settings
from dumpyarabot.gemini_analyzer import analyzer, image_generator
from dumpyarabot.message_queue import message_queue

console = Console()


async def dump(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handler for the /dump command."""
    chat: Optional[Chat] = update.effective_chat
    message: Optional[Message] = update.effective_message

    if not chat or not message:
        console.print("[red]Chat or message object is None[/red]")
        return

    # Ensure it can only be used in the correct group
    if chat.id not in settings.ALLOWED_CHATS:
        # Do nothing
        return

    # Ensure that we had some arguments passed
    if not context.args:
        console.print("[yellow]No arguments provided for dump command[/yellow]")
        usage = "Usage: `/dump [URL] [a|f|p]`\nURL: required, a: alt dumper, f: force, p: use privdump"
        await message_queue.send_reply(
            chat_id=chat.id,
            text=usage,
            reply_to_message_id=message.message_id,
            context={"command": "dump", "error": "missing_args"},
        )
        return

    url = context.args[0]
    options = "".join("".join(context.args[1:]).split())

    use_alt_dumper = "a" in options
    force = "f" in options
    use_privdump = "p" in options

    console.print("[green]Dump request:[/green]")
    console.print(f"  URL: {url}")
    console.print(f"  Alt dumper: {use_alt_dumper}")
    console.print(f"  Force: {force}")
    console.print(f"  Privdump: {use_privdump}")

    # Delete the user's message immediately if privdump is used
    if use_privdump:
        console.print(
            f"[blue]Privdump requested - deleting message {message.message_id}[/blue]"
        )
        try:
            await context.bot.delete_message(
                chat_id=chat.id, message_id=message.message_id
            )
            console.print(
                "[green]Successfully deleted original message for privdump[/green]"
            )
        except Exception as e:
            console.print(f"[red]Failed to delete message for privdump: {e}[/red]")

    # Try to check for existing build and call jenkins if necessary
    try:
        dump_args = schemas.DumpArguments(
            url=url,
            use_alt_dumper=use_alt_dumper,
            use_privdump=use_privdump,
        )

        if not force:
            console.print("[blue]Checking for existing builds...[/blue]")
            # Send initial status message through queue
            await message_queue.send_status_update(
                chat_id=chat.id,
                text="Checking for existing builds...",
                context={
                    "command": "dump",
                    "url": str(dump_args.url),
                    "checking_builds": True,
                },
            )

            exists, status_message = await utils.check_existing_build(dump_args)
            if exists:
                console.print(
                    f"[yellow]Found existing build: {status_message}[/yellow]"
                )
                await message_queue.send_reply(
                    chat_id=chat.id,
                    text=status_message,
                    reply_to_message_id=None if use_privdump else message.message_id,
                    context={
                        "command": "dump",
                        "url": str(dump_args.url),
                        "existing_build": True,
                    },
                )
                return

        if not use_privdump:
            dump_args.initial_message_id = message.message_id

        console.print("[blue]Calling Jenkins to start build...[/blue]")
        response_text = await utils.call_jenkins(dump_args)
        console.print(f"[green]Jenkins response: {response_text}[/green]")

    except ValidationError:
        console.print(f"[red]Invalid URL provided: {url}[/red]")
        response_text = "Invalid URL"

    except Exception:
        console.print("[red]Unexpected error occurred:[/red]")
        console.print_exception()
        response_text = "An error occurred"

    # Reply to the user with whatever the status is
    await message_queue.send_reply(
        chat_id=chat.id,
        text=response_text,
        reply_to_message_id=None if use_privdump else message.message_id,
        context={"command": "dump", "url": url, "final_response": True},
    )


async def cancel_dump(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for the /cancel command."""
    chat: Optional[Chat] = update.effective_chat
    message: Optional[Message] = update.effective_message
    user = update.effective_user

    if not chat or not message or not user:
        console.print("[red]Chat, message or user object is None[/red]")
        return

    # Ensure it can only be used in the correct group
    if chat.id not in settings.ALLOWED_CHATS:
        # Do nothing
        return

    # Check if the user is an admin
    admins = await chat.get_administrators()
    if user not in [admin.user for admin in admins]:
        console.print(
            f"[yellow]Non-admin user {user.id} tried to use cancel command[/yellow]"
        )
        await message_queue.send_error(
            chat_id=chat.id,
            text="You don't have permission to use this command",
            context={
                "command": "cancel",
                "user_id": user.id,
                "error": "permission_denied",
            },
        )
        return

    # Ensure that we had some arguments passed
    if not context.args:
        console.print("[yellow]No job_id provided for cancel command[/yellow]")
        usage = (
            "Usage: `/cancel [job_id] [p]`\njob_id: required, p: cancel privdump job"
        )
        await message_queue.send_reply(
            chat_id=chat.id,
            text=usage,
            reply_to_message_id=message.message_id,
            context={"command": "cancel", "error": "missing_args"},
        )
        return

    job_id = context.args[0]
    use_privdump = "p" in context.args[1:] if len(context.args) > 1 else False

    console.print("[blue]Cancel request:[/blue]")
    console.print(f"  Job ID: {job_id}")
    console.print(f"  Privdump: {use_privdump}")
    console.print(f"  Requested by: {user.username} (ID: {user.id})")

    try:
        response_message = await utils.cancel_jenkins_job(job_id, use_privdump)
        console.print(
            f"[green]Successfully processed cancel request: {response_message}[/green]"
        )
    except Exception as e:
        console.print("[red]Error processing cancel request:[/red]")
        console.print_exception()
        response_message = f"Error cancelling job: {str(e)}"

    await message_queue.send_reply(
        chat_id=chat.id,
        text=response_message,
        reply_to_message_id=message.message_id,
        context={
            "command": "cancel",
            "job_id": job_id,
            "success": "Successfully processed cancel request" in response_message,
        },
    )


async def blacklist(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handler for the /blacklist command."""
    chat: Optional[Chat] = update.effective_chat
    message: Optional[Message] = update.effective_message

    if not chat or not message:
        console.print("[red]Chat or message object is None[/red]")
        return

    # Ensure it can only be used in the correct group
    if chat.id not in settings.ALLOWED_CHATS:
        # Do nothing
        return

    # Ensure that we had some arguments passed
    if not context.args:
        console.print("[yellow]No arguments provided for blacklist command[/yellow]")
        usage = "Usage: `/blacklist [URL]`\nURL: required"
        await message_queue.send_reply(
            chat_id=chat.id,
            text=usage,
            reply_to_message_id=message.message_id,
            context={"command": "blacklist", "error": "missing_args"},
        )
        return

    url = context.args[0]

    console.print("[green]Blacklist request:[/green]")
    console.print(f"  URL: {url}")

    # Try to validate URL and call jenkins for blacklisting
    try:
        dump_args = schemas.DumpArguments(
            url=url,
            use_alt_dumper=False,
            add_blacklist=True,
            use_privdump=False,
            initial_message_id=message.message_id,
        )

        console.print("[blue]Calling Jenkins to add URL to blacklist...[/blue]")
        response_text = await utils.call_jenkins(dump_args, add_blacklist=True)
        console.print(f"[green]Jenkins response: {response_text}[/green]")

    except ValidationError:
        console.print(f"[red]Invalid URL provided: {url}[/red]")
        response_text = "Invalid URL"

    except Exception:
        console.print("[red]Unexpected error occurred:[/red]")
        console.print_exception()
        response_text = "An error occurred"

    # Reply to the user with whatever the status is
    await message_queue.send_reply(
        chat_id=chat.id,
        text=response_text,
        reply_to_message_id=message.message_id,
        context={"command": "blacklist", "url": url, "final_response": True},
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for the /help command."""
    chat: Optional[Chat] = update.effective_chat
    message: Optional[Message] = update.effective_message
    user = update.effective_user

    # Ensure it can only be used in the correct group
    if chat.id not in settings.ALLOWED_CHATS:
        # Do nothing
        return

    if not chat or not message or not user:
        return

    # Check if user is admin to show admin commands
    is_admin = False
    try:
        chat_member = await context.bot.get_chat_member(
            chat_id=chat.id, user_id=user.id
        )
        is_admin = chat_member.status in ["administrator", "creator"]
    except Exception:
        # If we can't check admin status, default to not showing admin commands
        is_admin = False

    help_text = "🤖 **DumpyaraBot Command Help**\n\n"

    # User commands
    help_text += "**🧑 User Commands:**\n"
    from dumpyarabot.config import USER_COMMANDS

    for cmd, desc in USER_COMMANDS:
        help_text += f"/{cmd} - {desc}\n"

    # Internal commands
    help_text += "\n**📱 Internal Commands:**\n"
    from dumpyarabot.config import INTERNAL_COMMANDS

    for cmd, desc in INTERNAL_COMMANDS:
        help_text += f"/{cmd} - {desc}\n"

    # Admin commands (only show to admins)
    if is_admin:
        help_text += "\n**⚙️ Admin Commands:**\n"
        from dumpyarabot.config import ADMIN_COMMANDS

        for cmd, desc in ADMIN_COMMANDS:
            help_text += f"/{cmd} - {desc}\n"

    help_text += "\n**Usage Examples:**\n"
    help_text += "• `/dump https://example.com/firmware.zip` - Basic dump\n"
    help_text += "• `/dump https://example.com/firmware.zip af` - Alt dumper + force\n"
    help_text += "• `/dump https://example.com/firmware.zip p` - Private dump\n"
    help_text += (
        "• `/blacklist https://example.com/firmware.zip` - Add URL to blacklist\n"
    )

    help_text += "\n**Option Flags:**\n"
    help_text += "• `a` - Use alternative dumper for rare firmware types unsupported by primary dumper\n"
    help_text += "• `f` - Force re-dump (skip existing dump/branch check)\n"
    help_text += "• `p` - Use private dump (Deletes message, hidden Jenkins job, Firmware URL = Not visibile, Finished dump in Gitlab = Visible.)\n"

    await message_queue.send_reply(
        chat_id=chat.id,
        text=help_text,
        reply_to_message_id=message.message_id,
        context={"command": "help", "is_admin": is_admin},
    )


async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for the /restart command with confirmation dialog."""
    chat: Optional[Chat] = update.effective_chat
    message: Optional[Message] = update.effective_message
    user = update.effective_user

    if not chat or not message or not user:
        return

    # Ensure it can only be used in the correct group
    if chat.id not in settings.ALLOWED_CHATS:
        # Do nothing
        return

    # Check if the user is a Telegram admin in this chat
    try:
        chat_member = await context.bot.get_chat_member(
            chat_id=chat.id, user_id=user.id
        )
        if chat_member.status not in ["administrator", "creator"]:
            await message_queue.send_error(
                chat_id=chat.id,
                text="❌ You don't have permission to restart the bot. Only chat administrators can use this command.",
                context={
                    "command": "restart",
                    "user_id": user.id,
                    "error": "permission_denied",
                },
            )
            return
    except Exception as e:
        console.print(f"[red]Error checking admin status: {e}[/red]")
        await message_queue.send_error(
            chat_id=chat.id,
            text="❌ Error checking admin permissions.",
            context={
                "command": "restart",
                "user_id": user.id,
                "error": "admin_check_failed",
            },
        )
        return

    # Create confirmation keyboard
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from dumpyarabot.config import CALLBACK_RESTART_CONFIRM, CALLBACK_RESTART_CANCEL

    keyboard = [
        [
            InlineKeyboardButton(
                "✅ Yes, Restart Bot",
                callback_data=f"{CALLBACK_RESTART_CONFIRM}{user.id}",
            ),
            InlineKeyboardButton(
                "❌ Cancel", callback_data=f"{CALLBACK_RESTART_CANCEL}{user.id}"
            ),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    confirmation_text = (
        "⚠️ **Bot Restart Confirmation**\n\n"
        f"👤 **Requested by:** {user.mention_markdown()}\n"
        f"🤖 **Action:** Restart dumpyarabot\n\n"
        "⚡ This will:\n"
        "• Stop all current operations\n"
        "• Reload configuration and code\n"
        "• Clear in-memory state\n"
        "• Restart with latest changes\n\n"
        "⏱️ *This confirmation will expire in 30 seconds*"
    )

    # Convert keyboard to dict for queue serialization
    keyboard_dict = {
        "inline_keyboard": [
            [
                {
                    "text": "✅ Yes, Restart Bot",
                    "callback_data": f"{CALLBACK_RESTART_CONFIRM}{user.id}",
                },
                {
                    "text": "❌ Cancel",
                    "callback_data": f"{CALLBACK_RESTART_CANCEL}{user.id}",
                },
            ]
        ]
    }

    # Create a custom queued message for restart confirmation
    from dumpyarabot.message_queue import QueuedMessage, MessageType, MessagePriority

    restart_message = QueuedMessage(
        type=MessageType.NOTIFICATION,
        priority=MessagePriority.URGENT,
        chat_id=chat.id,
        text=confirmation_text,
        parse_mode="Markdown",
        reply_to_message_id=message.message_id,
        keyboard=keyboard_dict,
        context={"command": "restart", "user_id": user.id, "confirmation": True},
    )
    await message_queue.publish(restart_message)


async def handle_restart_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle restart confirmation/cancellation callbacks."""
    query = update.callback_query
    user = update.effective_user

    if not query or not user:
        return

    await query.answer()

    from dumpyarabot.config import CALLBACK_RESTART_CONFIRM, CALLBACK_RESTART_CANCEL

    if query.data.startswith(CALLBACK_RESTART_CONFIRM):
        # Extract user ID from callback data
        requesting_user_id = int(query.data.replace(CALLBACK_RESTART_CONFIRM, ""))

        # Verify the user clicking is the same one who requested
        if user.id != requesting_user_id:
            await query.edit_message_text(
                "❌ Only the user who requested the restart can confirm it."
            )
            return

        # Verify user is still a chat admin
        try:
            chat_member = await query.get_bot().get_chat_member(
                chat_id=query.message.chat.id, user_id=user.id
            )
            if chat_member.status not in ["administrator", "creator"]:
                await query.edit_message_text(
                    "❌ Permission denied. You are no longer a chat administrator."
                )
                return
        except Exception as e:
            console.print(f"[red]Error checking admin status: {e}[/red]")
            await query.edit_message_text("❌ Error checking admin permissions.")
            return

        # Confirm restart
        await query.edit_message_text(
            f"🔄 **Restart Confirmed**\n\n"
            f"👤 **Confirmed by:** {user.mention_markdown()}\n"
            f"⚡ **Status:** Bot is restarting now...\n\n"
            f"🕐 The bot should be back online in a few seconds.",
            parse_mode="Markdown",
        )

        # Store restart context for post-restart message update in Redis
        from dumpyarabot.redis_storage import RedisStorage

        RedisStorage.store_restart_message_info(
            chat_id=query.message.chat.id,
            message_id=query.message.message_id,
            user_mention=user.mention_markdown(),
        )

        # Trigger restart
        console.print(
            "[yellow]Bot restart requested by admin - shutting down...[/yellow]"
        )
        context.application.stop_running()
        context.bot_data["restart"] = True

    elif query.data.startswith(CALLBACK_RESTART_CANCEL):
        # Extract user ID from callback data
        requesting_user_id = int(query.data.replace(CALLBACK_RESTART_CANCEL, ""))

        # Verify the user clicking is the same one who requested
        if user.id != requesting_user_id:
            await query.edit_message_text(
                "❌ Only the user who requested the restart can cancel it."
            )
            return

        # Cancel restart
        await query.edit_message_text(
            f"❌ **Restart Cancelled**\n\n"
            f"👤 **Cancelled by:** {user.mention_markdown()}\n"
            f"✅ **Status:** Bot restart was cancelled. Bot continues running normally.",
            parse_mode="Markdown",
        )


async def analyze(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handler for the /analyze command - analyze Jenkins console logs with AI."""
    chat: Optional[Chat] = update.effective_chat
    message: Optional[Message] = update.effective_message

    if not chat or not message:
        console.print("[red]Chat or message object is None[/red]")
        return

    # Ensure it can only be used in allowed chats
    if chat.id not in settings.ALLOWED_CHATS:
        return

    # Check if user is admin
    try:
        chat_member = await context.bot.get_chat_member(
            chat_id=chat.id, user_id=message.from_user.id
        )
        if chat_member.status not in ["administrator", "creator"]:
            await message_queue.send_error(
                chat_id=chat.id,
                text="❌ This command is restricted to chat administrators.",
                context={
                    "command": "analyze",
                    "user_id": message.from_user.id,
                    "error": "permission_denied",
                },
            )
            return
    except Exception as e:
        console.print(f"[red]Error checking admin status: {e}[/red]")
        await message_queue.send_error(
            chat_id=chat.id,
            text="❌ Error checking admin permissions.",
            context={
                "command": "analyze",
                "user_id": message.from_user.id,
                "error": "admin_check_failed",
            },
        )
        return

    # Check if Gemini analyzer is available
    if not analyzer.is_available():
        await message_queue.send_error(
            chat_id=chat.id,
            text="❌ Gemini AI analyzer is not configured. Set GEMINI_API_KEY environment variable.",
            context={"command": "analyze", "error": "gemini_not_configured"},
        )
        return

    # Ensure we have arguments passed
    if not context.args or len(context.args) < 2:
        usage = (
            "Usage: `/analyze [job_name] [build_number]`\n\n"
            "Example: `/analyze dumpyara 123`\n"
            "         `/analyze privdump 456`"
        )
        await message_queue.send_reply(
            chat_id=chat.id,
            text=usage,
            reply_to_message_id=message.message_id,
            context={"command": "analyze", "error": "missing_args"},
        )
        return

    job_name = context.args[0].lower()
    build_number = context.args[1]

    # Validate job name
    if job_name not in ["dumpyara", "privdump"]:
        await message_queue.send_error(
            chat_id=chat.id,
            text="❌ Invalid job name. Use 'dumpyara' or 'privdump'.",
            context={
                "command": "analyze",
                "job_name": job_name,
                "error": "invalid_job_name",
            },
        )
        return

    # Validate build number
    try:
        int(build_number)
    except ValueError:
        await message_queue.send_error(
            chat_id=chat.id,
            text="❌ Invalid build number. Must be a number.",
            context={
                "command": "analyze",
                "build_number": build_number,
                "error": "invalid_build_number",
            },
        )
        return

    console.print(f"[green]Analyze request: {job_name} #{build_number}[/green]")

    # Send initial status message
    await message_queue.send_status_update(
        chat_id=chat.id,
        text=f"🔍 **Analyzing Jenkins log...**\n\nJob: `{job_name}`\nBuild: `#{build_number}`\n\n⏳ Fetching console log...",
        context={
            "command": "analyze",
            "job_name": job_name,
            "build_number": build_number,
            "stage": "fetching_log",
        },
    )

    try:
        # Fetch Jenkins console log
        console_log = await utils.get_jenkins_console_log(job_name, build_number)

        # Update status
        await message_queue.send_status_update(
            chat_id=chat.id,
            text=f"🔍 **Analyzing Jenkins log...**\n\nJob: `{job_name}`\nBuild: `#{build_number}`\n\n🤖 Running AI analysis...",
            context={
                "command": "analyze",
                "job_name": job_name,
                "build_number": build_number,
                "stage": "ai_analysis",
            },
        )

        # Build info for analysis context
        build_info = {
            "job_name": job_name,
            "build_number": build_number,
            "build_url": f"{settings.JENKINS_URL}/job/{job_name}/{build_number}/",
        }

        # Run AI analysis
        analysis = await analyzer.analyze_jenkins_log(console_log, build_info)

        if analysis:
            # Format analysis for Telegram
            formatted_analysis = analyzer.format_analysis_for_telegram(
                analysis, build_info["build_url"]
            )

            # Update the status message with results
            await message_queue.send_reply(
                chat_id=chat.id,
                text=f"🔍 **AI Analysis Complete**\n\nJob: `{job_name}`\nBuild: `#{build_number}`\n\n{formatted_analysis}",
                reply_to_message_id=message.message_id,
                context={
                    "command": "analyze",
                    "job_name": job_name,
                    "build_number": build_number,
                    "stage": "complete",
                    "success": True,
                },
            )

            console.print(
                f"[green]Successfully analyzed {job_name} #{build_number}[/green]"
            )

        else:
            # Analysis failed
            await message_queue.send_error(
                chat_id=chat.id,
                text=f"❌ **Analysis Failed**\n\nJob: `{job_name}`\nBuild: `#{build_number}`\n\n"
                f"The AI analysis could not be completed. The console log may be too short or the AI service may be unavailable.\n\n"
                f"📊 <a href=\"{build_info['build_url']}\">View Build Details</a>",
                context={
                    "command": "analyze",
                    "job_name": job_name,
                    "build_number": build_number,
                    "stage": "failed",
                    "success": False,
                },
            )

    except Exception as e:
        console.print(f"[red]Error analyzing Jenkins log: {e}[/red]")

        # Update status with error
        error_message = str(e)
        if "404" in error_message:
            error_text = f"❌ **Build Not Found**\n\nJob: `{job_name}`\nBuild: `#{build_number}`\n\nThe specified build does not exist."
        elif "403" in error_message or "401" in error_message:
            error_text = f"❌ **Access Denied**\n\nJob: `{job_name}`\nBuild: `#{build_number}`\n\nCheck Jenkins credentials."
        else:
            error_text = f"❌ **Analysis Error**\n\nJob: `{job_name}`\nBuild: `#{build_number}`\n\nError: {error_message}"

        await message_queue.send_error(
            chat_id=chat.id,
            text=error_text,
            context={
                "command": "analyze",
                "job_name": job_name,
                "build_number": build_number,
                "stage": "error",
                "error": str(e),
            },
        )


async def surprise(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handler for the /surprise command - generate AI images based on random Jenkins logs.

    Usage:
    - /surprise - Generate image from random Jenkins build
    - /surprise 123 - Generate image from specific Jenkins build #123
    """
    chat: Optional[Chat] = update.effective_chat
    message: Optional[Message] = update.effective_message

    if not chat or not message:
        console.print("[red]Chat or message object is None[/red]")
        return

    # Parse command arguments for debug build number
    debug_build_number: Optional[int] = None
    if context.args and len(context.args) > 0:
        try:
            debug_build_number = int(context.args[0])
            console.print(f"[magenta]Debug mode: Using Jenkins build #{debug_build_number}[/magenta]")
        except ValueError:
            await message_queue.send_error(
                chat_id=chat.id,
                text="❌ Invalid build number. Usage: `/surprise` or `/surprise 123`",
                context={
                    "command": "surprise",
                    "user_id": message.from_user.id,
                    "error": "invalid_build_number",
                },
            )
            return

    # Ensure it can only be used in allowed chats
    if chat.id not in settings.ALLOWED_CHATS:
        return

    # Check if Gemini image generator is available
    if not image_generator.is_available():
        await message_queue.send_error(
            chat_id=chat.id,
            text="❌ Gemini AI image generator is not configured. Set GEMINI_API_KEY environment variable.",
            context={"command": "surprise", "error": "gemini_not_configured"},
        )
        return

    console.print("[green]Surprise command initiated[/green]")

    # Send initial status message (immediate, so we can edit it later)
    if debug_build_number is not None:
        status_text = f"🔧 **Generating Debug Image...**\n\n⏳ Fetching Jenkins build #{debug_build_number}..."
    else:
        status_text = "🎲 **Generating Surprise Image...**\n\n⏳ Selecting random Jenkins build..."

    initial_message = await message_queue.send_immediate_status_update(
        chat_id=chat.id,
        text=status_text,
        context={"command": "surprise", "stage": "selecting_build", "debug_build": debug_build_number},
    )

    try:
        if debug_build_number is not None:
            # Debug mode: use specific build number
            console.print(f"[magenta]Debug mode: Generating image for build #{debug_build_number}[/magenta]")

            # We'll let the image generator fetch the console log directly
            # Set up minimal build info for context
            job_name = "dumpyara"
            build = schemas.JenkinsBuild(number=debug_build_number, result=None, actions=None)  # Mock build object
            console_log = ""  # Will be fetched by image generator

        else:
            # Normal mode: Get random Jenkins build with retry logic
            max_retries = 3
            build_result = None

            for attempt in range(max_retries):
                console.print(f"[blue]Attempting to get random build (attempt {attempt + 1}/{max_retries})[/blue]")

                build_result = await utils.get_random_jenkins_build()

                if not build_result:
                    console.print(f"[yellow]No builds found on attempt {attempt + 1}[/yellow]")
                    continue

                job_name, build, console_log = build_result

                # Pre-validate the build before trying image generation
                if not console_log or len(console_log.strip()) < 50:
                    console.print(f"[yellow]Build #{build.number} has insufficient log content, trying another... (attempt {attempt + 1})[/yellow]")
                    continue

                # Build looks good, break out of retry loop
                console.print(f"[green]Found suitable build #{build.number} with {len(console_log)} chars[/green]")
                break

            if not build_result or not console_log or len(console_log.strip()) < 50:
                # Edit status message to show no builds found after retries
                await message_queue.send_status_update(
                    chat_id=chat.id,
                    text=f"❌ **No Suitable Builds Found**\n\nTried {max_retries} different builds but couldn't find any with meaningful content for image generation. Try again later when more builds are available.",
                    edit_message_id=initial_message.message_id,
                    context={"command": "surprise", "error": "no_builds_found_after_retries", "attempts": max_retries},
                )
                return

            job_name, build, console_log = build_result

        # Update status by editing the initial message
        await message_queue.send_status_update(
            chat_id=chat.id,
            text=f"🎲 **Generating Surprise Image...**\n\nJob: `{job_name}`\nBuild: `#{build.number}`\n\n🤖 Analyzing build log and generating image...",
            edit_message_id=initial_message.message_id,
            context={
                "command": "surprise",
                "job_name": job_name,
                "build_number": build.number,
                "stage": "generating_image",
            },
        )

        # Build info for image generation context
        build_info = {
            "job_name": job_name,
            "build_number": build.number,
            "build_url": f"{settings.JENKINS_URL}/job/{job_name}/{build.number}/",
        }

        # Generate surprise image with retry logic for normal mode
        image_data = await image_generator.generate_surprise_image(
            console_log, build_info, debug_build_number
        )

        # If image generation failed and we're in normal mode, try once more with a different build
        if not image_data and debug_build_number is None:
            console.print("[yellow]Image generation failed, trying one more random build...[/yellow]")

            # Update status to show retry
            await message_queue.send_status_update(
                chat_id=chat.id,
                text=f"🎲 **Retrying Image Generation...**\n\nFirst build didn't work out, trying another random build...",
                edit_message_id=initial_message.message_id,
                context={
                    "command": "surprise",
                    "stage": "retrying_with_different_build",
                },
            )

            # Try one more random build
            retry_build_result = await utils.get_random_jenkins_build()

            if retry_build_result:
                retry_job_name, retry_build, retry_console_log = retry_build_result

                if retry_console_log and len(retry_console_log.strip()) >= 50:
                    console.print(f"[blue]Retrying with build #{retry_build.number}[/blue]")

                    # Update build info
                    job_name, build, console_log = retry_job_name, retry_build, retry_console_log
                    build_info = {
                        "job_name": job_name,
                        "build_number": build.number,
                        "build_url": f"{settings.JENKINS_URL}/job/{job_name}/{build.number}/",
                    }

                    # Update status with new build info
                    await message_queue.send_status_update(
                        chat_id=chat.id,
                        text=f"🎲 **Generating Surprise Image (Retry)...**\n\nJob: `{job_name}`\nBuild: `#{build.number}`\n\n🤖 Analyzing build log and generating image...",
                        edit_message_id=initial_message.message_id,
                        context={
                            "command": "surprise",
                            "job_name": job_name,
                            "build_number": build.number,
                            "stage": "generating_image_retry",
                        },
                    )

                    # Try image generation again
                    image_data = await image_generator.generate_surprise_image(
                        console_log, build_info, None  # No debug build number for retry
                    )

        if image_data:
            # Get build summary info
            build_summary = await utils.get_build_summary_info(job_name, build)

            try:
                # Try to decode as text first (fallback description)
                content_text = image_data.decode("utf-8")

                # If it's a text description, send as formatted message
                if content_text.startswith("🎨"):
                    success_text = (
                        f"🎲 **Surprise Generated!**\n\n"
                        f"{build_summary}\n\n"
                        f"{content_text}\n\n"
                        f"📊 [View Original Build]({build_info['build_url']})"
                    )

                    await message_queue.send_reply(
                        chat_id=chat.id,
                        text=success_text,
                        reply_to_message_id=message.message_id,
                        context={
                            "command": "surprise",
                            "job_name": job_name,
                            "build_number": build.number,
                            "success": True,
                            "type": "description",
                        },
                    )

                    # Delete the status message since info is now in the final message
                    try:
                        await context.bot.delete_message(
                            chat_id=chat.id, message_id=initial_message.message_id
                        )
                    except Exception as delete_error:
                        console.print(
                            f"[yellow]Could not delete status message: {delete_error}[/yellow]"
                        )

                    console.print(
                        f"[green]Successfully generated surprise description for {job_name} #{build.number}[/green]"
                    )

            except UnicodeDecodeError:
                # It's actual image data, try to send as photo
                try:
                    import io

                    image_file = io.BytesIO(image_data)
                    image_file.name = f"dumpyara_surprise_{job_name}_{build.number}.png"

                    caption = (
                        f"🎉 **Dumpyara Surprise!**\n\n"
                        f"{build_summary}\n\n"
                        f"🤖 *Generated with Gemini 2.5-flash*\n"
                        f"📊 [View Original Build]({build_info['build_url']})"
                    )

                    # Use context.bot to send photo directly
                    await context.bot.send_photo(
                        chat_id=chat.id,
                        photo=image_file,
                        caption=caption,
                        parse_mode="Markdown",
                        reply_to_message_id=message.message_id,
                    )

                    # Delete the status message since info is now in the final message
                    try:
                        await context.bot.delete_message(
                            chat_id=chat.id, message_id=initial_message.message_id
                        )
                    except Exception as delete_error:
                        console.print(
                            f"[yellow]Could not delete status message: {delete_error}[/yellow]"
                        )

                    console.print(
                        f"[green]Successfully sent surprise image for {job_name} #{build.number}[/green]"
                    )

                except Exception as send_error:
                    console.print(f"[red]Failed to send image: {send_error}[/red]")

                    # Edit status message to show failure instead of creating new message
                    failure_text = f"❌ **Image Send Failed**\n\nJob: `{job_name}`\nBuild: `#{build.number}`\n\nImage was generated but failed to send: {str(send_error)[:100]}{'...' if len(str(send_error)) > 100 else ''}\n\n📊 [View Build Details]({build_info['build_url']})"

                    await message_queue.send_status_update(
                        chat_id=chat.id,
                        text=failure_text,
                        edit_message_id=initial_message.message_id,
                        context={
                            "command": "surprise",
                            "job_name": job_name,
                            "build_number": build.number,
                            "success": False,
                            "error": "image_send_failed",
                        },
                    )

        else:
            # Image generation failed - edit status message to show failure
            failure_text = f"❌ **Image Generation Failed**\n\nJob: `{job_name}`\nBuild: `#{build.number}`\n\nThe AI image generation could not be completed. This may be due to:\n• Insufficient build log content\n• AI service limitations\n• Network connectivity issues\n\n📊 [View Build Details]({build_info['build_url']})"

            await message_queue.send_status_update(
                chat_id=chat.id,
                text=failure_text,
                edit_message_id=initial_message.message_id,
                context={
                    "command": "surprise",
                    "job_name": job_name,
                    "build_number": build.number,
                    "success": False,
                    "error": "image_generation_failed",
                },
            )

    except Exception as e:
        console.print(f"[red]Error generating surprise image: {e}[/red]")

        # Edit status message to show error instead of creating new message
        error_message = str(e)
        if "404" in error_message:
            error_text = "❌ **Build Not Found**\n\nThe selected build no longer exists or is inaccessible."
        elif "403" in error_message or "401" in error_message:
            error_text = (
                "❌ **Access Denied**\n\nCheck Jenkins credentials and permissions."
            )
        else:
            error_text = f"❌ **Surprise Generation Error**\n\nUnexpected error: {error_message[:100]}{'...' if len(error_message) > 100 else ''}"

        await message_queue.send_status_update(
            chat_id=chat.id,
            text=error_text,
            edit_message_id=initial_message.message_id,
            context={"command": "surprise", "stage": "error", "error": str(e)},
        )
