# dumpbot (dumpyarabot)

A Telegram bot integrated with Jenkins for managing firmware dumps for AndroidDumps.

## Workflows

### 1. Moderated Request Flow

*   **User Request (in Request Chat):**
    A user sends `#request <URL>` in the `REQUEST_CHAT_ID`.
*   **Admin Review (in Review Chat):**
    The bot posts the request in the `REVIEW_CHAT_ID` with "Accept" / "Reject" buttons.
*   **Acceptance:**
    *   Clicking "Accept" shows a submenu with dump options (Alt, Force, Blacklist, Privdump).
    *   Toggle options (✅) and click "Submit Acceptance".
    *   Alternatively, use `/accept <req_id> [options]`.
*   **Rejection:**
    *   Clicking "Reject" prompts the admin to use the `/reject` command.
    *   Admin uses `/reject <req_id> <reason>`.
*   **Notifications:** The original requester is notified of submission, acceptance/start, or rejection (with reason).

### 2. Direct Admin Dump (in Review Chat)

*   Admins can use `/dump <URL> [options]` directly in the `REVIEW_CHAT_ID`.

## Commands

### Request Chat (`REQUEST_CHAT_ID`)

*   `#request <URL>`
    *   Submits a firmware URL for review.
    *   Example: `#request https://example.com/firmware.zip`

### Review Chat (`REVIEW_CHAT_ID`)

*   `/accept <request_id> [options]`
    *   Accepts a pending request and starts the dump.
    *   *Options:* `a` (alt), `f` (force), `b` (blacklist), `p` (privdump).
    *   Example: `/accept f4e3a2d1 a f`

*   `/reject <request_id> <reason>`
    *   Rejects a pending request.
    *   Example: `/reject f4e3a2d1 Duplicate link`

*   `/dump <URL> [options]`
    *   Directly starts a dump.
    *   *Options:* `a`, `f`, `b`, `p`.
    *   Example: `/dump https://example.com/firmware.zip a`

*   `/cancel <job_id> [p]` (Admin Only)
    *   Cancels a Jenkins job (Build # or Queue ID). `p` targets privdump job.
    *   Example: `/cancel 123`, `/cancel 456 p`

*   `/restart` (Admin Only)
    *   Restarts the bot.

## Setup

1.  Clone the repository.
2.  Install dependencies: `uv sync`
3.  Rename `.env.example` to `.env`.
4.  Fill in values in `.env`.
5.  Run: `python -m dumpyarabot`