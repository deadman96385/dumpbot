"""
Unit tests for dumpyarabot utility functions.
"""

from dumpyarabot.utils import escape_markdown, generate_request_id


class TestEscapeMarkdown:
    """Test cases for escape_markdown function."""

    def test_escape_markdown_basic(self):
        """Test basic markdown escaping."""
        input_text = "This has *bold* and _italic_ text"
        result = escape_markdown(input_text)
        expected = "This has \\*bold\\* and \\_italic\\_ text"
        assert result == expected

    def test_escape_markdown_special_chars(self):
        """Test escaping of special markdown characters."""
        input_text = "[link](url) `code` *bold* _italic_"
        result = escape_markdown(input_text)
        expected = "\\[link\\]\\(url\\) \\`code\\` \\*bold\\* \\_italic\\_"
        assert result == expected

    def test_escape_markdown_backslash(self):
        """Test that backslashes are properly escaped."""
        input_text = r"Path\to\file"
        result = escape_markdown(input_text)
        expected = r"Path\\to\\file"
        assert result == expected

    def test_escape_markdown_no_special_chars(self):
        """Test text with no special characters."""
        input_text = "This is normal text"
        result = escape_markdown(input_text)
        assert result == input_text

    def test_escape_markdown_empty_string(self):
        """Test empty string."""
        result = escape_markdown("")
        assert result == ""


class TestGenerateRequestId:
    """Test cases for generate_request_id function."""

    def test_generate_request_id_length(self):
        """Test that generated ID has correct length."""
        request_id = generate_request_id()
        assert len(request_id) == 8

    def test_generate_request_id_hex_chars(self):
        """Test that generated ID contains only hexadecimal characters."""
        request_id = generate_request_id()
        assert all(c in "0123456789abcdef" for c in request_id)

    def test_generate_request_id_uniqueness(self):
        """Test that generated IDs are unique."""
        ids = {generate_request_id() for _ in range(100)}
        assert len(ids) == 100  # All should be unique

    def test_generate_request_id_type(self):
        """Test that generated ID is a string."""
        request_id = generate_request_id()
        assert isinstance(request_id, str)
