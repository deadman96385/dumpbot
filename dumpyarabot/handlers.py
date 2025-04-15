import logging
import uuid
import re # Import re for URL extraction
from typing import Optional, Tuple, Dict, Any # Added Dict, Any

from pydantic import ValidationError
# Make sure User is imported if type hinting is desired
from telegram import Chat, InlineKeyboardButton, InlineKeyboardMarkup, Message, Update, User
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from dumpyarabot import schemas, utils
from dumpyarabot.config import settings

# Use the logger defined in __init__
logger = logging.getLogger("rich")

# --- Shared Constants ---
# (Keep existing constants)
CALLBACK_PREFIX_ACCEPT_START = "a_"
CALLBACK_PREFIX_REJECT_START = "r_"
CALLBACK_PREFIX_TOGGLE_OPT = "t_"
CALLBACK_PREFIX_SUBMIT_ACCEPT = "s_"
CALLBACK_PREFIX_CANCEL_ACCEPT = "c_"

OPT_ALT = 'a'
OPT_FORCE = 'f'
OPT_BLACKLIST = 'b'
OPT_PRIVDUMP = 'p'
OPTION_CHARS = [OPT_ALT, OPT_FORCE, OPT_BLACKLIST, OPT_PRIVDUMP]
OPTION_NAMES = {
    OPT_ALT: "Alt Dumper",
    OPT_FORCE: "Force",
    OPT_BLACKLIST: "Blacklist",
    OPT_PRIVDUMP: "Privdump",
}


# --- Helper Functions ---

def get_review_storage(context: ContextTypes.DEFAULT_TYPE) -> Dict[str, Dict[str, Any]]:
    """Gets the pending_reviews storage, initializing if needed."""
    return context.bot_data.setdefault("pending_reviews", {})

def get_options_storage(context: ContextTypes.DEFAULT_TYPE) -> Dict[str, Dict[str, bool]]:
    """Gets the review_options storage for acceptance submenu state, initializing if needed."""
    return context.bot_data.setdefault("review_options", {})

def cleanup_review_state(context: ContextTypes.DEFAULT_TYPE, request_id: str):
    """Removes data for a completed/cancelled review."""
    pending_reviews = get_review_storage(context)
    review_options = get_options_storage(context)
    if request_id in pending_reviews:
        del pending_reviews[request_id]
        logger.debug(f"Cleaned up pending_reviews for {request_id}")
    if request_id in review_options:
        del review_options[request_id]
        logger.debug(f"Cleaned up review_options for {request_id}")

# (build_accept_submenu remains the same)
def build_accept_submenu(request_id: str, options_state: schemas.AcceptOptionsState) -> InlineKeyboardMarkup:
    """Builds the dynamic inline keyboard for acceptance options."""
    buttons = []
    row1 = []
    row2 = []

    # Option toggles
    for opt_char in OPTION_CHARS:
        # Map option char to the field name in AcceptOptionsState (e.g., 'a' -> 'alt')
        state_field_name = ""
        if opt_char == OPT_ALT: state_field_name = "alt"
        elif opt_char == OPT_FORCE: state_field_name = "force"
        elif opt_char == OPT_BLACKLIST: state_field_name = "blacklist"
        elif opt_char == OPT_PRIVDUMP: state_field_name = "privdump"

        is_selected = getattr(options_state, state_field_name, False) if state_field_name else False
        text = f"{'✅' if is_selected else ''} {OPTION_NAMES[opt_char]}"
        callback_data = f"{CALLBACK_PREFIX_TOGGLE_OPT}{request_id}_{opt_char}"
        button = InlineKeyboardButton(text, callback_data=callback_data)
        if opt_char in [OPT_ALT, OPT_FORCE]:
            row1.append(button)
        else:
            row2.append(button)

    buttons.append(row1)
    if row2: # Only add second row if needed (blacklist/privdump)
        buttons.append(row2)

    # Submit and Cancel buttons
    buttons.append([
        InlineKeyboardButton("Submit Acceptance", callback_data=f"{CALLBACK_PREFIX_SUBMIT_ACCEPT}{request_id}"),
        InlineKeyboardButton("Cancel", callback_data=f"{CALLBACK_PREFIX_CANCEL_ACCEPT}{request_id}")
    ])

    return InlineKeyboardMarkup(buttons)

# (_start_dump_process remains the same)
async def _start_dump_process(
    context: ContextTypes.DEFAULT_TYPE,
    review_data_dict: Dict[str, Any], # Pass the dict directly
    dump_args: schemas.DumpArguments,
    force_check: bool = False # If True, skip check_existing_build
) -> str:
    """Handles the logic to check existing and call Jenkins. Returns final status string."""
    final_status_line = ""
    request_id = review_data_dict.get("request_id", "unknown") # Get ID for logging/cleanup

    # Check for existing builds unless force is specified
    if not force_check:
        logger.info(f"Checking existing builds for request {request_id[:8]}")
        exists, check_message = await utils.check_existing_build(dump_args)
        if exists:
            logger.info(f"Found existing build for accepted request {request_id[:8]}: {check_message}")
            final_status_line = f"**Status:** {check_message}"
            try: # Notify requester
                await context.bot.send_message(review_data_dict.get("original_chat_id"), reply_to_message_id=review_data_dict.get("original_message_id"),
                                                text=f"Request accepted, but existing build found: {check_message}", parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
            except Exception as e: logger.error(f"Failed notifying requester of existing build for {request_id[:8]}: {e}")
            cleanup_review_state(context, request_id)
            return final_status_line # Return early

    # Call Jenkins
    try:
        logger.info(f"Calling Jenkins for request {request_id[:8]}")
        jenkins_response = await utils.call_jenkins(dump_args)
        logger.info(f"Jenkins response for accepted request {request_id[:8]}: {jenkins_response}")
        final_status_line = f"**Status:** {jenkins_response}"
        try: # Notify requester
             # Display URL using backticks in notification
             await context.bot.send_message(review_data_dict.get("original_chat_id"), reply_to_message_id=review_data_dict.get("original_message_id"),
                                            text=f"Your request for `{dump_args.url}` was accepted and the dump process has started.", parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
        except Exception as e: logger.error(f"Failed notifying requester of acceptance for {request_id[:8]}: {e}")
    except Exception as e:
         logger.error(f"Error calling Jenkins for accepted request {request_id[:8]}: {e}", exc_info=False)
         final_status_line = "**Status:** Failed to start dump: An internal error occurred."
         try: # Notify requester
            await context.bot.send_message(review_data_dict.get("original_chat_id"), reply_to_message_id=review_data_dict.get("original_message_id"),
                                           text=f"Request accepted, but failed to start dump.", parse_mode=ParseMode.MARKDOWN)
         except Exception as e: logger.error(f"Failed notifying requester of start failure for {request_id[:8]}: {e}")

    cleanup_review_state(context, request_id)
    return final_status_line

# --- Moderated Flow Handlers ---

# (handle_request_message remains the same)
async def handle_request_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles messages starting with #request in the REQUEST_CHAT_ID, extracting the first URL."""
    message: Optional[Message] = update.effective_message
    user: Optional[User] = update.effective_user
    chat: Optional[Chat] = update.effective_chat

    if not message or not user or not chat or not message.text:
        logger.warning("handle_request_message: Missing message, user, chat or text.")
        return

    if chat.id != settings.REQUEST_CHAT_ID: return # Should be filtered

    message_text_lower = message.text.lower()
    # Check only for the prefix, URL can be anywhere after
    if not message_text_lower.startswith("#request"):
        return # Ignore non-matching messages silently

    # Find the first http or https URL in the message text
    url_match = re.search(r"https?://\S+", message.text, re.IGNORECASE)

    if not url_match:
        logger.info(f"No URL found in #request message: {message.text}")
        await message.reply_text("No valid URL found in your `#request` message.", parse_mode=ParseMode.MARKDOWN)
        return

    url_str = url_match.group(0) # Extract the matched URL string

    try:
        # Validate the extracted URL using Pydantic
        url_obj = schemas.AnyHttpUrl(url_str) # url_obj is the validated Pydantic model instance
    except ValidationError:
        logger.info(f"Invalid URL extracted: {url_str} from message: {message.text}")
        await message.reply_text(f"The extracted URL is invalid: `{url_str}`", parse_mode=ParseMode.MARKDOWN)
        return

    request_id = str(uuid.uuid4())
    requester_name = user.username or user.full_name
    pending_reviews = get_review_storage(context)

    # Use the validated URL string for duplicate check and storage
    validated_url_string = url_obj.unicode_string()

    # Check for duplicate pending URL using the validated string
    for review_dict in pending_reviews.values():
        if review_dict.get("url") == validated_url_string:
             await message.reply_text(f"A review request for this URL is already pending.", disable_web_page_preview=True)
             return

    pending_review = schemas.PendingReview(
        request_id=request_id,
        original_chat_id=chat.id,
        original_message_id=message.message_id,
        requester_id=user.id,
        requester_username=requester_name,
        url=url_obj, # Store the validated Pydantic object initially
        review_chat_id=settings.REVIEW_CHAT_ID,
        review_message_id=-1 # Placeholder
    )

    logger.info(f"Received valid request {request_id[:8]} from {requester_name} for URL: {validated_url_string}")

    keyboard = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("Accept", callback_data=f"{CALLBACK_PREFIX_ACCEPT_START}{request_id}"),
            InlineKeyboardButton("Reject", callback_data=f"{CALLBACK_PREFIX_REJECT_START}{request_id}"),
        ]]
    )

    # Use the validated URL string in the review message for display
    # Display the SHORT ID (first 8 chars) here
    review_text = (
        f"**New Dump Request** `({request_id[:8]})`\n\n"
        f"**Requester:** {requester_name} (`{user.id}`)\n"
        # Format URL as clickable link where the displayed text IS the URL
        f"**URL:** [{validated_url_string}]({validated_url_string})\n\n"
        f"Please review and choose an action."
    )

    try:
        review_message = await context.bot.send_message(
            chat_id=settings.REVIEW_CHAT_ID, text=review_text, reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True
        )
        pending_review.review_message_id = review_message.message_id

        # Store the dictionary representation of the Pydantic model
        pending_review_dict = pending_review.model_dump()
        # Ensure the 'url' key holds the validated string representation
        pending_review_dict["url"] = validated_url_string
        pending_reviews[request_id] = pending_review_dict

        await message.reply_text("Your dump request has been submitted for review.")
        logger.info(f"Successfully sent request {request_id[:8]} to review chat.")
    except Exception as e:
        logger.error(f"Failed to send request {request_id[:8]} to review chat: {e}", exc_info=False)
        await message.reply_text("Sorry, failed to submit your request for review.")
        if request_id in pending_reviews: del pending_reviews[request_id] # Clean up if sending failed
# (handle_callback_query remains the same)
async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles button clicks: Accept (starts submenu), Reject (gives info), Option Toggles, Submit, Cancel."""
    query = update.callback_query
    if not query or not query.data or not query.message:
        logger.warning("handle_callback_query: Missing query, data or message.")
        return

    try:
        await query.answer() # Acknowledge button press
    except BadRequest: # Ignore if query is too old
        logger.warning(f"Could not answer old callback query: {query.id}")
        # Attempt to proceed if state allows, otherwise it will fail gracefully below

    callback_data = query.data
    reviewer = query.from_user
    reviewer_name = reviewer.username or reviewer.full_name
    pending_reviews = get_review_storage(context)
    review_options = get_options_storage(context) # For accept submenu state

    request_id = "" # Extracted based on prefix
    processed = False # Flag to track if callback was handled

    # --- Reject Flow (Button Click) ---
    if callback_data.startswith(CALLBACK_PREFIX_REJECT_START):
        processed = True
        request_id = callback_data[len(CALLBACK_PREFIX_REJECT_START):]
        if request_id not in pending_reviews:
            try: await query.edit_message_text("This review request seems outdated or handled.")
            except Exception as e: logger.warning(f"Failed editing outdated reject message {query.message.message_id}: {e}")
            return

        logger.info(f"Reviewer {reviewer_name} clicked Reject button for request {request_id[:8]}")
        final_text = (
            f"{query.message.text}\n\n"
            f"**Action:** Marked for Rejection by {reviewer_name}.\n"
            # Clarify to use the short ID displayed
            f"To finalize, reply to this message with:\n`/reject YOUR REASON HERE`" # Updated instruction
        )
        try:
            await query.edit_message_text(text=final_text, parse_mode=ParseMode.MARKDOWN, reply_markup=None)
        except Exception as e:
            logger.warning(f"Failed editing reject instruction message {query.message.message_id}: {e}")

    # --- Acceptance Flow: Start Submenu ---
    elif callback_data.startswith(CALLBACK_PREFIX_ACCEPT_START):
        processed = True
        request_id = callback_data[len(CALLBACK_PREFIX_ACCEPT_START):]
        if request_id not in pending_reviews:
            try: await query.edit_message_text("This review request seems outdated or handled.")
            except Exception as e: logger.warning(f"Failed editing outdated accept message {query.message.message_id}: {e}")
            return

        logger.info(f"Reviewer {reviewer_name} clicked Accept button for request {request_id[:8]}, showing options...")
        current_options = schemas.AcceptOptionsState() # Fresh state
        review_options[request_id] = current_options.model_dump()

        keyboard = build_accept_submenu(request_id, current_options) # Use helper

        text_before_action = query.message.text.split('\n\n**Action:**')[0] if '\n\n**Action:**' in query.message.text else query.message.text
        text = (
            f"{text_before_action}\n\n"
            f"**Action:** Acceptance initiated by {reviewer_name}.\n"
            # Update instruction
            f"Select options below or reply with `/accept [options]`"
        )
        try:
            await query.edit_message_text(text=text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.warning(f"Failed editing accept options message {query.message.message_id}: {e}")

    # --- Acceptance Flow: Toggle Option ---
    elif callback_data.startswith(CALLBACK_PREFIX_TOGGLE_OPT):
        processed = True
        parts = callback_data.split("_")
        if len(parts) != 3: logger.error(f"Invalid toggle option cb: {callback_data}"); return
        request_id, opt_char = parts[1], parts[2]

        if request_id not in pending_reviews or request_id not in review_options:
            logger.warning(f"State missing for toggle option callback: {callback_data}")
            return # Don't edit message if state is gone
        if opt_char not in OPTION_CHARS: logger.error(f"Invalid option char: {opt_char}"); return

        state_field_name = {"a": "alt", "f": "force", "b": "blacklist", "p": "privdump"}.get(opt_char)
        if state_field_name:
            current_options_dict = review_options[request_id]
            current_options_dict[state_field_name] = not current_options_dict.get(state_field_name, False)
            review_options[request_id] = current_options_dict # Update storage
            current_options_state = schemas.AcceptOptionsState(**current_options_dict)
            logger.debug(f"Toggled option '{opt_char}' for {request_id[:8]}. New state: {current_options_dict}")

            keyboard = build_accept_submenu(request_id, current_options_state) # Use helper

            try:
                await query.edit_message_reply_markup(reply_markup=keyboard)
            except Exception as e:
                 logger.warning(f"Failed editing reply markup for toggle {query.message.message_id}: {e}")
        else: logger.error(f"Could not map opt_char '{opt_char}' to state field.")


    # --- Acceptance Flow: Submit ---
    elif callback_data.startswith(CALLBACK_PREFIX_SUBMIT_ACCEPT):
        processed = True
        request_id = callback_data[len(CALLBACK_PREFIX_SUBMIT_ACCEPT):]
        if request_id not in pending_reviews or request_id not in review_options:
            try: await query.edit_message_text("This review request seems outdated or options state is missing.")
            except Exception as e: logger.warning(f"Failed editing outdated submit message {query.message.message_id}: {e}")
            return

        try:
            review_data_dict = pending_reviews[request_id]
            review_data_url_str = review_data_dict.get("url")
            if not review_data_url_str: raise ValueError("Missing URL")
            review_data_url = schemas.AnyHttpUrl(review_data_url_str)
            final_options_dict = review_options[request_id]
            final_options_state = schemas.AcceptOptionsState(**final_options_dict)
        except Exception as e:
             logger.error(f"Failed loading state during submit for {request_id[:8]}: {e}")
             try: await query.edit_message_text("Error processing request state.")
             except Exception as e_edit: logger.warning(f"Failed editing error state message {query.message.message_id}: {e_edit}")
             return

        logger.info(f"Reviewer {reviewer_name} submitted acceptance via button for request {request_id[:8]} with options: {final_options_dict}")

        text_before_options = query.message.text.split("Select options below or reply")[0] # Adjust split text
        status_message_base = (
             f"{text_before_options}"
             f"**Action:** Accepted via button by {reviewer_name}.\n"
             f"Options: {final_options_state.model_dump_json()}\n"
        )
        try:
            await query.edit_message_text(
                f"{status_message_base}Processing acceptance...",
                reply_markup=None, parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
             logger.warning(f"Failed editing submit processing message {query.message.message_id}: {e}")

        # Prepare args for Jenkins
        dump_args = schemas.DumpArguments(
            url=review_data_url,
            use_alt_dumper=final_options_state.alt,
            add_blacklist=final_options_state.blacklist,
            use_privdump=final_options_state.privdump,
            initial_message_id=review_data_dict.get("original_message_id"),
        )

        # Call helper to start dump (includes check_existing, call_jenkins, notify, cleanup)
        final_status_line = await _start_dump_process(
            context=context, review_data_dict=review_data_dict, dump_args=dump_args,
            force_check=final_options_state.force
        )

        # Update review message (use context.bot for reliability)
        final_text = f"{status_message_base}{final_status_line}"
        try:
            await context.bot.edit_message_text(
                chat_id=review_data_dict.get("review_chat_id"), message_id=review_data_dict.get("review_message_id"),
                text=final_text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True
            )
        except Exception as e:
            logger.warning(f"Failed to edit final submit message {review_data_dict.get('review_message_id')}: {e}")


    # --- Cancel Acceptance Process (Back to Accept/Reject) ---
    elif callback_data.startswith(CALLBACK_PREFIX_CANCEL_ACCEPT):
        processed = True
        request_id = callback_data[len(CALLBACK_PREFIX_CANCEL_ACCEPT):]
        if request_id not in pending_reviews:
            try: await query.edit_message_text("This review request seems outdated or handled.")
            except Exception as e: logger.warning(f"Failed editing outdated cancel message {query.message.message_id}: {e}")
            if request_id in review_options: del review_options[request_id] # Cleanup options just in case
            return

        # No need to load full data if just canceling
        logger.info(f"Reviewer {reviewer_name} cancelled acceptance process for request {request_id[:8]}")
        if request_id in review_options: del review_options[request_id] # Clean up options state

        keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("Accept", callback_data=f"{CALLBACK_PREFIX_ACCEPT_START}{request_id}"),
                InlineKeyboardButton("Reject", callback_data=f"{CALLBACK_PREFIX_REJECT_START}{request_id}"),
        ]])
        text_before_action = query.message.text.split('\n\n**Action:**')[0] if '\n\n**Action:**' in query.message.text else query.message.text
        original_review_text = (
             f"{text_before_action}\n\n" # Restore original text
             f"Acceptance cancelled by {reviewer_name}. Please review again."
        )
        try:
            await query.edit_message_text(text=original_review_text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.warning(f"Failed editing cancel accept message {query.message.message_id}: {e}")


    if not processed:
        logger.warning(f"Received unknown callback query data: {callback_data}")


# --- Manual Command Handlers (Review Chat Only) ---
async def reject_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /reject <reason> command when replying to a review message."""
    chat: Optional[Chat] = update.effective_chat
    message: Optional[Message] = update.effective_message
    user: Optional[User] = update.effective_user

    if not chat or not message or not user: return
    if chat.id != settings.REVIEW_CHAT_ID: return

    if not message.reply_to_message:
        await message.reply_text("Please use this command by replying to the review message you want to reject.")
        return

    if not context.args:
        await message.reply_text(
             "You must provide a reason when rejecting.\n"
             "Usage (replying to review message): `/reject YOUR REASON HERE`",
             parse_mode=ParseMode.MARKDOWN
        )
        return

    target_message_id = message.reply_to_message.message_id
    reason = " ".join(context.args)
    pending_reviews = get_review_storage(context)

    # Find the request_id based on the replied-to message ID
    request_id: Optional[str] = None
    review_data_dict: Optional[Dict[str, Any]] = None
    for r_id, r_dict in pending_reviews.items():
        if r_dict.get("review_message_id") == target_message_id:
            request_id = r_id
            review_data_dict = r_dict
            break

    if not request_id or not review_data_dict:
        await message.reply_text("The message you replied to is not a pending review request or it has already been handled.")
        return

    try:
        # Validate stored URL before proceeding
        stored_url_str = review_data_dict.get("url")
        if not stored_url_str: raise ValueError("Missing URL")
        schemas.AnyHttpUrl(stored_url_str)
    except Exception as e:
        logger.error(f"Could not load/validate review data for {request_id} during /reject: {e}")
        await message.reply_text("Error loading review data for that request.")
        cleanup_review_state(context, request_id)
        return

    reviewer_name = user.username or user.full_name
    logger.info(f"Processing /reject command for {request_id[:8]} by {reviewer_name}. Reason: {reason}")

    # Notify original requester
    try:
        await context.bot.send_message(
            chat_id=review_data_dict.get("original_chat_id"),
            reply_to_message_id=review_data_dict.get("original_message_id"),
            text=f"Your request for `{stored_url_str}` was rejected by {reviewer_name}.\n**Reason:** {reason}",
            parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"Failed notifying requester of rejection for {request_id[:8]}: {e}")
        await message.reply_text("Warning: Failed to notify original requester.") # Reply to the command message

    # Update the review message (the one replied to)
    try:
        # Fetch the replied-to message text
        original_msg = message.reply_to_message
        original_text_base = original_msg.text.split('\n\n**Action:**')[0] if original_msg and original_msg.text else f"**Review for Request ID:** `{request_id[:8]}`"

        final_text = (
            f"{original_text_base}\n\n"
            f"**Action:** Rejected via command by {reviewer_name}.\n"
            f"**Reason:** {reason}\n\n"
            f"Original requester notified."
        )
        await context.bot.edit_message_text(
            chat_id=review_data_dict.get("review_chat_id"), message_id=target_message_id, # Edit the replied-to message
            text=final_text, parse_mode=ParseMode.MARKDOWN, reply_markup=None
        )
    except Exception as e:
        logger.warning(f"Failed editing final rejection message {target_message_id}: {e}")
        await message.reply_text(f"Rejected request {request_id[:8]}. Reason: {reason}. (Could not update review message).")

    # Clean up state
    cleanup_review_state(context, request_id)


async def accept_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /accept [options] command when replying to a review message."""
    chat: Optional[Chat] = update.effective_chat
    message: Optional[Message] = update.effective_message
    user: Optional[User] = update.effective_user

    if not chat or not message or not user: return
    if chat.id != settings.REVIEW_CHAT_ID: return

    if not message.reply_to_message:
        await message.reply_text("Please use this command by replying to the review message you want to accept.")
        return

    target_message_id = message.reply_to_message.message_id
    options_str = "".join(context.args) # Options are the arguments, if any
    pending_reviews = get_review_storage(context)

    # Find the request_id based on the replied-to message ID
    request_id: Optional[str] = None
    review_data_dict: Optional[Dict[str, Any]] = None
    for r_id, r_dict in pending_reviews.items():
        if r_dict.get("review_message_id") == target_message_id:
            request_id = r_id
            review_data_dict = r_dict
            break

    if not request_id or not review_data_dict:
        await message.reply_text("The message you replied to is not a pending review request or it has already been handled.")
        return

    try:
        # Validate stored URL
        stored_url_str = review_data_dict.get("url")
        if not stored_url_str: raise ValueError("Missing URL")
        review_data_url = schemas.AnyHttpUrl(stored_url_str)
    except Exception as e:
        logger.error(f"Could not load/validate review data for {request_id} during /accept: {e}")
        await message.reply_text("Error loading review data for that request.")
        cleanup_review_state(context, request_id)
        return

    accepter_name = user.username or user.full_name
    use_alt, force, add_blacklist, use_priv = utils.parse_options(options_str)

    logger.info(f"Processing /accept command for {request_id[:8]} by {accepter_name}. Options: {options_str}")

    # Update review message
    status_message_base = ""
    review_message_id = target_message_id # Use the ID we found
    review_chat_id = review_data_dict.get("review_chat_id")
    try:
        original_msg = message.reply_to_message # We have the replied-to message
        status_message_base = original_msg.text.split('\n\n**Action:**')[0] if original_msg and original_msg.text else f"**Review for Request ID:** `{request_id[:8]}`"
        await context.bot.edit_message_text(
            chat_id=review_chat_id, message_id=review_message_id,
            text=f"{status_message_base}\n\n**Action:** Accepted via command by {accepter_name}.\nOptions: `{options_str or 'None'}`\nProcessing...",
            parse_mode=ParseMode.MARKDOWN, reply_markup=None
        )
    except Exception as e:
        logger.warning(f"Could not edit review message {review_message_id} during /accept processing: {e}")
        status_message_base = f"**Review for Request ID:** `{request_id[:8]}`" # Use fallback

    # Prepare args for Jenkins
    dump_args = schemas.DumpArguments(
        url=review_data_url, use_alt_dumper=use_alt, add_blacklist=add_blacklist,
        use_privdump=use_priv, initial_message_id=review_data_dict.get("original_message_id")
    )

    # Call helper to start dump process (includes check_existing, call_jenkins, notify, cleanup)
    final_status_line = await _start_dump_process(
        context=context, review_data_dict=review_data_dict, dump_args=dump_args,
        force_check=force
    )

    # Update review message
    final_text = (
        f"{status_message_base}\n\n"
        f"**Action:** Accepted via command by {accepter_name}.\n"
        f"Options: `{options_str or 'None'}`\n{final_status_line}"
    )
    try:
        await context.bot.edit_message_text(
            chat_id=review_chat_id, message_id=review_message_id,
            text=final_text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True
        )
    except Exception as e:
        logger.warning(f"Failed editing final accept message {review_message_id}: {e}")

# --- Original /dump Command Handler (Restricted to Review Chat) ---
async def dump(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for the /dump command (only in Review Chat)."""
    chat: Optional[Chat] = update.effective_chat
    message: Optional[Message] = update.effective_message

    if not chat or not message: logger.warning("dump: Chat or message object is None"); return
    if chat.id != settings.REVIEW_CHAT_ID: return # Ignore silently

    if not context.args:
        usage = "Direct Dump: `/dump [URL] [options (a,f,b,p)]`"
        await message.reply_text(usage, parse_mode=ParseMode.MARKDOWN)
        return

    url_str = context.args[0]
    options_str = "".join("".join(context.args[1:]))

    try:
        url_obj = schemas.AnyHttpUrl(url_str)
    except ValidationError:
        await message.reply_text("Invalid URL provided.")
        return

    use_alt_dumper, force, add_blacklist, use_privdump = utils.parse_options(options_str)
    logger.info(f"Direct /dump request in review chat for {url_str} with options: {options_str}")

    original_msg_id_for_jenkins = message.message_id
    reply_to_id = message.message_id
    status_message: Optional[Message] = None

    try:
        if use_privdump:
            logger.info(f"Privdump requested - deleting command message {message.message_id}")
            original_msg_id_for_jenkins = None
            reply_to_id = None
            try: await context.bot.delete_message(chat.id, message.message_id)
            except Exception as e: logger.error(f"Failed to delete privdump message: {e}")

        dump_args = schemas.DumpArguments(
            url=url_obj, use_alt_dumper=use_alt_dumper, add_blacklist=add_blacklist,
            use_privdump=use_privdump, initial_message_id=original_msg_id_for_jenkins
        )

        # Send initial status message
        status_message = await context.bot.send_message(chat.id, "Processing dump request...", reply_to_message_id=reply_to_id)

        response_text = ""
        if not force:
            await status_message.edit_text("Checking for existing builds...")
            exists, check_message = await utils.check_existing_build(dump_args)
            if exists:
                response_text = check_message # Use existing status
            else:
                 await status_message.edit_text("No existing build found. Starting dump...")

        if not response_text: # If no existing build or forced
            response_text = await utils.call_jenkins(dump_args)

        # Final update
        await status_message.edit_text(response_text)

    except Exception as e:
        logger.error("Unexpected error during direct /dump processing:", exc_info=False)
        error_text = "An error occurred processing the dump request."
        if status_message:
            try: await status_message.edit_text(error_text)
            except Exception as edit_err: logger.error(f"Failed editing status msg with error: {edit_err}")
        else: # If initial status send failed
             try: await context.bot.send_message(chat.id, error_text, reply_to_message_id=reply_to_id)
             except Exception as send_err: logger.error(f"Failed sending fallback error msg: {send_err}")


# --- /cancel Command Handler (Restricted to Review Chat Admins) ---
async def cancel_dump(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for the /cancel command (Review Chat Admins only)."""
    chat: Optional[Chat] = update.effective_chat
    message: Optional[Message] = update.effective_message
    user: Optional[User] = update.effective_user

    if not chat or not message or not user: return
    if chat.id != settings.REVIEW_CHAT_ID: return

    is_admin = False
    try: # Basic admin check
        admins = await chat.get_administrators()
        if user.id in [admin.user.id for admin in admins]: is_admin = True
    except Exception as e:
        logger.error(f"Failed getting admins for /cancel: {e}")
        await message.reply_text("Could not verify admin permissions.")
        return

    if not is_admin:
        await message.reply_text("You need admin rights for this command.")
        return

    if not context.args:
        usage = "Usage: `/cancel [job_id] [p]` (p for privdump job)"
        await message.reply_text(usage, parse_mode=ParseMode.MARKDOWN)
        return

    job_id_str = context.args[0]
    use_privdump = 'p' in "".join(context.args[1:]) if len(context.args) > 1 else False

    logger.info(f"Admin {user.username} requesting cancel for {job_id_str} (privdump: {use_privdump})")
    response_message = await utils.cancel_jenkins_job(job_id_str, use_privdump)
    await message.reply_text(response_message)


# --- /restart Command Handler (Review Chat Admins only) ---
async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat: Optional[Chat] = update.effective_chat
    message: Optional[Message] = update.effective_message
    user: Optional[User] = update.effective_user

    if not chat or not message or not user: return
    if chat.id != settings.REVIEW_CHAT_ID: return

    is_admin = False
    try: # Basic admin check
        admins = await chat.get_administrators()
        if user.id in [admin.user.id for admin in admins]: is_admin = True
    except Exception as e:
        logger.error(f"Failed getting admins for /restart: {e}")
        await message.reply_text("Could not verify admin permissions.")
        return

    if not is_admin:
        await message.reply_text("You need admin rights for this command.")
        return

    logger.info(f"Restart requested by admin {user.username}")
    try: await message.reply_text("Restarting bot...")
    except Exception as e: logger.error(f"Failed sending restart msg: {e}")

    context.bot_data["restart"] = True
    context.application.stop() # Graceful stop