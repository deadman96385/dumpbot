# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is **dumpyarabot**, a Telegram bot for AndroidDumps that uses ARQ (Async Redis Queue) for distributed job processing to manage firmware dump processes. The bot handles `/dump` and `/cancel` commands for authorized users and chats, with support for both public dumps (`dumpyara`) and private dumps (`privdump`). It also includes a **moderated request system** that allows users to submit requests for review before processing.

The bot features a unified job processing system with comprehensive metadata tracking, enabling rich status displays and detailed error diagnostics across all entry points (direct dumps, moderated requests, and blacklist operations).

## System Architecture Overview

### Unified Job Processing Pipeline

The bot implements a single, unified job processing system that handles all firmware dump requests through ARQ:

**Entry Points:**
- **Direct Commands**: `/dump [URL] [options]` - Immediate processing for authorized users
- **Moderated Requests**: `#request [URL]` → Admin review → `/accept [id] [options]` - User submissions requiring approval
- **Blacklist Operations**: `/dump [URL] b` - URL blacklisting with automatic dump processing

**Core Processing Flow:**
1. **Request Validation** → URL validation, authorization checks, duplicate detection
2. **Job Initialization** → ARQ job creation with comprehensive metadata tracking
3. **Firmware Processing** → Download, extraction, analysis, GitLab repository creation
4. **Status Updates** → Progressive messaging with cross-chat threading support
5. **Completion/Error Handling** → Repository links or detailed error diagnostics

**Key Architectural Benefits:**
- **Single Source of Truth**: All job data stored in ARQ with automatic TTL management
- **Rich Metadata Tracking**: 25+ metadata fields tracking job lifecycle, device info, progress, errors
- **Unified Processing**: Identical processing pipeline regardless of entry point
- **Progressive Enhancement**: Messages show increasing detail as jobs progress
- **Cross-Chat Messaging**: Maintains conversation flow across different Telegram chats

## Development Commands

### Package Management
```bash
# Install dependencies (includes ARQ for job processing)
uv sync

# Run the application
python -m dumpyarabot

# Run ARQ worker (for job processing)
arq worker_settings.WorkerSettings
# Or alternatively:
# python run_arq_worker.py

# Or directly with uv
uv run python -m dumpyarabot
uv run python run_arq_worker.py
```

### Development Workflow
**IMPORTANT**: After making any code changes, always restart the bot to ensure changes take effect:
1. Kill any running bot processes
2. Start a new bot instance
3. Test the changes

This is critical since the bot runs as a long-running process and won't pick up code changes until restarted.

### Code Quality
```bash
# Format code
uv run black .

# Sort imports
uv run isort .

# Lint with ruff
uv run ruff check .

# Remove unused imports
uv run autoflake --in-place --remove-all-unused-imports --recursive .

# Type checking
uv run mypy dumpyarabot/
```

## Testing System

The project includes a comprehensive 3-tier testing system to ensure code quality and prevent regressions.

### Test Categories

#### Unit Tests (`tests/unit/`)
Fast, isolated tests that mock external dependencies to test individual components.

**Coverage:**
- Schema validation (`test_schemas.py`)
- Utility functions (`test_utils.py`)
- URL processing (`test_url_utils.py`)
- Message formatting (`test_message_formatting.py`)
- Message queue operations (`test_message_queue.py`)
- Moderated handlers (`test_moderated_handlers.py`)
- Telegram bot handlers (`test_handlers.py`)

#### Integration Tests (`tests/integration/`)
Test component interactions with real ARQ job processing but mocked external services.

**Coverage:**
- ARQ job pipeline (`test_arq_jobs.py`)
- Firmware processing components with mocked downloads/GitLab

#### End-to-End Tests (`tests/e2e/`)
Complete user workflow testing with real Telegram and GitLab APIs.

**Coverage:**
- Direct dump commands (`test_direct_dump_flow.py`)
- Moderated request flow (`test_moderated_request_flow.py`)

### Test Infrastructure Setup

#### Required Environment Variables for E2E Tests
```bash
# Test Telegram Bot
TEST_BOT_TOKEN=your_test_bot_token
TEST_DUMP_CHAT_ID=123456789
TEST_REQUEST_CHAT_ID=987654321
TEST_REVIEW_CHAT_ID=555666777

# Test GitLab (optional, falls back to production)
TEST_GITLAB_SERVER=test.gitlab.com
TEST_GITLAB_TOKEN=test_token

# Redis for ARQ job storage
TEST_REDIS_URL=redis://localhost:6379/0
```

#### Test Data
Test firmware files are stored in `tests/fixtures/mock_firmware/`:
- `xiaomi_firmware.zip` - Xiaomi-style firmware with realistic build properties
- `samsung_firmware.zip` - Samsung-style firmware
- `minimal_firmware.zip` - Basic test firmware
- `corrupted_firmware.zip` - Invalid firmware for error testing

Build properties are stored in `tests/fixtures/build_props/` with real device data.

### Running Tests

#### Development
```bash
# Install test dependencies
uv sync --extra test

# Run all tests with coverage
uv run pytest --cov=dumpyarabot --cov-report=html

# Run specific test categories
uv run pytest tests/unit/ -v          # Unit tests only (fast)
uv run pytest tests/integration/ -v   # Integration tests (requires Redis)
uv run pytest tests/e2e/ -v           # E2E tests (requires test infrastructure)

# Run tests with keyword filter
uv run pytest -k "dump" -v

# Debug failing test
uv run pytest tests/unit/test_schemas.py::TestDumpArguments::test_valid_dump_arguments -v -s
```

#### CI/CD
Tests run automatically on GitHub Actions:
- **Push to main/develop**: Unit and integration tests
- **Push to main with `[e2e]` in commit**: Includes E2E tests
- **Pull requests**: Unit and integration tests

### Test Configuration

#### Fixtures (`tests/conftest.py`)
Common test fixtures available across all test files:
- `test_config`: Test configuration with environment fallbacks
- `mock_telegram_update`: Mock Telegram update objects
- `mock_telegram_bot`: Mock Telegram bot instance
- `mock_arq_context`: Mock ARQ worker context
- `faker`: Fake data generator for test data

#### Test Markers
```python
@pytest.mark.unit      # Unit tests
@pytest.mark.integration  # Integration tests
@pytest.mark.e2e       # End-to-end tests
@pytest.mark.slow      # Slow running tests
```

### Writing Tests

#### Test Structure
```python
@pytest.mark.unit
class TestComponent:
    """Test class for component."""

    @pytest.mark.asyncio
    async def test_feature(self, test_config, mock_telegram_update):
        """Test specific feature."""
        # Arrange
        # Act
        # Assert
```

#### Mocking Strategy
- **Unit tests**: Mock all external dependencies (Telegram, ARQ, GitLab)
- **Integration tests**: Mock firmware downloads and GitLab, use real ARQ
- **E2E tests**: Mock firmware data, use real Telegram/GitLab APIs

### Coverage Goals

- **Unit Tests**: 80%+ coverage of core logic
- **Integration Tests**: Critical user paths and component interactions
- **E2E Tests**: Main user workflows (direct dumps, moderated requests)

Run coverage report:
```bash
uv run pytest --cov=dumpyarabot --cov-report=html
# Open htmlcov/index.html
```

## Architecture

### Core Components

**`dumpyarabot/__main__.py`** - Application entry point that sets up the Telegram bot with command handlers

**`dumpyarabot/handlers.py`** - Contains the main command handlers:
- `dump()` - Handles `/dump [URL] [options]` command for initiating firmware dumps via ARQ jobs
- `cancel_dump()` - Handles `/cancel [job_id]` command for cancelling ARQ jobs (admin only)
- `restart()` - Bot restart handler with admin confirmation dialog

**`dumpyarabot/moderated_handlers.py`** - Moderated request system handlers:
- `handle_request_message()` - Processes `#request [URL]` messages from users
- `handle_callback_query()` - Handles button interactions for accept/reject/options
- `accept_command()` - Handles `/accept [request_id] [options]` command, creates ARQ jobs with metadata
- `reject_command()` - Handles `/reject [request_id] [reason]` command

**`dumpyarabot/utils.py`** - Utility functions:
- `retry_http_request()` - HTTP request retry wrapper with exponential backoff
- `escape_markdown()` - Markdown text escaping for Telegram messages
- `generate_request_id()` - Unique ID generation for requests

**`dumpyarabot/schemas.py`** - Pydantic models for data validation:
- `DumpArguments` - Validates dump command parameters and URLs
- `DumpJob` - Models firmware dump job data and status
- `JobMetadata` - Comprehensive metadata tracking for ARQ jobs (25+ fields)
- `PendingReview` - Models pending review requests in moderated system
- `AcceptOptionsState` - Models acceptance options state (alt, force, privdump in moderated system)

**`dumpyarabot/storage.py`** - Data access layer for bot_data persistence:
- `ReviewStorage` - Manages pending reviews and options state in bot memory

**`dumpyarabot/ui.py`** - User interface components:
- `create_review_keyboard()` - Creates Accept/Reject button layouts
- `create_options_keyboard()` - Creates option toggle buttons with current state
- Message templates for different notification scenarios

**`dumpyarabot/config.py`** - Environment-based configuration using pydantic-settings

**`dumpyarabot/message_queue.py`** - ARQ job management and status retrieval:
- `enqueue_firmware_dump()` - Unified job creation with metadata initialization
- `get_job_status()` - Retrieves job status and metadata from ARQ
- `cancel_job()` - Job cancellation with proper cleanup

**`dumpyarabot/message_formatting.py`** - Status message formatting with metadata integration:
- `format_job_status()` - Rich status display using stored job metadata
- Progressive message enhancement as jobs progress through stages

### Authorization System

The bot uses a two-tier authorization system:
- **Chat-level**: Only allowed chats (configured in `ALLOWED_CHATS`) can use commands
- **User-level**: Admin commands (cancel, restart) require Telegram admin permissions in the chat

### ARQ Job Processing - Unified Firmware Pipeline

The bot uses ARQ (Async Redis Queue) for distributed job processing with comprehensive metadata tracking:

**`dumpyarabot/arq_jobs.py`** - ARQ job functions:
- `process_firmware_dump()` - Unified firmware processing job handling all dump types
- 25-stage processing pipeline with metadata updates at each step
- Cross-chat message threading for moderated requests
- Comprehensive error handling with detailed diagnostics

**`dumpyarabot/arq_config.py`** - ARQ configuration and worker setup:
- TTL configuration for different job states (60d completed, 15d failed, 7d running)
- Redis connection management with fallback to in-memory storage

**`run_arq_worker.py`** - ARQ worker entry point for processing jobs

**Core Processing Components (integrated into ARQ job):**
- `FirmwareDownloader` - URL optimization, mirror selection, multi-tool downloads
- `FirmwareExtractor` - Python dumper (default) + alternative extraction toolkit
- `PropertyExtractor` - Device metadata extraction from build.prop and system files
- `GitLabManager` - Repository creation, branch management, file uploads

**Job Metadata Integration:**
- Single source of truth for all job data and status
- Automatic metadata updates throughout processing pipeline
- Rich status displays with device info, repository links, error details
- Cross-chat messaging support for moderated system threading

### Job Lifecycle & Metadata Flow

The ARQ job processing system tracks comprehensive metadata throughout the entire firmware dump lifecycle:

**Job Initialization:**
- **Metadata Creation**: `JobMetadata` class captures initial context (telegram_context, request_source, options)
- **TTL Management**: Automatic expiration (60 days completed, 15 days failed, 7 days running)
- **Unique Job ID**: ARQ-generated job ID for tracking and cancellation

**Processing Stages with Metadata Updates:**
1. **Download Phase**: Tracks download progress, URL optimization, mirror selection
2. **Extraction Phase**: Records extraction method used, partition counts, boot image processing
3. **Analysis Phase**: Captures device properties, build information, fingerprint data
4. **Repository Phase**: Stores GitLab repository URLs, branch names, commit hashes
5. **Completion/Error**: Final status, repository links, or detailed error context

**Metadata Fields Tracked:**
- `telegram_context`: Message IDs, chat IDs, user info for cross-chat threading
- `progress_history`: Timestamped status updates for debugging
- `device_info`: Manufacturer, model, Android version, build details
- `repository`: GitLab URLs, branch names, commit information
- `error_context`: Detailed error messages, stack traces, failure points
- `timing`: Start time, duration, stage completion times

**Status Command Integration:**
- `/status [job_id]` command retrieves full metadata from ARQ
- Displays current stage, device info, repository links, error details
- Works across all job sources (direct, moderated, blacklist)

### Integration Points - Unified Processing

All job entry points converge on the same ARQ processing pipeline:

**Direct Dump Commands (`handlers.py`):**
```python
# /dump https://example.com/firmware.zip a f
job = await arq.enqueue_job(
    "process_firmware_dump",
    url="https://example.com/firmware.zip",
    use_alt_dumper=True,
    force_redump=True,
    metadata=JobMetadata(source="direct_command", ...)
)
```

**Moderated Request Acceptance (`moderated_handlers.py`):**
```python
# /accept abc123 a p
job = await arq.enqueue_job(
    "process_firmware_dump",
    url=request.url,
    use_alt_dumper=True,
    private_dump=True,
    metadata=JobMetadata(source="moderated_request", ...)
)
```

**Blacklist Operations (`handlers.py`):**
```python
# /dump https://example.com/firmware.zip b
job = await arq.enqueue_job(
    "process_firmware_dump",
    url="https://example.com/firmware.zip",
    add_to_blacklist=True,
    metadata=JobMetadata(source="blacklist_operation", ...)
)
```

**Unified Processing (`arq_jobs.py`):**
- Single `process_firmware_dump()` function handles all job types
- Identical firmware processing pipeline regardless of source
- Consistent metadata tracking and status updates
- Same error handling and completion logic

## Configuration

Create `config.json` from `config.json.example` or use environment variables:

**Required Environment Variables:**
- `TELEGRAM_BOT_TOKEN` - Bot token from @BotFather
- `ALLOWED_CHATS` - JSON array of allowed chat IDs
- `REQUEST_CHAT_ID` - Chat ID where users submit `#request` messages
- `REVIEW_CHAT_ID` - Chat ID where admins review and approve/reject requests
- `DUMPER_TOKEN` - GitLab API token for repository operations
- `API_KEY` - Telegram bot token for sending status updates (can be same as TELEGRAM_BOT_TOKEN)

**Optional:**
- `REDIS_URL` - Redis connection URL for persistent storage (falls back to in-memory storage if not provided)

## Command Options

**Dump command options:**
- `a` - Use alternative dumper
- `f` - Force new dump (skip existing build check)  
- `b` - Add URL to blacklist
- `p` - Use privdump (deletes original message for privacy)

**Cancel command options:**
- `p` - Cancel privdump job instead of regular dumpyara job

## Moderated Request System

### User Workflow
1. **Submit Request**: Users post `#request [URL]` in the designated request chat
2. **Automatic Processing**: Bot validates URL and forwards to review chat with Accept/Reject buttons
3. **Notification**: User receives confirmation that request was submitted for review
4. **Result**: User gets notified when request is accepted/rejected with processing status or reason

### Admin Workflow
1. **Review Request**: Admins see requests in review chat with Accept/Reject/Cancel buttons
2. **Configure Options**: Clicking Accept shows toggleable options (Alternative Dumper, Force Re-Dump, Private Dump)
3. **Process**: Click Submit to start dump with selected options, or use `/reject [id] [reason]`
4. **Commands**: 
   - `/accept [request_id] [options]` - Accept with option flags (a=alt, f=force, p=privdump)
   - `/reject [request_id] [reason]` - Reject with optional reason

### Request ID System
- Each request gets a unique 8-character hex ID for tracking
- Stored in bot memory with complete request context
- Auto-cleanup after processing (accept/reject)

### Message Flow & Status Updates
- **Submission Confirmation**: Users receive "✅ Request submitted for review" message (kept for status threading)
- **Acceptance Messages**: Different messages for regular vs private dumps
  - Regular: "🎉 Your request has been accepted and processing started"
  - Private: "Your request is under further review for private processing"
- **ARQ Status Updates**: Posted in reviewer chat using `reply_parameters` to reference original user request
- **Message Cleanup**: Review chat messages are auto-deleted after processing to keep chat clean

### Cross-Chat Integration
- ARQ jobs receive `telegram_context` with `INITIAL_MESSAGE_ID` and `INITIAL_CHAT_ID`
- Status updates appear in reviewer chat but link back to original `#request` message in requester chat
- Uses Telegram's `reply_parameters` for native cross-chat message threading
- Maintains proper conversation flow while keeping admin and user chats separate

## ARQ Processing Details

### Unified Firmware Processing Pipeline
The ARQ job processing system handles all firmware dump operations through a single, comprehensive pipeline:

**Core Processing Flow:**
- **Download Phase**: URL optimization, mirror selection, multi-tool fallback (aria2c → wget)
- **Extraction Phase**: Python dumper (default) or alternative toolkit with boot image processing
- **Analysis Phase**: Device property extraction, build information parsing, fingerprint generation
- **Repository Phase**: GitLab repository creation, branch management, file uploads
- **Notification Phase**: Status updates with cross-chat threading support

**ARQ Job Parameters:**
- `url`: Firmware download URL
- `use_alt_dumper`: Boolean flag for alternative extraction method
- `force_redump`: Skip existing build checks
- `add_to_blacklist`: Add URL to blacklist after processing
- `private_dump`: Enable private dump mode (message deletion)
- `telegram_context`: Message/chat IDs for cross-chat threading
- `metadata`: Comprehensive job metadata tracking

### Status Message Threading
- **Direct `/dump`**: Status updates reply directly in same chat
- **Moderated System**: Status updates use cross-chat threading to maintain conversation flow
- **Private Dumps**: Receive same status updates as regular dumps in moderated flow
- **Cross-Chat Support**: Uses `reply_parameters` for native Telegram threading

---

# Firmware Processing Components

The ARQ job integrates multiple specialized components for comprehensive firmware processing:

## ARQ Job Processing Overview

The ARQ job performs the complete firmware dump pipeline with comprehensive metadata tracking:
1. **Download** firmware from provided URL with mirror optimization and fallback handling
2. **Extract** partitions and boot images using Python dumper or alternative toolkit
3. **Analyze** device properties and generate comprehensive metadata
4. **Create** GitLab repository and branch with conflict detection
5. **Commit and push** extracted firmware with proper file organization
6. **Notify** users via Telegram with progressive status updates and cross-chat threading

## ARQ Job Parameters & Configuration

### Core Job Parameters
- `url`: Firmware download URL (string)
- `use_alt_dumper`: Use alternative extraction method (boolean)
- `force_redump`: Skip existing build checks (boolean)
- `add_to_blacklist`: Add URL to blacklist after processing (boolean)
- `private_dump`: Enable private dump mode (boolean)
- `telegram_context`: Message/chat IDs for cross-chat threading (dict)

### Configuration (from config.py)
- `GITLAB_SERVER`: GitLab instance URL (default: "dumps.tadiphone.dev")
- `GITLAB_TOKEN`: GitLab API token for repository operations
- `TELEGRAM_BOT_TOKEN`: Bot token for status updates
- `ALLOWED_CHATS`: List of authorized chat IDs
- `REDIS_URL`: Redis connection for persistent job storage

### Metadata Tracking
- `JobMetadata`: Comprehensive tracking class with 25+ fields
- Automatic TTL management (60d completed, 15d failed, 7d running)
- Progress history, device info, repository links, error context

## Core Processing Functions

### Telegram Integration (`send_status_update`)
```python
async def send_status_update(
    message: str,
    telegram_context: dict,
    mode: str = "edit"  # "normal", "reply", "edit"
) -> None:
    # Handles cross-chat replies using reply_parameters when INITIAL_CHAT_ID is set
```

**Cross-Chat Reply Logic:**
- If `telegram_context.chat_id` provided: Uses `reply_parameters` for cross-chat threading
- Otherwise: Uses standard `reply_to_message_id` for same-chat replies
- Posts to appropriate chat based on job type (reviewer chat for moderated, original chat for direct)

### Message Management (`update_progress_message`)
- **Progressive Updates**: Messages show increasing detail as processing advances
- **Metadata Integration**: Displays device info, repository links, error details
- **Status Tracking**: Maintains conversation flow with proper threading

### Error Handling & Completion
- **Success**: Returns repository links and device information
- **Failure**: Provides detailed error context and troubleshooting information
- **Cancellation**: Graceful job termination with cleanup

## Processing Pipeline

### 1. Validation & Setup
- **GitLab Connectivity**: Verifies API access and repository creation permissions
- **URL Validation**: Checks against whitelist and blacklist
- **Duplicate Detection**: Prevents processing of already dumped builds
- **Metadata Initialization**: Creates comprehensive job tracking structure

### 2. Download Phase
**URL Mirror Optimization** (Xiaomi firmware):
- Automatically detects Xiaomi URLs (`d.miui.com`)
- Tests multiple CDN mirrors for best performance:
  - `cdnorg.d.miui.com`
  - `bkt-sgp-miui-ota-update-alisgp.oss-ap-southeast-1.aliyuncs.com`
  - `bn.d.miui.com`
- Falls back to original URL if mirrors fail

**Special URL Handling:**
- **Pixeldrain**: Converts to direct download links
- **Google Drive**: Uses `gdown` for proper handling
- **MediaFire**: Uses specialized `mediafire-dl` tool
- **MEGA**: Uses `megatools` for .nz links
- **Default**: `aria2c` with fallback to `wget`

**Progress Tracking**: Updates metadata with download progress and speed

### 3. Extraction Methods

#### Python Dumper (Default)
```python
from dumpyarabot.firmware_extractor import FirmwareExtractor

extractor = FirmwareExtractor(use_alt_dumper=False)
await extractor.extract(firmware_path, output_dir)
```
- Modern Python-based extraction using `uvx dumpyara`
- Automatically handles most partition types
- Preferred method for reliability and speed

#### Alternative Dumper (`use_alt_dumper=True`)
Uses `FirmwareExtractor` toolkit for legacy firmware:
```python
extractor = FirmwareExtractor(use_alt_dumper=True)
await extractor.extract_with_fallback(firmware_path, output_dir)
```
- Handles partition extraction with multiple tools:
  - `fsck.erofs` - Primary EROFS extractor
  - `ext2rd` - EXT filesystem fallback
  - `7zz` - Archive extraction fallback
- Extracts additional components:
  - Boot image ramdisks
  - Device tree blobs (DTB/DTS)
  - Kernel configuration (`ikconfig`)
  - Kernel symbols (`kallsyms.txt`)

### 4. Boot Image Processing
Comprehensive boot image analysis using `BootImageProcessor`:
```python
from dumpyarabot.firmware_extractor import BootImageProcessor

processor = BootImageProcessor()
await processor.process_boot_images(extracted_dir)
```
- **Supported Images**: `boot.img`, `vendor_boot.img`, `vendor_kernel_boot.img`, `init_boot.img`, `dtbo.img`
- **Extraction**: Unpacks kernels, ramdisks, device trees
- **Analysis**: Generates ELF files, symbol tables, kernel configs
- **Device Trees**: Decompiles DTB to human-readable DTS format

### 5. Property Extraction
Comprehensive device metadata extraction using `PropertyExtractor`:
```python
from dumpyarabot.property_extractor import PropertyExtractor

extractor = PropertyExtractor()
device_info = await extractor.extract_properties(extracted_dir)
# Updates job metadata with device information
```
- **Build Properties**: Searches multiple build.prop locations
- **Device Info**: Manufacturer, brand, codename, platform
- **Version Info**: Android version, build ID, incremental
- **Fingerprint**: Full device fingerprint for identification
- **Special Handling**: OPPO/OnePlus pipeline keys, Honor versions

### 6. Repository Management

#### GitLab Integration
GitLab repository management using `GitLabManager`:
```python
from dumpyarabot.gitlab_manager import GitLabManager

manager = GitLabManager()
repo_info = await manager.create_repository(device_info, extracted_dir)
# Updates job metadata with repository information
```
- **Subgroup Creation**: Auto-creates manufacturer subgroups
- **Repository Creation**: Creates device-specific repositories
- **Branch Management**: Uses build description as branch name
- **Conflict Detection**: Aborts if branch already exists

#### Git Operations
```python
await manager.initialize_and_push(
    local_dir=extracted_dir,
    repo_url=repo_info.url,
    branch=repo_info.branch,
    commit_message=device_info.description
)
```

### 7. Device Tree Generation
Optional AOSP device tree generation:
```python
from dumpyarabot.gitlab_manager import GitLabManager

await manager.generate_device_tree(device_info, extracted_dir)
```
- Uses `aospdtgen` to generate AOSP device trees
- Creates Android build system compatible files
- Separate directory structure for device tree files

### 8. Final Output
Completion handling with comprehensive status updates:
```python
await send_status_update(
    f"✅ **Dump Complete!**\n\n"
    f"**Repository**: {repo_info.url}\n"
    f"**Device**: {device_info.model} ({device_info.codename})\n"
    f"**Android**: {device_info.android_version}\n"
    f"**Files**: {file_count} extracted",
    telegram_context
)
```
- **Repository Link**: Direct link to new GitLab branch
- **Channel Notification**: Public firmware announcement (if whitelisted)
- **Build Information**: Device specs and download links
- **File Manifest**: Complete list of extracted files

## Error Handling & Recovery

### Download Failures
- Multiple mirror attempts for known hosts
- Graceful fallback between download tools (`aria2c` → `wget`)
- Clear error messaging with troubleshooting context
- Metadata tracking of failure points and attempted methods

### Extraction Failures
- Progressive fallback through extraction methods (Python dumper → alternative toolkit)
- Detailed logging of each attempt with error context
- Continues processing if non-critical partitions fail
- Comprehensive error metadata for debugging

### GitLab Integration Failures
- API error handling with descriptive messages
- Branch conflict detection and reporting
- Authentication and permission validation
- Repository creation retry logic with exponential backoff

## Status Update Flow

Throughout execution, the ARQ job provides detailed progress updates with metadata integration:

1. **Initialization**: Download start notification with job ID and basic info
2. **Progress**: Real-time download and extraction status with device info as discovered
3. **Analysis**: Property extraction completion with device details and repository links
4. **GitLab**: Repository creation and pushing progress with final links
5. **Completion**: Final repository links, device information, and file manifest
6. **Errors**: Detailed failure information with error context and troubleshooting

## Integration with Bot

The ARQ job processing system seamlessly integrates with the Telegram bot through:
- **Job Metadata**: Comprehensive tracking passed through all job sources
- **Status Threading**: Cross-chat replies maintain conversation flow across different chats
- **Error Reporting**: Failed jobs notify users with detailed error context and troubleshooting
- **Success Notification**: Completed dumps provide repository access with rich device information

This unified architecture provides consistent processing and status reporting across all entry points (direct dumps, moderated requests, blacklist operations) while maintaining tight integration between the request system and firmware processing pipeline.