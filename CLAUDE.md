# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is **dumpyarabot**, a Telegram bot for AndroidDumps that integrates with Jenkins to manage firmware dump processes. The bot handles `/dump` and `/cancel` commands for authorized users and chats, with support for both public dumps (`dumpyara`) and private dumps (`privdump`). It also includes a **moderated request system** that allows users to submit requests for review before processing.

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

## Architecture

### Core Components

**`dumpyarabot/__main__.py`** - Application entry point that sets up the Telegram bot with command handlers

**`dumpyarabot/handlers.py`** - Contains the main command handlers:
- `dump()` - Handles `/dump [URL] [options]` command for initiating firmware dumps
- `cancel_dump()` - Handles `/cancel [job_id]` command for cancelling jobs (admin only)
- `restart()` - Bot restart handler with admin confirmation dialog

**`dumpyarabot/moderated_handlers.py`** - Moderated request system handlers:
- `handle_request_message()` - Processes `#request [URL]` messages from users
- `handle_callback_query()` - Handles button interactions for accept/reject/options
- `accept_command()` - Handles `/accept [request_id] [options]` command
- `reject_command()` - Handles `/reject [request_id] [reason]` command

**`dumpyarabot/utils.py`** - Jenkins integration utilities:
- `check_existing_build()` - Checks if build already exists before starting new one
- `call_jenkins()` - Triggers new Jenkins builds with parameters  
- `cancel_jenkins_job()` - Cancels running Jenkins jobs
- `get_jenkins_builds()` - Fetches build history from Jenkins API

**`dumpyarabot/schemas.py`** - Pydantic models for data validation:
- `DumpArguments` - Validates dump command parameters and URLs
- `JenkinsBuild` - Models Jenkins build response data
- `PendingReview` - Models pending review requests in moderated system
- `AcceptOptionsState` - Models acceptance options state (alt, force, privdump in moderated system)

**`dumpyarabot/storage.py`** - Data access layer for bot_data persistence:
- `ReviewStorage` - Manages pending reviews and options state in bot memory

**`dumpyarabot/ui.py`** - User interface components:
- `create_review_keyboard()` - Creates Accept/Reject button layouts
- `create_options_keyboard()` - Creates option toggle buttons with current state
- Message templates for different notification scenarios

**`dumpyarabot/config.py`** - Environment-based configuration using pydantic-settings

### Authorization System

The bot uses a two-tier authorization system:
- **Chat-level**: Only allowed chats (configured in `ALLOWED_CHATS`) can use commands
- **User-level**: Admin commands (cancel, restart) require Telegram admin permissions in the chat

### Jenkins Integration

The bot communicates with two Jenkins jobs:
- `dumpyara` - Public firmware dumps
- `privdump` - Private firmware dumps (auto-deletes trigger message)

Build parameters include URL, dumper type, blacklist flag, message ID and chat ID for cross-chat status updates.

## Configuration

Create `config.json` from `config.json.example` or use environment variables:

**Required Environment Variables:**
- `TELEGRAM_BOT_TOKEN` - Bot token from @BotFather
- `JENKINS_URL` - Jenkins server URL
- `JENKINS_USER_NAME` - Jenkins username
- `JENKINS_USER_TOKEN` - Jenkins API token
- `ALLOWED_CHATS` - JSON array of allowed chat IDs
- `REQUEST_CHAT_ID` - Chat ID where users submit `#request` messages
- `REVIEW_CHAT_ID` - Chat ID where admins review and approve/reject requests

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
- **Jenkins Status Updates**: Posted in reviewer chat but use `reply_parameters` to reference original user request
- **Message Cleanup**: Review chat messages are auto-deleted after processing to keep chat clean

### Cross-Chat Integration
- Jenkins receives both `INITIAL_MESSAGE_ID` and `INITIAL_CHAT_ID` parameters
- Status updates appear in reviewer chat but link back to original `#request` message in requester chat
- Uses Telegram's `reply_parameters` for native cross-chat message threading
- Maintains proper conversation flow while keeping admin and user chats separate

## Jenkins Integration Details

### extract_and_push.sh Script
The Jenkins job uses `extract_and_push.sh` which handles:
- **Cross-chat replies**: Uses `reply_parameters` when `INITIAL_CHAT_ID` is provided
- **Status updates**: Progress messages during firmware extraction and GitLab pushing
- **Environment variables**: 
  - `INITIAL_MESSAGE_ID` - Message to reply to
  - `INITIAL_CHAT_ID` - Chat containing the message (for cross-chat replies)
  - Standard Jenkins job parameters (URL, USE_ALT_DUMPER, ADD_BLACKLIST, etc.)

### Status Message Threading
- Original `/dump` command: Status updates reply directly in same chat
- Moderated system: Status updates use cross-chat threading to maintain conversation flow
- Private dumps: Receive same status updates as regular dumps in moderated flow

---

# extract_and_push.sh - Firmware Processing Script

The `extract_and_push.sh` script is the Jenkins-side component that handles the actual firmware downloading, extraction, and GitLab repository management. While separate from the bot, it's tightly integrated through environment variables and Telegram notifications.

## Script Overview

This bash script performs the complete firmware dump pipeline:
1. **Download** firmware from provided URL
2. **Extract** partitions and boot images 
3. **Analyze** device properties and generate metadata
4. **Create** GitLab repository and branch
5. **Commit and push** extracted firmware
6. **Notify** users via Telegram throughout the process

## Environment Variables

### Required by Jenkins
- `API_KEY` - Telegram bot token for sending status updates
- `DUMPER_TOKEN` - GitLab API token for repository operations
- `BUILD_URL` - Jenkins build URL for status links
- `BUILD_ID` - Jenkins build number
- `JOB_NAME` - Jenkins job name (determines public vs private processing)

### Passed from Bot
- `URL` - Firmware download URL
- `USE_ALT_DUMPER` - Boolean flag for alternative extraction method
- `ADD_BLACKLIST` - Boolean flag for blacklisting download URL
- `INITIAL_MESSAGE_ID` - Telegram message ID to reply to
- `INITIAL_CHAT_ID` - Telegram chat ID containing the message (for cross-chat replies)

### Configuration Defaults
- `GITLAB_SERVER` - GitLab instance (default: "dumps.tadiphone.dev")
- `PUSH_HOST` - Git remote name (default: "dumps")
- `ORG` - GitLab organization (default: "dumps")
- `CHAT_ID` - Hardcoded reviewer chat ID for status updates

## Core Functions

### Telegram Integration (`sendTG`)
```bash
sendTG() {
    local mode="${1}" && shift
    # Modes: normal, reply, edit
    # Handles cross-chat replies using reply_parameters when INITIAL_CHAT_ID is set
}
```

**Cross-Chat Reply Logic:**
- If `INITIAL_CHAT_ID` provided: Uses `reply_parameters` for cross-chat threading
- Otherwise: Uses standard `reply_to_message_id` for same-chat replies
- Always posts to hardcoded `CHAT_ID` (reviewer chat)

### Message Management (`sendTG_edit_wrapper`)
- **Temporary mode**: Updates message content temporarily
- **Permanent mode**: Stores content permanently, appends new updates
- Used extensively for progress tracking throughout extraction

### Error Handling (`terminate`)
Standardized exit with status codes:
- `0` - Success with links to GitLab repository
- `1` - Failure with error details and console logs
- `2` - Aborted (branch already exists)

## Processing Pipeline

### 1. Validation & Setup
- Checks GitLab server accessibility
- Validates download URL against whitelist (`~/dumpbot/whitelist.txt`)
- Determines if download link will be published based on whitelist and blacklist flags

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

### 3. Extraction Methods

#### Python Dumper (Default)
```bash
uvx dumpyara "${FILE}" -o "${PWD}"
```
- Modern Python-based extraction
- Automatically handles most partition types
- Preferred method for reliability

#### Alternative Dumper (`USE_ALT_DUMPER=true`)
Uses `Firmware_extractor` toolkit for legacy firmware:
- Clones/updates extractor from GitHub
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
Comprehensive boot image analysis:
- **Supported Images**: `boot.img`, `vendor_boot.img`, `vendor_kernel_boot.img`, `init_boot.img`, `dtbo.img`
- **Extraction**: Unpacks kernels, ramdisks, device trees
- **Analysis**: Generates ELF files, symbol tables, kernel configs
- **Device Trees**: Decompiles DTB to human-readable DTS format

### 5. Property Extraction
Comprehensive device metadata extraction:
- **Build Properties**: Searches multiple build.prop locations
- **Device Info**: Manufacturer, brand, codename, platform
- **Version Info**: Android version, build ID, incremental
- **Fingerprint**: Full device fingerprint for identification
- **Special Handling**: OPPO/OnePlus pipeline keys, Honor versions

### 6. Repository Management

#### GitLab Integration
- **Subgroup Creation**: Auto-creates manufacturer subgroups
- **Repository Creation**: Creates device-specific repositories
- **Branch Management**: Uses build description as branch name
- **Conflict Detection**: Aborts if branch already exists

#### Git Operations
```bash
git init --initial-branch "$branch"
git add --ignore-errors -A
git commit --quiet --signoff --message="$description"
git push "$PUSH_HOST:$ORG/$repo.git" HEAD:refs/heads/"$branch"
```

### 7. Device Tree Generation
- Uses `aospdtgen` to generate AOSP device trees
- Creates Android build system compatible files
- Separate directory structure for device tree files

### 8. Final Output
- **Repository Link**: Direct link to new GitLab branch
- **Channel Notification**: Public firmware announcement (if whitelisted)
- **Build Information**: Device specs and download links
- **File Manifest**: Complete list of extracted files

## Error Handling & Recovery

### Download Failures
- Multiple mirror attempts for known hosts
- Graceful fallback between download tools
- Clear error messaging with troubleshooting context

### Extraction Failures
- Progressive fallback through extraction methods
- Detailed logging of each attempt
- Continues processing if non-critical partitions fail

### GitLab Integration Failures
- API error handling with descriptive messages
- Branch conflict detection and reporting
- Authentication and permission validation

## Status Update Flow

Throughout execution, the script provides detailed progress updates:

1. **Initialization**: Download start notification with job ID
2. **Progress**: Real-time download and extraction status
3. **Analysis**: Property extraction and device tree generation
4. **GitLab**: Repository creation and pushing progress  
5. **Completion**: Final repository links and device information
6. **Errors**: Detailed failure information with console log links

## Integration with Bot

The script seamlessly integrates with the Telegram bot through:
- **Environment Variables**: All configuration passed from Jenkins
- **Status Threading**: Cross-chat replies maintain conversation flow
- **Error Reporting**: Failed builds notify users with actionable information
- **Success Notification**: Completed dumps provide repository access

This architecture separates concerns while maintaining tight integration between the request system and firmware processing pipeline.