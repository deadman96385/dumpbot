"""
Unit tests for dumpyarabot URL utilities.
"""
from unittest.mock import AsyncMock, patch

import pytest

from dumpyarabot.url_utils import (
    check_url_accessibility,
    parse_url_components,
    validate_and_normalize_url,
)


@pytest.mark.asyncio
class TestValidateAndNormalizeUrl:
    """Test cases for validate_and_normalize_url function."""

    async def test_validate_valid_http_url(self):
        """Test validation of valid HTTP URL."""
        is_valid, normalized_url, error_msg = await validate_and_normalize_url(
            "http://example.com/file.zip"
        )

        assert is_valid is True
        assert normalized_url == "http://example.com/file.zip"
        assert error_msg is None

    async def test_validate_valid_https_url(self):
        """Test validation of valid HTTPS URL."""
        is_valid, normalized_url, error_msg = await validate_and_normalize_url(
            "https://example.com/file.zip"
        )

        assert is_valid is True
        assert normalized_url == "https://example.com/file.zip"
        assert error_msg is None

    async def test_validate_invalid_url(self):
        """Test validation of invalid URL."""
        is_valid, normalized_url, error_msg = await validate_and_normalize_url(
            "not-a-valid-url"
        )

        assert is_valid is False
        assert normalized_url is None
        assert error_msg is not None
        assert "Invalid URL" in error_msg

    async def test_validate_url_without_scheme(self):
        """Test validation of URL without scheme."""
        is_valid, normalized_url, error_msg = await validate_and_normalize_url(
            "example.com/file.zip"
        )

        assert is_valid is False
        assert normalized_url is None
        assert error_msg is not None


@pytest.mark.asyncio
class TestCheckUrlAccessibility:
    """Test cases for check_url_accessibility function."""

    @patch("dumpyarabot.url_utils.httpx.AsyncClient")
    async def test_check_accessible_url(self, mock_client_class):
        """Test checking accessibility of accessible URL."""
        # Mock the client and response
        mock_client = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_client.head.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client

        result = await check_url_accessibility("https://example.com/file.zip")

        assert result is True
        mock_client.head.assert_called_once_with(
            "https://example.com/file.zip", timeout=10, follow_redirects=True
        )

    @patch("dumpyarabot.url_utils.httpx.AsyncClient")
    async def test_check_inaccessible_url(self, mock_client_class):
        """Test checking accessibility of inaccessible URL."""
        # Mock the client and response
        mock_client = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status_code = 404
        mock_client.head.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client

        result = await check_url_accessibility("https://example.com/missing.zip")

        assert result is False

    @patch("dumpyarabot.url_utils.httpx.AsyncClient")
    async def test_check_url_with_exception(self, mock_client_class):
        """Test checking accessibility when exception occurs."""
        # Mock the client to raise an exception
        mock_client = AsyncMock()
        mock_client.head.side_effect = Exception("Connection failed")
        mock_client_class.return_value.__aenter__.return_value = mock_client

        result = await check_url_accessibility("https://example.com/file.zip")

        assert result is False


class TestParseUrlComponents:
    """Test cases for parse_url_components function."""

    def test_parse_valid_url(self):
        """Test parsing of valid URL."""
        result = parse_url_components("https://example.com/path/to/file.zip")

        assert result is not None
        scheme, netloc, path = result
        assert scheme == "https"
        assert netloc == "example.com"
        assert path == "/path/to/file.zip"

    def test_parse_url_without_path(self):
        """Test parsing of URL without path."""
        result = parse_url_components("https://example.com")

        assert result is not None
        scheme, netloc, path = result
        assert scheme == "https"
        assert netloc == "example.com"
        assert path == ""

    def test_parse_invalid_url(self):
        """Test parsing of invalid URL."""
        result = parse_url_components("not-a-url")

        assert result is None

    def test_parse_url_without_scheme(self):
        """Test parsing of URL without scheme."""
        result = parse_url_components("example.com/path")

        assert result is None

    def test_parse_url_without_netloc(self):
        """Test parsing of URL without netloc."""
        result = parse_url_components("https:///path")

        assert result is None
