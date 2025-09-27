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
import telegram

from dumpyarabot.config import settings
from dumpyarabot.schemas import DumpJob, JobStatus

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
    parse_mode: str
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
        if "parse_mode" not in data or data.get("parse_mode") is None:
            data["parse_mode"] = settings.DEFAULT_PARSE_MODE
        super().__init__(**data)


# Rebuild the model to resolve any forward references
QueuedMessage.model_rebuild()

class MessageQueue:
    """Redis-based message queue for unified Telegram messaging."""

    def __init__(self):
        self._redis: Optional[redis.Redis] = None
        self._consumer_task: Optional[asyncio.Task] = None
        self._running = False
        self._bot: Optional[Bot] = None
        self._last_edit_times: Dict[str, datetime] = {}  # Track edit times by message_id

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
        parse_mode: Optional[str] = settings.DEFAULT_PARSE_MODE,
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
        parse_mode: Optional[str] = settings.DEFAULT_PARSE_MODE,
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """Send a status update message."""
        # Ensure parse_mode is always set to a valid value
        if parse_mode is None:
            parse_mode = settings.DEFAULT_PARSE_MODE
        message = QueuedMessage(
            type=MessageType.STATUS_UPDATE,
            priority=MessagePriority.NORMAL,
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            edit_message_id=edit_message_id,
            disable_web_page_preview=True,
            context=context or {}
        )
        await self.publish(message)

    async def send_cross_chat(
        self,
        chat_id: int,
        text: str,
        reply_to_message_id: int,
        reply_to_chat_id: int,
        parse_mode: Optional[str] = settings.DEFAULT_PARSE_MODE,
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
        parse_mode: Optional[str] = settings.DEFAULT_PARSE_MODE,
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
            parse_mode=settings.DEFAULT_PARSE_MODE,
            context=context or {}
        )
        await self.publish(message)

    class MessagePlaceholder:
        """Placeholder object that mimics a Telegram Message for compatibility."""
        def __init__(self, message_id: str, chat_id: int):
            self.message_id = message_id
            self.chat = type('Chat', (), {'id': chat_id})()

    async def publish_and_return_placeholder(
        self,
        message: QueuedMessage
    ) -> "MessageQueue.MessagePlaceholder":
        """Publish message and return a placeholder object for compatibility."""
        message_id = await self.publish(message)
        return self.MessagePlaceholder(message_id, message.chat_id)

    async def send_immediate_message(
        self,
        chat_id: int,
        text: str,
        parse_mode: str = settings.DEFAULT_PARSE_MODE,
        reply_to_message_id: Optional[int] = None,
        disable_web_page_preview: bool = True
    ) -> "telegram.Message":
        """Send message directly via bot and return real Telegram Message object.

        This bypasses the queue entirely and provides immediate access to the real
        Telegram message ID for subsequent editing operations.

        Args:
            chat_id: The Telegram chat ID
            text: The message text
            parse_mode: Telegram parse mode (default: Markdown)
            reply_to_message_id: Optional message ID to reply to

        Returns:
            Real Telegram Message object with integer message_id

        Raises:
            Exception: If bot is not initialized
        """
        if not self._bot:
            raise Exception("Bot not initialized - cannot send immediate message")

        console.print(f"[blue]Sending immediate message to chat {chat_id} with parse_mode={parse_mode}[/blue]")

        message = await self._bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            reply_to_message_id=reply_to_message_id,
            disable_web_page_preview=disable_web_page_preview
        )

        console.print(f"[green]Sent immediate message {message.message_id} to chat {chat_id}[/green]")
        return message

    async def send_immediate_status_update(
        self,
        chat_id: int,
        text: str,
        context: Optional[Dict[str, Any]] = None
    ) -> "MessageQueue.MessagePlaceholder":
        """Send a status update message immediately and return a message placeholder for tracking.

        This method is used when you need to get a message reference immediately
        for later editing or tracking purposes.

        Args:
            chat_id: The Telegram chat ID
            text: The status message text
            context: Optional context for tracking

        Returns:
            MessagePlaceholder object with message_id for tracking
        """
        message = QueuedMessage(
            type=MessageType.STATUS_UPDATE,
            priority=MessagePriority.HIGH,  # Higher priority for immediate messages
            chat_id=chat_id,
            text=text,
            parse_mode=settings.DEFAULT_PARSE_MODE,
            context=context or {}
        )
        return await self.publish_and_return_placeholder(message)

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
            parse_mode_info = f" with parse_mode={message.parse_mode}" if message.parse_mode else " with NO parse_mode"
            console.print(f"[blue]Processing {message.type.value} message for chat {message.chat_id}{parse_mode_info}[/blue]")

            # Prepare common parameters
            kwargs = {
                "chat_id": message.chat_id,
                "text": message.text,
            }

            if message.parse_mode:
                kwargs["parse_mode"] = message.parse_mode
                message.parse_mode = settings.DEFAULT_PARSE_MODE

            if message.disable_web_page_preview is not None:
                kwargs["disable_web_page_preview"] = message.disable_web_page_preview

            if message.keyboard:
                # Handle InlineKeyboardMarkup if provided
                from telegram import InlineKeyboardMarkup
                # Reconstruct InlineKeyboardMarkup from dict
                kwargs["reply_markup"] = InlineKeyboardMarkup.de_json(message.keyboard, bot=self._bot)

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

    # ========== JOB QUEUE FUNCTIONALITY ==========

    def _make_job_queue_key(self) -> str:
        """Create Redis key for the job queue."""
        return f"{settings.REDIS_KEY_PREFIX}job_queue"

    def _make_job_key(self, job_id: str) -> str:
        """Create Redis key for individual job data."""
        return f"{settings.REDIS_KEY_PREFIX}job:{job_id}"

    def _make_worker_key(self, worker_id: str) -> str:
        """Create Redis key for worker heartbeat."""
        return f"{settings.REDIS_KEY_PREFIX}worker:{worker_id}"

    async def queue_dump_job(self, job: DumpJob) -> str:
        """Add a dump job to the worker queue."""
        redis_client = await self._get_redis()
        job_queue_key = self._make_job_queue_key()
        job_key = self._make_job_key(job.job_id)

        # Store job data
        job_json = job.model_dump_json()
        await redis_client.set(job_key, job_json)

        # Add job ID to queue (LPUSH for FIFO with RPOP)
        await redis_client.lpush(job_queue_key, job.job_id)

        console.print(f"[green]Queued dump job {job.job_id} for URL: {job.dump_args.url}[/green]")
        return job.job_id

    async def get_next_job(self, worker_id: str) -> Optional[DumpJob]:
        """Get the next job from the queue for a worker."""
        redis_client = await self._get_redis()
        job_queue_key = self._make_job_queue_key()

        # Get next job ID (blocking for up to 1 second)
        result = await redis_client.brpop(job_queue_key, timeout=1)
        if not result:
            return None

        _, job_id = result
        job_key = self._make_job_key(job_id)

        # Get job data
        job_json = await redis_client.get(job_key)
        if not job_json:
            console.print(f"[red]Job {job_id} not found in Redis[/red]")
            return None

        job = DumpJob.model_validate_json(job_json)

        # Update job status and assign worker
        job.status = JobStatus.PROCESSING
        job.worker_id = worker_id
        job.started_at = datetime.utcnow()

        # Save updated job
        await redis_client.set(job_key, job.model_dump_json())

        # Update worker heartbeat
        worker_key = self._make_worker_key(worker_id)
        await redis_client.setex(worker_key, 300, job_id)  # 5 minute TTL

        console.print(f"[blue]Assigned job {job_id} to worker {worker_id}[/blue]")
        return job

    def _should_throttle_edit(self, message_id: str, min_interval: float = 2.0) -> bool:
        """Check if message edit should be throttled based on rate limiting."""
        now = datetime.utcnow()
        last_edit = self._last_edit_times.get(message_id)

        if last_edit and (now - last_edit).total_seconds() < min_interval:
            return True

        self._last_edit_times[message_id] = now
        return False

    async def send_job_progress_update(
        self,
        job_id: str,
        progress_data: Dict[str, Any],
        edit_message_id: Optional[int] = None,
        chat_id: Optional[int] = None
    ) -> None:
        """Send a job progress update that edits the initial message."""
        if not edit_message_id or not chat_id:
            console.print(f"[yellow]No message reference for job {job_id}, skipping progress update[/yellow]")
            return

        # Apply rate limiting for message edits
        message_key = f"{chat_id}:{edit_message_id}"
        if self._should_throttle_edit(message_key):
            console.print(f"[yellow]Throttling edit for job {job_id} due to rate limiting[/yellow]")
            return

        message = QueuedMessage(
            type=MessageType.STATUS_UPDATE,
            priority=MessagePriority.NORMAL,
            chat_id=chat_id,
            text=progress_data.get("formatted_message", "Progress update"),
            edit_message_id=edit_message_id,
            parse_mode=settings.DEFAULT_PARSE_MODE,
            context={"job_id": job_id, "progress": True}
        )
        await self.publish(message)

    async def send_cross_chat_edit(
        self,
        chat_id: int,
        text: str,
        edit_message_id: int,
        reply_to_message_id: int,
        reply_to_chat_id: int,
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """Send a cross-chat message edit with reply parameters."""
        reply_params = {
            "message_id": reply_to_message_id,
            "chat_id": reply_to_chat_id
        }

        message = QueuedMessage(
            type=MessageType.CROSS_CHAT,
            priority=MessagePriority.NORMAL,
            chat_id=chat_id,
            text=text,
            parse_mode=settings.DEFAULT_PARSE_MODE,
            edit_message_id=edit_message_id,
            reply_parameters=reply_params,
            disable_web_page_preview=True,
            context=context or {}
        )
        await self.publish(message)

    async def update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        progress: Optional[Dict[str, Any]] = None,
        error_details: Optional[str] = None,
        result_data: Optional[Dict[str, Any]] = None,
        job_data: Optional[DumpJob] = None
    ) -> bool:
        """Update job status and progress."""
        redis_client = await self._get_redis()
        job_key = self._make_job_key(job_id)

        # Use provided job_data or get from Redis
        if job_data:
            job = job_data
        else:
            job_json = await redis_client.get(job_key)
            if not job_json:
                console.print(f"[red]Job {job_id} not found for status update[/red]")
                return False
            job = DumpJob.model_validate_json(job_json)

        # Update job fields
        job.status = status
        if progress:
            from dumpyarabot.schemas import JobProgress
            job.progress = JobProgress(**progress)
        if error_details:
            job.error_details = error_details
        if result_data:
            job.result_data = result_data

        # Set completion time for terminal states
        if status in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]:
            job.completed_at = datetime.utcnow()

        # Save updated job
        await redis_client.set(job_key, job.model_dump_json())

        console.print(f"[blue]Updated job {job_id} status to {status.value}[/blue]")
        return True

    async def get_job_status(self, job_id: str) -> Optional[DumpJob]:
        """Get current status of a job."""
        redis_client = await self._get_redis()
        job_key = self._make_job_key(job_id)

        job_json = await redis_client.get(job_key)
        if not job_json:
            return None

        return DumpJob.model_validate_json(job_json)

    async def cancel_job(self, job_id: str) -> bool:
        """Cancel a job (if it's still queued or processing)."""
        redis_client = await self._get_redis()
        job_key = self._make_job_key(job_id)

        # Get current job
        job_json = await redis_client.get(job_key)
        if not job_json:
            console.print(f"[red]Job {job_id} not found for cancellation[/red]")
            return False

        job = DumpJob.model_validate_json(job_json)

        # Only cancel if job is still cancellable
        if job.status in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]:
            console.print(f"[yellow]Job {job_id} cannot be cancelled (status: {job.status.value})[/yellow]")
            return False

        # Update status
        job.status = JobStatus.CANCELLED
        job.completed_at = datetime.utcnow()
        await redis_client.set(job_key, job.model_dump_json())

        # If job is queued, remove from queue
        if job.status == JobStatus.QUEUED:
            job_queue_key = self._make_job_queue_key()
            await redis_client.lrem(job_queue_key, 1, job_id)

        console.print(f"[green]Cancelled job {job_id}[/green]")
        return True

    async def get_job_queue_stats(self) -> Dict[str, Any]:
        """Get statistics about the job queue."""
        redis_client = await self._get_redis()

        # Count jobs in queue
        job_queue_key = self._make_job_queue_key()
        queued_count = await redis_client.llen(job_queue_key)

        # Count jobs by status
        status_counts = {status.value: 0 for status in JobStatus}

        # Get all job keys
        job_pattern = f"{settings.REDIS_KEY_PREFIX}job:*"
        job_keys = await redis_client.keys(job_pattern)

        total_jobs = len(job_keys)

        for job_key in job_keys:
            job_json = await redis_client.get(job_key)
            if job_json:
                job = DumpJob.model_validate_json(job_json)
                status_counts[job.status.value] += 1

        # Count active workers
        worker_pattern = f"{settings.REDIS_KEY_PREFIX}worker:*"
        worker_keys = await redis_client.keys(worker_pattern)
        active_workers = len(worker_keys)

        return {
            "total_jobs": total_jobs,
            "queued_jobs": queued_count,
            "active_workers": active_workers,
            "status_breakdown": status_counts,
            "worker_keys": [key.decode() for key in worker_keys] if worker_keys else []
        }


# Global message queue instance
message_queue = MessageQueue()