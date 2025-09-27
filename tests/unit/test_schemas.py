"""
Unit tests for dumpyarabot schemas.
"""
import pytest
from pydantic import ValidationError

from dumpyarabot.schemas import DumpArguments, DumpJob, JobMetadata


class TestDumpArguments:
    """Test cases for DumpArguments schema."""

    def test_valid_dump_arguments(self):
        """Test creating valid DumpArguments."""
        args = DumpArguments(
            url="https://example.com/firmware.zip",
            use_alt_dumper=False,
            use_privdump=False,
            initial_message_id=123,
            initial_chat_id=456
        )

        assert str(args.url) == "https://example.com/firmware.zip"
        assert args.use_alt_dumper is False
        assert args.use_privdump is False
        assert args.initial_message_id == 123
        assert args.initial_chat_id == 456

    def test_dump_arguments_with_options(self):
        """Test DumpArguments with all options enabled."""
        args = DumpArguments(
            url="https://example.com/firmware.zip",
            use_alt_dumper=True,
            use_privdump=True,
            initial_message_id=123,
            initial_chat_id=456
        )

        assert args.use_alt_dumper is True
        assert args.use_privdump is True

    def test_dump_arguments_invalid_url(self):
        """Test DumpArguments with invalid URL."""
        with pytest.raises(ValidationError):
            DumpArguments(
                url="not-a-valid-url",
                use_alt_dumper=False,
                use_privdump=False,
                initial_message_id=123,
                initial_chat_id=456
            )


class TestDumpJob:
    """Test cases for DumpJob schema."""

    def test_valid_dump_job(self):
        """Test creating valid DumpJob."""
        args = DumpArguments(
            url="https://example.com/firmware.zip",
            use_alt_dumper=False,
            use_privdump=False,
            initial_message_id=123,
            initial_chat_id=456
        )

        job = DumpJob(
            job_id="test_123",
            dump_args=args,
            add_blacklist=False
        )

        assert job.job_id == "test_123"
        assert str(job.dump_args.url) == "https://example.com/firmware.zip"
        assert job.add_blacklist is False

    def test_dump_job_with_blacklist(self):
        """Test DumpJob with blacklist enabled."""
        args = DumpArguments(
            url="https://example.com/firmware.zip",
            use_alt_dumper=False,
            use_privdump=False,
            initial_message_id=123,
            initial_chat_id=456
        )

        job = DumpJob(
            job_id="test_123",
            dump_args=args,
            add_blacklist=True
        )

        assert job.add_blacklist is True


class TestJobMetadata:
    """Test cases for JobMetadata schema."""

    def test_valid_job_metadata(self):
        """Test creating valid JobMetadata."""
        metadata = JobMetadata(
            job_type="dump",
            telegram_context={
                "chat_id": 123456,
                "message_id": 789,
                "user_id": 999
            }
        )

        assert metadata.job_type == "dump"
        assert metadata.telegram_context["chat_id"] == 123456
        assert metadata.progress_history == []
        assert metadata.status is None

    def test_job_metadata_minimal(self):
        """Test JobMetadata with minimal required fields."""
        metadata = JobMetadata()

        assert metadata.job_type == "dump"  # Default value
        assert metadata.telegram_context is None
        assert metadata.progress_history == []