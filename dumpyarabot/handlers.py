import secrets
from datetime import datetime, timezone
import secrets
from typing import Optional
from io import BytesIO

from pydantic import ValidationError
from rich.console import Console
from telegram import Chat, Message, Update
from telegram.ext import ContextTypes

from dumpyarabot import schemas, utils, url_utils
from dumpyarabot.utils import escape_markdown
from dumpyarabot.config import settings
from dumpyarabot.auth import check_admin_permissions
from dumpyarabot.message_queue import message_queue
from dumpyarabot.message_formatting import generate_progress_bar

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
        usage = "Usage: `/dump \\[URL\\] \\[a\\|f\\|p\\]`\nURL: required, a: alt dumper, f: force, p: use privdump"
        await message_queue.send_reply(
            chat_id=chat.id,
            text=usage,
            reply_to_message_id=message.message_id,
            context={"command": "dump", "error": "missing_args"}
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

    # Try to validate args and queue dump job
    try:
        # Validate URL using new utility
        is_valid, normalized_url, error_msg = await url_utils.validate_and_normalize_url(url)
        if not is_valid:
            raise ValidationError(error_msg)

        dump_args = schemas.DumpArguments(
            url=normalized_url,
            use_alt_dumper=use_alt_dumper,
            use_privdump=use_privdump,
            initial_message_id=None if use_privdump else message.message_id,
            initial_chat_id=chat.id
        )


        # Create dump job
        job = schemas.DumpJob(
            job_id=secrets.token_hex(8),
            dump_args=dump_args,
            add_blacklist="b" in options
        )

        console.print(f"[blue]Queueing dump job {job.job_id}...[/blue]")

        # Send initial progress message directly (bypassing queue) to get real message ID
        if use_privdump:
            initial_text = "🔐 *Private Dump Job Queued*\n\n"
        else:
            initial_text = f"🚀 *Firmware Dump Queued*\n\n📥 *URL:* `{url}`\n"

        initial_text += f"🆔 *Job ID:* `{job.job_id}`\n"

        # Format options
        options_list = []
        if use_alt_dumper:
            options_list.append("Alt Dumper")
        if force:
            options_list.append("Force")
        if use_privdump:
            options_list.append("Private")
        if "b" in options:
            options_list.append("Blacklist")

        if options_list:
            initial_text += f"⚙️ *Options:* {', '.join(options_list)}\n"

        initial_text += f"\n{generate_progress_bar(None)}\n"
        initial_text += "🔄 Queued for processing...\n\n"
        initial_text += "⏱️ *Elapsed:* 0s\n"
        initial_text += "👷 *Worker:* Waiting for assignment...\n"

        # Send initial message directly to get real Telegram message ID
        initial_message = await message_queue.send_immediate_message(
            chat_id=chat.id,
            text=initial_text,
            reply_to_message_id=None if use_privdump else message.message_id
        )

        # Store the REAL Telegram message ID in the job
        job.initial_message_id = initial_message.message_id
        job.initial_chat_id = chat.id

        # Queue the job with the real message reference
        job_id = await message_queue.queue_dump_job(job)

        console.print(f"[green]Dump job {job_id} queued with real message ID {initial_message.message_id}[/green]")

    except ValidationError as e:
        console.print(f"[red]Invalid URL provided: {url} - {e}[/red]")
        response_text = f"❌ *Invalid URL:* {url}\n\nPlease provide a valid firmware download URL."

        # Send error message as reply
        await message_queue.send_reply(
            chat_id=chat.id,
            text=response_text,
            reply_to_message_id=None if use_privdump else message.message_id,
            context={"command": "dump", "url": url, "error": "validation_error"}
        )

    except Exception as e:
        console.print(f"[red]Unexpected error occurred: {e}[/red]")
        console.print_exception()
        escaped_error = escape_markdown(str(e))
        response_text = f"❌ *Error occurred:* {escaped_error}\n\nPlease try again or contact an administrator."

        # Send error message as reply
        await message_queue.send_reply(
            chat_id=chat.id,
            text=response_text,
            reply_to_message_id=None if use_privdump else message.message_id,
            context={"command": "dump", "url": url, "error": "unexpected_error"}
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
    has_permission, error_message = await check_admin_permissions(update, context, require_admin=True)
    if not has_permission:
        console.print(
            f"[yellow]Non-admin user {user.id} tried to use cancel command: {error_message}[/yellow]"
        )
        await message_queue.send_error(
            chat_id=chat.id,
            text="You don't have permission to use this command",
            context={"command": "cancel", "user_id": user.id, "error": "permission_denied"}
        )
        return

    # Ensure that we had some arguments passed
    if not context.args:
        console.print("[yellow]No job_id provided for cancel command[/yellow]")
        usage = (
            "Usage: `/cancel \\[job\\_id\\] \\[p\\]`\njob\\_id: required, p: cancel privdump job"
        )
        await message_queue.send_reply(
            chat_id=chat.id,
            text=usage,
            reply_to_message_id=message.message_id,
            context={"command": "cancel", "error": "missing_args"}
        )
        return

    job_id = context.args[0]
    use_privdump = "p" in context.args[1:] if len(context.args) > 1 else False

    console.print("[blue]Cancel request:[/blue]")
    console.print(f"  Job ID: {job_id}")
    console.print(f"  Privdump: {use_privdump}")
    console.print(f"  Requested by: {user.username} (ID: {user.id})")

    try:
        # Try to cancel the job in the worker queue
        cancelled = await message_queue.cancel_job(job_id)

        if cancelled:
            escaped_job_id = escape_markdown(job_id)
            response_message = f"✅ *Job cancelled successfully*\n\n🆔 *Job ID:* `{escaped_job_id}`\n\nThe dump job has been removed from the queue or stopped if it was in progress."
            console.print(f"[green]Successfully cancelled job {job_id}[/green]")
        else:
            escaped_job_id = escape_markdown(job_id)
            response_message = f"❌ *Job not found*\n\n🆔 *Job ID:* `{escaped_job_id}`\n\nThe job was not found in the queue or may have already completed." 
    except Exception as e:
        console.print(f"[red]Error processing cancel request: {e}[/red]")
        console.print_exception()
        escaped_job_id = escape_markdown(job_id)
        escaped_error = escape_markdown(str(e))
        response_message = f"❌ *Error cancelling job*\n\n🆔 *Job ID:* `{escaped_job_id}`\n\nError: {escaped_error}"

    await message_queue.send_reply(
        chat_id=chat.id,
        text=response_message,
        reply_to_message_id=message.message_id,
        context={"command": "cancel", "job_id": job_id}
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for the /status command to check job queue status."""
    chat: Optional[Chat] = update.effective_chat
    message: Optional[Message] = update.effective_message
    user = update.effective_user

    if not chat or not message or not user:
        console.print("[red]Chat, message or user object is None[/red]")
        return

    # Ensure it can only be used in the correct group
    if chat.id not in settings.ALLOWED_CHATS:
        return

    try:
        if context.args and context.args[0]:
            # Check specific job status
            job_id = context.args[0]
            job = await message_queue.get_job_status(job_id)

            if job:
                escaped_job_id = escape_markdown(job_id)
                status_text = f"📋 *Job Status: {escaped_job_id}*\n\n"
                status_text += f"🔄 *Status:* {job.status.value.title()}\n"
                status_text += f"📅 *Created:* {job.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"

                if job.started_at:
                    status_text += f"🚀 *Started:* {job.started_at.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"

                if job.worker_id:
                    escaped_worker_id = escape_markdown(job.worker_id)
                    status_text += f"👷 *Worker:* `{escaped_worker_id}`\n"

                if job.progress:
                    status_text += f"📊 *Progress:* {job.progress.percentage:.1f}% ({job.progress.current_step})\n"

                if job.error_details:
                    escaped_error = escape_markdown(job.error_details)
                    status_text += f"❌ *Error:* {escaped_error}\n"

                if job.result_data:
                    if repo_url := job.result_data.get("repository_url"):
                        escaped_repo_url = escape_markdown(repo_url)
                        status_text += f"🗂️ *Repository:* {escaped_repo_url}\n"

            else:
                escaped_job_id = escape_markdown(job_id)
                status_text = f"❌ *Job not found:* `{escaped_job_id}`"

        else:
            # Get queue statistics
            stats = await message_queue.get_job_queue_stats()

            status_text = "📊 *Job Queue Status*\n\n"
            status_text += f"📈 *Total Jobs:* {stats['total_jobs']}\n"
            status_text += f"⏳ *Queued Jobs:* {stats['queued_jobs']}\n"
            status_text += f"👷 *Active Workers:* {stats['active_workers']}\n\n"

            status_text += "*Job Status Breakdown:*\n"
            for status_name, count in stats['status_breakdown'].items():
                if count > 0:
                    emoji = {
                        'queued': '⏳',
                        'processing': '🔄',
                        'completed': '✅',
                        'failed': '❌',
                        'cancelled': '🛑',
                        'retrying': '🔄'
                    }.get(status_name, '📋')
                    status_text += f"{emoji} *{status_name.title()}:* {count}\n"

    except Exception as e:
        console.print(f"[red]Error getting status: {e}[/red]")
        escaped_error = escape_markdown(str(e))
        status_text = f"❌ *Error getting status:* {escaped_error}"

    await message_queue.send_reply(
        chat_id=chat.id,
        text=status_text,
        reply_to_message_id=message.message_id,
        context={"command": "status"}
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
        usage = "Usage: `/blacklist \\[URL\\]`\nURL: required"
        await message_queue.send_reply(
            chat_id=chat.id,
            text=usage,
            reply_to_message_id=message.message_id,
            context={"command": "blacklist", "error": "missing_args"}
        )
        return

    url = context.args[0]

    console.print("[green]Blacklist request:[/green]")
    console.print(f"  URL: {url}")

    # Try to validate URL and queue blacklist job
    try:
        dump_args = schemas.DumpArguments(
            url=url,
            use_alt_dumper=False,
            add_blacklist=True,
            use_privdump=False,
            initial_message_id=message.message_id,
            initial_chat_id=chat.id
        )

        job = schemas.DumpJob(
            job_id=secrets.token_hex(8),
            dump_args=dump_args,
            add_blacklist=True,
            created_at=datetime.now(timezone.utc)
        )

        console.print("[blue]Queueing blacklist job...[/blue]")
        job_id = await message_queue.queue_dump_job(job)
        console.print(f"[green]Successfully queued blacklist job {job_id}[/green]")
        response_text = f"Blacklist job queued successfully. Job ID: {job_id}"

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
        context={"command": "blacklist", "url": url, "final_response": True}
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
    has_permission, _ = await check_admin_permissions(update, context, require_admin=True)
    is_admin = has_permission

    help_text = "🤖 *DumpyaraBot Command Help*\n\n"

    # User commands
    help_text += "*🧑 User Commands:*\n"
    from dumpyarabot.config import USER_COMMANDS
    for cmd, desc in USER_COMMANDS:
        escaped_desc = escape_markdown(desc)
        help_text += f"/{cmd} \\- {escaped_desc}\n"

    # Internal commands
    help_text += "\n*📱 Internal Commands:*\n"
    from dumpyarabot.config import INTERNAL_COMMANDS
    for cmd, desc in INTERNAL_COMMANDS:
        escaped_desc = escape_markdown(desc)
        help_text += f"/{cmd} \\- {escaped_desc}\n"

    # Admin commands (only show to admins)
    if is_admin:
        help_text += "\n*⚙️ Admin Commands:*\n"
        from dumpyarabot.config import ADMIN_COMMANDS
        for cmd, desc in ADMIN_COMMANDS:
            escaped_desc = escape_markdown(desc)
            help_text += f"/{cmd} \\- {escaped_desc}\n"

    help_text += "\n*Usage Examples:*\n"
    help_text += "• `/dump https://example.com/firmware.zip` \\- Basic dump\n"
    help_text += "• `/dump https://example.com/firmware.zip af` \\- Alt dumper \\+ force\n"
    help_text += "• `/dump https://example.com/firmware.zip p` \\- Private dump\n"
    help_text += "• `/blacklist https://example.com/firmware.zip` \\- Add URL to blacklist\n"

    help_text += "\n*Option Flags:*\n"
    help_text += "• `a` \\- Use alternative dumper for rare firmware types unsupported by primary dumper\n"
    help_text += "• `f` \\- Force re\\-dump (skip existing dump/branch check)\n"
    help_text += "• `p` \\- Use private dump (Deletes message, processes in background, Firmware URL = Not visibile, Finished dump in Gitlab = Visible.)\n"

    await message_queue.send_reply(
        chat_id=chat.id,
        text=help_text,
        reply_to_message_id=message.message_id,
        context={"command": "help", "is_admin": is_admin}
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
    has_permission, error_message = await check_admin_permissions(update, context, require_admin=True)
    if not has_permission:
        console.print(f"[red]Error checking admin status: {error_message}[/red]")
        await message_queue.send_error(
            chat_id=chat.id,
            text="❌ You don't have permission to restart the bot. Only chat administrators can use this command.",
            context={"command": "restart", "user_id": user.id, "error": "permission_denied"}
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
        "⚠️ *Bot Restart Confirmation*\n\n"
        f"👤 *Requested by:* {user.mention_markdown()}\n"
        f"🤖 *Action:* Restart dumpyarabot\n\n"
        "⚡ This will:\n"
        "• Stop all current operations\n"
        "• Reload configuration and code\n"
        "• Clear in-memory state\n"
        "• Restart with latest changes\n\n"
        "⏱️ *This confirmation will expire in 30 seconds*"
    )

    # Convert keyboard to dict for queue serialization
    keyboard_dict = {
        "inline_keyboard": [[
            {"text": "✅ Yes, Restart Bot", "callback_data": f"{CALLBACK_RESTART_CONFIRM}{user.id}"},
            {"text": "❌ Cancel", "callback_data": f"{CALLBACK_RESTART_CANCEL}{user.id}"}
        ]]
    }

    # Create a custom queued message for restart confirmation
    from dumpyarabot.message_queue import QueuedMessage, MessageType, MessagePriority
    restart_message = QueuedMessage(
        type=MessageType.NOTIFICATION,
        priority=MessagePriority.URGENT,
        chat_id=chat.id,
        text=confirmation_text,
        parse_mode=settings.DEFAULT_PARSE_MODE,
        reply_to_message_id=message.message_id,
        keyboard=keyboard_dict,
        context={"command": "restart", "user_id": user.id, "confirmation": True}
    )
    await message_queue.publish(restart_message)


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
        has_permission, error_message = await check_admin_permissions(update, context, require_admin=True)
        if not has_permission:
            console.print(f"[red]Error checking admin status: {error_message}[/red]")
            await query.edit_message_text(
                "❌ Permission denied. You are no longer a chat administrator."
            )
            return

        # Confirm restart
        await query.edit_message_text(
            f"🔄 *Restart Confirmed*\n\n"
            f"👤 *Confirmed by:* {user.mention_markdown()}\n"
            f"⚡ *Status:* Bot is restarting now...\n\n"
            f"🕐 The bot should be back online in a few seconds.",
            parse_mode=settings.DEFAULT_PARSE_MODE
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
            f"❌ *Restart Cancelled*\n\n"
            f"👤 *Cancelled by:* {user.mention_markdown()}\n"
            f"✅ *Status:* Bot restart was cancelled. Bot continues running normally.",
            parse_mode=settings.DEFAULT_PARSE_MODE
        )


