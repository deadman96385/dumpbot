import asyncio
import secrets
from typing import Any

import httpx
from rich.console import Console

console = Console()


async def retry_http_request(
    method: str, url: str, max_retries: int = 3, base_delay: float = 2.0, **kwargs: Any
) -> httpx.Response:
    """
    Simple retry wrapper for HTTP requests with exponential backoff.

    Args:
        method: HTTP method (GET, POST, etc.)
        url: Request URL
        max_retries: Maximum number of retry attempts
        base_delay: Base delay between retries in seconds
        **kwargs: Additional arguments passed to httpx request
    """
    last_exception: Exception = Exception("No attempts made")

    for attempt in range(max_retries + 1):  # +1 for initial attempt
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(method, url, **kwargs)
                response.raise_for_status()
                return response

        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as e:
            last_exception = e

            if attempt == max_retries:  # Last attempt
                console.print(
                    f"[red]HTTP request failed after {max_retries + 1} attempts: {e}[/red]"
                )
                break

            # Calculate delay with exponential backoff
            delay = base_delay * (2**attempt)
            console.print(
                f"[yellow]Attempt {attempt + 1} failed, retrying in {delay:.1f}s: {e}[/yellow]"
            )
            await asyncio.sleep(delay)

    # If all attempts failed, raise the last exception
    raise last_exception


def escape_markdown(text: str) -> str:
    """Escape special characters for Telegram legacy Markdown format.

    Args:
        text: The text to escape

    Returns:
        Text with Markdown special characters escaped
    """
    if not text:
        return text

    # Escape backslash first, then other special characters for legacy Markdown
    return (
        text.replace("\\", "\\\\")  # Backslash first
        .replace("*", "\\*")
        .replace("_", "\\_")
        .replace("`", "\\`")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .replace("#", "\\#")
        .replace("+", "\\+")
        .replace("-", "\\-")
        .replace(".", "\\.")
        .replace("!", "\\!")
    )


def generate_request_id() -> str:
    """Generate a unique request ID."""
    return secrets.token_hex(4)  # 8-character hex string
