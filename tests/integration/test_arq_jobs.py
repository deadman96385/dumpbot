"""
Integration tests for ARQ job processing.
Tests the complete firmware processing pipeline with mock external dependencies.
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
import tempfile

from dumpyarabot.arq_jobs import process_firmware_dump
from dumpyarabot.schemas import JobMetadata


@pytest.mark.integration
class TestARQJobProcessing:
    """Integration tests for ARQ firmware processing jobs."""

    @pytest.fixture
    def mock_firmware_path(self, tmp_path):
        """Create a mock firmware file for testing."""
        firmware_file = tmp_path / "test_firmware.zip"
        # Create a minimal ZIP file for testing
        import zipfile
        with zipfile.ZipFile(firmware_file, 'w') as zf:
            # Add a basic build.prop
            zf.writestr('build.prop', """ro.product.brand=TestBrand
ro.product.model=TestModel
ro.build.version.release=13
ro.build.id=TEST123""")
        return str(firmware_file)

    @pytest.mark.asyncio
    async def test_process_firmware_dump_basic(self, mock_firmware_path):
        """Test basic firmware dump processing with mocked components."""
        with patch('dumpyarabot.arq_jobs.FirmwareDownloader') as mock_downloader_class, \
             patch('dumpyarabot.arq_jobs.FirmwareExtractor') as mock_extractor_class, \
             patch('dumpyarabot.arq_jobs.PropertyExtractor') as mock_property_class, \
             patch('dumpyarabot.arq_jobs.GitLabManager') as mock_gitlab_class, \
             patch('dumpyarabot.arq_jobs.settings') as mock_settings, \
             patch('dumpyarabot.message_queue.message_queue.send_status_update') as mock_status_update, \
             patch('dumpyarabot.message_queue.message_queue.send_cross_chat_edit') as mock_cross_chat_edit:

            # Setup mocks
            mock_downloader = MagicMock()
            mock_downloader.download_firmware = AsyncMock(return_value=(mock_firmware_path, "test_firmware.zip"))
            mock_downloader_class.return_value = mock_downloader

            mock_extractor = MagicMock()
            mock_extractor.extract_firmware = AsyncMock(return_value="/tmp/extracted")
            mock_extractor_class.return_value = mock_extractor

            mock_property_extractor = MagicMock()
            mock_property_extractor.extract_properties = AsyncMock(return_value={
                "brand": "TestBrand",
                "model": "TestModel",
                "android_version": "13",
                "build_id": "TEST123"
            })
            mock_property_class.return_value = mock_property_extractor

            mock_gitlab = MagicMock()
            mock_gitlab.create_and_push_repository = AsyncMock(return_value=(
                "https://test.gitlab.com/test/repo",
                "/tmp/extracted"
            ))
            mock_gitlab.check_whitelist = AsyncMock(return_value=True)
            mock_gitlab.send_channel_notification = AsyncMock()
            mock_gitlab_class.return_value = mock_gitlab

            # Mock settings
            mock_settings.DUMPER_TOKEN = "test_dumper_token"
            mock_settings.API_KEY = "test_api_key"

            # Execute job with ARQ-style parameters (DumpJob model dump)
            from dumpyarabot.schemas import DumpJob, DumpArguments
            from datetime import datetime

            ctx = MagicMock()  # Mock ARQ context
            dump_args = DumpArguments(
                url="https://example.com/test_firmware.zip",
                use_alt_dumper=False,
                use_privdump=False,
                initial_message_id=123,
                initial_chat_id=456
            )

            job = DumpJob(
                job_id="test_job_123",
                dump_args=dump_args,
                add_blacklist=False,
                initial_message_id=123,
                initial_chat_id=456,
                metadata=JobMetadata(job_type="dump")
            )

            job_data = job.model_dump()

            result = await process_firmware_dump(ctx, job_data)

            # Verify the pipeline executed
            assert result is not None
            # For success case, we need to check what the success result structure looks like

            # Verify components were called
            mock_downloader.download_firmware.assert_called_once()
            mock_extractor.extract_firmware.assert_called_once()
            mock_property_extractor.extract_properties.assert_called_once()
            mock_gitlab.create_and_push_repository.assert_called_once()

            # Verify status updates were sent
            total_updates = mock_status_update.call_count + mock_cross_chat_edit.call_count
            assert total_updates >= 3  # At least init, progress, completion

    @pytest.mark.asyncio
    async def test_process_firmware_dump_download_failure(self, mock_firmware_path):
        """Test firmware processing when download fails."""
        with patch('dumpyarabot.arq_jobs.FirmwareDownloader') as mock_downloader_class, \
             patch('dumpyarabot.message_queue.message_queue.send_status_update') as mock_status_update, \
             patch('dumpyarabot.message_queue.message_queue.send_cross_chat_edit') as mock_cross_chat_edit:

            # Setup mock to fail download
            mock_downloader = MagicMock()
            mock_downloader.download_firmware = AsyncMock(side_effect=Exception("Download failed"))
            mock_downloader_class.return_value = mock_downloader

            # Execute job with proper DumpJob structure
            from dumpyarabot.schemas import DumpJob, DumpArguments

            ctx = MagicMock()
            dump_args = DumpArguments(
                url="https://example.com/test_firmware.zip",
                use_alt_dumper=False,
                use_privdump=False,
                initial_message_id=123,
                initial_chat_id=456
            )

            job = DumpJob(
                job_id="test_job_123",
                dump_args=dump_args,
                add_blacklist=False,
                initial_message_id=123,
                initial_chat_id=456,
                metadata=JobMetadata(job_type="dump")
            )

            job_data = job.model_dump()

            result = await process_firmware_dump(ctx, job_data)

            # Verify failure handling
            assert result is not None
            assert result.get("success") == False
            assert "error" in result

            # Verify error status was sent
            assert mock_status_update.called or mock_cross_chat_edit.called