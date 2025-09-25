import asyncio
import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, Optional

import redis.asyncio as redis
from pydantic import BaseModel
from rich.console import Console
from telegram import Bot
from telegram.error import RetryAfter, TelegramError

from dumpyarabot.config import settings

console = Console()


class MessageType(str, Enum):
    """Types of messages that can be queued."""
    COMMAND_REPLY = "command_reply"
    STATUS_UPDATE = "status_update"
    NOTIFICATION = "notification"
    CROSS_CHAT = "cross_chat"
    ERROR = "error"


class MessagePriority(str, Enum):
    """Message priority levels."""
    URGENT = "urgent"     # Errors, critical notifications
    HIGH = "high"         # Command replies, user-facing updates
    NORMAL = "normal"     # Status updates, progress reports
    LOW = "low"           # Background notifications, cleanup


class QueuedMessage(BaseModel):
    """Schema for messages in the Redis queue."""
    message_id: str
    type: MessageType
    priority: MessagePriority
    chat_id: int
    text: str
    parse_mode: Optional[str] = None
    reply_to_message_id: Optional[int] = None
    reply_parameters: Optional[Dict[str, Any]] = None
    edit_message_id: Optional[int] = None
    delete_after: Optional[int] = None
    keyboard: Optional[Dict[str, Any]] = None
    disable_web_page_preview: Optional[bool] = None
    retry_count: int = 0
    max_retries: int = 3
    created_at: datetime
    scheduled_for: Optional[datetime] = None
    context: Dict[str, Any] = {}

    def __init__(self, **data):
        if "message_id" not in data:
            data["message_id"] = str(uuid.uuid4())
        if "created_at" not in data:
            data["created_at"] = datetime.utcnow()
        super().__init__(**data)


class MessageQueue:
    """Redis-based message queue for unified Telegram messaging."""

    def __init__(self):
        self._redis: Optional[redis.Redis] = None
        self._consumer_task: Optional[asyncio.Task] = None
        self._running = False
        self._bot: Optional[Bot] = None

    async def _get_redis(self) -> redis.Redis:
        """Get or create Redis connection."""
        if self._redis is None:
            self._redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
        return self._redis

    def _make_queue_key(self, priority: MessagePriority) -> str:
        """Create Redis key for priority queue."""
        return f"{settings.REDIS_KEY_PREFIX}msg_queue:{priority.value}"

    async def publish(self, message: QueuedMessage) -> str:
        """Publish a message to the appropriate priority queue and return message_id."""
        redis_client = await self._get_redis()
        queue_key = self._make_queue_key(message.priority)

        # Serialize message
        message_json = message.model_dump_json()

        # Add to priority queue (LPUSH for FIFO with RPOP)
        await redis_client.lpush(queue_key, message_json)

        console.print(f"[green]Queued {message.type.value} message for chat {message.chat_id} (priority: {message.priority.value})[/green]")

        # Return the message_id for cases where we need to track it
        return message.message_id

    async def send_reply(
        self,
        chat_id: int,
        text: str,
        reply_to_message_id: Optional[int] = None,
        parse_mode: Optional[str] = "Markdown",
        priority: MessagePriority = MessagePriority.HIGH,
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """Send a reply message."""
        message = QueuedMessage(
            type=MessageType.COMMAND_REPLY,
            priority=priority,
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            reply_to_message_id=reply_to_message_id,
            context=context or {}
        )
        await self.publish(message)

    async def send_status_update(
        self,
        chat_id: int,
        text: str,
        edit_message_id: Optional[int] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """Send a status update message."""
        message = QueuedMessage(
            type=MessageType.STATUS_UPDATE,
            priority=MessagePriority.NORMAL,
            chat_id=chat_id,
            text=text,
            edit_message_id=edit_message_id,
            context=context or {}
        )
        await self.publish(message)

    async def send_cross_chat(
        self,
        chat_id: int,
        text: str,
        reply_to_message_id: int,
        reply_to_chat_id: int,
        parse_mode: Optional[str] = "Markdown",
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """Send a cross-chat message with reply parameters."""
        reply_params = {
            "message_id": reply_to_message_id,
            "chat_id": reply_to_chat_id
        }

        message = QueuedMessage(
            type=MessageType.CROSS_CHAT,
            priority=MessagePriority.HIGH,
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            reply_parameters=reply_params,
            context=context or {}
        )
        await self.publish(message)

    async def send_notification(
        self,
        chat_id: int,
        text: str,
        priority: MessagePriority = MessagePriority.URGENT,
        parse_mode: Optional[str] = "Markdown",
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """Send a notification message."""
        message = QueuedMessage(
            type=MessageType.NOTIFICATION,
            priority=priority,
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            context=context or {}
        )
        await self.publish(message)

    async def send_error(
        self,
        chat_id: int,
        text: str,
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """Send an error message with urgent priority."""
        message = QueuedMessage(
            type=MessageType.ERROR,
            priority=MessagePriority.URGENT,
            chat_id=chat_id,
            text=text,
            parse_mode="Markdown",
            context=context or {}
        )
        await self.publish(message)

    class MessagePlaceholder:
        """Placeholder object that mimics a Telegram Message for compatibility."""
        def __init__(self, message_id: str, chat_id: int):
            self.message_id = int(message_id.replace('-', '')[:9])  # Convert UUID to int-like
            self.chat = type('Chat', (), {'id': chat_id})()

    async def publish_and_return_placeholder(
        self,
        message: QueuedMessage
    ) -> "MessageQueue.MessagePlaceholder":
        """Publish message and return a placeholder object for compatibility."""
        message_id = await self.publish(message)
        return self.MessagePlaceholder(message_id, message.chat_id)

    def set_bot(self, bot: Bot) -> None:
        """Set the Telegram bot instance."""
        self._bot = bot

    async def start_consumer(self) -> None:
        """Start the message consumer background task."""
        if self._consumer_task and not self._consumer_task.done():
            console.print("[yellow]Message consumer is already running[/yellow]")
            return

        self._running = True
        self._consumer_task = asyncio.create_task(self._consume_messages())
        console.print("[green]Message queue consumer started[/green]")

    async def stop_consumer(self) -> None:
        """Stop the message consumer."""
        self._running = False
        if self._consumer_task:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
        console.print("[yellow]Message queue consumer stopped[/yellow]")

    async def _consume_messages(self) -> None:
        """Main consumer loop that processes messages from Redis queues."""
        redis_client = await self._get_redis()

        # Priority order: URGENT -> HIGH -> NORMAL -> LOW
        priorities = [
            MessagePriority.URGENT,
            MessagePriority.HIGH,
            MessagePriority.NORMAL,
            MessagePriority.LOW
        ]

        last_message_time = datetime.utcnow()
        rate_limit_delay = 0

        while self._running:
            try:
                message_processed = False

                # Check each priority queue in order
                for priority in priorities:
                    queue_key = self._make_queue_key(priority)

                    # Try to get a message (non-blocking)
                    message_json = await redis_client.rpop(queue_key)
                    if message_json:
                        message = QueuedMessage.model_validate_json(message_json)
                        success = await self._process_message(message)

                        if success:
                            message_processed = True
                            last_message_time = datetime.utcnow()

                            # Implement basic rate limiting (30 messages/second max)
                            now = datetime.utcnow()
                            time_since_last = (now - last_message_time).total_seconds()
                            if time_since_last < 0.033:  # ~30 messages/second
                                rate_limit_delay = 0.033 - time_since_last
                                await asyncio.sleep(rate_limit_delay)
                        else:
                            # Re-queue failed message with incremented retry count
                            await self._handle_failed_message(message)

                        break  # Process one message at a time

                # If no message was processed, wait a bit before checking again
                if not message_processed:
                    await asyncio.sleep(0.1)

            except asyncio.CancelledError:
                console.print("[yellow]Message consumer cancelled[/yellow]")
                break
            except Exception as e:
                console.print(f"[red]Error in message consumer: {e}[/red]")
                await asyncio.sleep(1)  # Wait before retrying

    async def _process_message(self, message: QueuedMessage) -> bool:
        """Process a single message."""
        if not self._bot:
            console.print("[red]Bot instance not set in MessageQueue[/red]")
            return False

        try:
            console.print(f"[blue]Processing {message.type.value} message for chat {message.chat_id}[/blue]")

            # Prepare common parameters
            kwargs = {
                "chat_id": message.chat_id,
                "text": message.text,
            }

            if message.parse_mode:
                kwargs["parse_mode"] = message.parse_mode

            if message.disable_web_page_preview is not None:
                kwargs["disable_web_page_preview"] = message.disable_web_page_preview

            if message.keyboard:
                # Handle InlineKeyboardMarkup if provided
                from telegram import InlineKeyboardMarkup
                kwargs["reply_markup"] = InlineKeyboardMarkup.from_dict(message.keyboard)

            # Handle different message types
            if message.edit_message_id:
                # Edit existing message
                kwargs["message_id"] = message.edit_message_id
                del kwargs["chat_id"]  # edit_message_text uses chat_id differently
                kwargs["chat_id"] = message.chat_id
                await self._bot.edit_message_text(**kwargs)
            else:
                # Send new message
                if message.reply_parameters:
                    # Cross-chat reply
                    from telegram import ReplyParameters
                    kwargs["reply_parameters"] = ReplyParameters(
                        message_id=message.reply_parameters["message_id"],
                        chat_id=message.reply_parameters["chat_id"]
                    )
                elif message.reply_to_message_id:
                    kwargs["reply_to_message_id"] = message.reply_to_message_id

                sent_message = await self._bot.send_message(**kwargs)

                # Handle auto-delete if specified
                if message.delete_after:
                    asyncio.create_task(
                        self._auto_delete_message(message.chat_id, sent_message.message_id, message.delete_after)
                    )

            console.print(f"[green]Successfully processed {message.type.value} message[/green]")
            return True

        except RetryAfter as e:
            console.print(f"[yellow]Rate limited by Telegram API. Retry after {e.retry_after} seconds[/yellow]")
            # Re-queue the message with a delay
            message.scheduled_for = datetime.utcnow() + timedelta(seconds=e.retry_after)
            await self._requeue_message(message)
            return True  # Don't increment retry count for rate limits

        except TelegramError as e:
            console.print(f"[red]Telegram API error processing message: {e}[/red]")
            return False

        except Exception as e:
            console.print(f"[red]Unexpected error processing message: {e}[/red]")
            return False

    async def _handle_failed_message(self, message: QueuedMessage) -> None:
        """Handle a failed message by retrying or moving to dead letter queue."""
        message.retry_count += 1

        if message.retry_count <= message.max_retries:
            console.print(f"[yellow]Retrying message {message.message_id} (attempt {message.retry_count})[/yellow]")
            # Add exponential backoff delay
            delay = min(2 ** message.retry_count, 300)  # Max 5 minutes
            message.scheduled_for = datetime.utcnow() + timedelta(seconds=delay)
            await self._requeue_message(message)
        else:
            console.print(f"[red]Message {message.message_id} exceeded max retries, moving to dead letter queue[/red]")
            await self._move_to_dead_letter_queue(message)

    async def _requeue_message(self, message: QueuedMessage) -> None:
        """Re-queue a message, potentially with a delay."""
        if message.scheduled_for and message.scheduled_for > datetime.utcnow():
            # Use Redis to schedule the message
            redis_client = await self._get_redis()
            delay_key = f"{settings.REDIS_KEY_PREFIX}delayed_messages"
            score = message.scheduled_for.timestamp()
            await redis_client.zadd(delay_key, {message.model_dump_json(): score})
        else:
            # Re-queue immediately
            await self.publish(message)

    async def _move_to_dead_letter_queue(self, message: QueuedMessage) -> None:
        """Move a failed message to the dead letter queue for manual review."""
        redis_client = await self._get_redis()
        dlq_key = f"{settings.REDIS_KEY_PREFIX}dead_letter_queue"
        await redis_client.lpush(dlq_key, message.model_dump_json())

    async def _auto_delete_message(self, chat_id: int, message_id: int, delay: int) -> None:
        """Auto-delete a message after the specified delay."""
        await asyncio.sleep(delay)
        try:
            await self._bot.delete_message(chat_id=chat_id, message_id=message_id)
            console.print(f"[green]Auto-deleted message {message_id} from chat {chat_id}[/green]")
        except Exception as e:
            console.print(f"[yellow]Failed to auto-delete message {message_id}: {e}[/yellow]")

    async def get_queue_stats(self) -> Dict[str, int]:
        """Get statistics about the message queues."""
        redis_client = await self._get_redis()
        stats = {}

        for priority in MessagePriority:
            queue_key = self._make_queue_key(priority)
            count = await redis_client.llen(queue_key)
            stats[priority.value] = count

        # Add dead letter queue stats
        dlq_key = f"{settings.REDIS_KEY_PREFIX}dead_letter_queue"
        stats["dead_letter"] = await redis_client.llen(dlq_key)

        return stats


# Global message queue instance
message_queue = MessageQueue()