"""ARQ job functions for firmware dump processing.

This module contains ARQ job functions that replace the custom worker system
while preserving all Telegram messaging features and cross-chat functionality.
"""

import asyncio
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

import arq
from rich.console import Console

from dumpyarabot.config import settings
from dumpyarabot.firmware_downloader import FirmwareDownloader
from dumpyarabot.firmware_extractor import FirmwareExtractor
from dumpyarabot.gitlab_manager import GitLabManager
from dumpyarabot.message_queue import message_queue
from dumpyarabot.property_extractor import PropertyExtractor
from dumpyarabot.schemas import DumpJob, JobStatus
from dumpyarabot.message_formatting import format_comprehensive_progress_message

console = Console()


class PeriodicTimerUpdate:
    """Context manager for periodic elapsed time updates during long operations."""

    def __init__(self, job_data: Dict[str, Any], message: str, progress: Dict[str, Any], interval: int = 30):
        self.job_data = job_data
        self.message = message
        self.progress = progress
        self.interval = interval
        self.task = None
        self.running = False

    async def __aenter__(self):
        self.running = True
        self.task = asyncio.create_task(self._periodic_update())
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.running = False
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def _periodic_update(self):
        """Send periodic updates with refreshed elapsed time."""
        try:
            while self.running:
                await asyncio.sleep(self.interval)
                if self.running:  # Check again after sleep
                    await _send_status_update(self.job_data, self.message, self.progress)
        except asyncio.CancelledError:
            pass


async def _send_status_update(
    job_data: Dict[str, Any],
    message: str,
    progress: Optional[Dict[str, Any]] = None
) -> None:
    """Send a status update message using the existing message queue - PRESERVING ALL TELEGRAM FEATURES."""

    # Format the comprehensive progress message using utility function (with ARQ fallback)
    formatted_message = await format_comprehensive_progress_message(job_data, message, progress)

    # PRESERVE: Check for required message context (from original logic)
    initial_message_id = job_data.get("initial_message_id")
    initial_chat_id = job_data.get("initial_chat_id")

    if not initial_message_id or not initial_chat_id:
        console.print(f"[red]ERROR: Job {job_data['job_id']} missing initial message reference! Cannot send updates.[/red]")
        return

    chat_id = initial_chat_id

    # PRESERVE: Cross-chat logic for moderated system (exact original logic)
    dump_args_initial_message_id = job_data["dump_args"].get("initial_message_id")

    if dump_args_initial_message_id and initial_chat_id != settings.ALLOWED_CHATS[0]:
        # Cross-chat update for moderated system - edit with cross-chat reply
        await message_queue.send_cross_chat_edit(
            chat_id=settings.ALLOWED_CHATS[0],
            text=formatted_message,
            edit_message_id=initial_message_id,
            reply_to_message_id=dump_args_initial_message_id,
            reply_to_chat_id=initial_chat_id,
            context={
                "job_id": job_data["job_id"],
                "worker_id": "arq_worker",
                "progress": progress
            }
        )
    else:
        # Same-chat update - edit the initial message
        await message_queue.send_status_update(
            chat_id=chat_id,
            text=formatted_message,
            edit_message_id=initial_message_id,
            parse_mode=settings.DEFAULT_PARSE_MODE,
            context={
                "job_id": job_data["job_id"],
                "worker_id": "arq_worker",
                "progress": progress
            }
        )


async def _send_failure_notification(job_data: Dict[str, Any], error_details: str) -> None:
    """Send a failure notification using existing message queue - PRESERVING ALL TELEGRAM FEATURES."""

    try:
        # Create progress data to show failure state (exact original logic)
        failure_progress = {
            "current_step": "Failed",
            "total_steps": 10,
            "current_step_number": 0,
            "percentage": 0.0,
            "error_message": error_details
        }

        # Format the failure message using the standard progress format
        progress = job_data.get("progress") or {}
        current_step = progress.get("current_step", "Unknown step")
        formatted_message = await format_comprehensive_progress_message(
            job_data,
            f"❌ Failed at: {current_step}",
            failure_progress
        )

        # PRESERVE: Check for required message context
        initial_message_id = job_data.get("initial_message_id")
        initial_chat_id = job_data.get("initial_chat_id")

        if not initial_message_id or not initial_chat_id:
            console.print(f"[red]ERROR: Job {job_data.get('job_id', 'unknown')} missing initial message reference! Cannot send failure update.[/red]")
            console.print(f"[red]Job data keys: {list(job_data.keys())}[/red]")
            return

        chat_id = initial_chat_id

        # PRESERVE: Cross-chat logic for moderated system (exact original logic)
        dump_args_initial_message_id = job_data.get("dump_args", {}).get("initial_message_id")

        if dump_args_initial_message_id and initial_chat_id != settings.ALLOWED_CHATS[0]:
            # Cross-chat failure update for moderated system - edit with cross-chat reply
            await message_queue.send_cross_chat_edit(
                chat_id=settings.ALLOWED_CHATS[0],
                text=formatted_message,
                edit_message_id=initial_message_id,
                reply_to_message_id=dump_args_initial_message_id,
                reply_to_chat_id=initial_chat_id,
                context={"job_id": job_data.get("job_id", "unknown"), "type": "failure"}
            )
        else:
            # Same-chat failure update - edit the initial message
            await message_queue.send_status_update(
                chat_id=chat_id,
                text=formatted_message,
                edit_message_id=initial_message_id,
                parse_mode=settings.DEFAULT_PARSE_MODE,
                context={"job_id": job_data.get("job_id", "unknown"), "type": "failure"}
            )

        console.print(f"[green]Sent failure notification for job {job_data.get('job_id', 'unknown')}[/green]")

    except Exception as e:
        console.print(f"[red]Failed to send failure notification: {e}[/red]")
        console.print_exception()


async def _validate_gitlab_access() -> None:
    """Validate GitLab server access - from original worker logic."""
    import httpx
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get("https://dumps.tadiphone.dev", timeout=10.0)
            if response.status_code >= 400:
                raise Exception(f"GitLab server returned {response.status_code}")
            console.print("[green]GitLab server access validated[/green]")
    except Exception as e:
        raise Exception(f"Cannot access GitLab server: {e}")


async def process_firmware_dump(ctx, job_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    ARQ job function to process firmware dumps.

    This provides firmware dump processing as an ARQ job function while preserving
    ALL Telegram messaging features, cross-chat functionality, and progress formatting.

    Args:
        ctx: ARQ context (provides job_id, etc.)
        job_data: Serialized DumpJob data

    Returns:
        Dict with result data or error information
    """
    job_id = job_data["job_id"]
    console.print(f"[blue]ARQ processing job {job_id}[/blue]")

    # Add ARQ job context to job_data for tracking
    job_data["arq_job_id"] = getattr(ctx, 'job_id', None)
    job_data["started_at"] = datetime.now(timezone.utc).isoformat()

    try:
        # Create temporary work directory
        with tempfile.TemporaryDirectory(prefix=f"dump_{job_id}_") as temp_dir:
            work_dir = Path(temp_dir)
            console.print(f"[blue]Working directory: {work_dir}[/blue]")

            try:
                # Initialize components (exact same as original)
                downloader = FirmwareDownloader(str(work_dir))
                extractor = FirmwareExtractor(str(work_dir))
                prop_extractor = PropertyExtractor(str(work_dir))
                gitlab_manager = GitLabManager(str(work_dir))

                # Step 1: Environment setup and URL validation (4%)
                await _send_status_update(
                    job_data,
                    "🔍 Validating URL and setting up environment...",
                    progress={"current_step": "Setup", "total_steps": 25, "current_step_number": 1, "percentage": 4.0}
                )
                # Step 2: GitLab access validation (8%)
                await _send_status_update(
                    job_data,
                    "🔗 Validating GitLab access...",
                    progress={"current_step": "Validation", "total_steps": 25, "current_step_number": 2, "percentage": 8.0}
                )
                await _validate_gitlab_access()
                is_whitelisted = await gitlab_manager.check_whitelist(str(job_data["dump_args"]["url"]))

                # Step 3: URL optimization and mirror selection (12%)
                await _send_status_update(
                    job_data,
                    "🔍 Optimizing download URL and selecting mirrors...",
                    progress={"current_step": "URL Optimization", "total_steps": 25, "current_step_number": 3, "percentage": 12.0}
                )

                # Step 4: Starting download (16%)
                download_progress = {"current_step": "Download", "total_steps": 25, "current_step_number": 4, "percentage": 16.0}
                await _send_status_update(
                    job_data,
                    "📥 Downloading firmware...",
                    progress=download_progress
                )

                # Create DumpJob object for components that need it
                dump_job = DumpJob.model_validate(job_data)

                # Use periodic timer for download operation
                async with PeriodicTimerUpdate(job_data, "📥 Downloading firmware...", download_progress):
                    firmware_path, firmware_name = await downloader.download_firmware(dump_job)

                # Step 5: Download completed (20%)
                await _send_status_update(
                    job_data,
                    "✅ Firmware download completed",
                    progress={"current_step": "Download Complete", "total_steps": 25, "current_step_number": 5, "percentage": 20.0}
                )

                # Step 6: Starting firmware extraction (24%)
                extract_progress = {"current_step": "Extract", "total_steps": 25, "current_step_number": 6, "percentage": 24.0}
                await _send_status_update(
                    job_data,
                    "📦 Extracting firmware partitions...",
                    progress=extract_progress
                )

                # Use periodic timer for extraction operation
                async with PeriodicTimerUpdate(job_data, "📦 Extracting firmware partitions...", extract_progress):
                    await extractor.extract_firmware(dump_job, firmware_path)

                # Step 7: Python/Alternative dumper completed (28%)
                await _send_status_update(
                    job_data,
                    "✅ Firmware extraction completed",
                    progress={"current_step": "Extract Complete", "total_steps": 25, "current_step_number": 7, "percentage": 28.0}
                )

                # Step 8: Processing individual partitions (32%)
                await _send_status_update(
                    job_data,
                    "📁 Processing individual partitions...",
                    progress={"current_step": "Partitions", "total_steps": 25, "current_step_number": 8, "percentage": 32.0}
                )

                # Step 9: Extracting boot images (36%)
                await _send_status_update(
                    job_data,
                    "🥾 Processing boot images...",
                    progress={"current_step": "Boot Images", "total_steps": 25, "current_step_number": 9, "percentage": 36.0}
                )
                await extractor.process_boot_images()

                # Step 10: Processing ikconfig and kallsyms (40%)
                await _send_status_update(
                    job_data,
                    "⚙️ Processing kernel configuration and symbols...",
                    progress={"current_step": "Kernel Analysis", "total_steps": 25, "current_step_number": 10, "percentage": 40.0}
                )

                # Step 11: Extracting device trees (44%)
                await _send_status_update(
                    job_data,
                    "🌳 Extracting device trees...",
                    progress={"current_step": "Device Trees", "total_steps": 25, "current_step_number": 11, "percentage": 44.0}
                )

                # Step 12: Partition extraction completed (48%)
                await _send_status_update(
                    job_data,
                    "✅ Partition extraction completed",
                    progress={"current_step": "Extract Done", "total_steps": 25, "current_step_number": 12, "percentage": 48.0}
                )

                # Step 13: Extracting device properties (52%)
                await _send_status_update(
                    job_data,
                    "📋 Extracting device properties...",
                    progress={"current_step": "Properties", "total_steps": 25, "current_step_number": 13, "percentage": 52.0}
                )
                device_props = await prop_extractor.extract_properties()

                # Step 14: Generating file manifest (56%)
                await _send_status_update(
                    job_data,
                    "📄 Generating board info and file listings...",
                    progress={"current_step": "File Generation", "total_steps": 25, "current_step_number": 14, "percentage": 56.0}
                )
                await prop_extractor.generate_board_info()
                await prop_extractor.generate_all_files_list()

                # Step 15: Creating device trees (60%)
                await _send_status_update(
                    job_data,
                    "🌳 Generating device tree...",
                    progress={"current_step": "Device Tree", "total_steps": 25, "current_step_number": 15, "percentage": 60.0}
                )
                await prop_extractor.generate_device_tree()

                # Step 16: Analysis completed (64%)
                await _send_status_update(
                    job_data,
                    "✅ Device analysis completed",
                    progress={"current_step": "Analysis Done", "total_steps": 25, "current_step_number": 16, "percentage": 64.0}
                )

                # Step 17: Checking/creating GitLab subgroup (68%)
                await _send_status_update(
                    job_data,
                    "🗒️ Checking GitLab subgroup...",
                    progress={"current_step": "GitLab Subgroup", "total_steps": 25, "current_step_number": 17, "percentage": 68.0}
                )

                # Step 18: Checking/creating GitLab project (72%)
                await _send_status_update(
                    job_data,
                    "📁 Checking GitLab project...",
                    progress={"current_step": "GitLab Project", "total_steps": 25, "current_step_number": 18, "percentage": 72.0}
                )

                # Step 19: Setting up git repository (76%)
                gitlab_progress = {"current_step": "GitLab Setup", "total_steps": 25, "current_step_number": 19, "percentage": 76.0}
                await _send_status_update(
                    job_data,
                    "🗂️ Creating GitLab repository...",
                    progress=gitlab_progress
                )

                # Get DUMPER_TOKEN from environment or settings
                dumper_token = getattr(settings, 'DUMPER_TOKEN', None)
                if not dumper_token:
                    raise Exception("DUMPER_TOKEN not configured")

                # Use periodic timer for GitLab operation (longest operation)
                async with PeriodicTimerUpdate(job_data, "🗂️ Creating GitLab repository...", gitlab_progress):
                    repo_url, repo_path = await gitlab_manager.create_and_push_repository(device_props, dumper_token)

                # Step 20: Adding and committing files (80%)
                await _send_status_update(
                    job_data,
                    "📝 Adding and committing files...",
                    progress={"current_step": "Git Commit", "total_steps": 25, "current_step_number": 20, "percentage": 80.0}
                )

                # Step 21: Pushing to GitLab (84%)
                await _send_status_update(
                    job_data,
                    "🚀 Pushing to GitLab...",
                    progress={"current_step": "Git Push", "total_steps": 25, "current_step_number": 21, "percentage": 84.0}
                )

                # Step 22: Setting default branch (88%)
                await _send_status_update(
                    job_data,
                    "🌱 Setting default branch...",
                    progress={"current_step": "Branch Setup", "total_steps": 25, "current_step_number": 22, "percentage": 88.0}
                )

                # Step 23: Preparing channel notification (92%)
                await _send_status_update(
                    job_data,
                    "📢 Preparing channel notification...",
                    progress={"current_step": "Notification Prep", "total_steps": 25, "current_step_number": 23, "percentage": 92.0}
                )

                # Step 24: Sending notification (96%)
                await _send_status_update(
                    job_data,
                    "📢 Sending channel notification...",
                    progress={"current_step": "Notification", "total_steps": 25, "current_step_number": 24, "percentage": 96.0}
                )

                # Get API_KEY from environment or settings for channel notification
                api_key = getattr(settings, 'API_KEY', None)
                if api_key:
                    await gitlab_manager.send_channel_notification(
                        device_props,
                        repo_url,
                        str(job_data["dump_args"]["url"]),
                        is_whitelisted,
                        job_data.get("add_blacklist", False),
                        api_key
                    )

                # Step 25: Process completed (100%)
                await _send_status_update(
                    job_data,
                    f"✅ *Dump completed successfully!*\n\n📁 *Repository:* {repo_url}\n📱 *Device:* {device_props.get('brand', 'Unknown')} {device_props.get('codename', 'Unknown')}",
                    progress={"current_step": "Completed", "total_steps": 25, "current_step_number": 25, "percentage": 100.0}
                )

                # Return result data
                return {
                    "success": True,
                    "repository_url": repo_url,
                    "repository_path": repo_path,
                    "device_info": device_props,
                    "firmware_file": firmware_name,
                    "is_whitelisted": is_whitelisted
                }

            except Exception as e:
                console.print(f"[red]Error in inner processing for job {job_id}: {e}[/red]")

                # Send failure notification using existing message queue system
                await _send_failure_notification(job_data, str(e))

                # Return error result
                return {
                    "success": False,
                    "error": str(e)
                }

    except Exception as e:
        console.print(f"[red]Critical error processing job {job_id}: {e}[/red]")
        console.print_exception()

        # Send failure notification for any unhandled exceptions
        try:
            await _send_failure_notification(job_data, f"Critical error: {str(e)}")
        except Exception as notification_error:
            console.print(f"[red]Failed to send failure notification: {notification_error}[/red]")

        # Return error result
        return {
            "success": False,
            "error": str(e)
        }