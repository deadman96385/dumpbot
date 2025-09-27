"""
Unit tests for dumpyarabot moderated handlers.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from dumpyarabot.moderated_handlers import (
    handle_request_message,
    handle_callback_query,
    accept_command,
    reject_command,
    _truncate_message,
    _cleanup_request
)


@pytest.mark.unit
class TestRequestMessageHandler:
    """Test cases for the handle_request_message function."""

    @pytest.mark.asyncio
    async def test_handle_request_message_valid(self, mock_telegram_update, mock_telegram_bot):
        """Test handling valid #request message."""
        context = MagicMock()
        context.bot = mock_telegram_bot

        # Setup message content
        mock_telegram_update.effective_message.text = "#request https://example.com/firmware.zip please dump this"
        mock_telegram_update.effective_user.username = "testuser"
        mock_telegram_update.effective_user.id = 12345

        with patch('dumpyarabot.moderated_handlers.settings') as mock_settings, \
             patch('dumpyarabot.moderated_handlers.message_queue') as mock_queue, \
             patch('dumpyarabot.moderated_handlers.url_utils.validate_and_normalize_url') as mock_validate, \
             patch('dumpyarabot.moderated_handlers.utils.generate_request_id') as mock_gen_id, \
             patch('dumpyarabot.moderated_handlers.ReviewStorage') as mock_storage:

            # Setup mocks
            mock_settings.REQUEST_CHAT_ID = mock_telegram_update.effective_chat.id
            mock_settings.REVIEW_CHAT_ID = 98765
            mock_settings.DEFAULT_PARSE_MODE = "Markdown"
            mock_validate.return_value = (True, "https://example.com/firmware.zip", None)
            mock_gen_id.return_value = "abc12345"
            mock_queue.send_immediate_message = AsyncMock(return_value=MagicMock(message_id=123))
            mock_queue.send_reply = AsyncMock()
            mock_queue.send_error = AsyncMock()
            mock_queue.publish_and_return_placeholder = AsyncMock(return_value=MagicMock(message_id=456))
            mock_storage.store_pending_review = MagicMock()

            await handle_request_message(mock_telegram_update, context)

            # Verify URL validation was called
            mock_validate.assert_called_once_with("https://example.com/firmware.zip")

            # Verify review message was sent (called twice: review + submission confirmation)
            assert mock_queue.publish_and_return_placeholder.call_count == 2

            # Check the review message (first call)
            review_call = mock_queue.publish_and_return_placeholder.call_args_list[0]
            review_message = review_call[0][0]
            assert review_message.chat_id == 98765
            assert "testuser" in review_message.text
            assert "https://example.com/firmware.zip" in review_message.text
            assert "abc12345" in review_message.text

            # Check the submission confirmation (second call)
            submission_call = mock_queue.publish_and_return_placeholder.call_args_list[1]
            submission_message = submission_call[0][0]
            assert "Request submitted for review" in submission_message.text

            # Verify request was stored
            mock_storage.store_pending_review.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_request_message_wrong_chat(self, mock_telegram_update, mock_telegram_bot):
        """Test #request message in wrong chat is ignored."""
        context = MagicMock()
        context.bot = mock_telegram_bot

        mock_telegram_update.effective_message.text = "#request https://example.com/firmware.zip"

        with patch('dumpyarabot.moderated_handlers.settings') as mock_settings, \
             patch('dumpyarabot.moderated_handlers.message_queue') as mock_queue:

            mock_settings.REQUEST_CHAT_ID = 99999  # Different from update's chat ID
            mock_queue.send_immediate_message = AsyncMock()

            await handle_request_message(mock_telegram_update, context)

            # Should not send any messages
            mock_queue.send_immediate_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_request_message_invalid_url(self, mock_telegram_update, mock_telegram_bot):
        """Test #request message with invalid URL."""
        context = MagicMock()
        context.bot = mock_telegram_bot

        mock_telegram_update.effective_message.text = "#request https://invalid-url"

        with patch('dumpyarabot.moderated_handlers.settings') as mock_settings, \
             patch('dumpyarabot.moderated_handlers.message_queue') as mock_queue, \
             patch('dumpyarabot.moderated_handlers.url_utils.validate_and_normalize_url') as mock_validate:

            mock_settings.REQUEST_CHAT_ID = mock_telegram_update.effective_chat.id
            mock_settings.DEFAULT_PARSE_MODE = "Markdown"
            mock_validate.return_value = (False, None, "Invalid URL format")
            mock_queue.send_reply = AsyncMock()
            mock_queue.send_error = AsyncMock()
            mock_queue.publish_and_return_placeholder = AsyncMock()

            await handle_request_message(mock_telegram_update, context)

            # Should send error message
            mock_queue.send_error.assert_called_once()
            call_args = mock_queue.send_error.call_args
            assert "error occurred" in call_args[1]["text"].lower() or "invalid" in call_args[1]["text"].lower()

    @pytest.mark.asyncio
    async def test_handle_request_message_no_pattern(self, mock_telegram_update, mock_telegram_bot):
        """Test message without #request pattern is ignored."""
        context = MagicMock()
        context.bot = mock_telegram_bot

        mock_telegram_update.effective_message.text = "Just a regular message https://example.com/firmware.zip"

        with patch('dumpyarabot.moderated_handlers.settings') as mock_settings, \
             patch('dumpyarabot.moderated_handlers.message_queue') as mock_queue:

            mock_settings.REQUEST_CHAT_ID = mock_telegram_update.effective_chat.id
            mock_queue.send_immediate_message = AsyncMock()

            await handle_request_message(mock_telegram_update, context)

            # Should not send any messages
            mock_queue.send_immediate_message.assert_not_called()


@pytest.mark.unit
class TestCallbackQueryHandler:
    """Test cases for the handle_callback_query function."""

    @pytest.mark.asyncio
    async def test_handle_callback_query_accept(self, mock_telegram_update, mock_telegram_bot):
        """Test accept callback query."""
        context = MagicMock()
        context.bot = mock_telegram_bot

        # Setup callback query
        mock_telegram_update.callback_query.data = "accept_abc12345"

        with patch('dumpyarabot.moderated_handlers.settings') as mock_settings, \
             patch('dumpyarabot.moderated_handlers.ReviewStorage') as mock_storage, \
             patch('dumpyarabot.moderated_handlers.message_queue') as mock_queue:

            mock_settings.REVIEW_CHAT_ID = mock_telegram_update.effective_chat.id
            mock_storage.get_pending_review.return_value = MagicMock(
                url="https://example.com/firmware.zip",
                user_id=12345,
                username="testuser"
            )
            mock_storage.get_options_state.return_value = MagicMock(alt=False, force=False, privdump=False)

            # Mock the callback query methods
            mock_telegram_update.callback_query.edit_message_text = AsyncMock()

            await handle_callback_query(mock_telegram_update, context)

            # Verify callback query was answered
            mock_telegram_update.callback_query.answer.assert_called_once()

            # Verify options state was retrieved
            mock_storage.get_options_state.assert_called_once()

            # Verify message was edited to show options
            mock_telegram_update.callback_query.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_callback_query_reject(self, mock_telegram_update, mock_telegram_bot):
        """Test reject callback query."""
        context = MagicMock()
        context.bot = mock_telegram_bot

        # Setup callback query
        mock_telegram_update.callback_query.data = "reject_abc12345"

        with patch('dumpyarabot.moderated_handlers.settings') as mock_settings, \
             patch('dumpyarabot.moderated_handlers.ReviewStorage') as mock_storage:

            mock_settings.REVIEW_CHAT_ID = mock_telegram_update.effective_chat.id

            # Mock the callback query methods
            mock_telegram_update.callback_query.edit_message_text = AsyncMock()

            await handle_callback_query(mock_telegram_update, context)

            # Verify callback query was answered
            mock_telegram_update.callback_query.answer.assert_called_once()

            # Verify review message was updated with reject instructions
            mock_telegram_update.callback_query.edit_message_text.assert_called_once()
            call_args = mock_telegram_update.callback_query.edit_message_text.call_args
            assert "/reject" in call_args[1]["text"]


@pytest.mark.unit
class TestAcceptCommand:
    """Test cases for the accept_command function."""

    @pytest.mark.asyncio
    async def test_accept_command_valid(self, mock_telegram_update, mock_telegram_bot):
        """Test accept command with valid request ID."""
        context = MagicMock()
        context.args = ["abc12345", "a", "f"]
        context.bot = mock_telegram_bot

        # Set up the reply_to_message to have the Request ID pattern
        mock_telegram_update.effective_message.reply_to_message.text = "Some message with Request ID: abc12345"

        with patch('dumpyarabot.moderated_handlers.settings') as mock_settings, \
             patch('dumpyarabot.moderated_handlers.ReviewStorage') as mock_storage, \
             patch('dumpyarabot.moderated_handlers.message_queue') as mock_queue, \
             patch('dumpyarabot.moderated_handlers.secrets.token_hex') as mock_token, \
             patch('dumpyarabot.moderated_handlers._cleanup_request') as mock_cleanup:

            mock_settings.REVIEW_CHAT_ID = mock_telegram_update.effective_chat.id
            mock_storage.get_pending_review.return_value = MagicMock(
                url="https://example.com/firmware.zip",
                user_id=12345,
                username="testuser",
                initial_message_id=123,
                initial_chat_id=456
            )
            mock_queue.queue_dump_job_with_metadata = AsyncMock(return_value="job123")
            mock_queue.send_reply = AsyncMock()
            mock_queue.send_cross_chat = AsyncMock()
            mock_token.return_value = "job123"
            mock_cleanup.return_value = None

            await accept_command(mock_telegram_update, context)

            # Verify job was queued with options
            mock_queue.queue_dump_job_with_metadata.assert_called_once()
            job_data = mock_queue.queue_dump_job_with_metadata.call_args[0][0]
            assert job_data["dump_args"]["use_alt_dumper"] is True  # 'a' option
            assert str(job_data["dump_args"]["url"]) == "https://example.com/firmware.zip"

            # Verify acceptance message was sent
            mock_queue.send_reply.assert_called_once()

            # Verify cleanup was called
            mock_cleanup.assert_called_once_with(context, "abc12345")

    @pytest.mark.asyncio
    async def test_accept_command_invalid_request(self, mock_telegram_update, mock_telegram_bot):
        """Test accept command with invalid request ID."""
        context = MagicMock()
        context.args = ["invalid123"]
        context.bot = mock_telegram_bot

        # Set up the reply_to_message to NOT have a valid Request ID pattern
        mock_telegram_update.effective_message.reply_to_message = None

        with patch('dumpyarabot.moderated_handlers.settings') as mock_settings, \
             patch('dumpyarabot.moderated_handlers.ReviewStorage') as mock_storage, \
             patch('dumpyarabot.moderated_handlers.message_queue') as mock_queue:

            mock_settings.REVIEW_CHAT_ID = mock_telegram_update.effective_chat.id
            mock_storage.get_pending_review.return_value = None
            mock_queue.send_error = AsyncMock()
            mock_queue.send_cross_chat = AsyncMock()

            await accept_command(mock_telegram_update, context)

            # Should send error message for invalid request ID
            mock_queue.send_error.assert_called_once()
            call_args = mock_queue.send_error.call_args
            assert "not found" in call_args[1]["text"].lower() or "expired" in call_args[1]["text"].lower()

    @pytest.mark.asyncio
    async def test_accept_command_no_args(self, mock_telegram_update, mock_telegram_bot):
        """Test accept command with no arguments."""
        context = MagicMock()
        context.args = []
        context.bot = mock_telegram_bot

        # Ensure no reply_to_message so it uses argument parsing
        mock_telegram_update.effective_message.reply_to_message = None

        with patch('dumpyarabot.moderated_handlers.settings') as mock_settings, \
             patch('dumpyarabot.moderated_handlers.message_queue') as mock_queue:

            mock_settings.REVIEW_CHAT_ID = mock_telegram_update.effective_chat.id
            mock_queue.send_reply = AsyncMock()
            mock_queue.send_error = AsyncMock()
            mock_queue.send_cross_chat = AsyncMock()

            await accept_command(mock_telegram_update, context)

            # Should send usage message
            mock_queue.send_reply.assert_called_once()
            call_args = mock_queue.send_reply.call_args
            assert "Usage:" in call_args[1]["text"]


@pytest.mark.unit
class TestRejectCommand:
    """Test cases for the reject_command function."""

    @pytest.mark.asyncio
    async def test_reject_command_valid(self, mock_telegram_update, mock_telegram_bot):
        """Test reject command with valid request ID."""
        context = MagicMock()
        context.args = ["abc12345", "Invalid", "URL"]
        context.bot = mock_telegram_bot

        # Set up the reply_to_message to have the Request ID pattern
        mock_telegram_update.effective_message.reply_to_message.text = "Some message with Request ID: abc12345"

        with patch('dumpyarabot.moderated_handlers.settings') as mock_settings, \
             patch('dumpyarabot.moderated_handlers.ReviewStorage') as mock_storage, \
             patch('dumpyarabot.moderated_handlers.message_queue') as mock_queue, \
             patch('dumpyarabot.moderated_handlers._cleanup_request') as mock_cleanup:

            mock_settings.REVIEW_CHAT_ID = mock_telegram_update.effective_chat.id
            mock_storage.get_pending_review.return_value = MagicMock(
                url="https://example.com/firmware.zip",
                user_id=12345,
                username="testuser",
                initial_message_id=123,
                initial_chat_id=456
            )
            mock_queue.send_cross_chat = AsyncMock()
            mock_cleanup.return_value = None

            await reject_command(mock_telegram_update, context)

            # Verify rejection messages were sent (admin confirmation + user notification)
            assert mock_queue.send_cross_chat.call_count == 2
            # Check admin confirmation message (first call)
            admin_call = mock_queue.send_cross_chat.call_args_list[0]
            assert "rejected" in admin_call[1]["text"].lower()
            assert "Invalid URL" in admin_call[1]["text"]

            # Verify cleanup was called
            mock_cleanup.assert_called_once_with(context, "abc12345")

    @pytest.mark.asyncio
    async def test_reject_command_no_reason(self, mock_telegram_update, mock_telegram_bot):
        """Test reject command without reason."""
        context = MagicMock()
        context.args = ["abc12345"]
        context.bot = mock_telegram_bot

        # Set up the reply_to_message to have the Request ID pattern
        mock_telegram_update.effective_message.reply_to_message.text = "Some message with Request ID: abc12345"

        with patch('dumpyarabot.moderated_handlers.settings') as mock_settings, \
             patch('dumpyarabot.moderated_handlers.ReviewStorage') as mock_storage, \
             patch('dumpyarabot.moderated_handlers.message_queue') as mock_queue, \
             patch('dumpyarabot.moderated_handlers._cleanup_request') as mock_cleanup:

            mock_settings.REVIEW_CHAT_ID = mock_telegram_update.effective_chat.id
            mock_storage.get_pending_review.return_value = MagicMock(
                url="https://example.com/firmware.zip",
                user_id=12345,
                username="testuser",
                initial_message_id=123,
                initial_chat_id=456
            )
            mock_queue.send_cross_chat = AsyncMock()
            mock_cleanup.return_value = None

            await reject_command(mock_telegram_update, context)

            # Verify rejection messages were sent (admin confirmation + user notification)
            assert mock_queue.send_cross_chat.call_count == 2
            # Check admin confirmation message (first call)
            admin_call = mock_queue.send_cross_chat.call_args_list[0]
            assert "rejected" in admin_call[1]["text"].lower()

            # Verify cleanup was called
            mock_cleanup.assert_called_once_with(context, "abc12345")


@pytest.mark.unit
class TestUtilityFunctions:
    """Test cases for utility functions."""

    def test_truncate_message_short(self):
        """Test truncating a short message."""
        text = "This is a short message"
        result = _truncate_message(text, max_length=100)
        assert result == text

    def test_truncate_message_long(self):
        """Test truncating a long message."""
        text = "This is a very long message that exceeds the maximum length limit and should be truncated properly"
        result = _truncate_message(text, max_length=50)
        assert len(result) <= 53  # 50 + "..."
        assert result.endswith("...")

    def test_truncate_message_word_boundary(self):
        """Test truncating at word boundary."""
        text = "This is a very long message with words"
        result = _truncate_message(text, max_length=25)
        assert result.endswith("...")
        # Should not cut in the middle of a word if possible
        assert not result.replace("...", "").endswith("lon")

    @pytest.mark.asyncio
    async def test_cleanup_request(self, mock_telegram_update):
        """Test request cleanup function."""
        context = MagicMock()

        with patch('dumpyarabot.moderated_handlers.ReviewStorage') as mock_storage:
            mock_storage.remove_pending_review = MagicMock()
            mock_storage.remove_options_state = MagicMock()

            await _cleanup_request(context, "test123")

            # Verify both cleanup methods were called
            mock_storage.remove_pending_review.assert_called_once_with(context, "test123")
            mock_storage.remove_options_state.assert_called_once_with(context, "test123")