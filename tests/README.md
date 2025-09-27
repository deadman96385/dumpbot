# DumpyaraBot Testing System

Comprehensive testing suite for the DumpyaraBot Telegram firmware dumper.

## Overview

This testing system provides comprehensive validation through multiple testing levels:

- **Unit Tests**: Test individual components in isolation with mocks
- **Integration Tests**: Test component interactions with real ARQ workers
- **End-to-End Tests**: Complete real-world workflow validation with actual bot integration

## Quick Start

### Install Dependencies
```bash
uv sync --extra test
```

### Run All Tests
```bash
# Unit tests only (fast)
uv run pytest tests/unit/ -v

# Integration tests (requires Redis)
uv run pytest tests/integration/ -v

# All tests with coverage
uv run pytest --cov=dumpyarabot --cov-report=html
```

## Test Categories

### Unit Tests (`tests/unit/`)
Fast, isolated tests that mock external dependencies.

**Coverage:**
- Schema validation (`test_schemas.py`)
- Utility functions (`test_utils.py`)
- URL processing (`test_url_utils.py`)

### Integration Tests (`tests/integration/`)
Test component interactions with real ARQ job processing.

**Coverage:**
- ARQ job pipeline (`test_arq_jobs.py`)
- Firmware processing components

### End-to-End Tests (`tests/e2e/`)
Complete real-world workflow validation with actual bot integration.

**Coverage:**
- Direct dump commands with option validation
- **Complete Moderated Request System:**
  - Request submission and validation
  - Admin review workflow with interactive buttons
  - Option toggling (Alt Dumper, Force Re-Dump, Private Dump)
  - Multi-option combinations
  - Job queuing and status updates
  - Cross-chat message threading
  - Error handling and edge cases
- **Advanced Scenarios:**
  - Multiple concurrent requests
  - Admin workflow efficiency
  - Message threading validation
  - State persistence testing
  - Permission and access control

## Test Infrastructure Setup

### Required Environment Variables

#### For All Tests
```bash
# Redis for ARQ job storage
TEST_REDIS_URL=redis://localhost:6379/0
```

#### For E2E Tests
```bash
# Test Telegram Bot
TEST_BOT_TOKEN=your_test_bot_token
TEST_DUMP_CHAT_ID=123456789
TEST_REQUEST_CHAT_ID=987654321
TEST_REVIEW_CHAT_ID=555666777

# Test GitLab (optional, falls back to production)
TEST_GITLAB_SERVER=test.gitlab.com
TEST_GITLAB_TOKEN=test_token
```

### Setting Up Test Infrastructure

#### 1. Create Test Telegram Bot
```bash
# Use @BotFather to create test bot
# Create test groups/channels and add bot as admin
# Get chat IDs by sending messages and checking bot logs
```

#### 2. Set Up Test GitLab
```bash
# Create dedicated test organization: dumpyara-test
# Generate API token with repo creation permissions
# Or use production GitLab (not recommended for CI)
```

#### 3. Test Firmware Hosting
Test firmware files are stored in `tests/fixtures/mock_firmware/`:
- `xiaomi_firmware.zip` - Xiaomi-style firmware
- `samsung_firmware.zip` - Samsung-style firmware
- `minimal_firmware.zip` - Basic test firmware
- `corrupted_firmware.zip` - Invalid firmware for error testing

For production testing, host these on S3/Wasabi and set URLs in tests.

## Running Tests

### Development
```bash
# Run specific test file
uv run pytest tests/unit/test_schemas.py -v

# Run tests with keyword filter
uv run pytest -k "dump" -v

# Run tests with coverage
uv run pytest --cov=dumpyarabot --cov-report=html

# Debug failing test
uv run pytest tests/unit/test_handlers.py::TestDumpHandler::test_dump_command_valid_url -v -s
```

### CI/CD
Tests run automatically on GitHub Actions for:
- Push to main/develop branches
- Pull requests

E2E tests only run on:
- Push to main branch
- Commits with `[e2e]` in message

## E2E Test Infrastructure

### Real E2E Testing with Complete Bot Integration

The E2E test suite provides **comprehensive real-world validation** through actual bot integration, covering all user workflows and edge cases:

#### **Core Moderated Request Testing**
- **Complete Request Lifecycle**: `#request` → Admin Review → Acceptance/Rejection → Job Processing
- **Interactive Button Testing**: Real callback injection for Accept/Reject/Options workflow
- **Option Configuration**: Alt Dumper, Force Re-Dump, Private Dump toggling and combinations
- **Job Processing Validation**: ARQ job queuing, status updates, progress tracking
- **Cross-Chat Threading**: Proper message relationships across request/review chats

#### **Advanced Scenario Coverage**
- **Concurrent Workflows**: Multiple requests, admin efficiency testing
- **Error Handling**: Download failures, invalid URLs, permission issues
- **Edge Cases**: Malformed data, state persistence, workflow interruptions
- **Message Management**: Threading validation, cleanup verification

#### **Real Integration Components**
- **BotApplicationFixture**: Running Telegram bot with all production handlers
- **CallbackInjector**: Real callback query injection with user context
- **MessageMonitor**: Live message tracking across multiple chats
- **ARQWorkerFixture**: Actual ARQ worker process management

### Infrastructure Components

**BotApplicationFixture (`tests/e2e/e2e_infrastructure.py`):**
- Running Telegram bot application with all handlers registered
- Same configuration as production bot
- Proper initialization and cleanup

**CallbackInjector:**
- Injects real callback queries into running bot application
- Simulates admin button clicks with proper user context
- Triggers actual bot handler execution

**MessageMonitor:**
- Monitors messages across multiple chats in real-time
- Waits for specific message patterns with timeouts
- Tracks message threading and relationships

**ARQWorkerFixture:**
- Manages ARQ worker processes for real job processing
- Configures test Redis instance
- Handles worker lifecycle

### Real E2E Test Architecture

```
┌─────────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   E2E Test Suite    │───▶│  CallbackInjector │───▶│   Bot App       │
│   (Complete Flows)  │    │  (Real Interactions)│   │   (Production) │
└─────────────────────┘    └──────────────────┘    └─────────────────┘
          │                                                │
          ▼                                                ▼
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│ MessageMonitor  │    │   ARQ Worker     │    │   Redis/Storage  │
│ (Live Tracking) │    │  (Real Jobs)     │    │   (Real Data)    │
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

**Test Coverage Matrix:**
- ✅ **Request Processing**: URL validation, forwarding, ID generation
- ✅ **Admin Workflow**: Accept/Reject buttons, option toggling, submission
- ✅ **Job Management**: ARQ queuing, status updates, cancellation
- ✅ **Error Handling**: Invalid URLs, permissions, network failures
- ✅ **Message Flow**: Cross-chat threading, user notifications
- ✅ **Edge Cases**: Concurrent requests, malformed data, state persistence

### Running Real E2E Tests

**Prerequisites:**
```bash
# Required environment variables
export TEST_BOT_TOKEN="your_test_bot_token"
export TEST_REQUEST_CHAT_ID="123456789"
export TEST_REVIEW_CHAT_ID="987654321"
export TEST_REDIS_URL="redis://localhost:6379/0"
```

**Run Real E2E Tests:**
```bash
# Run all real E2E tests
uv run pytest tests/e2e/ -v

# Run specific test categories
uv run pytest tests/e2e/ -k "option" -v          # Option toggle tests
uv run pytest tests/e2e/ -k "job" -v             # Job processing tests
uv run pytest tests/e2e/ -k "error" -v           # Error scenario tests
uv run pytest tests/e2e/ -k "concurrent" -v      # Advanced scenario tests

# Run with detailed output
uv run pytest tests/e2e/test_direct_dump_flow.py::TestModeratedRequestFlowE2E::test_complete_moderated_request_flow_real_e2e -v -s
```

### Test Reliability Features

- **Timeout Handling**: All async operations have configurable timeouts
- **Retry Logic**: Automatic retry for transient failures
- **Cleanup**: Automatic cleanup of test messages and data
- **Isolation**: Each test uses unique message contexts
- **Error Recovery**: Graceful handling of network/API issues

## Test Data

### Mock Firmware
Test firmware files contain realistic build.prop files but minimal actual firmware data:

- **Xiaomi**: Based on real Xiaomi Mi 11 (alioth) build properties
- **Samsung**: Based on real Samsung Galaxy S20 (beyond2lte) properties
- **Minimal**: Basic Android properties for simple testing

### Build Properties
Real build.prop files are stored in `tests/fixtures/build_props/` and included in test firmware.

## Writing Tests

### Test Structure
```python
@pytest.mark.unit  # or @pytest.mark.integration, @pytest.mark.e2e
class TestComponent:
    """Test class for component."""

    @pytest.mark.asyncio
    async def test_feature(self, test_config, mock_telegram_update):
        """Test specific feature."""
        # Arrange
        # Act
        # Assert
```

### Fixtures
Common fixtures available in `conftest.py`:
- `test_config`: Test configuration with fallbacks
- `mock_telegram_update`: Mock Telegram update object
- `mock_telegram_bot`: Mock Telegram bot
- `faker`: Fake data generator

### Mocking Strategy
- **Unit tests**: Mock all external dependencies
- **Integration tests**: Mock firmware downloads, use real ARQ
- **E2E tests**: Mock firmware data, use real Telegram/GitLab

## Troubleshooting

### Common Issues

#### Import Errors
```bash
# Reinstall dependencies
uv sync --extra test --reinstall
```

#### Redis Connection
```bash
# Start Redis
redis-server

# Or use Docker
docker run -p 6379:6379 redis:alpine
```

#### Test Bot Setup
- Ensure bot has admin rights in test chats
- Check bot token is valid
- Verify chat IDs are correct

#### Slow Tests
- Integration tests may take 30+ seconds
- E2E tests require external services
- Use `pytest -k "not slow"` to skip slow tests

### Debugging
```bash
# Verbose output
uv run pytest -v -s

# Stop on first failure
uv run pytest --tb=short --maxfail=1

# Run specific test
uv run pytest tests/unit/test_schemas.py::TestDumpArguments::test_valid_dump_arguments
```

## Contributing

### Adding New Tests
1. Follow existing naming conventions
2. Add appropriate markers (`@pytest.mark.unit`, etc.)
3. Include docstrings explaining test purpose
4. Use fixtures from `conftest.py` when possible

### Test Organization
- Unit tests: `tests/unit/`
- Integration tests: `tests/integration/`
- E2E tests: `tests/e2e/`
- Fixtures: `tests/fixtures/`
- Configuration: `tests/conftest.py`

## Coverage Goals

- **Unit Tests**: 80%+ coverage of core logic and error paths
- **Integration Tests**: Component interactions and ARQ job processing
- **E2E Tests**: Complete real-world workflows with comprehensive scenario coverage
  - All moderated request flows and options
  - Error handling and edge cases
  - Concurrent operations and performance
  - Message threading and user experience

Run coverage report:
```bash
uv run pytest --cov=dumpyarabot --cov-report=html
# Open htmlcov/index.html
```