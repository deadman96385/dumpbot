import re
from typing import Any, Optional

from pydantic import ValidationError
from rich.console import Console
from telegram import Chat, Message, Update
from telegram.ext import ContextTypes

from dumpyarabot import schemas, utils
from dumpyarabot.config import (CALLBACK_ACCEPT, CALLBACK_REJECT,
                                CALLBACK_SUBMIT_ACCEPTANCE,
                                CALLBACK_TOGGLE_ALT, CALLBACK_TOGGLE_FORCE,
                                settings)
from dumpyarabot.storage import ReviewStorage
from dumpyarabot.ui import (ACCEPTANCE_TEMPLATE, REJECTION_TEMPLATE,
                            REVIEW_TEMPLATE, SUBMISSION_TEMPLATE,
                            create_options_keyboard, create_review_keyboard,
                            create_submission_keyboard)

console = Console()


async def _cleanup_request(context: ContextTypes.DEFAULT_TYPE, request_id: str) -> None:
    """Clean up a processed request - remove from storage but keep submission message for status updates."""
    ReviewStorage.remove_pending_review(context, request_id)
    ReviewStorage.remove_options_state(context, request_id)


async def handle_request_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle #request messages with URL parsing and validation."""
    chat: Optional[Chat] = update.effective_chat
    message: Optional[Message] = update.effective_message
    user = update.effective_user

    if not chat or not message or not user:
        console.print("[red]Chat, message or user object is None[/red]")
        return

    # 1. Check if message is in REQUEST_CHAT_ID
    if chat.id != settings.REQUEST_CHAT_ID:
        console.print(f"[yellow]Message from non-request chat: {chat.id}[/yellow]")
        return

    # 2. Parse message for "#request <URL>" pattern (flexible format)
    # Supports: "#requesthttps://...", "#request https://...", "#request please https://...", etc.
    # DOTALL flag allows . to match newlines for multi-line messages
    request_pattern = r"#request\s*.*?(https?://[^\s]+)"
    match = re.search(request_pattern, message.text or "", re.IGNORECASE | re.DOTALL)

    if not match:
        console.print("[yellow]No valid #request pattern found[/yellow]")
        return

    url_str = match.group(1)
    console.print(f"[blue]Processing request for URL: {url_str}[/blue]")

    try:
        # 3. Validate URL using Pydantic
        url = schemas.AnyHttpUrl(url_str)

        # 4. Generate request_id
        request_id = utils.generate_request_id()

        # 5. Send review message to REVIEW_CHAT_ID with Accept/Reject buttons
        review_text = REVIEW_TEMPLATE.format(
            username=user.username or user.first_name or str(user.id),
            url=url,
            request_id=request_id,
        )

        review_message = await context.bot.send_message(
            chat_id=settings.REVIEW_CHAT_ID,
            text=review_text,
            reply_markup=create_review_keyboard(request_id),
            disable_web_page_preview=True,
        )

        # 6. Notify user of successful submission
        submission_message = await context.bot.send_message(
            chat_id=chat.id,
            reply_to_message_id=message.message_id,
            text=SUBMISSION_TEMPLATE.format(url=url),
            disable_web_page_preview=True,
        )

        # 7. Store PendingReview in bot_data
        pending_review = schemas.PendingReview(
            request_id=request_id,
            original_chat_id=chat.id,
            original_message_id=message.message_id,
            requester_id=user.id,
            requester_username=user.username,
            url=url,
            review_chat_id=settings.REVIEW_CHAT_ID,
            review_message_id=review_message.message_id,
            submission_confirmation_message_id=submission_message.message_id,
        )

        ReviewStorage.store_pending_review(context, pending_review)

        console.print(f"[green]Request {request_id} processed successfully[/green]")

    except ValidationError:
        console.print(f"[red]Invalid URL provided: {url_str}[/red]")
        await context.bot.send_message(
            chat_id=chat.id,
            reply_to_message_id=message.message_id,
            text="❌ Invalid URL format provided",
        )
    except Exception as e:
        console.print(f"[red]Error processing request: {e}[/red]")
        console.print_exception()
        await context.bot.send_message(
            chat_id=chat.id,
            reply_to_message_id=message.message_id,
            text="❌ An error occurred while processing your request",
        )


async def handle_callback_query(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle button callbacks for accept/reject and option toggles."""
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()

    callback_data = query.data
    console.print(f"[blue]Processing callback: {callback_data}[/blue]")

    # Parse callback_data to determine action type
    if callback_data.startswith(CALLBACK_ACCEPT):
        await _handle_accept_callback(query, context, callback_data)
    elif callback_data.startswith(CALLBACK_REJECT):
        await _handle_reject_callback(query, context, callback_data)
    elif callback_data.startswith(CALLBACK_TOGGLE_ALT):
        await _handle_toggle_callback(query, context, callback_data, "alt")
    elif callback_data.startswith(CALLBACK_TOGGLE_FORCE):
        await _handle_toggle_callback(query, context, callback_data, "force")
    elif callback_data.startswith(CALLBACK_TOGGLE_PRIVDUMP):
        await _handle_toggle_callback(query, context, callback_data, "privdump")
    elif callback_data.startswith(CALLBACK_CANCEL_REQUEST):
        await _handle_cancel_callback(query, context, callback_data)
    elif callback_data.startswith(CALLBACK_SUBMIT_ACCEPTANCE):
        await _handle_submit_callback(query, context, callback_data)


async def _handle_accept_callback(
    query: Any, context: ContextTypes.DEFAULT_TYPE, callback_data: str
) -> None:
    """Handle accept button -> Show options submenu."""
    request_id = callback_data[len(CALLBACK_ACCEPT) :]

    pending_review = ReviewStorage.get_pending_review(context, request_id)
    if not pending_review:
        await query.edit_message_text("❌ Request not found or expired")
        return

    # Get current options state
    options_state = ReviewStorage.get_options_state(context, request_id)

    # Update message to show options
    await query.edit_message_text(
        text=f"📋 Configure options for request {request_id}\nURL: {pending_review.url}",
        reply_markup=create_options_keyboard(request_id, options_state),
        disable_web_page_preview=True,
    )


async def _handle_reject_callback(
    query: Any, context: ContextTypes.DEFAULT_TYPE, callback_data: str
) -> None:
    """Handle reject button -> Prompt for /reject command."""
    request_id = callback_data[len(CALLBACK_REJECT) :]

    await query.edit_message_text(
        text=f"❌ To reject request {request_id}, use:\n`/reject {request_id} [reason]`",
        parse_mode="Markdown",
    )


async def _handle_toggle_callback(
    query: Any,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: str,
    option: str,
) -> None:
    """Handle option toggles -> Update state and refresh keyboard."""
    request_id = callback_data.split("_")[-1]  # Extract request_id from end

    pending_review = ReviewStorage.get_pending_review(context, request_id)
    if not pending_review:
        await query.edit_message_text("❌ Request not found or expired")
        return

    # Update option state
    options_state = ReviewStorage.get_options_state(context, request_id)

    if option == "alt":
        options_state.alt = not options_state.alt
    elif option == "force":
        options_state.force = not options_state.force

    ReviewStorage.update_options_state(context, request_id, options_state)

    # Refresh keyboard with updated state
    await query.edit_message_reply_markup(
        reply_markup=create_options_keyboard(request_id, options_state)
    )


async def _handle_submit_callback(
    query: Any, context: ContextTypes.DEFAULT_TYPE, callback_data: str
) -> None:
    """Handle submit acceptance -> Process with selected options."""
    request_id = callback_data[len(CALLBACK_SUBMIT_ACCEPTANCE) :]

    pending_review = ReviewStorage.get_pending_review(context, request_id)
    if not pending_review:
        await query.edit_message_text("❌ Request not found or expired")
        return

    options_state = ReviewStorage.get_options_state(context, request_id)

    try:
        # Create DumpArguments with the selected options (blacklist disabled in moderated system)
        dump_args = schemas.DumpArguments(
            url=pending_review.url,
            use_alt_dumper=options_state.alt,
            add_blacklist=False,
            use_privdump=options_state.privdump,
            initial_message_id=pending_review.original_message_id,
        )

        # Start dump process using existing logic
        if not options_state.force:
            console.print("[blue]Checking for existing builds...[/blue]")
            exists, status_message = await utils.check_existing_build(dump_args)
            if exists:
                console.print(
                    f"[yellow]Found existing build: {status_message}[/yellow]"
                )
                # Notify original requester with user-friendly message
                if options_state.privdump:
                    user_message = f"{ACCEPTANCE_TEMPLATE}\nYour request is under further review for private processing."
                else:
                    user_message = f"{ACCEPTANCE_TEMPLATE}\n{status_message}"
                await context.bot.send_message(
                    chat_id=pending_review.original_chat_id,
                    text=user_message,
                    reply_to_message_id=pending_review.original_message_id,
                )

                # Delete the admin confirmation message after processing
                await query.delete_message()

                # Clean up request data and submission message
                await _cleanup_request(context, request_id)
                return

        console.print("[blue]Calling Jenkins to start build...[/blue]")
        response_text = await utils.call_jenkins(dump_args)
        console.print(f"[green]Jenkins response: {response_text}[/green]")

        # Notify original requester with user-friendly message (hide Jenkins technical details)
        if options_state.privdump:
            user_message = f"{ACCEPTANCE_TEMPLATE}\nYour request is under further review for private processing."
        else:
            user_message = f"{ACCEPTANCE_TEMPLATE}\nYour firmware dump is now being processed."
        
        await context.bot.send_message(
            chat_id=pending_review.original_chat_id,
            text=user_message,
            reply_to_message_id=pending_review.original_message_id,
        )

        # Delete the admin confirmation message after successful job start
        await query.delete_message()

    except Exception as e:
        console.print(f"[red]Error processing acceptance: {e}[/red]")
        console.print_exception()
        await query.edit_message_text(
            f"❌ Error processing request {request_id}: {str(e)}"
        )

    # Clean up request data and submission message
    await _cleanup_request(context, request_id)


async def accept_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /accept command with request_id and option flags."""
    chat: Optional[Chat] = update.effective_chat
    message: Optional[Message] = update.effective_message

    if not chat or not message:
        console.print("[red]Chat or message object is None[/red]")
        return

    # Ensure it can only be used in the correct review chat
    if chat.id != settings.REVIEW_CHAT_ID:
        console.print(f"[yellow]/accept used in wrong chat: {chat.id}[/yellow]")
        await context.bot.send_message(
            chat_id=chat.id,
            reply_to_message_id=message.message_id,
            text="This command can only be used in the review chat",
        )
        return

    # Parse arguments: request_id and option flags
    if not context.args:
        await context.bot.send_message(
            chat_id=chat.id,
            reply_to_message_id=message.message_id,
            text="Usage: `/accept [request_id] [options]`\nOptions: a=alt, f=force",
            parse_mode="Markdown",
        )
        return

    request_id = context.args[0]
    options = "".join(context.args[1:]) if len(context.args) > 1 else ""

    # Validate request_id exists in pending reviews
    pending_review = ReviewStorage.get_pending_review(context, request_id)
    if not pending_review:
        await context.bot.send_message(
            chat_id=chat.id,
            reply_to_message_id=message.message_id,
            text=f"❌ Request {request_id} not found or expired",
        )
        return

    # Parse option flags (only alt and force available in moderated system)
    use_alt = "a" in options
    force = "f" in options

    try:
        # Start dump process with options (blacklist and privdump disabled in moderated system)
        dump_args = schemas.DumpArguments(
            url=pending_review.url,
            use_alt_dumper=use_alt,
            add_blacklist=False,
            use_privdump=False,
            initial_message_id=pending_review.original_message_id,
        )

        if not force:
            console.print("[blue]Checking for existing builds...[/blue]")
            exists, status_message = await utils.check_existing_build(dump_args)
            if exists:
                console.print(
                    f"[yellow]Found existing build: {status_message}[/yellow]"
                )
                await context.bot.send_message(
                    chat_id=chat.id,
                    reply_to_message_id=message.message_id,
                    text=f"✅ Request {request_id} processed\n{status_message}",
                )

                # Notify original requester with user-friendly message
                user_message = f"{ACCEPTANCE_TEMPLATE}\n{status_message}"
                await context.bot.send_message(
                    chat_id=pending_review.original_chat_id,
                    text=user_message,
                    reply_to_message_id=pending_review.original_message_id,
                )

                # Clean up request data and submission message
                await _cleanup_request(context, request_id)
                return

        console.print("[blue]Calling Jenkins to start build...[/blue]")
        response_text = await utils.call_jenkins(dump_args)
        console.print(f"[green]Jenkins response: {response_text}[/green]")

        await context.bot.send_message(
            chat_id=chat.id,
            reply_to_message_id=message.message_id,
            text=f"✅ Request {request_id} accepted and {response_text}",
        )

        # Notify original requester with user-friendly message (hide Jenkins technical details)
        user_message = f"{ACCEPTANCE_TEMPLATE}\nYour firmware dump is now being processed."
        await context.bot.send_message(
            chat_id=pending_review.original_chat_id,
            text=user_message,
            reply_to_message_id=pending_review.original_message_id,
        )

    except Exception as e:
        console.print(f"[red]Error processing acceptance: {e}[/red]")
        console.print_exception()
        await context.bot.send_message(
            chat_id=chat.id,
            reply_to_message_id=message.message_id,
            text=f"❌ Error processing request {request_id}: {str(e)}",
        )

    # Clean up request data and submission message
    await _cleanup_request(context, request_id)


async def reject_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /reject command with request_id and reason."""
    chat: Optional[Chat] = update.effective_chat
    message: Optional[Message] = update.effective_message

    if not chat or not message:
        console.print("[red]Chat or message object is None[/red]")
        return

    # Ensure it can only be used in the correct review chat
    if chat.id != settings.REVIEW_CHAT_ID:
        console.print(f"[yellow]/reject used in wrong chat: {chat.id}[/yellow]")
        await context.bot.send_message(
            chat_id=chat.id,
            reply_to_message_id=message.message_id,
            text="This command can only be used in the review chat",
        )
        return

    # Parse arguments: request_id and reason
    if not context.args:
        await context.bot.send_message(
            chat_id=chat.id,
            reply_to_message_id=message.message_id,
            text="Usage: `/reject [request_id] [reason]`",
            parse_mode="Markdown",
        )
        return

    request_id = context.args[0]
    reason = (
        " ".join(context.args[1:]) if len(context.args) > 1 else "No reason provided"
    )

    # Validate request_id exists
    pending_review = ReviewStorage.get_pending_review(context, request_id)
    if not pending_review:
        await context.bot.send_message(
            chat_id=chat.id,
            reply_to_message_id=message.message_id,
            text=f"❌ Request {request_id} not found or expired",
        )
        return

    try:
        # Send rejection notification to original requester
        await context.bot.send_message(
            chat_id=pending_review.original_chat_id,
            text=REJECTION_TEMPLATE.format(reason=reason),
            reply_to_message_id=pending_review.original_message_id,
        )

        # Confirm rejection in review chat
        await context.bot.send_message(
            chat_id=chat.id,
            reply_to_message_id=message.message_id,
            text=f"❌ Request {request_id} rejected\nReason: {reason}",
        )

        # Log rejection with reason
        console.print(f"[yellow]Request {request_id} rejected: {reason}[/yellow]")

    except Exception as e:
        console.print(f"[red]Error processing rejection: {e}[/red]")
        console.print_exception()
        await context.bot.send_message(
            chat_id=chat.id,
            reply_to_message_id=message.message_id,
            text=f"❌ Error processing rejection for request {request_id}: {str(e)}",
        )

    # Clean up request data and submission message
    await _cleanup_request(context, request_id)


async def _handle_cancel_callback(
    query: Any, context: ContextTypes.DEFAULT_TYPE, callback_data: str
) -> None:
    """Handle cancel request callback."""
    request_id = callback_data.replace(CALLBACK_CANCEL_REQUEST, "")
    
    if not query.message:
        return
        
    storage = ReviewStorage(context.bot_data)
    pending = storage.get_pending_review(request_id)
    
    if not pending:
        await query.edit_message_text(
            text="❌ Request not found or already processed",
            reply_markup=None
        )
        return
    
    try:
        # Send cancellation message in review chat
        await context.bot.send_message(
            chat_id=pending.review_chat_id,
            text=f"🚫 Request {request_id} cancelled by user @{pending.requester_username}"
        )
        
        # Update submission confirmation message to show cancelled
        await query.edit_message_text(
            text="🚫 Request cancelled",
            reply_markup=None
        )
        
        # Clean up request data
        await _cleanup_request(context, request_id)
        
        console.print(f"[yellow]Request {request_id} cancelled by user[/yellow]")
        
    except Exception as e:
        console.print(f"[red]Error cancelling request: {e}[/red]")
        console.print_exception()
        await query.edit_message_text(
            text="❌ Error cancelling request",
            reply_markup=None
        )
