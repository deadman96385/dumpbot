"""
Shared test configuration and fixtures for dumpyarabot tests.
"""
import asyncio
import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from faker import Faker

from dumpyarabot.config import Settings
from dumpyarabot.schemas import JobMetadata


@pytest.fixture(scope="session")
def event_loop_policy():
    """Create event loop policy for async tests."""
    return asyncio.get_event_loop_policy()


@pytest.fixture
def faker():
    """Provide faker instance for generating test data."""
    return Faker()


def load_test_config():
    """Load test config with fallback to production values."""
    # Test-specific overrides from environment
    test_overrides = {
        'telegram_bot_token': os.getenv('TEST_BOT_TOKEN'),
        'allowed_chats': [int(os.getenv('TEST_DUMP_CHAT_ID', 0))] if os.getenv('TEST_DUMP_CHAT_ID') else None,
        'request_chat_id': int(os.getenv('TEST_REQUEST_CHAT_ID', 0)) if os.getenv('TEST_REQUEST_CHAT_ID') else None,
        'review_chat_id': int(os.getenv('TEST_REVIEW_CHAT_ID', 0)) if os.getenv('TEST_REVIEW_CHAT_ID') else None,
        'gitlab_server': os.getenv('TEST_GITLAB_SERVER'),
        'gitlab_token': os.getenv('TEST_GITLAB_TOKEN'),
        'redis_url': os.getenv('TEST_REDIS_URL'),
    }

    # Load production config as base
    prod_config = Settings()

    # Override with test values where provided
    for key, value in test_overrides.items():
        if value is not None:  # Only override if test value exists
            setattr(prod_config, key, value)

    return prod_config


@pytest.fixture
def test_config():
    """Test configuration with test credentials."""
    return load_test_config()


@pytest.fixture
def mock_telegram_update(faker):
    """Mock Telegram update object."""
    update = MagicMock()
    # Ensure all nested objects exist
    update.effective_chat = MagicMock()
    update.effective_chat.id = faker.random_int(min=100000000, max=999999999)
    update.effective_message = MagicMock()
    update.effective_message.chat = update.effective_chat
    update.effective_message.message_id = faker.random_int(min=1, max=1000)
    update.effective_message.text = "/dump https://example.com/firmware.zip"
    update.effective_message.from_user = MagicMock()
    update.effective_message.from_user.id = faker.random_int(min=100000000, max=999999999)
    update.effective_message.from_user.username = faker.user_name()
    update.effective_message.from_user.first_name = faker.first_name()

    # Add effective_user
    update.effective_user = update.effective_message.from_user

    # Add reply_to_message for moderated handlers
    update.effective_message.reply_to_message = MagicMock()
    update.effective_message.reply_to_message.text = "Sample replied message with Request ID: abc12345"

    # Add callback_query
    update.callback_query = MagicMock()
    update.callback_query.answer = AsyncMock()
    update.callback_query.from_user = update.effective_user
    update.callback_query.message = update.effective_message


    return update


@pytest.fixture
def mock_telegram_bot():
    """Mock Telegram bot instance."""
    bot = MagicMock()
    bot.send_message = AsyncMock()
    bot.edit_message_text = AsyncMock()
    bot.delete_message = AsyncMock()
    return bot


@pytest.fixture
def mock_message_queue():
    """Mock message queue with all necessary async methods."""
    queue = MagicMock()
    queue.send_reply = AsyncMock()
    queue.send_error = AsyncMock()
    queue.send_immediate_message = AsyncMock(return_value=MagicMock(message_id=123))
    queue.queue_dump_job_with_metadata = AsyncMock(return_value="test_job_123")
    queue.cancel_job = AsyncMock(return_value=True)
    queue.get_job_status = AsyncMock(return_value=None)
    queue.get_active_jobs_with_metadata = AsyncMock(return_value=[])
    queue.get_recent_jobs_with_metadata = AsyncMock(return_value=[])
    queue.publish = AsyncMock()
    queue.publish_and_return_placeholder = AsyncMock(return_value=MagicMock(message_id=123))
    queue.edit_message = AsyncMock()
    queue.edit_message_text = AsyncMock()
    queue.send_cross_chat = AsyncMock()
    return queue


@pytest.fixture
def mock_settings(mock_telegram_update):
    """Mock settings with proper defaults."""
    settings = MagicMock()
    settings.ALLOWED_CHATS = [mock_telegram_update.effective_chat.id]
    settings.DEFAULT_PARSE_MODE = "Markdown"
    settings.TELEGRAM_BOT_TOKEN = "test_token"
    return settings


@pytest.fixture
def mock_arq_context():
    """Mock ARQ worker context."""
    context = MagicMock()
    context.redis = MagicMock()
    return context


@pytest.fixture(autouse=True)
async def cleanup_test_data():
    """Clean up test data between tests."""
    # This fixture runs automatically before/after each test
    yield
    # Cleanup logic would go here if needed


# Test markers configuration is now in pyproject.toml


# Real E2E Test Fixtures

@pytest.fixture
async def bot_application():
    """Provide a running bot application for real E2E testing."""
    from tests.e2e.e2e_infrastructure import create_test_bot_application
    async with create_test_bot_application() as app:
        yield app


@pytest.fixture
async def callback_injector(bot_application):
    """Provide callback injector for real callback testing."""
    from tests.e2e.e2e_infrastructure import CallbackInjector
    return CallbackInjector(bot_application)


@pytest.fixture
async def message_monitor(bot_application):
    """Provide message monitor for tracking messages across chats."""
    from tests.e2e.e2e_infrastructure import MessageMonitor
    monitor = MessageMonitor(bot_application.bot)
    yield monitor
    await monitor.stop_monitoring()


@pytest.fixture
async def arq_worker_fixture():
    """Provide ARQ worker fixture for real job processing."""
    from tests.e2e.e2e_infrastructure import ARQWorkerFixture
    worker = ARQWorkerFixture()
    await worker.start_worker()
    yield worker
    await worker.stop_worker()