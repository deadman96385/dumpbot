"""
Unit tests for dumpyarabot message queue system.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dumpyarabot.message_queue import (
    MessagePriority,
    MessageQueue,
    MessageType,
    QueuedMessage,
)


@pytest.mark.unit
class TestQueuedMessage:
    """Test cases for QueuedMessage schema."""

    def test_queued_message_valid(self):
        """Test creating valid QueuedMessage."""
        message = QueuedMessage(
            message_id="test123",
            type=MessageType.COMMAND_REPLY,
            priority=MessagePriority.HIGH,
            chat_id=123456,
            text="Test message",
            parse_mode="Markdown",
        )

        assert message.message_id == "test123"
        assert message.type == MessageType.COMMAND_REPLY
        assert message.priority == MessagePriority.HIGH
        assert message.chat_id == 123456
        assert message.text == "Test message"
        assert message.parse_mode == "Markdown"

    def test_queued_message_with_defaults(self):
        """Test QueuedMessage with auto-generated defaults."""
        with patch("dumpyarabot.message_queue.settings") as mock_settings:
            mock_settings.DEFAULT_PARSE_MODE = "Markdown"

            message = QueuedMessage(
                type=MessageType.NOTIFICATION,
                priority=MessagePriority.NORMAL,
                chat_id=123456,
                text="Test message",
            )

            # Should have auto-generated message_id and created_at
            assert message.message_id is not None
            assert message.created_at is not None
            assert message.parse_mode == "Markdown"

    def test_queued_message_with_optional_fields(self):
        """Test QueuedMessage with optional fields."""
        message = QueuedMessage(
            message_id="test123",
            type=MessageType.CROSS_CHAT,
            priority=MessagePriority.URGENT,
            chat_id=123456,
            text="Test message",
            parse_mode="Markdown",
            reply_to_message_id=789,
            keyboard={
                "inline_keyboard": [[{"text": "Button", "callback_data": "test"}]]
            },
            disable_web_page_preview=True,
        )

        assert message.reply_to_message_id == 789
        assert message.keyboard is not None
        assert message.disable_web_page_preview is True


@pytest.fixture
def mock_redis():
    """Mock Redis connection."""
    redis_mock = AsyncMock()
    redis_mock.ping = AsyncMock(return_value=True)
    redis_mock.lpush = AsyncMock(return_value=1)
    redis_mock.brpop = AsyncMock()
    redis_mock.set = AsyncMock()
    redis_mock.get = AsyncMock()
    redis_mock.delete = AsyncMock()
    redis_mock.hset = AsyncMock()
    redis_mock.hget = AsyncMock()
    redis_mock.hdel = AsyncMock()
    redis_mock.llen = AsyncMock()
    return redis_mock


@pytest.fixture
def mock_bot():
    """Mock Telegram bot."""
    bot_mock = AsyncMock()
    bot_mock.send_message = AsyncMock()
    bot_mock.edit_message_text = AsyncMock()
    bot_mock.delete_message = AsyncMock()
    return bot_mock


@pytest.fixture
def message_queue_instance(mock_redis, mock_bot):
    """MessageQueue instance with mocked dependencies."""
    with patch("dumpyarabot.message_queue.redis.from_url") as mock_redis_factory:
        mock_redis_factory.return_value = mock_redis

        queue = MessageQueue()
        queue._redis = mock_redis
        queue._bot = mock_bot
        return queue


@pytest.mark.unit
class TestMessageQueue:
    """Test cases for MessageQueue class."""

    @pytest.mark.asyncio
    async def test_send_reply(self, message_queue_instance, mock_redis, mock_bot):
        """Test send_reply method."""
        await message_queue_instance.send_reply(
            chat_id=123456, text="Test reply", reply_to_message_id=789
        )

        # Verify message was queued
        mock_redis.lpush.assert_called_once()
        call_args = mock_redis.lpush.call_args
        queue_name = call_args[0][0]
        assert "high" in queue_name  # High priority queue

    @pytest.mark.asyncio
    async def test_send_error(self, message_queue_instance, mock_redis, mock_bot):
        """Test send_error method."""
        await message_queue_instance.send_error(
            chat_id=123456, text="Error message", context={"error": "test"}
        )

        # Verify error message was queued with urgent priority
        mock_redis.lpush.assert_called_once()
        call_args = mock_redis.lpush.call_args
        queue_name = call_args[0][0]
        assert "urgent" in queue_name  # Urgent priority queue

    @pytest.mark.asyncio
    async def test_send_immediate_message(
        self, message_queue_instance, mock_redis, mock_bot
    ):
        """Test send_immediate_message method."""
        mock_message = MagicMock()
        mock_message.message_id = 123
        mock_bot.send_message.return_value = mock_message

        result = await message_queue_instance.send_immediate_message(
            chat_id=123456, text="Immediate message"
        )

        # Verify message was sent immediately
        mock_bot.send_message.assert_called_once_with(
            chat_id=123456,
            text="Immediate message",
            parse_mode="Markdown",
            reply_to_message_id=None,
            disable_web_page_preview=True,
        )
        assert result.message_id == 123

    @pytest.mark.asyncio
    async def test_publish_and_return_placeholder(
        self, message_queue_instance, mock_redis, mock_bot
    ):
        """Test publish_and_return_placeholder method."""
        message = QueuedMessage(
            message_id="test123",
            type=MessageType.NOTIFICATION,
            priority=MessagePriority.HIGH,
            chat_id=123456,
            text="Test message",
            parse_mode="Markdown",
        )

        result = await message_queue_instance.publish_and_return_placeholder(message)

        # Verify message was queued
        mock_redis.lpush.assert_called_once()

        # Verify placeholder was returned
        assert result.message_id == "test123"

    @pytest.mark.asyncio
    async def test_queue_dump_job_with_metadata(
        self, message_queue_instance, mock_redis, mock_bot
    ):
        """Test queue_dump_job_with_metadata method."""
        job_data = {
            "job_id": "test_job_123",
            "dump_args": {
                "url": "https://example.com/firmware.zip",
                "use_alt_dumper": False,
                "use_privdump": False,
            },
            "metadata": {"telegram_context": {"chat_id": 123456, "message_id": 789}},
        }

        mock_pool = AsyncMock()
        mock_pool.enqueue_job = AsyncMock(return_value=MagicMock(job_id="test_job_123"))

        with patch("dumpyarabot.arq_config.arq_pool", mock_pool), patch(
            "dumpyarabot.arq_config.get_job_result_ttl", return_value=86400
        ):
            result = await message_queue_instance.queue_dump_job_with_metadata(job_data)

            # Verify ARQ job was queued
            mock_pool.enqueue_job.assert_called_once_with(
                "process_firmware_dump",
                job_data,
                job_id="test_job_123",
                result_ttl=86400,
            )
            assert result == "test_job_123"

    @pytest.mark.asyncio
    async def test_get_job_status(self, message_queue_instance, mock_redis, mock_bot):
        """Test get_job_status method."""
        mock_arq_status = {
            "status": "complete",
            "result": {
                "status": "success",
                "metadata": {
                    "telegram_context": {"url": "https://example.com/test.zip"},
                    "device_info": {"model": "Test Device"},
                    "progress_history": [{"message": "Processing", "percentage": 50}],
                },
            },
            "enqueue_time": "2023-01-01T00:00:00Z",
        }

        # Mock the DumpJob creation since it has complex validation requirements
        mock_dump_job = MagicMock()
        mock_dump_job.job_id = "test_job_123"

        mock_pool = AsyncMock()
        mock_pool.get_job_status = AsyncMock(return_value=mock_arq_status)

        with patch("dumpyarabot.arq_config.arq_pool", mock_pool), patch(
            "dumpyarabot.message_queue.DumpJob.model_validate",
            return_value=mock_dump_job,
        ):
            result = await message_queue_instance.get_job_status("test_job_123")

            # Verify job status was retrieved and processed
            mock_pool.get_job_status.assert_called_once_with("test_job_123")
            assert result is not None
            assert result.job_id == "test_job_123"

    @pytest.mark.asyncio
    async def test_cancel_job(self, message_queue_instance, mock_redis, mock_bot):
        """Test cancel_job method."""
        mock_pool = AsyncMock()
        mock_pool.cancel_job = AsyncMock(return_value=True)

        with patch("dumpyarabot.arq_config.arq_pool", mock_pool):
            result = await message_queue_instance.cancel_job("test_job_123")

            # Verify job was cancelled
            mock_pool.cancel_job.assert_called_once_with("test_job_123")
            assert result is True

    @pytest.mark.asyncio
    async def test_get_active_jobs_with_metadata(
        self, message_queue_instance, mock_redis, mock_bot
    ):
        """Test get_active_jobs_with_metadata method."""
        # This method returns empty list as noted in implementation
        result = await message_queue_instance.get_active_jobs_with_metadata()

        # Verify active jobs were retrieved (empty list for now)
        assert result == []
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_send_status_update(
        self, message_queue_instance, mock_redis, mock_bot
    ):
        """Test send_status_update method."""
        await message_queue_instance.send_status_update(
            chat_id=123456,
            text="Status update message",
            edit_message_id=789,
            context={"test": "context"},
        )

        # Verify status update message was queued
        mock_redis.lpush.assert_called_once()
        call_args = mock_redis.lpush.call_args
        queue_name = call_args[0][0]
        assert "normal" in queue_name  # Normal priority queue

    @pytest.mark.asyncio
    async def test_send_notification(
        self, message_queue_instance, mock_redis, mock_bot
    ):
        """Test send_notification method."""
        await message_queue_instance.send_notification(
            chat_id=123456,
            text="Notification message",
            priority=MessagePriority.HIGH,
            context={"test": "context"},
        )

        # Verify notification message was queued
        mock_redis.lpush.assert_called_once()
        call_args = mock_redis.lpush.call_args
        queue_name = call_args[0][0]
        assert "high" in queue_name  # High priority queue

    @pytest.mark.asyncio
    async def test_send_cross_chat_edit(
        self, message_queue_instance, mock_redis, mock_bot
    ):
        """Test send_cross_chat_edit method."""
        await message_queue_instance.send_cross_chat_edit(
            chat_id=123456,
            text="Updated message",
            edit_message_id=789,
            reply_to_message_id=456,
            reply_to_chat_id=654321,
            context={"test": "context"},
        )

        # Verify message was queued for cross-chat editing
        mock_redis.lpush.assert_called_once()
        call_args = mock_redis.lpush.call_args
        queue_name = call_args[0][0]
        assert "normal" in queue_name  # Normal priority queue

    @pytest.mark.asyncio
    async def test_send_cross_chat(self, message_queue_instance, mock_redis, mock_bot):
        """Test send_cross_chat method."""
        await message_queue_instance.send_cross_chat(
            chat_id=123456,
            text="Cross-chat message",
            reply_to_message_id=789,
            reply_to_chat_id=654321,
            context={"test": "context"},
        )

        # Verify cross-chat message was queued
        mock_redis.lpush.assert_called_once()
        call_args = mock_redis.lpush.call_args
        queue_name = call_args[0][0]
        assert "high" in queue_name  # High priority queue


@pytest.mark.unit
class TestMessageQueueIntegration:
    """Integration tests for message queue functionality."""

    @pytest.mark.asyncio
    async def test_message_queue_singleton(self):
        """Test that message_queue is a singleton instance."""
        # The message_queue should be the same instance
        from dumpyarabot.message_queue import message_queue as mq1
        from dumpyarabot.message_queue import message_queue as mq2

        assert mq1 is mq2

    @pytest.mark.asyncio
    async def test_queue_priority_ordering(self, message_queue_instance, mock_redis):
        """Test that messages are queued with correct priority ordering."""
        # Send messages with different priorities
        await message_queue_instance.send_error(chat_id=123456, text="Error message")

        await message_queue_instance.send_reply(chat_id=123456, text="Reply message")

        # Verify calls were made to different priority queues
        assert mock_redis.lpush.call_count == 2

        # Check that urgent and high priority queues were used
        call_args_list = mock_redis.lpush.call_args_list
        queue_names = [call[0][0] for call in call_args_list]

        assert any("urgent" in name for name in queue_names)
        assert any("high" in name for name in queue_names)

    @pytest.mark.asyncio
    async def test_error_handling_redis_failure(
        self, message_queue_instance, mock_redis
    ):
        """Test error handling when Redis operations fail."""
        # Make Redis operation fail
        mock_redis.lpush.side_effect = Exception("Redis connection failed")

        # Should raise exception since Redis failure is not handled gracefully in publish method
        with pytest.raises(Exception, match="Redis connection failed"):
            await message_queue_instance.send_reply(chat_id=123456, text="Test message")

    @pytest.mark.asyncio
    async def test_telegram_rate_limiting(self, message_queue_instance, mock_bot):
        """Test handling of Telegram rate limiting."""
        from telegram.error import RetryAfter

        # Mock RetryAfter exception
        mock_bot.send_message.side_effect = RetryAfter(retry_after=5)

        # Should propagate RetryAfter exception since send_immediate_message doesn't handle it
        with pytest.raises(RetryAfter):
            await message_queue_instance.send_immediate_message(
                chat_id=123456, text="Test message"
            )

    @pytest.mark.asyncio
    async def test_get_recent_jobs_with_metadata(
        self, message_queue_instance, mock_redis, mock_bot
    ):
        """Test get_recent_jobs_with_metadata method."""
        # This method returns empty list as noted in implementation
        result = await message_queue_instance.get_recent_jobs_with_metadata(limit=5)

        # Verify recent jobs were retrieved (empty list for now)
        assert result == []
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_send_immediate_status_update(
        self, message_queue_instance, mock_redis, mock_bot
    ):
        """Test send_immediate_status_update method."""
        result = await message_queue_instance.send_immediate_status_update(
            chat_id=123456, text="Immediate status update", context={"test": "context"}
        )

        # Verify message was queued and placeholder returned
        mock_redis.lpush.assert_called_once()
        assert hasattr(result, "message_id")
        assert result.chat.id == 123456

    @pytest.mark.asyncio
    async def test_get_queue_stats(self, message_queue_instance, mock_redis, mock_bot):
        """Test get_queue_stats method."""
        # Mock Redis llen responses for different priority queues
        mock_redis.llen.side_effect = [
            5,
            3,
            2,
            1,
            0,
        ]  # urgent, high, normal, low, dead_letter

        result = await message_queue_instance.get_queue_stats()

        # Verify queue stats were retrieved
        assert result["urgent"] == 5
        assert result["high"] == 3
        assert result["normal"] == 2
        assert result["low"] == 1
        assert result["dead_letter"] == 0
        assert mock_redis.llen.call_count == 5

    @pytest.mark.asyncio
    async def test_get_job_queue_stats(
        self, message_queue_instance, mock_redis, mock_bot
    ):
        """Test get_job_queue_stats method."""
        mock_arq_stats = {"queue_length": 10, "active_health_checks": 2}

        mock_pool = AsyncMock()
        mock_pool.get_queue_stats = AsyncMock(return_value=mock_arq_stats)

        with patch("dumpyarabot.arq_config.arq_pool", mock_pool):
            result = await message_queue_instance.get_job_queue_stats()

            # Verify ARQ stats were retrieved and converted
            mock_pool.get_queue_stats.assert_called_once()
            assert result["total_jobs"] == 10
            assert result["queued_jobs"] == 10
            assert result["active_workers"] == 2
            assert "arq_stats" in result

    @pytest.mark.asyncio
    async def test_set_bot(self, message_queue_instance, mock_bot):
        """Test set_bot method."""
        message_queue_instance.set_bot(mock_bot)
        assert message_queue_instance._bot == mock_bot

    @pytest.mark.asyncio
    async def test_consumer_lifecycle(
        self, message_queue_instance, mock_redis, mock_bot
    ):
        """Test message consumer start/stop lifecycle."""
        # Test starting consumer
        await message_queue_instance.start_consumer()
        assert message_queue_instance._running is True
        assert message_queue_instance._consumer_task is not None

        # Test stopping consumer
        await message_queue_instance.stop_consumer()
        assert message_queue_instance._running is False
