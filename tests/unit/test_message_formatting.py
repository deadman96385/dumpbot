"""
Unit tests for dumpyarabot message formatting utilities.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dumpyarabot.message_formatting import (
    _create_ascii_bar,
    _create_block_bar,
    _create_empty_bar,
    _create_progress_bar,
    _create_unicode_bar,
    calculate_elapsed_time,
    format_build_summary_info,
    format_channel_notification_message,
    format_comprehensive_progress_message,
    format_device_properties_message,
    format_dump_options,
    format_enhanced_job_status,
    format_error_message,
    format_jobs_overview,
    format_status_update_message,
    format_success_message,
    format_time_ago,
    format_url_display,
    generate_progress_bar,
    get_arq_start_time,
)


@pytest.mark.unit
class TestARQUtilities:
    """Test ARQ-related utility functions."""

    @pytest.mark.asyncio
    async def test_get_arq_start_time_success(self):
        """Test successful ARQ start time retrieval."""
        mock_arq_status = {"start_time": "2023-01-01T12:00:00Z"}

        mock_pool = AsyncMock()
        mock_pool.get_job_status = AsyncMock(return_value=mock_arq_status)

        with patch("dumpyarabot.arq_config.arq_pool", mock_pool):
            result = await get_arq_start_time("test_job_123")

            mock_pool.get_job_status.assert_called_once_with("test_job_123")
            assert result == "2023-01-01T12:00:00Z"

    @pytest.mark.asyncio
    async def test_get_arq_start_time_no_status(self):
        """Test ARQ start time retrieval when no status available."""
        mock_pool = AsyncMock()
        mock_pool.get_job_status = AsyncMock(return_value=None)

        with patch("dumpyarabot.arq_config.arq_pool", mock_pool):
            result = await get_arq_start_time("test_job_123")

            assert result is None

    @pytest.mark.asyncio
    async def test_get_arq_start_time_exception(self):
        """Test ARQ start time retrieval when exception occurs."""
        mock_pool = AsyncMock()
        mock_pool.get_job_status = AsyncMock(side_effect=Exception("Connection error"))

        with patch("dumpyarabot.arq_config.arq_pool", mock_pool):
            result = await get_arq_start_time("test_job_123")

            assert result is None


@pytest.mark.unit
class TestProgressBar:
    """Test progress bar generation functions."""

    def test_generate_progress_bar_with_progress(self):
        """Test progress bar generation with valid progress data."""
        progress = {"percentage": 45, "current_step_number": 4, "total_steps": 8}

        result = generate_progress_bar(progress)

        assert "📊 *Progress:* [" in result
        assert "] 45% (Step 4/8)" in result

    def test_generate_progress_bar_empty_progress(self):
        """Test progress bar generation with empty progress."""
        result = generate_progress_bar(None)

        assert "📊 *Progress:* [" in result
        assert "] 0% (Step 0/10)" in result

    def test_generate_progress_bar_with_style_options(self):
        """Test progress bar generation with different styles."""
        progress = {"percentage": 50, "current_step_number": 5, "total_steps": 10}

        # Unicode style (default)
        unicode_bar = generate_progress_bar(progress, style="unicode")
        assert "📊 *Progress:*" in unicode_bar

        # ASCII style
        ascii_bar = generate_progress_bar(progress, style="ascii")
        assert "📊 *Progress:*" in ascii_bar

        # Blocks style
        blocks_bar = generate_progress_bar(progress, style="blocks")
        assert "📊 *Progress:*" in blocks_bar

    def test_generate_progress_bar_clamping(self):
        """Test progress bar percentage clamping."""
        # Test over 100%
        progress = {"percentage": 150, "current_step_number": 1, "total_steps": 1}
        result = generate_progress_bar(progress)
        assert "] 100% " in result

        # Test under 0%
        progress = {"percentage": -10, "current_step_number": 0, "total_steps": 10}
        result = generate_progress_bar(progress)
        assert "] 0% " in result

    def test_create_unicode_bar(self):
        """Test Unicode progress bar creation."""
        bar = _create_unicode_bar(50, 10)
        assert len(bar) == 10
        assert "█" in bar or "▌" in bar

    def test_create_block_bar(self):
        """Test block progress bar creation."""
        bar = _create_block_bar(50, 10)
        assert len(bar) == 10
        assert "█" in bar and "░" in bar

    def test_create_ascii_bar(self):
        """Test ASCII progress bar creation."""
        bar = _create_ascii_bar(50, 10)
        assert len(bar) == 10
        assert "=" in bar and "-" in bar

    def test_create_empty_bar(self):
        """Test empty progress bar creation."""
        unicode_bar = _create_empty_bar(10, "unicode")
        assert len(unicode_bar) == 10
        assert unicode_bar == " " * 10

        ascii_bar = _create_empty_bar(10, "ascii")
        assert len(ascii_bar) == 10
        assert ascii_bar == "-" * 10

        blocks_bar = _create_empty_bar(10, "blocks")
        assert len(blocks_bar) == 10
        assert blocks_bar == "░" * 10


@pytest.mark.unit
class TestTimeCalculations:
    """Test time calculation functions."""

    def test_calculate_elapsed_time_with_iso_format(self):
        """Test elapsed time calculation with ISO format timestamp."""
        # Create a timestamp 2 hours ago
        start_time = datetime.now(timezone.utc) - timedelta(hours=2, minutes=5)
        start_time_str = start_time.isoformat().replace("+00:00", "Z")

        result = calculate_elapsed_time(start_time_str)

        assert "h" in result and "m" in result

    def test_calculate_elapsed_time_with_fallback(self):
        """Test elapsed time calculation with fallback timestamp."""
        start_time = datetime.now(timezone.utc) - timedelta(minutes=30)
        fallback_str = start_time.isoformat().replace("+00:00", "Z")

        result = calculate_elapsed_time(None, fallback_str)

        assert "m" in result and "s" in result

    def test_calculate_elapsed_time_no_timestamp(self):
        """Test elapsed time calculation with no timestamp."""
        result = calculate_elapsed_time(None)
        assert result == "0s"

    def test_calculate_elapsed_time_invalid_format(self):
        """Test elapsed time calculation with invalid timestamp format."""
        result = calculate_elapsed_time("invalid-timestamp")
        assert result == "0s"

    def test_calculate_elapsed_time_seconds_only(self):
        """Test elapsed time calculation for short durations."""
        start_time = datetime.now(timezone.utc) - timedelta(seconds=30)
        start_time_str = start_time.isoformat().replace("+00:00", "Z")

        result = calculate_elapsed_time(start_time_str)

        assert result.endswith("s")
        assert "m" not in result and "h" not in result

    def test_format_time_ago(self):
        """Test time ago formatting."""
        now = datetime.now(timezone.utc)

        # Test seconds ago
        seconds_ago = now - timedelta(seconds=30)
        assert format_time_ago(seconds_ago) == "30s ago"

        # Test minutes ago
        minutes_ago = now - timedelta(minutes=5)
        assert format_time_ago(minutes_ago) == "5m ago"

        # Test hours ago
        hours_ago = now - timedelta(hours=2)
        assert format_time_ago(hours_ago) == "2h ago"

        # Test days ago
        days_ago = now - timedelta(days=3)
        assert format_time_ago(days_ago) == "3d ago"

        # Test None timestamp
        assert format_time_ago(None) == "Unknown"


@pytest.mark.unit
class TestFormatting:
    """Test formatting utility functions."""

    def test_format_url_display_short_url(self):
        """Test URL formatting for short URLs."""
        url = "https://example.com/short"
        result = format_url_display(url)
        assert result == url

    def test_format_url_display_long_url(self):
        """Test URL formatting for long URLs."""
        long_url = "https://example.com/" + "a" * 60
        result = format_url_display(long_url, max_length=60)
        assert len(result) == 60
        assert result.endswith("...")

    def test_format_dump_options_all_options(self):
        """Test dump options formatting with all options enabled."""
        dump_args = {"use_alt_dumper": True, "use_privdump": True}
        options = format_dump_options(dump_args, add_blacklist=True)

        assert "Alt Dumper" in options
        assert "Blacklist" in options
        assert "Private" in options

    def test_format_dump_options_no_options(self):
        """Test dump options formatting with no options enabled."""
        dump_args = {"use_alt_dumper": False, "use_privdump": False}
        options = format_dump_options(dump_args, add_blacklist=False)

        assert options == []

    def test_format_dump_options_partial(self):
        """Test dump options formatting with some options enabled."""
        dump_args = {"use_alt_dumper": True, "use_privdump": False}
        options = format_dump_options(dump_args, add_blacklist=False)

        assert options == ["Alt Dumper"]


@pytest.mark.unit
class TestMessageFormatting:
    """Test complex message formatting functions."""

    @pytest.mark.asyncio
    async def test_format_comprehensive_progress_message_basic(self):
        """Test comprehensive progress message formatting."""
        job_data = {
            "job_id": "test_job_123",
            "dump_args": {
                "url": "https://example.com/firmware.zip",
                "use_alt_dumper": False,
                "use_privdump": False,
            },
            "add_blacklist": False,
            "worker_id": "worker_001",
        }

        progress = {"percentage": 45, "current_step_number": 4, "total_steps": 8}

        current_step = "Extracting partitions..."

        result = await format_comprehensive_progress_message(
            job_data, current_step, progress
        )

        assert "🚀 *Firmware Dump in Progress*" in result
        assert "test_job_123" in result
        assert "Extracting partitions..." in result
        assert "45%" in result

    @pytest.mark.asyncio
    async def test_format_comprehensive_progress_message_completed(self):
        """Test comprehensive progress message for completed job."""
        job_data = {
            "job_id": "test_job_123",
            "dump_args": {
                "url": "https://example.com/firmware.zip",
                "use_alt_dumper": True,
                "use_privdump": False,
            },
            "add_blacklist": True,
            "worker_id": "worker_001",
        }

        progress = {"percentage": 100, "current_step_number": 8, "total_steps": 8}

        metadata = {
            "device_info": {
                "brand": "Samsung",
                "codename": "galaxy_s21",
                "android_version": "13",
            },
            "repository": {"url": "https://gitlab.com/test/repo"},
        }

        current_step = "Dump completed successfully"

        result = await format_comprehensive_progress_message(
            job_data, current_step, progress, metadata
        )

        assert "✅ *Firmware Dump Completed*" in result
        assert "Samsung galaxy_s21" in result
        assert "Android 13" in result
        assert "Alt Dumper, Blacklist" in result
        assert "https://gitlab.com/test/repo" in result

    @pytest.mark.asyncio
    async def test_format_comprehensive_progress_message_with_error(self):
        """Test comprehensive progress message with error."""
        job_data = {
            "job_id": "test_job_123",
            "dump_args": {
                "url": "https://example.com/firmware.zip",
                "use_alt_dumper": False,
                "use_privdump": False,
            },
            "add_blacklist": False,
        }

        progress = {"current_step": "Failed", "error_message": "Network timeout"}

        metadata = {
            "error_context": {
                "message": "Failed to download firmware",
                "current_step": "Download",
                "last_successful_step": "Validation",
            }
        }

        current_step = "Download failed"

        result = await format_comprehensive_progress_message(
            job_data, current_step, progress, metadata
        )

        assert "❌ *Firmware Dump Failed*" in result
        assert "Failed to download firmware" in result
        assert "Download" in result
        assert "Validation" in result

    def test_format_build_summary_info(self):
        """Test build summary formatting."""
        result = format_build_summary_info(
            "firmware_build", 42, "SUCCESS", "2023-01-01 12:00:00"
        )

        assert "**Job:** `firmware\\_build`" in result  # Underscores are escaped
        assert "**Build:** `#42`" in result
        assert "✅ SUCCESS" in result
        assert "**Date:** 2023-01-01 12:00:00" in result

    def test_format_device_properties_message(self):
        """Test device properties formatting."""
        device_props = {
            "brand": "Samsung",
            "codename": "galaxy_s21",
            "release": "13",
            "fingerprint": "samsung/galaxy_s21/...",
            "platform": "sm8350",
        }

        result = format_device_properties_message(device_props)

        assert "*Brand*: `Samsung`" in result
        assert "*Device*: `galaxy\\_s21`" in result  # Underscores are escaped
        assert "*Version*: `13`" in result
        assert "*Platform*: `sm8350`" in result

    def test_format_channel_notification_message(self):
        """Test channel notification formatting."""
        device_props = {"brand": "Samsung", "codename": "galaxy_s21"}

        result = format_channel_notification_message(
            device_props,
            "https://gitlab.com/test/repo",
            "https://example.com/firmware.zip",
        )

        assert "*Brand*: `Samsung`" in result
        assert "[[repo](https://gitlab.com/test/repo)]" in result
        assert "[[firmware](https://example.com/firmware.zip)]" in result

    def test_format_error_message(self):
        """Test error message formatting."""
        result = format_error_message(
            "Network Error",
            "Connection timeout after 30 seconds",
            "test_job_123",
            {"url": "https://example.com", "attempts": 3},
        )

        assert "❌ *Network Error*" in result
        assert "🆔 *Job ID:* `test_job_123`" in result
        assert "**Details:** Connection timeout after 30 seconds" in result
        assert "**Url:** `https://example.com`" in result
        assert "**Attempts:** `3`" in result

    def test_format_success_message(self):
        """Test success message formatting."""
        links = {
            "Repository": "https://gitlab.com/test/repo",
            "Download": "https://example.com/firmware.zip",
        }

        result = format_success_message(
            "Dump Completed", "Firmware extracted successfully", links
        )

        assert "✅ *Dump Completed*" in result
        assert "Firmware extracted successfully" in result
        assert "🔗 [Repository](https://gitlab.com/test/repo)" in result
        assert "🔗 [Download](https://example.com/firmware.zip)" in result

    def test_format_status_update_message(self):
        """Test status update message formatting."""
        result = format_status_update_message(
            "processing", "test_job_123", "Extracting system partition", 75.5
        )

        assert "🚀 *Status: Processing*" in result
        assert "🆔 *Job ID:* `test_job_123`" in result
        assert "Extracting system partition" in result
        assert "76%" in result  # Progress bar (rounded percentage)


@pytest.mark.unit
class TestEnhancedFormatting:
    """Test enhanced formatting functions with mock objects."""

    @pytest.mark.asyncio
    async def test_format_enhanced_job_status_basic(self):
        """Test enhanced job status formatting."""
        # Create a mock DumpJob
        mock_job = MagicMock()
        mock_job.job_id = "test_job_123"
        mock_job.status = "completed"
        mock_job.result_data = {
            "metadata": {
                "device_info": {
                    "brand": "Samsung",
                    "codename": "galaxy_s21",
                    "android_version": "13",
                },
                "repository": {"url": "https://gitlab.com/test/repo"},
            }
        }
        mock_job.progress = {"percentage": 100, "current_step": "Completed"}
        mock_job.started_at = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_job.completed_at = datetime(2023, 1, 1, 13, 0, 0, tzinfo=timezone.utc)

        result = await format_enhanced_job_status(mock_job)

        assert "📋 *Job Details: test\\_job\\_123*" in result
        assert "✅ *Status:* Completed" in result
        assert "📱 *Device:* Samsung galaxy_s21" in result
        assert "🤖 *Android:* 13" in result
        assert "🗂️ *Repository:*" in result

    @pytest.mark.asyncio
    async def test_format_enhanced_job_status_with_error(self):
        """Test enhanced job status formatting with error."""
        mock_job = MagicMock()
        mock_job.job_id = "test_job_123"
        mock_job.status = "failed"
        mock_job.result_data = {
            "metadata": {
                "error_context": {
                    "message": "Network timeout",
                    "current_step": "Download",
                }
            }
        }
        mock_job.progress = None
        mock_job.started_at = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_job.completed_at = None

        result = await format_enhanced_job_status(mock_job)

        assert "❌ *Status:* Failed" in result
        assert "❌ *Error:* Network timeout" in result
        assert "🔍 *Failed at:* Download" in result

    @pytest.mark.asyncio
    async def test_format_jobs_overview_with_jobs(self):
        """Test jobs overview formatting with active and recent jobs."""
        # Mock active jobs
        active_job = MagicMock()
        active_job.job_id = "active_job_123"
        active_job.result_data = {
            "metadata": {
                "telegram_context": {"url": "https://example.com/firmware.zip"}
            }
        }
        active_job.progress = {"current_step": "Extracting", "percentage": 45}

        # Mock recent jobs
        recent_job = MagicMock()
        recent_job.job_id = "recent_job_456"
        recent_job.status = "completed"
        recent_job.result_data = {
            "metadata": {"device_info": {"brand": "Samsung", "codename": "galaxy_s21"}}
        }
        recent_job.completed_at = datetime.now(timezone.utc) - timedelta(hours=1)
        recent_job.started_at = None

        result = await format_jobs_overview([active_job], [recent_job])

        assert "📊 *Job Status Overview*" in result
        assert "🟢 *Active Jobs (1):*" in result
        assert "active_j" in result  # Truncated job ID (8 chars)
        assert "Extracting (45.0%)" in result
        assert "📋 *Recent Jobs (1):*" in result
        assert "✅ `recent_j`" in result  # Truncated job ID (8 chars)
        assert "Samsung galaxy\\_s21" in result  # Underscores are escaped

    @pytest.mark.asyncio
    async def test_format_jobs_overview_empty(self):
        """Test jobs overview formatting with no jobs."""
        result = await format_jobs_overview([], [])

        assert "📊 *Job Status Overview*" in result
        assert "🟢 *Active Jobs:* None" in result
        assert "📋 *Recent Jobs" not in result  # No recent jobs section if empty


@pytest.mark.unit
class TestInternalFunctions:
    """Test internal/private formatting functions."""

    def test_create_progress_bar_styles(self):
        """Test _create_progress_bar function with different styles."""
        # Test unicode style
        unicode_bar = _create_progress_bar(50, 10, "unicode")
        assert len(unicode_bar) == 10

        # Test blocks style
        blocks_bar = _create_progress_bar(50, 10, "blocks")
        assert len(blocks_bar) == 10
        assert "█" in blocks_bar and "░" in blocks_bar

        # Test ascii style (default for unknown style)
        ascii_bar = _create_progress_bar(50, 10, "ascii")
        assert len(ascii_bar) == 10
        assert "=" in ascii_bar and "-" in ascii_bar

        # Test unknown style (defaults to ascii)
        unknown_bar = _create_progress_bar(50, 10, "unknown")
        assert len(unknown_bar) == 10
        assert "=" in unknown_bar and "-" in unknown_bar


@pytest.mark.unit
class TestIntegration:
    """Integration tests for message formatting components."""

    @pytest.mark.asyncio
    async def test_comprehensive_message_with_arq_fallback(self):
        """Test comprehensive message formatting with ARQ time fallback."""
        job_data = {
            "job_id": "test_job_123",
            "arq_job_id": "arq_123",
            "dump_args": {
                "url": "https://example.com/firmware.zip",
                "use_alt_dumper": False,
                "use_privdump": False,
            },
        }

        progress = {"percentage": 30, "current_step_number": 3, "total_steps": 10}

        current_step = "Downloading firmware..."

        # Mock ARQ start time retrieval
        with patch(
            "dumpyarabot.message_formatting.get_arq_start_time"
        ) as mock_get_arq_time:
            mock_get_arq_time.return_value = "2023-01-01T12:00:00Z"

            result = await format_comprehensive_progress_message(
                job_data, current_step, progress
            )

            mock_get_arq_time.assert_called_once_with("arq_123")
            assert "🚀 *Firmware Dump in Progress*" in result
            assert "Downloading firmware..." in result
            assert "30%" in result

    def test_edge_cases_and_validation(self):
        """Test edge cases and input validation."""
        # Test empty or malformed progress data
        empty_progress = {}
        result = generate_progress_bar(empty_progress)
        assert "0%" in result

        # Test malformed device properties
        malformed_props = {}
        result = format_device_properties_message(malformed_props)
        assert "*Brand*: `Unknown`" in result
        assert "*Device*: `Unknown`" in result

        # Test empty dump args
        empty_args = {}
        options = format_dump_options(empty_args)
        assert options == []

        # Test very long error messages
        long_error = "A" * 1000
        result = format_error_message("Test Error", long_error)
        assert "❌ *Test Error*" in result
        assert long_error in result  # Should include full error message
