"""
Unit tests for dumpyarabot handlers.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from dumpyarabot.handlers import dump, cancel_dump, status, blacklist, help_command, restart


@pytest.mark.unit
class TestDumpHandler:
    """Test cases for the /dump command handler."""

    @pytest.mark.asyncio
    async def test_dump_command_valid_url(self, test_config, mock_telegram_update, mock_telegram_bot):
        """Test /dump command with valid URL."""
        context = MagicMock()
        context.args = ["https://example.com/firmware.zip"]
        context.bot = mock_telegram_bot

        # Mock dependencies - use proper module path
        with patch('dumpyarabot.handlers.settings') as mock_settings, \
             patch('dumpyarabot.handlers.message_queue') as mock_queue, \
             patch('dumpyarabot.handlers.url_utils.validate_and_normalize_url') as mock_validate, \
             patch('dumpyarabot.handlers.secrets.token_hex') as mock_token:

            # Setup settings mock
            chat_id = mock_telegram_update.effective_chat.id
            mock_settings.ALLOWED_CHATS = [chat_id]

            # Setup other mocks
            mock_validate.return_value = (True, "https://example.com/firmware.zip", None)
            mock_queue.send_immediate_message = AsyncMock(return_value=MagicMock(message_id=123))
            mock_queue.queue_dump_job_with_metadata = AsyncMock(return_value="test_job_123")
            mock_token.return_value = "testjob123"

            await dump(mock_telegram_update, context)

            # Verify URL validation was called
            mock_validate.assert_called_once_with("https://example.com/firmware.zip")

            # Verify immediate message was sent
            mock_queue.send_immediate_message.assert_called_once()
            call_args = mock_queue.send_immediate_message.call_args
            assert call_args[1]['chat_id'] == chat_id
            assert 'Firmware Dump Queued' in call_args[1]['text']

            # Verify job was queued
            mock_queue.queue_dump_job_with_metadata.assert_called_once()
            job_data = mock_queue.queue_dump_job_with_metadata.call_args[0][0]

            assert str(job_data["dump_args"]["url"]) == "https://example.com/firmware.zip"
            assert job_data["job_id"] == "testjob123"
            assert "metadata" in job_data

    @pytest.mark.asyncio
    async def test_dump_command_unauthorized_chat(self, test_config, mock_telegram_update, mock_telegram_bot):
        """Test /dump command from unauthorized chat."""
        context = MagicMock()
        context.args = ["https://example.com/firmware.zip"]
        context.bot = mock_telegram_bot

        with patch('dumpyarabot.handlers.settings') as mock_settings, \
             patch('dumpyarabot.handlers.message_queue') as mock_queue:
            # Chat ID not in allowed chats
            mock_settings.ALLOWED_CHATS = [999999]  # Different from update's chat ID

            await dump(mock_telegram_update, context)

            # Should not send any messages for unauthorized chat
            mock_queue.send_immediate_message.assert_not_called()
            mock_queue.queue_dump_job_with_metadata.assert_not_called()

    @pytest.mark.asyncio
    async def test_dump_command_no_args(self, test_config, mock_telegram_update, mock_telegram_bot):
        """Test /dump command with no arguments."""
        context = MagicMock()
        context.args = []
        context.bot = mock_telegram_bot

        with patch('dumpyarabot.handlers.settings') as mock_settings, \
             patch('dumpyarabot.handlers.message_queue') as mock_queue:

            mock_settings.ALLOWED_CHATS = [mock_telegram_update.effective_chat.id]
            mock_queue.send_reply = AsyncMock()

            await dump(mock_telegram_update, context)

            # Should send usage message
            mock_queue.send_reply.assert_called_once()
            call_args = mock_queue.send_reply.call_args
            assert "Usage:" in call_args[1]["text"]
            assert "URL: required" in call_args[1]["text"]

    @pytest.mark.asyncio
    async def test_dump_command_invalid_url(self, test_config, mock_telegram_update, mock_telegram_bot):
        """Test /dump command with invalid URL."""
        context = MagicMock()
        context.args = ["not-a-valid-url"]
        context.bot = mock_telegram_bot

        with patch('dumpyarabot.handlers.settings') as mock_settings, \
             patch('dumpyarabot.handlers.message_queue') as mock_queue, \
             patch('dumpyarabot.handlers.url_utils.validate_and_normalize_url') as mock_validate:

            mock_settings.ALLOWED_CHATS = [mock_telegram_update.effective_chat.id]
            mock_validate.return_value = (False, None, "Invalid URL format")
            mock_queue.send_reply = AsyncMock()

            await dump(mock_telegram_update, context)

            # Should send error message
            mock_queue.send_reply.assert_called_once()
            call_args = mock_queue.send_reply.call_args
            # The error message format may vary, just check that an error was sent
            assert "Error" in call_args[1]["text"] or "Invalid" in call_args[1]["text"]

    @pytest.mark.asyncio
    async def test_dump_command_with_options(self, test_config, mock_telegram_update, mock_telegram_bot):
        """Test /dump command with various options."""
        context = MagicMock()
        context.args = ["https://example.com/firmware.zip", "afp"]
        context.bot = mock_telegram_bot

        with patch('dumpyarabot.handlers.settings') as mock_settings, \
             patch('dumpyarabot.handlers.message_queue') as mock_queue, \
             patch('dumpyarabot.handlers.url_utils.validate_and_normalize_url') as mock_validate, \
             patch('dumpyarabot.handlers.secrets.token_hex') as mock_token:

            mock_settings.ALLOWED_CHATS = [mock_telegram_update.effective_chat.id]
            mock_validate.return_value = (True, "https://example.com/firmware.zip", None)
            mock_queue.send_immediate_message = AsyncMock(return_value=MagicMock(message_id=123))
            mock_queue.queue_dump_job_with_metadata = AsyncMock(return_value="test_job_123")
            mock_token.return_value = "testjob123"

            await dump(mock_telegram_update, context)

            # Verify options were parsed correctly
            job_data = mock_queue.queue_dump_job_with_metadata.call_args[0][0]
            assert job_data["dump_args"]["use_alt_dumper"] is True
            assert job_data["dump_args"]["use_privdump"] is True
            # Note: 'f' option affects force behavior but isn't stored in dump_args

    @pytest.mark.asyncio
    async def test_dump_command_privdump_deletes_message(self, test_config, mock_telegram_update, mock_telegram_bot):
        """Test /dump command with privdump option deletes original message."""
        context = MagicMock()
        context.args = ["https://example.com/firmware.zip", "p"]
        context.bot = mock_telegram_bot

        with patch('dumpyarabot.handlers.settings') as mock_settings, \
             patch('dumpyarabot.handlers.message_queue') as mock_queue, \
             patch('dumpyarabot.handlers.url_utils.validate_and_normalize_url') as mock_validate, \
             patch('dumpyarabot.handlers.secrets.token_hex') as mock_token:

            mock_settings.ALLOWED_CHATS = [mock_telegram_update.effective_chat.id]
            mock_validate.return_value = (True, "https://example.com/firmware.zip", None)
            mock_queue.send_immediate_message = AsyncMock(return_value=MagicMock(message_id=123))
            mock_queue.queue_dump_job_with_metadata = AsyncMock(return_value="test_job_123")
            mock_token.return_value = "testjob123"

            await dump(mock_telegram_update, context)

            # Should attempt to delete original message
            mock_telegram_bot.delete_message.assert_called_once_with(
                chat_id=mock_telegram_update.effective_chat.id,
                message_id=mock_telegram_update.effective_message.message_id
            )

            # Should not reply to deleted message
            job_data = mock_queue.queue_dump_job_with_metadata.call_args[0][0]
            assert job_data["dump_args"]["initial_message_id"] is None


@pytest.mark.unit
class TestCancelHandler:
    """Test cases for the /cancel command handler."""

    @pytest.mark.asyncio
    async def test_cancel_command_valid_job_id(self, test_config, mock_telegram_update, mock_telegram_bot):
        """Test /cancel command with valid job ID."""
        context = MagicMock()
        context.args = ["abc123"]
        context.bot = mock_telegram_bot

        with patch('dumpyarabot.handlers.settings') as mock_settings, \
             patch('dumpyarabot.handlers.message_queue') as mock_queue, \
             patch('dumpyarabot.handlers.check_admin_permissions') as mock_admin:

            mock_settings.ALLOWED_CHATS = [mock_telegram_update.effective_chat.id]
            mock_admin.return_value = (True, None)  # User is admin
            mock_queue.cancel_job = AsyncMock(return_value=True)
            mock_queue.send_reply = AsyncMock()

            await cancel_dump(mock_telegram_update, context)

            # Should attempt to cancel job
            mock_queue.cancel_job.assert_called_once_with("abc123")

            # Should send success message
            mock_queue.send_reply.assert_called_once()
            call_args = mock_queue.send_reply.call_args
            assert "Job cancelled successfully" in call_args[1]["text"]

    @pytest.mark.asyncio
    async def test_cancel_command_non_admin(self, test_config, mock_telegram_update, mock_telegram_bot):
        """Test /cancel command from non-admin user."""
        context = MagicMock()
        context.args = ["abc123"]
        context.bot = mock_telegram_bot

        with patch('dumpyarabot.handlers.settings') as mock_settings, \
             patch('dumpyarabot.handlers.message_queue') as mock_queue, \
             patch('dumpyarabot.handlers.check_admin_permissions') as mock_admin:

            mock_settings.ALLOWED_CHATS = [mock_telegram_update.effective_chat.id]
            mock_admin.return_value = (False, "Not an admin")
            mock_queue.send_error = AsyncMock()

            await cancel_dump(mock_telegram_update, context)

            # Should send permission denied error
            mock_queue.send_error.assert_called_once()
            call_args = mock_queue.send_error.call_args
            assert "don't have permission" in call_args[1]["text"]

    @pytest.mark.asyncio
    async def test_cancel_command_job_not_found(self, test_config, mock_telegram_update, mock_telegram_bot):
        """Test /cancel command when job is not found."""
        context = MagicMock()
        context.args = ["nonexistent"]
        context.bot = mock_telegram_bot

        with patch('dumpyarabot.handlers.settings') as mock_settings, \
             patch('dumpyarabot.handlers.message_queue') as mock_queue, \
             patch('dumpyarabot.handlers.check_admin_permissions') as mock_admin:

            mock_settings.ALLOWED_CHATS = [mock_telegram_update.effective_chat.id]
            mock_admin.return_value = (True, None)
            mock_queue.cancel_job = AsyncMock(return_value=False)
            mock_queue.send_reply = AsyncMock()

            await cancel_dump(mock_telegram_update, context)

            # Should send job not found message
            mock_queue.send_reply.assert_called_once()
            call_args = mock_queue.send_reply.call_args
            assert "Job not found" in call_args[1]["text"]


@pytest.mark.unit
class TestStatusHandler:
    """Test cases for the /status command handler."""

    @pytest.mark.asyncio
    async def test_status_command_no_args(self, test_config, mock_telegram_update, mock_telegram_bot):
        """Test /status command without arguments (overview)."""
        context = MagicMock()
        context.args = []
        context.bot = mock_telegram_bot

        with patch('dumpyarabot.handlers.settings') as mock_settings, \
             patch('dumpyarabot.handlers.message_queue') as mock_queue, \
             patch('dumpyarabot.message_formatting.format_jobs_overview') as mock_format:

            mock_settings.ALLOWED_CHATS = [mock_telegram_update.effective_chat.id]
            mock_queue.get_active_jobs_with_metadata = AsyncMock(return_value=[])
            mock_queue.get_recent_jobs_with_metadata = AsyncMock(return_value=[])
            mock_queue.send_reply = AsyncMock()
            mock_format.return_value = "No active jobs"

            await status(mock_telegram_update, context)

            # Should get overview of jobs
            mock_queue.get_active_jobs_with_metadata.assert_called_once()
            mock_queue.get_recent_jobs_with_metadata.assert_called_once()
            mock_format.assert_called_once()

    @pytest.mark.asyncio
    async def test_status_command_with_job_id(self, test_config, mock_telegram_update, mock_telegram_bot):
        """Test /status command with specific job ID."""
        context = MagicMock()
        context.args = ["abc123"]
        context.bot = mock_telegram_bot

        mock_job = MagicMock()

        with patch('dumpyarabot.handlers.settings') as mock_settings, \
             patch('dumpyarabot.handlers.message_queue') as mock_queue, \
             patch('dumpyarabot.message_formatting.format_enhanced_job_status') as mock_format:

            mock_settings.ALLOWED_CHATS = [mock_telegram_update.effective_chat.id]
            mock_queue.get_job_status = AsyncMock(return_value=mock_job)
            mock_queue.send_reply = AsyncMock()
            mock_format.return_value = "Job status details"

            await status(mock_telegram_update, context)

            # Should get specific job status
            mock_queue.get_job_status.assert_called_once_with("abc123")
            mock_format.assert_called_once_with(mock_job)

    @pytest.mark.asyncio
    async def test_status_command_job_not_found(self, test_config, mock_telegram_update, mock_telegram_bot):
        """Test /status command when job is not found."""
        context = MagicMock()
        context.args = ["nonexistent"]
        context.bot = mock_telegram_bot

        with patch('dumpyarabot.handlers.settings') as mock_settings, \
             patch('dumpyarabot.handlers.message_queue') as mock_queue:

            mock_settings.ALLOWED_CHATS = [mock_telegram_update.effective_chat.id]
            mock_queue.get_job_status = AsyncMock(return_value=None)
            mock_queue.send_reply = AsyncMock()

            await status(mock_telegram_update, context)

            # Should send job not found message
            mock_queue.send_reply.assert_called_once()
            call_args = mock_queue.send_reply.call_args
            assert "Job not found:" in call_args[1]["text"]


@pytest.mark.unit
class TestBlacklistHandler:
    """Test cases for the /blacklist command handler."""

    @pytest.mark.asyncio
    async def test_blacklist_command_valid_url(self, test_config, mock_telegram_update, mock_telegram_bot):
        """Test /blacklist command with valid URL."""
        context = MagicMock()
        context.args = ["https://example.com/firmware.zip"]
        context.bot = mock_telegram_bot

        with patch('dumpyarabot.handlers.settings') as mock_settings, \
             patch('dumpyarabot.handlers.message_queue') as mock_queue, \
             patch('dumpyarabot.handlers.secrets.token_hex') as mock_token:

            mock_settings.ALLOWED_CHATS = [mock_telegram_update.effective_chat.id]
            mock_queue.queue_dump_job_with_metadata = AsyncMock(return_value="blacklist_job_123")
            mock_queue.send_reply = AsyncMock()
            mock_token.return_value = "testjob123"

            await blacklist(mock_telegram_update, context)

            # Should queue blacklist job
            mock_queue.queue_dump_job_with_metadata.assert_called_once()
            job_data = mock_queue.queue_dump_job_with_metadata.call_args[0][0]

            assert str(job_data["dump_args"]["url"]) == "https://example.com/firmware.zip"
            assert job_data["add_blacklist"] is True
            assert job_data["metadata"]["telegram_context"]["url"] == "https://example.com/firmware.zip"

    @pytest.mark.asyncio
    async def test_blacklist_command_no_args(self, test_config, mock_telegram_update, mock_telegram_bot):
        """Test /blacklist command with no arguments."""
        context = MagicMock()
        context.args = []
        context.bot = mock_telegram_bot

        with patch('dumpyarabot.handlers.settings') as mock_settings, \
             patch('dumpyarabot.handlers.message_queue') as mock_queue:

            mock_settings.ALLOWED_CHATS = [mock_telegram_update.effective_chat.id]
            mock_queue.send_reply = AsyncMock()

            await blacklist(mock_telegram_update, context)

            # Should send usage message
            mock_queue.send_reply.assert_called_once()
            call_args = mock_queue.send_reply.call_args
            assert "Usage:" in call_args[1]["text"]
            assert "URL: required" in call_args[1]["text"]


@pytest.mark.unit
class TestHelpHandler:
    """Test cases for the /help command handler."""

    @pytest.mark.asyncio
    async def test_help_command_admin_user(self, test_config, mock_telegram_update, mock_telegram_bot):
        """Test /help command for admin user."""
        context = MagicMock()
        context.bot = mock_telegram_bot

        with patch('dumpyarabot.handlers.settings') as mock_settings, \
             patch('dumpyarabot.handlers.message_queue') as mock_queue, \
             patch('dumpyarabot.handlers.check_admin_permissions') as mock_admin:

            mock_settings.ALLOWED_CHATS = [mock_telegram_update.effective_chat.id]
            mock_admin.return_value = (True, None)  # User is admin
            mock_queue.send_reply = AsyncMock()

            # Mock config constants
            with patch('dumpyarabot.config.USER_COMMANDS', [('dump', 'Dump firmware')]), \
                 patch('dumpyarabot.config.INTERNAL_COMMANDS', [('status', 'Check status')]), \
                 patch('dumpyarabot.config.ADMIN_COMMANDS', [('cancel', 'Cancel job')]):

                await help_command(mock_telegram_update, context)

                # Should send help message with admin commands
                mock_queue.send_reply.assert_called_once()
                call_args = mock_queue.send_reply.call_args
                help_text = call_args[1]["text"]

                assert "User Commands:" in help_text
                assert "Admin Commands:" in help_text
                assert "/cancel" in help_text

    @pytest.mark.asyncio
    async def test_help_command_regular_user(self, test_config, mock_telegram_update, mock_telegram_bot):
        """Test /help command for regular user."""
        context = MagicMock()
        context.bot = mock_telegram_bot

        with patch('dumpyarabot.handlers.settings') as mock_settings, \
             patch('dumpyarabot.handlers.message_queue') as mock_queue, \
             patch('dumpyarabot.handlers.check_admin_permissions') as mock_admin:

            mock_settings.ALLOWED_CHATS = [mock_telegram_update.effective_chat.id]
            mock_admin.return_value = (False, "Not admin")  # User is not admin
            mock_queue.send_reply = AsyncMock()

            # Mock config constants
            with patch('dumpyarabot.config.USER_COMMANDS', [('dump', 'Dump firmware')]), \
                 patch('dumpyarabot.config.INTERNAL_COMMANDS', [('status', 'Check status')]), \
                 patch('dumpyarabot.config.ADMIN_COMMANDS', [('cancel', 'Cancel job')]):

                await help_command(mock_telegram_update, context)

                # Should send help message without admin commands
                mock_queue.send_reply.assert_called_once()
                call_args = mock_queue.send_reply.call_args
                help_text = call_args[1]["text"]

                assert "User Commands:" in help_text
                assert "Admin Commands:" not in help_text
                assert "/cancel" not in help_text


@pytest.mark.unit
class TestRestartHandler:
    """Test cases for the /restart command handler."""

    @pytest.mark.asyncio
    async def test_restart_command_admin_user(self, test_config, mock_telegram_update, mock_telegram_bot):
        """Test /restart command for admin user."""
        context = MagicMock()
        context.bot = mock_telegram_bot

        with patch('dumpyarabot.handlers.settings') as mock_settings, \
             patch('dumpyarabot.handlers.message_queue') as mock_queue, \
             patch('dumpyarabot.handlers.check_admin_permissions') as mock_admin:

            mock_settings.ALLOWED_CHATS = [mock_telegram_update.effective_chat.id]
            mock_settings.DEFAULT_PARSE_MODE = "Markdown"
            mock_admin.return_value = (True, None)  # User is admin
            mock_queue.publish = AsyncMock()

            await restart(mock_telegram_update, context)

            # Should send restart confirmation message
            mock_queue.publish.assert_called_once()
            message = mock_queue.publish.call_args[0][0]

            assert "Bot Restart Confirmation" in message.text
            assert "inline_keyboard" in message.keyboard

    @pytest.mark.asyncio
    async def test_restart_command_non_admin(self, test_config, mock_telegram_update, mock_telegram_bot):
        """Test /restart command for non-admin user."""
        context = MagicMock()
        context.bot = mock_telegram_bot

        with patch('dumpyarabot.handlers.settings') as mock_settings, \
             patch('dumpyarabot.handlers.message_queue') as mock_queue, \
             patch('dumpyarabot.handlers.check_admin_permissions') as mock_admin:

            mock_settings.ALLOWED_CHATS = [mock_telegram_update.effective_chat.id]
            mock_settings.DEFAULT_PARSE_MODE = "Markdown"
            mock_admin.return_value = (False, "Not admin")
            mock_queue.send_error = AsyncMock()

            await restart(mock_telegram_update, context)

            # Should send permission denied error
            mock_queue.send_error.assert_called_once()
            call_args = mock_queue.send_error.call_args
            assert "don't have permission" in call_args[1]["text"]