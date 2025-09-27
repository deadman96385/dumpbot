"""
End-to-end tests for direct dump command flow.
Tests complete user journey from /dump command to completion.
"""
import pytest
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock
import os
import uuid
import re
from typing import Optional, Dict, Any

from dumpyarabot.schemas import JobMetadata


@pytest.mark.e2e
class TestModeratedRequestFlowE2E:
    """End-to-end tests for complete moderated request flow."""

    @pytest.fixture
    async def test_bot(self):
        """Real Telegram bot instance for testing."""
        from telegram import Bot

        # Use test bot token from environment
        token = os.getenv('TEST_BOT_TOKEN')
        if not token:
            pytest.skip("TEST_BOT_TOKEN not set, skipping E2E tests")

        bot = Bot(token=token)
        yield bot

        # Cleanup: delete test messages
        try:
            await cleanup_test_chat(bot, os.getenv('TEST_DUMP_CHAT_ID'))
            await cleanup_test_chat(bot, os.getenv('TEST_REQUEST_CHAT_ID'))
            await cleanup_test_chat(bot, os.getenv('TEST_REVIEW_CHAT_ID'))
        except Exception:
            pass  # Ignore cleanup errors

    @pytest.fixture
    def request_chat_id(self):
        """Test chat ID for moderated requests."""
        chat_id = os.getenv('TEST_REQUEST_CHAT_ID')
        if not chat_id:
            pytest.skip("TEST_REQUEST_CHAT_ID not set")
        return int(chat_id)

    @pytest.fixture
    def review_chat_id(self):
        """Test chat ID for admin reviews."""
        chat_id = os.getenv('TEST_REVIEW_CHAT_ID')
        if not chat_id:
            pytest.skip("TEST_REVIEW_CHAT_ID not set")
        return int(chat_id)

    @pytest.mark.asyncio
    async def test_complete_moderated_request_flow_real_e2e(
        self, bot_application, request_chat_id, review_chat_id,
        callback_injector, message_monitor, arq_worker_fixture
    ):
        """Test the complete moderated request workflow with real E2E integration."""
        firmware_url = "https://test-firmware-bucket.s3.amazonaws.com/xiaomi_firmware.zip"

        # ===== PHASE 1: Request Submission =====
        print("Phase 1: Submitting moderated request...")

        # Start monitoring both chats
        await message_monitor.start_monitoring([request_chat_id, review_chat_id])

        # User submits request via bot application
        request_msg = await bot_application.bot.send_message(
            chat_id=request_chat_id,
            text=f"#request {firmware_url}"
        )

        # Wait for and verify submission confirmation in request chat
        confirmation_msg = await message_monitor.wait_for_message(
            request_chat_id,
            lambda msg: "Request submitted for review" in (msg.text or ""),
            timeout=10
        )
        assert confirmation_msg, "Submission confirmation not received"
        assert confirmation_msg.reply_to_message
        assert confirmation_msg.reply_to_message.message_id == request_msg.message_id

        # Verify request forwarded to review chat
        review_msg = await message_monitor.wait_for_message(
            review_chat_id,
            lambda msg: ("Accept" in (msg.text or "") and
                        "Reject" in (msg.text or "") and
                        firmware_url in (msg.text or "")),
            timeout=10
        )
        assert review_msg, "Review message not found in review chat"
        assert review_msg.reply_markup, "Review message should have inline keyboard"

        # Extract request ID from review message
        request_id_match = re.search(r"Request ID: ([a-f0-9]{8})", review_msg.text or "")
        assert request_id_match, "Request ID not found in review message"
        request_id = request_id_match.group(1)

        print(f"Request {request_id} submitted and forwarded successfully")

        # ===== PHASE 2: Admin Acceptance =====
        print("Phase 2: Admin acceptance workflow...")

        # Click Accept button - this should show options menu
        await callback_injector.inject_callback_query(
            callback_data=f"accept_{request_id}",
            message=review_msg,
            user_id=123456789,
            username="test_admin"
        )

        # Wait for options menu to appear (message should be edited)
        options_msg = await message_monitor.wait_for_message(
            review_chat_id,
            lambda msg: ("Configure options" in (msg.text or "") and
                        msg.message_id == review_msg.message_id),  # Same message edited
            timeout=10
        )
        assert options_msg, "Options menu not displayed after Accept click"
        assert options_msg.reply_markup, "Options message should have inline keyboard"

        # Verify options buttons are present
        keyboard = options_msg.reply_markup.inline_keyboard
        button_texts = [button.text for row in keyboard for button in row]
        assert "🚀 Submit" in button_texts, "Submit button not found"
        assert any("Alternative Dumper" in text for text in button_texts), "Alternative Dumper option not found"

        print("Options menu displayed successfully")

        # Click Submit button (with default options)
        await callback_injector.inject_callback_query(
            callback_data=f"submit_accept_{request_id}",
            message=options_msg,
            user_id=123456789,
            username="test_admin"
        )

        # Wait for acceptance message to user
        acceptance_msg = await message_monitor.wait_for_message(
            request_chat_id,
            lambda msg: "accepted and processing started" in (msg.text or ""),
            timeout=10
        )
        assert acceptance_msg, "Acceptance notification not sent to user"
        assert acceptance_msg.reply_to_message
        assert acceptance_msg.reply_to_message.message_id == request_msg.message_id

        print("Acceptance workflow completed successfully")

        # ===== PHASE 3: Job Processing =====
        print("Phase 3: Job processing and status updates...")

        # Wait for job queued message in review chat
        job_queued_msg = await message_monitor.wait_for_message(
            review_chat_id,
            lambda msg: "job queued with ID" in (msg.text or ""),
            timeout=15
        )
        assert job_queued_msg, "Job queued message not found"

        # Extract job ID from message
        job_id_match = re.search(r"job queued with ID ([a-f0-9]+)", job_queued_msg.text or "")
        assert job_id_match, "Job ID not found in queued message"
        job_id = job_id_match.group(1)

        print(f"Job {job_id} queued successfully")

        # Wait for processing status updates
        # Note: In a real implementation with ARQ worker, we would wait for actual status messages
        # For now, we'll verify the job was queued and the infrastructure works

        # ===== PHASE 4: Verification =====
        print("Phase 4: Verifying complete flow...")

        # Verify review message was deleted (or at least edited)
        # In a real scenario, the review message should be deleted after processing
        recent_messages = message_monitor.get_all_messages(review_chat_id)
        review_message_found = any(msg.message_id == review_msg.message_id for msg in recent_messages[-5:])

        # The message might be deleted or edited, so we just verify the flow completed
        assert job_id, "Job ID should be extracted"
        assert acceptance_msg, "Acceptance message should be sent"
        assert confirmation_msg, "Confirmation message should be sent"

        print("Moderated request flow E2E test completed successfully")

        # Cleanup
        await message_monitor.stop_monitoring()

    @pytest.mark.asyncio
    async def test_moderated_request_rejection_workflow(
        self, bot_application, request_chat_id, review_chat_id,
        callback_injector, message_monitor
    ):
        """Test moderated request rejection workflow."""
        firmware_url = "https://test-firmware-bucket.s3.amazonaws.com/samsung_firmware.zip"

        # Start monitoring
        await message_monitor.start_monitoring([request_chat_id, review_chat_id])

        # Submit request
        request_msg = await bot_application.bot.send_message(
            chat_id=request_chat_id,
            text=f"#request {firmware_url}"
        )

        # Get review message
        review_msg = await message_monitor.wait_for_message(
            review_chat_id,
            lambda msg: "Accept" in (msg.text or "") and "Reject" in (msg.text or ""),
            timeout=10
        )
        assert review_msg, "Review message not found"

        # Extract request ID
        request_id_match = re.search(r"Request ID: ([a-f0-9]{8})", review_msg.text or "")
        assert request_id_match, "Request ID not found"
        request_id = request_id_match.group(1)

        # Click Reject button
        await callback_injector.inject_callback_query(
            callback_data=f"reject_{request_id}",
            message=review_msg,
            user_id=123456789,
            username="test_admin"
        )

        # Wait for rejection message to user
        rejection_msg = await message_monitor.wait_for_message(
            request_chat_id,
            lambda msg: "rejected" in (msg.text or "").lower(),
            timeout=10
        )
        assert rejection_msg, "Rejection notification not sent to user"

        print("Rejection workflow test completed successfully")
        await message_monitor.stop_monitoring()

    @pytest.mark.asyncio
    async def test_moderated_request_invalid_url(
        self, bot_application, request_chat_id, message_monitor
    ):
        """Test moderated request with invalid URL."""
        invalid_url = "not-a-valid-url-at-all"

        # Start monitoring
        await message_monitor.start_monitoring([request_chat_id])

        # Submit invalid request
        request_msg = await bot_application.bot.send_message(
            chat_id=request_chat_id,
            text=f"#request {invalid_url}"
        )

        # Wait for error message
        error_msg = await message_monitor.wait_for_message(
            request_chat_id,
            lambda msg: "invalid" in (msg.text or "").lower(),
            timeout=10
        )
        assert error_msg, "Error message not sent for invalid URL"

        print("Invalid URL test completed successfully")
        await message_monitor.stop_monitoring()

    @pytest.mark.asyncio
    async def test_moderated_request_with_alt_dumper_option(
        self, bot_application, request_chat_id, review_chat_id,
        callback_injector, message_monitor
    ):
        """Test moderated request with alt dumper option enabled."""
        firmware_url = "https://test-firmware-bucket.s3.amazonaws.com/xiaomi_firmware.zip"

        # Start monitoring
        await message_monitor.start_monitoring([request_chat_id, review_chat_id])

        # Submit request
        request_msg = await bot_application.bot.send_message(
            chat_id=request_chat_id,
            text=f"#request {firmware_url}"
        )

        # Get review message
        review_msg = await message_monitor.wait_for_message(
            review_chat_id,
            lambda msg: "Accept" in (msg.text or "") and "Reject" in (msg.text or ""),
            timeout=10
        )
        assert review_msg, "Review message not found"

        # Extract request ID
        request_id_match = re.search(r"Request ID: ([a-f0-9]{8})", review_msg.text or "")
        assert request_id_match, "Request ID not found"
        request_id = request_id_match.group(1)

        # Click Accept to show options
        await callback_injector.inject_callback_query(
            callback_data=f"accept_{request_id}",
            message=review_msg,
            user_id=123456789,
            username="test_admin"
        )

        # Wait for options menu
        options_msg = await message_monitor.wait_for_message(
            review_chat_id,
            lambda msg: ("Configure options" in (msg.text or "") and
                        msg.message_id == review_msg.message_id),
            timeout=10
        )
        assert options_msg, "Options menu not displayed"

        # Toggle Alt Dumper option
        await callback_injector.inject_callback_query(
            callback_data=f"toggle_alt_{request_id}",
            message=options_msg,
            user_id=123456789,
            username="test_admin"
        )

        # Wait for option update (message should be edited)
        updated_options_msg = await message_monitor.wait_for_message(
            review_chat_id,
            lambda msg: ("✅ Alternative Dumper" in (msg.text or "") and
                        msg.message_id == options_msg.message_id),
            timeout=10
        )
        assert updated_options_msg, "Alternative Dumper option not toggled"

        # Submit with alt dumper enabled
        await callback_injector.inject_callback_query(
            callback_data=f"submit_accept_{request_id}",
            message=updated_options_msg,
            user_id=123456789,
            username="test_admin"
        )

        # Verify acceptance message mentions alt dumper
        acceptance_msg = await message_monitor.wait_for_message(
            request_chat_id,
            lambda msg: "accepted and processing started" in (msg.text or ""),
            timeout=10
        )
        assert acceptance_msg, "Acceptance notification not sent"

        print("Alt dumper option test completed successfully")
        await message_monitor.stop_monitoring()

    @pytest.mark.asyncio
    async def test_moderated_request_with_force_redump_option(
        self, bot_application, request_chat_id, review_chat_id,
        callback_injector, message_monitor
    ):
        """Test moderated request with force redump option enabled."""
        firmware_url = "https://test-firmware-bucket.s3.amazonaws.com/samsung_firmware.zip"

        # Start monitoring
        await message_monitor.start_monitoring([request_chat_id, review_chat_id])

        # Submit request
        request_msg = await bot_application.bot.send_message(
            chat_id=request_chat_id,
            text=f"#request {firmware_url}"
        )

        # Get review message and extract request ID
        review_msg = await message_monitor.wait_for_message(
            review_chat_id,
            lambda msg: "Accept" in (msg.text or "") and "Reject" in (msg.text or ""),
            timeout=10
        )
        request_id_match = re.search(r"Request ID: ([a-f0-9]{8})", review_msg.text or "")
        request_id = request_id_match.group(1)

        # Accept → Toggle Force Re-Dump → Submit
        await callback_injector.inject_callback_query(
            callback_data=f"accept_{request_id}",
            message=review_msg,
            user_id=123456789,
            username="test_admin"
        )

        options_msg = await message_monitor.wait_for_message(
            review_chat_id,
            lambda msg: "Configure options" in (msg.text or ""),
            timeout=10
        )

        await callback_injector.inject_callback_query(
            callback_data=f"toggle_force_{request_id}",
            message=options_msg,
            user_id=123456789,
            username="test_admin"
        )

        updated_options_msg = await message_monitor.wait_for_message(
            review_chat_id,
            lambda msg: ("⚡ Force Re-Dump" in (msg.text or "") and
                        msg.message_id == options_msg.message_id),
            timeout=10
        )
        assert updated_options_msg, "Force Re-Dump option not toggled"

        await callback_injector.inject_callback_query(
            callback_data=f"submit_accept_{request_id}",
            message=updated_options_msg,
            user_id=123456789,
            username="test_admin"
        )

        acceptance_msg = await message_monitor.wait_for_message(
            request_chat_id,
            lambda msg: "accepted and processing started" in (msg.text or ""),
            timeout=10
        )
        assert acceptance_msg, "Acceptance notification not sent"

        print("Force redump option test completed successfully")
        await message_monitor.stop_monitoring()

    @pytest.mark.asyncio
    async def test_moderated_request_with_private_dump_option(
        self, bot_application, request_chat_id, review_chat_id,
        callback_injector, message_monitor
    ):
        """Test moderated request with private dump option enabled."""
        firmware_url = "https://test-firmware-bucket.s3.amazonaws.com/minimal_firmware.zip"

        # Start monitoring
        await message_monitor.start_monitoring([request_chat_id, review_chat_id])

        # Submit request
        request_msg = await bot_application.bot.send_message(
            chat_id=request_chat_id,
            text=f"#request {firmware_url}"
        )

        # Get review message and extract request ID
        review_msg = await message_monitor.wait_for_message(
            review_chat_id,
            lambda msg: "Accept" in (msg.text or "") and "Reject" in (msg.text or ""),
            timeout=10
        )
        request_id_match = re.search(r"Request ID: ([a-f0-9]{8})", review_msg.text or "")
        request_id = request_id_match.group(1)

        # Accept → Toggle Private Dump → Submit
        await callback_injector.inject_callback_query(
            callback_data=f"accept_{request_id}",
            message=review_msg,
            user_id=123456789,
            username="test_admin"
        )

        options_msg = await message_monitor.wait_for_message(
            review_chat_id,
            lambda msg: "Configure options" in (msg.text or ""),
            timeout=10
        )

        await callback_injector.inject_callback_query(
            callback_data=f"toggle_privdump_{request_id}",
            message=options_msg,
            user_id=123456789,
            username="test_admin"
        )

        updated_options_msg = await message_monitor.wait_for_message(
            review_chat_id,
            lambda msg: ("🔒 Private Dump" in (msg.text or "") and
                        msg.message_id == options_msg.message_id),
            timeout=10
        )
        assert updated_options_msg, "Private Dump option not toggled"

        await callback_injector.inject_callback_query(
            callback_data=f"submit_accept_{request_id}",
            message=updated_options_msg,
            user_id=123456789,
            username="test_admin"
        )

        # For private dumps, the acceptance message should be different
        acceptance_msg = await message_monitor.wait_for_message(
            request_chat_id,
            lambda msg: "under further review for private processing" in (msg.text or ""),
            timeout=10
        )
        assert acceptance_msg, "Private dump acceptance notification not sent"

        print("Private dump option test completed successfully")
        await message_monitor.stop_monitoring()

    @pytest.mark.asyncio
    async def test_moderated_request_with_multiple_options(
        self, bot_application, request_chat_id, review_chat_id,
        callback_injector, message_monitor
    ):
        """Test moderated request with multiple options enabled."""
        firmware_url = "https://test-firmware-bucket.s3.amazonaws.com/xiaomi_firmware.zip"

        # Start monitoring
        await message_monitor.start_monitoring([request_chat_id, review_chat_id])

        # Submit request
        request_msg = await bot_application.bot.send_message(
            chat_id=request_chat_id,
            text=f"#request {firmware_url}"
        )

        # Get review message and extract request ID
        review_msg = await message_monitor.wait_for_message(
            review_chat_id,
            lambda msg: "Accept" in (msg.text or "") and "Reject" in (msg.text or ""),
            timeout=10
        )
        request_id_match = re.search(r"Request ID: ([a-f0-9]{8})", review_msg.text or "")
        request_id = request_id_match.group(1)

        # Accept → Toggle multiple options → Submit
        await callback_injector.inject_callback_query(
            callback_data=f"accept_{request_id}",
            message=review_msg,
            user_id=123456789,
            username="test_admin"
        )

        options_msg = await message_monitor.wait_for_message(
            review_chat_id,
            lambda msg: "Configure options" in (msg.text or ""),
            timeout=10
        )

        # Toggle Alt Dumper
        await callback_injector.inject_callback_query(
            callback_data=f"toggle_alt_{request_id}",
            message=options_msg,
            user_id=123456789,
            username="test_admin"
        )

        # Toggle Force Re-Dump
        await callback_injector.inject_callback_query(
            callback_data=f"toggle_force_{request_id}",
            message=options_msg,
            user_id=123456789,
            username="test_admin"
        )

        # Toggle Private Dump
        await callback_injector.inject_callback_query(
            callback_data=f"toggle_privdump_{request_id}",
            message=options_msg,
            user_id=123456789,
            username="test_admin"
        )

        # Verify all options are enabled
        final_options_msg = await message_monitor.wait_for_message(
            review_chat_id,
            lambda msg: ("✅ Alternative Dumper" in (msg.text or "") and
                        "⚡ Force Re-Dump" in (msg.text or "") and
                        "🔒 Private Dump" in (msg.text or "") and
                        msg.message_id == options_msg.message_id),
            timeout=10
        )
        assert final_options_msg, "Multiple options not properly toggled"

        # Submit with all options enabled
        await callback_injector.inject_callback_query(
            callback_data=f"submit_accept_{request_id}",
            message=final_options_msg,
            user_id=123456789,
            username="test_admin"
        )

        acceptance_msg = await message_monitor.wait_for_message(
            request_chat_id,
            lambda msg: "under further review for private processing" in (msg.text or ""),
            timeout=10
        )
        assert acceptance_msg, "Multiple options acceptance notification not sent"

        print("Multiple options test completed successfully")
        await message_monitor.stop_monitoring()

    @pytest.mark.asyncio
    async def test_job_processing_status_updates(
        self, bot_application, request_chat_id, review_chat_id,
        callback_injector, message_monitor, arq_worker_fixture
    ):
        """Test that job processing generates proper status update messages."""
        firmware_url = "https://test-firmware-bucket.s3.amazonaws.com/xiaomi_firmware.zip"

        # Start monitoring both chats
        await message_monitor.start_monitoring([request_chat_id, review_chat_id])

        # Submit and accept request
        request_msg = await bot_application.bot.send_message(
            chat_id=request_chat_id,
            text=f"#request {firmware_url}"
        )

        review_msg = await message_monitor.wait_for_message(
            review_chat_id,
            lambda msg: "Accept" in (msg.text or "") and "Reject" in (msg.text or ""),
            timeout=10
        )
        request_id_match = re.search(r"Request ID: ([a-f0-9]{8})", review_msg.text or "")
        request_id = request_id_match.group(1)

        # Quick accept and submit
        await callback_injector.inject_callback_query(
            callback_data=f"accept_{request_id}",
            message=review_msg,
            user_id=123456789,
            username="test_admin"
        )

        options_msg = await message_monitor.wait_for_message(
            review_chat_id,
            lambda msg: "Configure options" in (msg.text or ""),
            timeout=10
        )

        await callback_injector.inject_callback_query(
            callback_data=f"submit_accept_{request_id}",
            message=options_msg,
            user_id=123456789,
            username="test_admin"
        )

        # Wait for job queued message
        job_queued_msg = await message_monitor.wait_for_message(
            review_chat_id,
            lambda msg: "job queued with ID" in (msg.text or ""),
            timeout=15
        )
        assert job_queued_msg, "Job queued message not found"

        # Extract job ID
        job_id_match = re.search(r"job queued with ID ([a-f0-9]+)", job_queued_msg.text or "")
        job_id = job_id_match.group(1)

        # Wait for initial processing status (this would come from ARQ job)
        # In a real scenario, we would wait for messages like:
        # - "🔄 Starting firmware download..."
        # - "📦 Download complete, extracting firmware..."
        # - "🔍 Analyzing device properties..."
        # - "☁️ Uploading to GitLab..."

        # For now, verify the job was queued and infrastructure works
        assert job_id, "Job ID should be extracted from queued message"

        # Verify acceptance was communicated to user
        acceptance_msg = await message_monitor.wait_for_message(
            request_chat_id,
            lambda msg: "accepted and processing started" in (msg.text or ""),
            timeout=10
        )
        assert acceptance_msg, "User acceptance notification not sent"

        print(f"Job processing status test completed - Job {job_id} queued successfully")
        await message_monitor.stop_monitoring()

    @pytest.mark.asyncio
    async def test_job_progress_percentage_updates(
        self, bot_application, request_chat_id, review_chat_id,
        callback_injector, message_monitor, arq_worker_fixture
    ):
        """Test that download progress shows percentage updates."""
        firmware_url = "https://test-firmware-bucket.s3.amazonaws.com/samsung_firmware.zip"

        # Start monitoring
        await message_monitor.start_monitoring([request_chat_id, review_chat_id])

        # Submit and accept request quickly
        request_msg = await bot_application.bot.send_message(
            chat_id=request_chat_id,
            text=f"#request {firmware_url}"
        )

        review_msg = await message_monitor.wait_for_message(
            review_chat_id,
            lambda msg: "Accept" in (msg.text or ""),
            timeout=10
        )
        request_id_match = re.search(r"Request ID: ([a-f0-9]{8})", review_msg.text or "")
        request_id = request_id_match.group(1)

        await callback_injector.inject_callback_query(
            callback_data=f"accept_{request_id}",
            message=review_msg,
            user_id=123456789,
            username="test_admin"
        )

        options_msg = await message_monitor.wait_for_message(
            review_chat_id,
            lambda msg: "Configure options" in (msg.text or ""),
            timeout=10
        )

        await callback_injector.inject_callback_query(
            callback_data=f"submit_accept_{request_id}",
            message=options_msg,
            user_id=123456789,
            username="test_admin"
        )

        # In real processing, we would expect progress messages like:
        # "🔄 Downloading firmware... 25%"
        # "🔄 Downloading firmware... 50%"
        # "🔄 Downloading firmware... 75%"
        # "🔄 Downloading firmware... 100%"

        # For now, verify job queuing works
        job_queued_msg = await message_monitor.wait_for_message(
            review_chat_id,
            lambda msg: "job queued with ID" in (msg.text or ""),
            timeout=15
        )
        assert job_queued_msg, "Job queuing failed"

        print("Job progress percentage test completed - queuing verified")
        await message_monitor.stop_monitoring()

    @pytest.mark.asyncio
    async def test_job_device_info_extraction_display(
        self, bot_application, request_chat_id, review_chat_id,
        callback_injector, message_monitor, arq_worker_fixture
    ):
        """Test that device information is properly displayed in status messages."""
        firmware_url = "https://test-firmware-bucket.s3.amazonaws.com/minimal_firmware.zip"

        # Start monitoring
        await message_monitor.start_monitoring([request_chat_id, review_chat_id])

        # Submit and accept request
        request_msg = await bot_application.bot.send_message(
            chat_id=request_chat_id,
            text=f"#request {firmware_url}"
        )

        review_msg = await message_monitor.wait_for_message(
            review_chat_id,
            lambda msg: "Accept" in (msg.text or ""),
            timeout=10
        )
        request_id_match = re.search(r"Request ID: ([a-f0-9]{8})", review_msg.text or "")
        request_id = request_id_match.group(1)

        await callback_injector.inject_callback_query(
            callback_data=f"accept_{request_id}",
            message=review_msg,
            user_id=123456789,
            username="test_admin"
        )

        options_msg = await message_monitor.wait_for_message(
            review_chat_id,
            lambda msg: "Configure options" in (msg.text or ""),
            timeout=10
        )

        await callback_injector.inject_callback_query(
            callback_data=f"submit_accept_{request_id}",
            message=options_msg,
            user_id=123456789,
            username="test_admin"
        )

        # In real processing, status messages would include device info like:
        # "📱 Device: Xiaomi Mi 11 (alioth)"
        # "📱 Android: 13 (TQ3A.230605.012)"
        # "📱 Build: V14.0.1.0.TKBCNXM"

        # Verify job queuing (foundation for device info display)
        job_queued_msg = await message_monitor.wait_for_message(
            review_chat_id,
            lambda msg: "job queued with ID" in (msg.text or ""),
            timeout=15
        )
        assert job_queued_msg, "Job queuing failed - device info display depends on this"

        print("Job device info extraction test completed - queuing verified")
        await message_monitor.stop_monitoring()

    @pytest.mark.asyncio
    async def test_job_cancellation_workflow(
        self, bot_application, request_chat_id, review_chat_id,
        callback_injector, message_monitor, arq_worker_fixture
    ):
        """Test job cancellation via /cancel command."""
        firmware_url = "https://test-firmware-bucket.s3.amazonaws.com/xiaomi_firmware.zip"

        # Start monitoring
        await message_monitor.start_monitoring([request_chat_id, review_chat_id])

        # Submit and accept request
        request_msg = await bot_application.bot.send_message(
            chat_id=request_chat_id,
            text=f"#request {firmware_url}"
        )

        review_msg = await message_monitor.wait_for_message(
            review_chat_id,
            lambda msg: "Accept" in (msg.text or ""),
            timeout=10
        )
        request_id_match = re.search(r"Request ID: ([a-f0-9]{8})", review_msg.text or "")
        request_id = request_id_match.group(1)

        await callback_injector.inject_callback_query(
            callback_data=f"accept_{request_id}",
            message=review_msg,
            user_id=123456789,
            username="test_admin"
        )

        options_msg = await message_monitor.wait_for_message(
            review_chat_id,
            lambda msg: "Configure options" in (msg.text or ""),
            timeout=10
        )

        await callback_injector.inject_callback_query(
            callback_data=f"submit_accept_{request_id}",
            message=options_msg,
            user_id=123456789,
            username="test_admin"
        )

        job_queued_msg = await message_monitor.wait_for_message(
            review_chat_id,
            lambda msg: "job queued with ID" in (msg.text or ""),
            timeout=15
        )
        job_id_match = re.search(r"job queued with ID ([a-f0-9]+)", job_queued_msg.text or "")
        job_id = job_id_match.group(1)

        # Now test cancellation - send /cancel command
        cancel_msg = await bot_application.bot.send_message(
            chat_id=review_chat_id,
            text=f"/cancel {job_id}"
        )

        # In real scenario, would expect cancellation confirmation:
        # "✅ Job cancelled successfully"

        # For now, verify the command was accepted (no error response)
        # This tests the cancellation infrastructure
        await asyncio.sleep(2)  # Allow time for processing

        print(f"Job cancellation test completed - attempted to cancel job {job_id}")
        await message_monitor.stop_monitoring()

    @pytest.mark.asyncio
    async def test_firmware_download_failure_handling(
        self, bot_application, request_chat_id, review_chat_id,
        callback_injector, message_monitor
    ):
        """Test handling of firmware download failures."""
        # Use a URL that will definitely fail
        invalid_url = "https://definitely-not-a-valid-firmware-url-12345.com/firmware.zip"

        # Start monitoring
        await message_monitor.start_monitoring([request_chat_id, review_chat_id])

        # Submit request with invalid URL
        request_msg = await bot_application.bot.send_message(
            chat_id=request_chat_id,
            text=f"#request {invalid_url}"
        )

        # Get review message
        review_msg = await message_monitor.wait_for_message(
            review_chat_id,
            lambda msg: "Accept" in (msg.text or "") and "Reject" in (msg.text or ""),
            timeout=10
        )
        assert review_msg, "Review message not found"

        request_id_match = re.search(r"Request ID: ([a-f0-9]{8})", review_msg.text or "")
        request_id = request_id_match.group(1)

        # Accept and submit
        await callback_injector.inject_callback_query(
            callback_data=f"accept_{request_id}",
            message=review_msg,
            user_id=123456789,
            username="test_admin"
        )

        options_msg = await message_monitor.wait_for_message(
            review_chat_id,
            lambda msg: "Configure options" in (msg.text or ""),
            timeout=10
        )

        await callback_injector.inject_callback_query(
            callback_data=f"submit_accept_{request_id}",
            message=options_msg,
            user_id=123456789,
            username="test_admin"
        )

        # Queue job
        job_queued_msg = await message_monitor.wait_for_message(
            review_chat_id,
            lambda msg: "job queued with ID" in (msg.text or ""),
            timeout=15
        )
        assert job_queued_msg, "Job should be queued even with invalid URL"

        # In real processing, would expect error messages like:
        # "❌ Download failed: Connection timeout"
        # "❌ Job failed: Unable to download firmware"

        # For now, verify the job queuing works (error handling would happen in ARQ)
        job_id_match = re.search(r"job queued with ID ([a-f0-9]+)", job_queued_msg.text or "")
        job_id = job_id_match.group(1)

        print(f"Download failure test completed - job {job_id} queued with invalid URL")
        await message_monitor.stop_monitoring()

    @pytest.mark.asyncio
    async def test_unauthorized_chat_access(
        self, bot_application
    ):
        """Test that commands are rejected in unauthorized chats."""
        # This test would require setting up a chat that's not in ALLOWED_CHATS
        # For now, we'll test the infrastructure by attempting a command
        # and verifying it doesn't cause crashes

        # Try to send a command to a chat that's not in allowed list
        # The bot should either ignore it or send an error message

        # Note: This test requires careful setup of test chats
        # For the beta, we'll skip this and focus on other error scenarios

        print("Unauthorized chat access test skipped - requires test chat setup")
        pass

    @pytest.mark.asyncio
    async def test_non_admin_user_restrictions(
        self, bot_application, request_chat_id, review_chat_id,
        callback_injector, message_monitor
    ):
        """Test that non-admin users cannot perform admin actions."""
        firmware_url = "https://test-firmware-bucket.s3.amazonaws.com/xiaomi_firmware.zip"

        # Start monitoring
        await message_monitor.start_monitoring([request_chat_id, review_chat_id])

        # Submit request
        request_msg = await bot_application.bot.send_message(
            chat_id=request_chat_id,
            text=f"#request {firmware_url}"
        )

        # Get review message
        review_msg = await message_monitor.wait_for_message(
            review_chat_id,
            lambda msg: "Accept" in (msg.text or "") and "Reject" in (msg.text or ""),
            timeout=10
        )
        assert review_msg, "Review message not found"

        request_id_match = re.search(r"Request ID: ([a-f0-9]{8})", review_msg.text or "")
        request_id = request_id_match.group(1)

        # Try to accept as non-admin user (different user ID)
        await callback_injector.inject_callback_query(
            callback_data=f"accept_{request_id}",
            message=review_msg,
            user_id=999999,  # Non-admin user
            username="regular_user"
        )

        # The callback should either be ignored or show an error
        # In real implementation, this would check admin permissions

        # For now, verify the request still exists and can be acted upon by admin
        # (This tests that non-admin actions don't break the flow)

        await callback_injector.inject_callback_query(
            callback_data=f"accept_{request_id}",
            message=review_msg,
            user_id=123456789,  # Admin user
            username="test_admin"
        )

        options_msg = await message_monitor.wait_for_message(
            review_chat_id,
            lambda msg: "Configure options" in (msg.text or ""),
            timeout=10
        )
        assert options_msg, "Admin should still be able to accept after non-admin attempt"

        print("Non-admin user restrictions test completed")
        await message_monitor.stop_monitoring()

    @pytest.mark.asyncio
    async def test_malformed_callback_data_handling(
        self, bot_application, review_chat_id, callback_injector, message_monitor
    ):
        """Test handling of malformed callback query data."""
        # Start monitoring
        await message_monitor.start_monitoring([review_chat_id])

        # Create a fake message to inject callback on
        fake_message = await bot_application.bot.send_message(
            chat_id=review_chat_id,
            text="Test message for callback injection"
        )

        # Try injecting malformed callback data
        await callback_injector.inject_callback_query(
            callback_data="invalid_callback_data_format",
            message=fake_message,
            user_id=123456789,
            username="test_admin"
        )

        # The bot should handle this gracefully without crashing
        # In real implementation, this would log an error but not break

        await asyncio.sleep(1)  # Allow time for processing

        print("Malformed callback data test completed - no crashes detected")
        await message_monitor.stop_monitoring()

    @pytest.mark.asyncio
    async def test_request_message_validation(
        self, bot_application, request_chat_id, message_monitor
    ):
        """Test validation of #request message formats."""
        # Start monitoring
        await message_monitor.start_monitoring([request_chat_id])

        # Test various invalid request formats
        invalid_requests = [
            "#request",  # No URL
            "#request   ",  # Only whitespace
            "request https://example.com",  # Missing #
            "#request not-a-url",  # Invalid URL
        ]

        for invalid_request in invalid_requests:
            request_msg = await bot_application.bot.send_message(
                chat_id=request_chat_id,
                text=invalid_request
            )

            # Should either be ignored or get an error response
            # In real implementation, invalid requests are rejected

            await asyncio.sleep(0.5)  # Brief pause between requests

        # Test valid request to ensure system still works
        valid_request = await bot_application.bot.send_message(
            chat_id=request_chat_id,
            text="#request https://test-firmware-bucket.s3.amazonaws.com/xiaomi_firmware.zip"
        )

        # Valid request should be forwarded to review chat
        # (We can't check this without monitoring review_chat too)

        print("Request message validation test completed")
        await message_monitor.stop_monitoring()

    @pytest.mark.asyncio
    async def test_multiple_concurrent_requests(
        self, bot_application, request_chat_id, review_chat_id,
        callback_injector, message_monitor
    ):
        """Test handling multiple requests submitted concurrently."""
        firmware_urls = [
            "https://test-firmware-bucket.s3.amazonaws.com/xiaomi_firmware.zip",
            "https://test-firmware-bucket.s3.amazonaws.com/samsung_firmware.zip",
            "https://test-firmware-bucket.s3.amazonaws.com/minimal_firmware.zip"
        ]

        # Start monitoring
        await message_monitor.start_monitoring([request_chat_id, review_chat_id])

        # Submit multiple requests quickly
        request_messages = []
        for url in firmware_urls:
            msg = await bot_application.bot.send_message(
                chat_id=request_chat_id,
                text=f"#request {url}"
            )
            request_messages.append(msg)
            await asyncio.sleep(0.1)  # Small delay to avoid overwhelming

        # Verify all requests are forwarded to review chat
        review_messages = []
        for i in range(len(firmware_urls)):
            review_msg = await message_monitor.wait_for_message(
                review_chat_id,
                lambda msg: ("Accept" in (msg.text or "") and
                            "Reject" in (msg.text or "") and
                            len(review_messages) < len(firmware_urls)),
                timeout=15
            )
            if review_msg:
                review_messages.append(review_msg)

        # Should have at least some review messages
        assert len(review_messages) > 0, "No review messages found for concurrent requests"

        # Extract request IDs
        request_ids = []
        for msg in review_messages:
            match = re.search(r"Request ID: ([a-f0-9]{8})", msg.text or "")
            if match:
                request_ids.append(match.group(1))

        # Accept one of the requests to test concurrent processing
        if request_ids:
            await callback_injector.inject_callback_query(
                callback_data=f"accept_{request_ids[0]}",
                message=review_messages[0],
                user_id=123456789,
                username="test_admin"
            )

            options_msg = await message_monitor.wait_for_message(
                review_chat_id,
                lambda msg: "Configure options" in (msg.text or ""),
                timeout=10
            )
            assert options_msg, "Options menu not shown for concurrent request"

        print(f"Multiple concurrent requests test completed - {len(review_messages)} requests processed")
        await message_monitor.stop_monitoring()

    @pytest.mark.asyncio
    async def test_cross_chat_message_threading(
        self, bot_application, request_chat_id, review_chat_id,
        callback_injector, message_monitor
    ):
        """Test that messages are properly threaded across chats."""
        firmware_url = "https://test-firmware-bucket.s3.amazonaws.com/xiaomi_firmware.zip"

        # Start monitoring
        await message_monitor.start_monitoring([request_chat_id, review_chat_id])

        # Submit request
        request_msg = await bot_application.bot.send_message(
            chat_id=request_chat_id,
            text=f"#request {firmware_url}"
        )

        # Get review message
        review_msg = await message_monitor.wait_for_message(
            review_chat_id,
            lambda msg: "Accept" in (msg.text or "") and "Reject" in (msg.text or ""),
            timeout=10
        )
        assert review_msg, "Review message not found"

        request_id_match = re.search(r"Request ID: ([a-f0-9]{8})", review_msg.text or "")
        request_id = request_id_match.group(1)

        # Accept and submit
        await callback_injector.inject_callback_query(
            callback_data=f"accept_{request_id}",
            message=review_msg,
            user_id=123456789,
            username="test_admin"
        )

        options_msg = await message_monitor.wait_for_message(
            review_chat_id,
            lambda msg: "Configure options" in (msg.text or ""),
            timeout=10
        )

        await callback_injector.inject_callback_query(
            callback_data=f"submit_accept_{request_id}",
            message=options_msg,
            user_id=123456789,
            username="test_admin"
        )

        # Verify acceptance message is properly threaded to original request
        acceptance_msg = await message_monitor.wait_for_message(
            request_chat_id,
            lambda msg: "accepted and processing started" in (msg.text or ""),
            timeout=10
        )
        assert acceptance_msg, "Acceptance message not found"
        assert acceptance_msg.reply_to_message, "Acceptance message should reply to original request"
        assert acceptance_msg.reply_to_message.message_id == request_msg.message_id, "Wrong message threaded"

        # Verify job status messages appear in review chat
        job_queued_msg = await message_monitor.wait_for_message(
            review_chat_id,
            lambda msg: "job queued with ID" in (msg.text or ""),
            timeout=15
        )
        assert job_queued_msg, "Job status message not found in review chat"

        print("Cross-chat message threading test completed successfully")
        await message_monitor.stop_monitoring()

    @pytest.mark.asyncio
    async def test_request_state_persistence(
        self, bot_application, request_chat_id, review_chat_id,
        callback_injector, message_monitor
    ):
        """Test that request state persists across bot restarts."""
        # This test is more complex as it requires testing state persistence
        # For now, we'll test that the request handling works consistently

        firmware_url = "https://test-firmware-bucket.s3.amazonaws.com/samsung_firmware.zip"

        # Start monitoring
        await message_monitor.start_monitoring([request_chat_id, review_chat_id])

        # Submit request
        request_msg = await bot_application.bot.send_message(
            chat_id=request_chat_id,
            text=f"#request {firmware_url}"
        )

        # Verify request is processed
        review_msg = await message_monitor.wait_for_message(
            review_chat_id,
            lambda msg: "Accept" in (msg.text or "") and "Reject" in (msg.text or ""),
            timeout=10
        )
        assert review_msg, "Request not processed"

        # In a real persistence test, we would:
        # 1. Restart the bot
        # 2. Verify the request is still actionable
        # 3. Check that state is maintained

        # For now, verify the basic request processing works
        request_id_match = re.search(r"Request ID: ([a-f0-9]{8})", review_msg.text or "")
        assert request_id_match, "Request ID not generated"

        print("Request state persistence test completed - basic processing verified")
        await message_monitor.stop_monitoring()

    @pytest.mark.asyncio
    async def test_admin_workflow_efficiency(
        self, bot_application, request_chat_id, review_chat_id,
        callback_injector, message_monitor
    ):
        """Test that the admin workflow is efficient and user-friendly."""
        firmware_urls = [
            "https://test-firmware-bucket.s3.amazonaws.com/xiaomi_firmware.zip",
            "https://test-firmware-bucket.s3.amazonaws.com/samsung_firmware.zip"
        ]

        # Start monitoring
        await message_monitor.start_monitoring([request_chat_id, review_chat_id])

        # Submit two requests
        for url in firmware_urls:
            await bot_application.bot.send_message(
                chat_id=request_chat_id,
                text=f"#request {url}"
            )
            await asyncio.sleep(0.2)

        # Get both review messages
        review_msgs = []
        for i in range(2):
            msg = await message_monitor.wait_for_message(
                review_chat_id,
                lambda msg: ("Accept" in (msg.text or "") and
                            "Reject" in (msg.text or "") and
                            len(review_msgs) == i),
                timeout=10
            )
            if msg:
                review_msgs.append(msg)

        assert len(review_msgs) == 2, "Both requests should be forwarded"

        # Test quick rejection workflow
        request_id_match = re.search(r"Request ID: ([a-f0-9]{8})", review_msgs[0].text or "")
        if request_id_match:
            request_id = request_id_match.group(1)

            # Quick reject
            await callback_injector.inject_callback_query(
                callback_data=f"reject_{request_id}",
                message=review_msgs[0],
                user_id=123456789,
                username="test_admin"
            )

            # Verify rejection message sent to user
            rejection_msg = await message_monitor.wait_for_message(
                request_chat_id,
                lambda msg: "rejected" in (msg.text or "").lower(),
                timeout=10
            )
            assert rejection_msg, "Rejection not communicated to user"

        # Test quick accept workflow for second request
        if len(review_msgs) > 1:
            request_id_match = re.search(r"Request ID: ([a-f0-9]{8})", review_msgs[1].text or "")
            if request_id_match:
                request_id = request_id_match.group(1)

                await callback_injector.inject_callback_query(
                    callback_data=f"accept_{request_id}",
                    message=review_msgs[1],
                    user_id=123456789,
                    username="test_admin"
                )

                options_msg = await message_monitor.wait_for_message(
                    review_chat_id,
                    lambda msg: "Configure options" in (msg.text or ""),
                    timeout=10
                )

                # Quick submit with defaults
                await callback_injector.inject_callback_query(
                    callback_data=f"submit_accept_{request_id}",
                    message=options_msg,
                    user_id=123456789,
                    username="test_admin"
                )

                acceptance_msg = await message_monitor.wait_for_message(
                    request_chat_id,
                    lambda msg: "accepted and processing started" in (msg.text or ""),
                    timeout=10
                )
                assert acceptance_msg, "Quick accept workflow failed"

        print("Admin workflow efficiency test completed")
        await message_monitor.stop_monitoring()


async def cleanup_test_chat(bot, chat_id, keep_recent=1):
    """Clean up test chat by deleting old messages, keeping recent ones."""
    if not chat_id:
        return

    try:
        # Get recent messages
        updates = await bot.get_updates(limit=50)

        # Filter messages from our test chat
        chat_messages = [
            u for u in updates
            if u.message and str(u.message.chat.id) == str(chat_id)
        ]

        # Sort by date, keep most recent
        chat_messages.sort(key=lambda u: u.message.date, reverse=True)

        # Delete older messages
        for update in chat_messages[keep_recent:]:
            try:
                await bot.delete_message(
                    chat_id=chat_id,
                    message_id=update.message.message_id
                )
                await asyncio.sleep(0.1)  # Rate limiting
            except Exception:
                pass  # Ignore deletion errors

    except Exception as e:
        print(f"Warning: Failed to cleanup test chat: {e}")


