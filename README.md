# DumpyaraBot

A Telegram bot for AndroidDumps that uses ARQ (Async Redis Queue) for distributed job processing with rich metadata tracking. The bot supports direct dump commands, a moderated request system, and automated blacklist processing for community contributions.

## 🔗 Bot Link
https://t.me/dumpyarabot

## ✨ Features

- **Direct Dump Commands**: `/dump` command for authorized users and chats
- **Moderated Request System**: Users can submit `#request` messages for admin review
- **Private Dumps**: Support for private dumps that auto-delete trigger messages
- **ARQ Integration**: Automated firmware extraction and GitLab repository creation
- **Cross-Chat Support**: Status updates with proper message threading
- **Admin Controls**: Bot restart and job cancellation with permission checks

## 🚀 Quick Setup

### Prerequisites

- Python 3.8+
- [uv](https://github.com/astral-sh/uv) package manager
- Telegram Bot Token from [@BotFather](https://t.me/BotFather)
- ARQ worker processes for `dumpyara` and `privdump` job handling
- Redis server (optional, for persistent storage)

### Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd dumpbot
   ```

2. **Install dependencies**
   ```bash
   # Install base dependencies
   uv sync
   ```

3. **Configure environment variables**

   Create a `.env` file or set the following environment variables:

    **Required:**
    ```bash
    TELEGRAM_BOT_TOKEN=your_bot_token_here
    ALLOWED_CHATS=[-1001234567890, -1001234567891]
    REQUEST_CHAT_ID=-1001234567892
    REVIEW_CHAT_ID=-1001234567893
    DUMPER_TOKEN=your_gitlab_api_token
    API_KEY=your_telegram_bot_token_for_updates
    ```

   **Optional:**
   ```bash
   REDIS_URL=redis://localhost:6379/0
   ```

4. **Run the bot**
   ```bash
   uv run python -m dumpyarabot
   ```

## 📋 Commands

### User Commands

#### `/dump [URL] [options]`
Initiate a new firmware dump process (authorized chats only).

**Parameters:**
- `URL`: The URL of the firmware to be dumped (required)

**Options:**
- `a`: Use alternative dumper
- `f`: Force a new dump even if an existing one is found
- `b`: Add the URL to blacklist
- `p`: Use private dump (deletes original message)

**Examples:**
```
/dump https://example.com/firmware.zip
/dump https://example.com/firmware.zip af
/dump https://example.com/firmware.zip p
```

#### `/help`
Show available commands and usage information.

#### `#request [URL]`
Submit a firmware dump request for admin review (request chat only).

**Example:**
```
#request https://example.com/firmware.zip Please dump this new OTA update
```

### Admin Commands

#### `/accept [request_id] [options]`
Accept a pending dump request with optional parameters.

**Examples:**
```
/accept a1b2c3d4
/accept a1b2c3d4 af
```

#### `/reject [request_id] [reason]`
Reject a pending dump request with optional reason.

**Examples:**
```
/reject a1b2c3d4
/reject a1b2c3d4 Invalid URL format
```

#### `/cancel [job_id] [options]`
Cancel an ongoing ARQ job (admin only).

**Options:**
- `p`: Cancel privdump job instead of regular dumpyara job

**Examples:**
```
/cancel 123
/cancel 456 p
```

#### `/restart`
Restart the bot with admin confirmation dialog (admin only).

#### `/mockup`
Generate test UI components for development purposes.

## 🏗 Architecture

### Core Components

- **`dumpyarabot/handlers.py`**: Main command handlers (dump, cancel, restart, help)
- **`dumpyarabot/moderated_handlers.py`**: Moderated request system handlers
- **`dumpyarabot/utils.py`**: Jenkins integration utilities
- **`dumpyarabot/schemas.py`**: Pydantic models for data validation
- **`dumpyarabot/storage.py`**: Data access layer with Redis support
- **`dumpyarabot/ui.py`**: User interface components and message templates
- **`dumpyarabot/config.py`**: Environment-based configuration

### Authorization System

1. **Chat-level**: Only allowed chats can use commands
2. **User-level**: Admin commands require Telegram admin permissions

### Request Flow

1. **User submits**: `#request [URL]` in request chat
2. **Bot validates**: URL format and creates review message
3. **Admin reviews**: Accept/reject with options in review chat
4. **Processing**: Jenkins job triggered with parameters
5. **Status updates**: Cross-chat threading maintains conversation flow

## 🔧 Development

### Code Quality Tools

```bash
# Format code
uv run black .

# Sort imports
uv run isort .

# Lint with ruff
uv run ruff check .

# Type checking
uv run mypy dumpyarabot/
```

### Development Workflow

**Important**: After making code changes, always restart the bot:

1. Stop any running bot processes
2. Start a new bot instance
3. Test the changes

The bot runs as a long-running process and won't pick up code changes until restarted.

### Testing

The project includes a comprehensive testing system with unit, integration, and end-to-end tests.

#### Quick Test Commands
```bash
# Install test dependencies
uv sync --extra test

# Run all tests with coverage
uv run pytest --cov=dumpyarabot --cov-report=html

# Run specific test categories
uv run pytest tests/unit/ -v          # Unit tests only (fast)
uv run pytest tests/integration/ -v   # Integration tests (requires Redis)
uv run pytest tests/e2e/ -v           # E2E tests (requires test infrastructure)
```

#### Test Infrastructure Setup
For end-to-end tests, set up test infrastructure:

```bash
# Test Telegram Bot (create via @BotFather)
TEST_BOT_TOKEN=your_test_bot_token
TEST_DUMP_CHAT_ID=123456789
TEST_REQUEST_CHAT_ID=987654321
TEST_REVIEW_CHAT_ID=555666777

# Test GitLab (optional)
TEST_GITLAB_SERVER=test.gitlab.com
TEST_GITLAB_TOKEN=test_token

# Redis for ARQ
TEST_REDIS_URL=redis://localhost:6379/0
```

#### Test Categories
- **Unit Tests**: Fast isolated tests for individual components
- **Integration Tests**: Component interactions with real ARQ workers
- **End-to-End Tests**: Complete user workflows with real services

Test firmware fixtures are available in `tests/fixtures/mock_firmware/` for realistic testing scenarios.

## 📊 ARQ Integration

The bot uses ARQ (Async Redis Queue) for distributed job processing with integrated firmware extraction:

### Supported Features
- **URL Mirror Optimization**: Automatic CDN selection for better download speeds
- **Multiple Extraction Methods**: Python dumper and alternative Firmware_extractor
- **GitLab Integration**: Automatic repository creation and branch management
- **Cross-Chat Status Updates**: Progress messages with proper threading
- **Error Handling**: Comprehensive error reporting and recovery

### ARQ Job Processing
Jobs are processed asynchronously using ARQ workers with the following components:
- `FirmwareDownloader`: URL optimization and download handling
- `FirmwareExtractor`: Partition extraction and boot image processing
- `PropertyExtractor`: Device metadata and property extraction
- `GitLabManager`: Repository management and notifications

## 🔄 Storage Options

### In-Memory Storage (Default)
Basic bot_data storage that resets on restart.

### Redis Storage (Recommended)
Persistent storage that survives bot restarts:

```bash
# Install Redis
# Ubuntu/Debian: apt install redis-server
# macOS: brew install redis
# Windows: Use Redis on Windows or Docker

# Set Redis URL
export REDIS_URL=redis://localhost:6379/0
```

## 🚨 Error Handling

The bot includes comprehensive error handling:

- **Network failures**: Automatic retries and fallback mechanisms
- **ARQ errors**: Detailed error reporting with job logs
- **Permission errors**: Clear error messages for unauthorized access
- **Validation errors**: User-friendly error messages for invalid inputs

## 🔐 Security Considerations

- **Token Security**: Never commit bot tokens to version control
- **Chat Restrictions**: Only authorized chats can use commands
- **Admin Verification**: Admin commands check Telegram permissions
- **Input Validation**: All URLs and parameters are validated
- **Private Dumps**: Automatically delete sensitive messages

## 📈 Monitoring

The bot provides detailed logging:

```bash
# View logs while running
uv run python -m dumpyarabot

# Check for successful startup
# Look for: "Application started"
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes following the code quality guidelines
4. Test thoroughly including restart functionality
5. Submit a pull request

## 📝 License

[License information]

## 🆘 Support

For issues, feature requests, or questions:
- Create an issue in the repository
- Contact the maintainers via Telegram

---

*This bot is designed for the AndroidDumps community to streamline firmware dump processes and GitLab repository management.*