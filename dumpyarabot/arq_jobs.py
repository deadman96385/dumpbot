"""ARQ job functions for firmware dump processing.

This module contains ARQ job functions that replace the custom worker system
while preserving all Telegram messaging features and cross-chat functionality.
"""

import tempfile
import uuid
from datetime import datetime
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

console = Console()


def _format_progress_message(
    job_data: Dict[str, Any],
    current_step: str,
    progress: Optional[Dict[str, Any]] = None
) -> str:
    """Format a comprehensive progress message - preserving exact original formatting."""

    # Generate progress bar
    progress_bar = _generate_progress_bar(progress)

    # Calculate elapsed time
    elapsed = _calculate_elapsed_time(job_data)

    # Build message
    if progress and progress.get("percentage", 0) >= 100:
        status_emoji = "✅"
        status_text = "Firmware Dump Completed"
    elif progress and progress.get("current_step") == "Failed":
        status_emoji = "❌"
        status_text = "Firmware Dump Failed"
    else:
        status_emoji = "🚀"
        status_text = "Firmware Dump in Progress"

    url_display = _format_url_display(job_data["dump_args"]["url"])
    job_id_display = job_data["job_id"]
    worker_id_display = job_data.get("worker_id", "arq_worker")
    current_step_display = current_step

    message = f"{status_emoji} *{status_text}*\n\n"
    message += f"📥 *URL:* `{url_display}`\n"
    message += f"🆔 *Job ID:* `{job_id_display}`\n"

    # Format options
    options = []
    if job_data["dump_args"].get("use_alt_dumper"):
        options.append("Alt Dumper")
    if job_data.get("add_blacklist"):
        options.append("Blacklist")
    if job_data["dump_args"].get("use_privdump"):
        options.append("Private")

    if options:
        message += f"⚙️ *Options:* {', '.join(options)}\n"

    message += f"\n{progress_bar}\n"
    message += f"{current_step_display}\n\n"
    message += f"⏱️ *Elapsed:* {elapsed}\n"
    message += f"👷 *Worker:* `{worker_id_display}`\n"

    if progress and progress.get("error_message"):
        error_display = progress['error_message']
        message += f"❌ *Error:* {error_display}\n"

    return message


def _generate_progress_bar(progress: Optional[Dict[str, Any]]) -> str:
    """Generate ASCII progress bar - preserving exact original logic."""
    if not progress:
        return "📊 *Progress:* [----------] 0% (Step 0/10)"

    percentage = progress.get("percentage", 0)
    current_step = progress.get("current_step_number", 0)
    total_steps = progress.get("total_steps", 10)

    # Generate progress bar (10 blocks) using simple ASCII characters
    filled_blocks = int(percentage / 10)
    bar = "=" * filled_blocks + "-" * (10 - filled_blocks)

    return f"📊 *Progress:* [{bar}] {percentage:.0f}% (Step {current_step}/{total_steps})"


def _calculate_elapsed_time(job_data: Dict[str, Any]) -> str:
    """Calculate elapsed time since job started - preserving exact original logic."""
    started_at_str = job_data.get("started_at")
    if not started_at_str:
        return "0s"

    # Parse the datetime string back to datetime object
    try:
        started_at = datetime.fromisoformat(started_at_str.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return "0s"

    elapsed = datetime.utcnow() - started_at.replace(tzinfo=None)
    total_seconds = int(elapsed.total_seconds())

    if total_seconds < 60:
        return f"{total_seconds}s"
    elif total_seconds < 3600:
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"{minutes}m {seconds}s"
    else:
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        return f"{hours}h {minutes}m"


def _format_url_display(url: str) -> str:
    """Format URL for display (truncate if too long) - preserving exact original logic."""
    url_str = str(url)
    if len(url_str) > 60:
        return url_str[:57] + "..."
    return url_str


async def _send_status_update(
    job_data: Dict[str, Any],
    message: str,
    progress: Optional[Dict[str, Any]] = None
) -> None:
    """Send a status update message using the existing message queue - PRESERVING ALL TELEGRAM FEATURES."""

    # Format the comprehensive progress message using original logic
    formatted_message = _format_progress_message(job_data, message, progress)

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
        formatted_message = _format_progress_message(
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
    job_data["started_at"] = datetime.utcnow().isoformat()

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

                # Step 1: Validation and setup
                await _send_status_update(
                    job_data,
                    "🔍 Validating URL and setting up environment...",
                    progress={"current_step": "Setup", "total_steps": 10, "current_step_number": 1, "percentage": 10.0}
                )
                await _validate_gitlab_access()
                is_whitelisted = await gitlab_manager.check_whitelist(str(job_data["dump_args"]["url"]))

                # Step 2: Download firmware
                await _send_status_update(
                    job_data,
                    "📥 Downloading firmware...",
                    progress={"current_step": "Download", "total_steps": 10, "current_step_number": 2, "percentage": 20.0}
                )

                # Create DumpJob object for components that need it
                dump_job = DumpJob.model_validate(job_data)
                firmware_path, firmware_name = await downloader.download_firmware(dump_job)

                # Step 3: Extract partitions
                await _send_status_update(
                    job_data,
                    "📦 Extracting firmware partitions...",
                    progress={"current_step": "Extract", "total_steps": 10, "current_step_number": 3, "percentage": 30.0}
                )
                await extractor.extract_firmware(dump_job, firmware_path)

                # Step 4: Process boot images
                await _send_status_update(
                    job_data,
                    "🥾 Processing boot images...",
                    progress={"current_step": "Boot Images", "total_steps": 10, "current_step_number": 4, "percentage": 40.0}
                )
                await extractor.process_boot_images()

                # Step 5: Extract device properties
                await _send_status_update(
                    job_data,
                    "📋 Extracting device properties...",
                    progress={"current_step": "Properties", "total_steps": 10, "current_step_number": 5, "percentage": 50.0}
                )
                device_props = await prop_extractor.extract_properties()

                # Step 6: Generate additional files
                await _send_status_update(
                    job_data,
                    "📄 Generating board info and file listings...",
                    progress={"current_step": "File Generation", "total_steps": 10, "current_step_number": 6, "percentage": 60.0}
                )
                await prop_extractor.generate_board_info()
                await prop_extractor.generate_all_files_list()

                # Step 7: Generate device tree
                await _send_status_update(
                    job_data,
                    "🌳 Generating device tree...",
                    progress={"current_step": "Device Tree", "total_steps": 10, "current_step_number": 7, "percentage": 70.0}
                )
                await prop_extractor.generate_device_tree()

                # Step 8: Create GitLab repository
                await _send_status_update(
                    job_data,
                    "🗂️ Creating GitLab repository...",
                    progress={"current_step": "GitLab Setup", "total_steps": 10, "current_step_number": 8, "percentage": 80.0}
                )

                # Get DUMPER_TOKEN from environment or settings
                dumper_token = getattr(settings, 'DUMPER_TOKEN', None)
                if not dumper_token:
                    raise Exception("DUMPER_TOKEN not configured")

                repo_url, repo_path = await gitlab_manager.create_and_push_repository(device_props, dumper_token)

                # Step 9: Send channel notification
                await _send_status_update(
                    job_data,
                    "📢 Sending channel notification...",
                    progress={"current_step": "Notification", "total_steps": 10, "current_step_number": 9, "percentage": 90.0}
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

                # Step 10: Complete
                await _send_status_update(
                    job_data,
                    f"✅ *Dump completed successfully!*\n\n📁 *Repository:* {repo_url}\n📱 *Device:* {device_props.get('brand', 'Unknown')} {device_props.get('codename', 'Unknown')}",
                    progress={"current_step": "Completed", "total_steps": 10, "current_step_number": 10, "percentage": 100.0}
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