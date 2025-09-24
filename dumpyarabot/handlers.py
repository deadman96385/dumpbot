from typing import Optional

from pydantic import ValidationError
from rich.console import Console
from telegram import Chat, Message, Update
from telegram.ext import ContextTypes

from dumpyarabot import schemas, utils
from dumpyarabot.config import settings
from dumpyarabot.gemini_analyzer import analyzer

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
        await context.bot.send_message(
            chat_id=chat.id,
            reply_to_message_id=message.message_id,
            text=usage,
            parse_mode="Markdown",
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
            initial_message = await context.bot.send_message(
                chat_id=chat.id,
                reply_to_message_id=None if use_privdump else message.message_id,
                text="Checking for existing builds...",
            )

            exists, status_message = await utils.check_existing_build(dump_args)
            if exists:
                console.print(
                    f"[yellow]Found existing build: {status_message}[/yellow]"
                )
                await context.bot.edit_message_text(
                    chat_id=chat.id,
                    message_id=initial_message.message_id,
                    text=status_message,
                )
                return

            await context.bot.delete_message(
                chat_id=chat.id,
                message_id=initial_message.message_id,
            )

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
    await context.bot.send_message(
        chat_id=chat.id,
        reply_to_message_id=None if use_privdump else message.message_id,
        text=response_text,
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
        await context.bot.send_message(
            chat_id=chat.id,
            reply_to_message_id=message.message_id,
            text="You don't have permission to use this command",
        )
        return

    # Ensure that we had some arguments passed
    if not context.args:
        console.print("[yellow]No job_id provided for cancel command[/yellow]")
        usage = (
            "Usage: `/cancel [job_id] [p]`\njob_id: required, p: cancel privdump job"
        )
        await context.bot.send_message(
            chat_id=chat.id,
            reply_to_message_id=message.message_id,
            text=usage,
            parse_mode="Markdown",
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

    await context.bot.send_message(
        chat_id=chat.id,
        reply_to_message_id=message.message_id,
        text=response_message,
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
        await context.bot.send_message(
            chat_id=chat.id,
            reply_to_message_id=message.message_id,
            text=usage,
            parse_mode="Markdown",
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
    await context.bot.send_message(
        chat_id=chat.id,
        reply_to_message_id=message.message_id,
        text=response_text,
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
        chat_member = await context.bot.get_chat_member(chat_id=chat.id, user_id=user.id)
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
    help_text += "• `/blacklist https://example.com/firmware.zip` - Add URL to blacklist\n"

    help_text += "\n**Option Flags:**\n"
    help_text += "• `a` - Use alternative dumper for rare firmware types unsupported by primary dumper\n"
    help_text += "• `f` - Force re-dump (skip existing dump/branch check)\n"
    help_text += "• `p` - Use private dump (Deletes message, hidden Jenkins job, Firmware URL = Not visibile, Finished dump in Gitlab = Visible.)\n"

    await context.bot.send_message(
        chat_id=chat.id,
        reply_to_message_id=message.message_id,
        text=help_text,
        parse_mode="Markdown",
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
        chat_member = await context.bot.get_chat_member(chat_id=chat.id, user_id=user.id)
        if chat_member.status not in ["administrator", "creator"]:
            await context.bot.send_message(
                chat_id=chat.id,
                reply_to_message_id=message.message_id,
                text="❌ You don't have permission to restart the bot. Only chat administrators can use this command.",
            )
            return
    except Exception as e:
        console.print(f"[red]Error checking admin status: {e}[/red]")
        await context.bot.send_message(
            chat_id=chat.id,
            reply_to_message_id=message.message_id,
            text="❌ Error checking admin permissions.",
        )
        return

    # Create confirmation keyboard
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from dumpyarabot.config import CALLBACK_RESTART_CONFIRM, CALLBACK_RESTART_CANCEL

    keyboard = [
        [
            InlineKeyboardButton(
                "✅ Yes, Restart Bot",
                callback_data=f"{CALLBACK_RESTART_CONFIRM}{user.id}"
            ),
            InlineKeyboardButton(
                "❌ Cancel",
                callback_data=f"{CALLBACK_RESTART_CANCEL}{user.id}"
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

    await context.bot.send_message(
        chat_id=chat.id,
        reply_to_message_id=message.message_id,
        text=confirmation_text,
        reply_markup=reply_markup,
        parse_mode="Markdown",
    )


async def handle_restart_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
            chat_member = await query.get_bot().get_chat_member(chat_id=query.message.chat.id, user_id=user.id)
            if chat_member.status not in ["administrator", "creator"]:
                await query.edit_message_text(
                    "❌ Permission denied. You are no longer a chat administrator."
                )
                return
        except Exception as e:
            console.print(f"[red]Error checking admin status: {e}[/red]")
            await query.edit_message_text(
                "❌ Error checking admin permissions."
            )
            return

        # Confirm restart
        await query.edit_message_text(
            f"🔄 **Restart Confirmed**\n\n"
            f"👤 **Confirmed by:** {user.mention_markdown()}\n"
            f"⚡ **Status:** Bot is restarting now...\n\n"
            f"🕐 The bot should be back online in a few seconds.",
            parse_mode="Markdown"
        )

        # Store restart context for post-restart message update in Redis
        from dumpyarabot.redis_storage import RedisStorage
        RedisStorage.store_restart_message_info(
            chat_id=query.message.chat.id,
            message_id=query.message.message_id,
            user_mention=user.mention_markdown()
        )

        # Trigger restart
        console.print("[yellow]Bot restart requested by admin - shutting down...[/yellow]")
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
            parse_mode="Markdown"
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
        chat_member = await context.bot.get_chat_member(chat_id=chat.id, user_id=message.from_user.id)
        if chat_member.status not in ["administrator", "creator"]:
            await context.bot.send_message(
                chat_id=chat.id,
                reply_to_message_id=message.message_id,
                text="❌ This command is restricted to chat administrators.",
            )
            return
    except Exception as e:
        console.print(f"[red]Error checking admin status: {e}[/red]")
        await context.bot.send_message(
            chat_id=chat.id,
            reply_to_message_id=message.message_id,
            text="❌ Error checking admin permissions.",
        )
        return

    # Check if Gemini analyzer is available
    if not analyzer.is_available():
        await context.bot.send_message(
            chat_id=chat.id,
            reply_to_message_id=message.message_id,
            text="❌ Gemini AI analyzer is not configured. Set GEMINI_API_KEY environment variable.",
            parse_mode="HTML"
        )
        return

    # Ensure we have arguments passed
    if not context.args or len(context.args) < 2:
        usage = (
            "Usage: `/analyze [job_name] [build_number]`\n\n"
            "Example: `/analyze dumpyara 123`\n"
            "         `/analyze privdump 456`"
        )
        await context.bot.send_message(
            chat_id=chat.id,
            reply_to_message_id=message.message_id,
            text=usage,
            parse_mode="Markdown",
        )
        return

    job_name = context.args[0].lower()
    build_number = context.args[1]

    # Validate job name
    if job_name not in ["dumpyara", "privdump"]:
        await context.bot.send_message(
            chat_id=chat.id,
            reply_to_message_id=message.message_id,
            text="❌ Invalid job name. Use 'dumpyara' or 'privdump'.",
        )
        return

    # Validate build number
    try:
        int(build_number)
    except ValueError:
        await context.bot.send_message(
            chat_id=chat.id,
            reply_to_message_id=message.message_id,
            text="❌ Invalid build number. Must be a number.",
        )
        return

    console.print(f"[green]Analyze request: {job_name} #{build_number}[/green]")

    # Send initial status message
    status_message = await context.bot.send_message(
        chat_id=chat.id,
        reply_to_message_id=message.message_id,
        text=f"🔍 **Analyzing Jenkins log...**\n\nJob: `{job_name}`\nBuild: `#{build_number}`\n\n⏳ Fetching console log...",
        parse_mode="Markdown",
    )

    try:
        # Fetch Jenkins console log
        console_log = await utils.get_jenkins_console_log(job_name, build_number)

        # Update status
        await context.bot.edit_message_text(
            chat_id=chat.id,
            message_id=status_message.message_id,
            text=f"🔍 **Analyzing Jenkins log...**\n\nJob: `{job_name}`\nBuild: `#{build_number}`\n\n🤖 Running AI analysis...",
            parse_mode="Markdown",
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
            await context.bot.edit_message_text(
                chat_id=chat.id,
                message_id=status_message.message_id,
                text=f"🔍 **AI Analysis Complete**\n\nJob: `{job_name}`\nBuild: `#{build_number}`\n\n{formatted_analysis}",
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )

            console.print(f"[green]Successfully analyzed {job_name} #{build_number}[/green]")

        else:
            # Analysis failed
            await context.bot.edit_message_text(
                chat_id=chat.id,
                message_id=status_message.message_id,
                text=f"❌ **Analysis Failed**\n\nJob: `{job_name}`\nBuild: `#{build_number}`\n\n"
                     f"The AI analysis could not be completed. The console log may be too short or the AI service may be unavailable.\n\n"
                     f"📊 <a href=\"{build_info['build_url']}\">View Build Details</a>",
                parse_mode="HTML",
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

        await context.bot.edit_message_text(
            chat_id=chat.id,
            message_id=status_message.message_id,
            text=error_text,
            parse_mode="Markdown",
        )

