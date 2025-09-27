import asyncio
import secrets
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from rich.console import Console

from dumpyarabot.config import settings
from dumpyarabot.firmware_downloader import FirmwareDownloader
from dumpyarabot.firmware_extractor import FirmwareExtractor
from dumpyarabot.gitlab_manager import GitLabManager
from dumpyarabot.message_queue import message_queue
from dumpyarabot.property_extractor import PropertyExtractor
from dumpyarabot.schemas import DumpJob, JobStatus, JobProgress
from dumpyarabot.utils import escape_markdown

console = Console()


class DumpWorker:
    """Base class for processing dump jobs from the Redis queue."""

    def __init__(self, worker_id: Optional[str] = None):
        self.worker_id = worker_id or f"worker_{secrets.token_hex(4)}"
        self._running = False
        self._current_job: Optional[DumpJob] = None

    async def start(self) -> None:
        """Start the worker loop."""
        console.print(f"[green]Starting dump worker {self.worker_id}[/green]")
        self._running = True

        try:
            while self._running:
                await self._worker_loop()
        except Exception as e:
            console.print(f"[red]Worker {self.worker_id} crashed: {e}[/red]")
            raise
        finally:
            console.print(f"[yellow]Worker {self.worker_id} stopped[/yellow]")

    async def stop(self) -> None:
        """Stop the worker."""
        console.print(f"[yellow]Stopping worker {self.worker_id}[/yellow]")
        self._running = False

        # If we have a current job, mark it as failed so it can be retried
        if self._current_job:
            await self._handle_worker_shutdown()

    async def _worker_loop(self) -> None:
        """Main worker loop - get jobs and process them."""
        try:
            # Get next job from queue
            job = await message_queue.get_next_job(self.worker_id)
            if not job:
                # No job available, wait a bit
                await asyncio.sleep(1)
                return

            self._current_job = job
            console.print(f"[blue]Worker {self.worker_id} processing job {job.job_id}[/blue]")

            # Process the job
            success = await self._process_job(job)

            if success:
                await message_queue.update_job_status(
                    job.job_id,
                    JobStatus.COMPLETED,
                    result_data=getattr(job, '_result_data', None)
                )
                console.print(f"[green]Job {job.job_id} completed successfully[/green]")
            else:
                await self._handle_job_failure(job)

        except Exception as e:
            console.print(f"[red]Error in worker loop: {e}[/red]")
            if self._current_job:
                await self._handle_job_failure(self._current_job, str(e))
        finally:
            self._current_job = None

    async def _process_job(self, job: DumpJob) -> bool:
        """Process a single dump job. Override this in subclasses."""
        console.print(f"[yellow]Base worker processing job {job.job_id} - this should be overridden[/yellow]")

        # Send initial status update
        await self._send_status_update(
            job,
            "🔄 Starting firmware dump...",
            progress={"current_step": "Starting", "total_steps": 5, "current_step_number": 1, "percentage": 0.0}
        )

        # Simulate work
        await asyncio.sleep(2)

        # Send progress update
        await self._send_status_update(
            job,
            "📥 Downloading firmware...",
            progress={"current_step": "Downloading", "total_steps": 5, "current_step_number": 2, "percentage": 20.0}
        )

        await asyncio.sleep(2)

        # Send completion
        await self._send_status_update(
            job,
            "✅ Base worker completed (override this method)",
            progress={"current_step": "Completed", "total_steps": 5, "current_step_number": 5, "percentage": 100.0}
        )

        return True

    def _format_progress_message(
        self,
        job: DumpJob,
        current_step: str,
        progress: Optional[Dict[str, Any]] = None
    ) -> str:
        """Format a comprehensive progress message."""

        # Generate progress bar
        progress_bar = self._generate_progress_bar(progress)

        # Calculate elapsed time
        elapsed = self._calculate_elapsed_time(job)

        # Format URL (truncate if too long)
        url = self._format_url_display(job.dump_args.url)

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

        url_display = self._format_url_display(job.dump_args.url)
        job_id_display = job.job_id
        worker_id_display = self.worker_id
        current_step_display = current_step

        message = f"{status_emoji} *{status_text}*\n\n"
        message += f"📥 *URL:* `{url_display}`\n"
        message += f"🆔 *Job ID:* `{job_id_display}`\n"

        # Format options
        options = []
        if job.dump_args.use_alt_dumper:
            options.append("Alt Dumper")
        if job.add_blacklist:
            options.append("Blacklist")
        if job.dump_args.use_privdump:
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

    def _generate_progress_bar(self, progress: Optional[Dict[str, Any]]) -> str:
        """Generate ASCII progress bar."""
        if not progress:
            return "📊 *Progress:* [----------] 0% (Step 0/10)"

        percentage = progress.get("percentage", 0)
        current_step = progress.get("current_step_number", 0)
        total_steps = progress.get("total_steps", 10)

        # Generate progress bar (10 blocks) using simple ASCII characters
        filled_blocks = int(percentage / 10)
        bar = "=" * filled_blocks + "-" * (10 - filled_blocks)
        # Escape special characters in the progress bar
        escaped_bar = bar.replace("-", "\-").replace("=", "\=")

        return f"📊 *Progress:* [{bar}] {percentage:.0f}% (Step {current_step}/{total_steps})"

    def _calculate_elapsed_time(self, job: DumpJob) -> str:
        """Calculate elapsed time since job started."""
        if not job.started_at:
            return "0s"

        elapsed = datetime.utcnow() - job.started_at
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

    def _format_url_display(self, url: str) -> str:
        """Format URL for display (truncate if too long)."""
        url_str = str(url)
        if len(url_str) > 60:
            return url_str[:57] + "..."
        return url_str


    async def _send_status_update(
        self,
        job: DumpJob,
        message: str,
        progress: Optional[Dict[str, Any]] = None
    ) -> None:
        """Send a status update message for the job."""
        # Update job progress in Redis
        if progress:
            await message_queue.update_job_status(
                job.job_id,
                JobStatus.PROCESSING,
                progress=progress
            )

        # Format the comprehensive progress message
        formatted_message = self._format_progress_message(job, message, progress)

        # ALWAYS edit the initial message - no fallbacks, no multiple messages
        if not job.initial_message_id or not job.initial_chat_id:
            console.print(f"[red]ERROR: Job {job.job_id} missing initial message reference! Cannot send updates.[/red]")
            return

        chat_id = job.initial_chat_id

        if job.dump_args.initial_message_id and job.initial_chat_id != settings.ALLOWED_CHATS[0]:
            # Cross-chat update for moderated system - edit with cross-chat reply
            await message_queue.send_cross_chat_edit(
                chat_id=settings.ALLOWED_CHATS[0],
                text=formatted_message,
                edit_message_id=job.initial_message_id,
                reply_to_message_id=job.dump_args.initial_message_id,
                reply_to_chat_id=job.initial_chat_id,
                context={
                    "job_id": job.job_id,
                    "worker_id": self.worker_id,
                    "progress": progress
                }
            )
        else:
            # Same-chat update - edit the initial message
            await message_queue.send_status_update(
                chat_id=chat_id,
                text=formatted_message,
                edit_message_id=job.initial_message_id,
                parse_mode=settings.DEFAULT_PARSE_MODE,
                context={
                    "job_id": job.job_id,
                    "worker_id": self.worker_id,
                    "progress": progress
                }
            )

    async def _handle_job_failure(self, job: DumpJob, error_message: Optional[str] = None) -> None:
        """Handle a job failure."""
        # Check if job already has meaningful error details from a previous status update
        existing_error_details = getattr(job, 'error_details', None)
        if existing_error_details and existing_error_details != "Unknown error occurred":
            # Job already has proper error details from _process_job, no need for redundant notification
            console.print(f"[red]Job {job.job_id} already has error details: {existing_error_details}[/red]")
            # Still mark as failed in case it wasn't already
            await message_queue.update_job_status(
                job.job_id,
                JobStatus.FAILED,
                error_details=existing_error_details
            )
            return

        error_details = error_message or "Unknown error occurred"

        console.print(f"[red]Job {job.job_id} failed: {error_details}[/red]")

        # Mark job as failed
        await message_queue.update_job_status(
            job.job_id,
            JobStatus.FAILED,
            error_details=error_details
        )

        # Send failure notification
        await self._send_failure_notification(job, error_details)

    async def _send_failure_notification(self, job: DumpJob, error_details: str) -> None:
        """Send a failure notification to the user."""
        # Create progress data to show failure state
        failure_progress = {
            "current_step": "Failed",
            "total_steps": 10,
            "current_step_number": 0,
            "percentage": 0.0,
            "error_message": error_details
        }

        # Format the failure message using the standard progress format
        formatted_message = self._format_progress_message(
            job,
            f"❌ Failed at: {job.progress.current_step if job.progress else 'Unknown step'}",
            failure_progress
        )

        # ALWAYS edit the initial message for failure updates too
        if not job.initial_message_id or not job.initial_chat_id:
            console.print(f"[red]ERROR: Job {job.job_id} missing initial message reference! Cannot send failure update.[/red]")
            return

        chat_id = job.initial_chat_id

        if job.dump_args.initial_message_id and job.initial_chat_id != settings.ALLOWED_CHATS[0]:
            # Cross-chat failure update for moderated system - edit with cross-chat reply
            await message_queue.send_cross_chat_edit(
                chat_id=settings.ALLOWED_CHATS[0],
                text=formatted_message,
                edit_message_id=job.initial_message_id,
                reply_to_message_id=job.dump_args.initial_message_id,
                reply_to_chat_id=job.initial_chat_id,
                context={"job_id": job.job_id, "type": "failure"}
            )
        else:
            # Same-chat failure update - edit the initial message
            await message_queue.send_status_update(
                chat_id=chat_id,
                text=formatted_message,
                edit_message_id=job.initial_message_id,
                parse_mode=settings.DEFAULT_PARSE_MODE,  # Use unified setting
                context={"job_id": job.job_id, "type": "failure"}
            )

    async def _handle_worker_shutdown(self) -> None:
        """Handle graceful worker shutdown when a job is in progress."""
        if not self._current_job:
            return

        console.print(f"[yellow]Worker shutting down with active job {self._current_job.job_id}[/yellow]")

        # Mark job as failed due to worker shutdown
        await message_queue.update_job_status(
            self._current_job.job_id,
            JobStatus.FAILED,
            error_details="Worker shut down during processing"
        )

        console.print(f"[red]Job {self._current_job.job_id} marked as failed due to worker shutdown[/red]")


class ExtractAndPushWorker(DumpWorker):
    """Worker that implements the extract_and_push.sh functionality in Python."""

    async def _process_job(self, job: DumpJob) -> bool:
        """Process a dump job by replicating extract_and_push.sh functionality."""
        console.print(f"[blue]ExtractAndPushWorker processing job {job.job_id}[/blue]")

        # Create temporary work directory
        with tempfile.TemporaryDirectory(prefix=f"dump_{job.job_id}_") as temp_dir:
            work_dir = Path(temp_dir)
            console.print(f"[blue]Working directory: {work_dir}[/blue]")

            try:
                # Initialize components
                downloader = FirmwareDownloader(str(work_dir))
                extractor = FirmwareExtractor(str(work_dir))
                prop_extractor = PropertyExtractor(str(work_dir))
                gitlab_manager = GitLabManager(str(work_dir))

                # Step 1: Validation and setup
                await self._send_status_update(
                    job,
                    "🔍 Validating URL and setting up environment...",
                    progress={"current_step": "Setup", "total_steps": 10, "current_step_number": 1, "percentage": 10.0}
                )
                await self._validate_gitlab_access()
                is_whitelisted = await gitlab_manager.check_whitelist(str(job.dump_args.url))

                # Step 2: Download firmware
                await self._send_status_update(
                    job,
                    "📥 Downloading firmware...",
                    progress={"current_step": "Download", "total_steps": 10, "current_step_number": 2, "percentage": 20.0}
                )
                firmware_path, firmware_name = await downloader.download_firmware(job)

                # Step 3: Extract partitions
                await self._send_status_update(
                    job,
                    "📦 Extracting firmware partitions...",
                    progress={"current_step": "Extract", "total_steps": 10, "current_step_number": 3, "percentage": 30.0}
                )
                await extractor.extract_firmware(job, firmware_path)

                # Step 4: Process boot images
                await self._send_status_update(
                    job,
                    "🥾 Processing boot images...",
                    progress={"current_step": "Boot Images", "total_steps": 10, "current_step_number": 4, "percentage": 40.0}
                )
                await extractor.process_boot_images()

                # Step 5: Extract device properties
                await self._send_status_update(
                    job,
                    "📋 Extracting device properties...",
                    progress={"current_step": "Properties", "total_steps": 10, "current_step_number": 5, "percentage": 50.0}
                )
                device_props = await prop_extractor.extract_properties()

                # Step 6: Generate additional files
                await self._send_status_update(
                    job,
                    "📄 Generating board info and file listings...",
                    progress={"current_step": "File Generation", "total_steps": 10, "current_step_number": 6, "percentage": 60.0}
                )
                await prop_extractor.generate_board_info()
                await prop_extractor.generate_all_files_list()

                # Step 7: Generate device tree
                await self._send_status_update(
                    job,
                    "🌳 Generating device tree...",
                    progress={"current_step": "Device Tree", "total_steps": 10, "current_step_number": 7, "percentage": 70.0}
                )
                await prop_extractor.generate_device_tree()

                # Step 8: Create GitLab repository
                await self._send_status_update(
                    job,
                    "🗂️ Creating GitLab repository...",
                    progress={"current_step": "GitLab Setup", "total_steps": 10, "current_step_number": 8, "percentage": 80.0}
                )

                # Get DUMPER_TOKEN from environment or settings
                dumper_token = getattr(settings, 'DUMPER_TOKEN', None)
                if not dumper_token:
                    raise Exception("DUMPER_TOKEN not configured")

                repo_url, repo_path = await gitlab_manager.create_and_push_repository(device_props, dumper_token)

                # Step 9: Send channel notification
                await self._send_status_update(
                    job,
                    "📢 Sending channel notification...",
                    progress={"current_step": "Notification", "total_steps": 10, "current_step_number": 9, "percentage": 90.0}
                )

                # Get API_KEY from environment or settings for channel notification
                api_key = getattr(settings, 'API_KEY', None)
                if api_key:
                    await gitlab_manager.send_channel_notification(
                        device_props,
                        repo_url,
                        str(job.dump_args.url),
                        is_whitelisted,
                        job.add_blacklist,
                        api_key
                    )

                # Step 10: Complete
                await self._send_status_update(
                    job,
                    f"✅ *Dump completed successfully!*\n\n📁 *Repository:* {repo_url}\n📱 *Device:* {device_props.get('brand', 'Unknown')} {device_props.get('codename', 'Unknown')}",
                    progress={"current_step": "Completed", "total_steps": 10, "current_step_number": 10, "percentage": 100.0}
                )

                # Store result data for completion
                job._result_data = {
                    "repository_url": repo_url,
                    "repository_path": repo_path,
                    "device_info": device_props,
                    "firmware_file": firmware_name,
                    "is_whitelisted": is_whitelisted
                }

                return True

            except Exception as e:
                console.print(f"[red]Error processing job {job.job_id}: {e}[/red]")
                await self._send_status_update(
                    job,
                    f"❌ *Job failed:* {str(e)}",
                    progress={"current_step": "Failed", "total_steps": 10, "current_step_number": 0, "percentage": 0.0}
                )
                return False

    async def _validate_gitlab_access(self) -> None:
        """Validate GitLab server access."""
        import httpx
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get("https://dumps.tadiphone.dev", timeout=10.0)
                if response.status_code >= 400:
                    raise Exception(f"GitLab server returned {response.status_code}")
                console.print("[green]GitLab server access validated[/green]")
        except Exception as e:
            raise Exception(f"Cannot access GitLab server: {e}")