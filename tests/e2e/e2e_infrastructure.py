"""
E2E Testing Infrastructure for Real Bot Integration Testing.
Provides fixtures and utilities for testing complete bot workflows.
"""
import asyncio
import os
import uuid
from typing import Dict, List, Optional, Any, Callable
from contextlib import asynccontextmanager

from telegram import Bot, Update, CallbackQuery, Message, Chat, User
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, MessageHandler, CommandHandler, filters

from dumpyarabot import handlers, moderated_handlers, mockup_handlers
from dumpyarabot.config import settings
from dumpyarabot.message_queue import message_queue


class CallbackInjector:
    """Inject callback queries into running bot application for testing."""

    def __init__(self, application):
        self.application = application
        self.injected_updates = []

    async def inject_callback_query(
        self,
        callback_data: str,
        message: Message,
        user_id: int = 123456789,
        username: str = "test_admin",
        chat_instance: str = "test_instance"
    ) -> None:
        """Inject a callback query into the bot application."""
        # Create callback query
        callback_query = CallbackQuery(
            id=f"test_callback_{uuid.uuid4().hex[:8]}",
            from_user=User(
                id=user_id,
                is_bot=False,
                first_name="Test Admin",
                username=username
            ),
            chat_instance=chat_instance,
            data=callback_data,
            message=message
        )

        # Create update
        update = Update(
            update_id=int(uuid.uuid4().hex[:8], 16),
            callback_query=callback_query
        )

        # Process the update
        await self.application.process_update(update)
        self.injected_updates.append(update)

        # Small delay to allow async processing
        await asyncio.sleep(0.1)


class MessageMonitor:
    """Monitor and track messages across multiple chats for E2E testing."""

    def __init__(self, bot: Bot):
        self.bot = bot
        self.monitored_chats = set()
        self.message_history: Dict[int, List[Message]] = {}
        self._monitoring_task = None
        self._stop_monitoring = False

    async def start_monitoring(self, chat_ids: List[int]) -> None:
        """Start monitoring messages in specified chats."""
        self.monitored_chats.update(chat_ids)
        for chat_id in chat_ids:
            self.message_history[chat_id] = []

        self._stop_monitoring = False
        self._monitoring_task = asyncio.create_task(self._monitor_messages())

    async def stop_monitoring(self) -> None:
        """Stop monitoring messages."""
        self._stop_monitoring = True
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass

    async def _monitor_messages(self) -> None:
        """Background task to monitor messages."""
        try:
            while not self._stop_monitoring:
                for chat_id in self.monitored_chats:
                    try:
                        updates = await self.bot.get_updates(limit=10, timeout=1)
                        for update in updates:
                            if (update.message and
                                update.message.chat.id == chat_id and
                                update.message not in self.message_history[chat_id]):
                                self.message_history[chat_id].append(update.message)
                    except Exception:
                        # Ignore polling errors
                        pass

                await asyncio.sleep(0.5)  # Poll every 500ms
        except asyncio.CancelledError:
            pass

    async def wait_for_message(
        self,
        chat_id: int,
        predicate: Callable[[Message], bool],
        timeout: int = 30,
        poll_interval: float = 0.5
    ) -> Optional[Message]:
        """Wait for a message matching the predicate in the specified chat."""
        start_time = asyncio.get_event_loop().time()

        while (asyncio.get_event_loop().time() - start_time) < timeout:
            # Check existing history
            for message in self.message_history.get(chat_id, []):
                if predicate(message):
                    return message

            # Poll for new messages
            try:
                updates = await self.bot.get_updates(limit=10, timeout=1)
                for update in updates:
                    if update.message and update.message.chat.id == chat_id:
                        if update.message not in self.message_history[chat_id]:
                            self.message_history[chat_id].append(update.message)
                            if predicate(update.message):
                                return update.message
            except Exception:
                pass

            await asyncio.sleep(poll_interval)

        return None

    async def get_messages_since(self, chat_id: int, since_message: Message) -> List[Message]:
        """Get all messages in chat since the specified message."""
        messages = self.message_history.get(chat_id, [])
        since_index = -1
        for i, msg in enumerate(messages):
            if msg.message_id == since_message.message_id:
                since_index = i
                break

        if since_index >= 0:
            return messages[since_index + 1:]
        return messages

    def get_all_messages(self, chat_id: int) -> List[Message]:
        """Get all monitored messages for a chat."""
        return self.message_history.get(chat_id, [])


class ARQWorkerFixture:
    """Fixture for managing ARQ worker during E2E tests."""

    def __init__(self):
        self.worker_process = None
        self.redis_url = os.getenv('TEST_REDIS_URL', 'redis://localhost:6379/0')

    async def start_worker(self) -> None:
        """Start ARQ worker process."""
        import subprocess
        import sys

        # Start ARQ worker as subprocess
        try:
            cmd = [
                sys.executable, "-m", "arq", "worker_settings.WorkerSettings"
            ]

            # Set environment variables for the worker
            env = os.environ.copy()
            env['REDIS_URL'] = self.redis_url

            self.worker_process = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            )

            # Wait a bit for worker to start
            await asyncio.sleep(2)

            # Check if process is still running
            if self.worker_process.poll() is not None:
                stdout, stderr = self.worker_process.communicate()
                raise RuntimeError(f"ARQ worker failed to start: {stderr.decode()}")

        except Exception as e:
            print(f"Warning: Could not start ARQ worker: {e}")
            # Don't fail the test if worker can't start, just continue without it
            self.worker_process = None

    async def stop_worker(self) -> None:
        """Stop ARQ worker process."""
        if self.worker_process:
            self.worker_process.terminate()
            await asyncio.sleep(1)
            if self.worker_process.poll() is None:
                self.worker_process.kill()
            self.worker_process = None


@asynccontextmanager
async def create_test_bot_application():
    """Create and configure a test bot application with all handlers."""
    # Create application
    application = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).build()

    # Register handlers (same as main application)
    dump_handler = CommandHandler("dump", handlers.dump)
    blacklist_handler = CommandHandler("blacklist", handlers.blacklist)
    cancel_dump_handler = CommandHandler("cancel", handlers.cancel_dump)
    status_handler = CommandHandler("status", handlers.status)
    help_handler = CommandHandler("help", handlers.help_command)

    # Mockup handler for testing UI flow
    mockup_handler = CommandHandler("mockup", mockup_handlers.mockup_command)

    # Moderated request system handlers
    accept_handler = CommandHandler("accept", moderated_handlers.accept_command)
    reject_handler = CommandHandler("reject", moderated_handlers.reject_command)
    request_message_handler = MessageHandler(
        filters.TEXT & filters.Regex(r"#request"), moderated_handlers.handle_request_message
    )
    # Use enhanced callback handler that supports both production and mockup callbacks
    callback_handler = CallbackQueryHandler(moderated_handlers.handle_enhanced_callback_query)

    # Restart handler
    restart_handler = CommandHandler("restart", handlers.restart)

    # Add all handlers
    application.add_handler(dump_handler)
    application.add_handler(blacklist_handler)
    application.add_handler(cancel_dump_handler)
    application.add_handler(status_handler)
    application.add_handler(help_handler)
    application.add_handler(mockup_handler)
    application.add_handler(accept_handler)
    application.add_handler(reject_handler)
    application.add_handler(request_message_handler)
    application.add_handler(callback_handler)
    application.add_handler(restart_handler)

    # Initialize message queue
    message_queue.set_bot(application.bot)

    try:
        # Start the application
        await application.initialize()
        await application.start()

        yield application

    finally:
        # Cleanup
        await application.stop()
        await application.shutdown()


# Fixtures are defined in conftest.py to avoid pytest import issues