"""Message formatting utilities for consistent Telegram messaging."""

from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from dumpyarabot.utils import escape_markdown


async def get_arq_start_time(arq_job_id: str) -> Optional[str]:
    """
    Fetch ARQ job start time from ARQ metadata.

    Args:
        arq_job_id: ARQ job ID to fetch metadata for

    Returns:
        ISO format start time string or None if not available
    """
    try:
        from dumpyarabot.arq_config import arq_pool

        arq_status = await arq_pool.get_job_status(arq_job_id)
        if arq_status and arq_status.get("start_time"):
            return arq_status["start_time"]
    except Exception:
        # If ARQ is not available or job not found, return None
        pass

    return None


def generate_progress_bar(
    progress: Optional[Dict[str, Any]],
    width: int = 10,
    style: str = "unicode"
) -> str:
    """
    Generate a visual progress bar from progress data with enhanced styling options.

    Args:
        progress: Progress dictionary with percentage, current_step_number, total_steps
        width: Width of the progress bar in characters (default: 10)
        style: Style of progress bar - "unicode", "ascii", or "blocks" (default: "unicode")

    Returns:
        Formatted progress bar string with emoji, percentage, and step info

    Examples:
        >>> generate_progress_bar({"percentage": 45, "current_step_number": 4, "total_steps": 8})
        "📊 *Progress:* [████▌     ] 45% (Step 4/8)"

        >>> generate_progress_bar({"percentage": 100}, style="ascii")
        "📊 *Progress:* [==========] 100% (Step 0/10)"
    """
    if not progress:
        empty_bar = _create_empty_bar(width, style)
        return f"📊 *Progress:* [{empty_bar}] 0% (Step 0/10)"

    # Extract and validate progress data
    percentage = max(0, min(100, progress.get("percentage", 0)))  # Clamp 0-100
    current_step = max(0, progress.get("current_step_number", 0))
    total_steps = max(1, progress.get("total_steps", 10))  # Avoid division by zero

    # Generate the visual progress bar
    bar = _create_progress_bar(percentage, width, style)

    return f"📊 *Progress:* [{bar}] {percentage:.0f}% (Step {current_step}/{total_steps})"


def _create_progress_bar(percentage: float, width: int, style: str) -> str:
    """Create the visual progress bar based on percentage and style."""
    if style == "unicode":
        return _create_unicode_bar(percentage, width)
    elif style == "blocks":
        return _create_block_bar(percentage, width)
    else:  # ascii
        return _create_ascii_bar(percentage, width)


def _create_unicode_bar(percentage: float, width: int) -> str:
    """Create a Unicode progress bar with smooth sub-block precision."""
    # Unicode block characters for smooth progress
    blocks = ["", "▏", "▎", "▍", "▌", "▋", "▊", "▉", "█"]

    # Calculate progress
    progress_chars = (percentage / 100) * width
    full_blocks = int(progress_chars)
    remainder = progress_chars - full_blocks

    # Build the bar
    bar = "█" * full_blocks

    # Add partial block if there's remainder and space
    if full_blocks < width and remainder > 0:
        partial_index = min(8, int(remainder * 8) + 1)
        bar += blocks[partial_index]
        full_blocks += 1

    # Fill remaining space
    bar += " " * (width - len(bar))

    return bar


def _create_block_bar(percentage: float, width: int) -> str:
    """Create a block-style progress bar using solid blocks."""
    filled_blocks = round((percentage / 100) * width)
    return "█" * filled_blocks + "░" * (width - filled_blocks)


def _create_ascii_bar(percentage: float, width: int) -> str:
    """Create an ASCII progress bar using = and - characters."""
    filled_blocks = round((percentage / 100) * width)
    return "=" * filled_blocks + "-" * (width - filled_blocks)


def _create_empty_bar(width: int, style: str) -> str:
    """Create an empty progress bar."""
    if style == "unicode":
        return " " * width
    elif style == "blocks":
        return "░" * width
    else:  # ascii
        return "-" * width


def calculate_elapsed_time(
    started_at_str: Optional[str],
    fallback_started_at: Optional[str] = None
) -> str:
    """
    Calculate elapsed time since a job started with fallback support.

    Args:
        started_at_str: Primary start time as ISO format string or None
        fallback_started_at: Fallback start time (e.g., from ARQ job metadata)

    Returns:
        Human-readable elapsed time string

    Examples:
        >>> calculate_elapsed_time("2024-01-01T12:00:00Z")
        "2h 5m"

        >>> calculate_elapsed_time("2024-01-01T12:00:00+00:00")
        "45m 20s"

        >>> calculate_elapsed_time(None, "2024-01-01T12:00:00Z")
        "2h 5m"

        >>> calculate_elapsed_time(None)
        "0s"
    """
    # Use fallback if primary is not available
    time_str = started_at_str or fallback_started_at
    if not time_str:
        return "0s"

    try:
        # Simple ISO format parsing - handles most common cases
        started_at = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
        elapsed = datetime.now(timezone.utc) - started_at
        total_seconds = max(0, int(elapsed.total_seconds()))

        # Simple, consistent time formatting
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
    except (ValueError, AttributeError):
        return "0s"


def format_url_display(url: str, max_length: int = 60) -> str:
    """
    Format URL for display, truncating if too long.

    Args:
        url: URL to format
        max_length: Maximum length before truncation

    Returns:
        Formatted URL string
    """
    url_str = str(url)
    if len(url_str) > max_length:
        return url_str[:max_length - 3] + "..."
    return url_str


def format_dump_options(dump_args: Dict[str, Any], add_blacklist: bool = False) -> List[str]:
    """
    Format dump options for display.

    Args:
        dump_args: Dump arguments dictionary
        add_blacklist: Whether to add blacklist option

    Returns:
        List of option strings
    """
    options = []

    if dump_args.get("use_alt_dumper"):
        options.append("Alt Dumper")
    if add_blacklist:
        options.append("Blacklist")
    if dump_args.get("use_privdump"):
        options.append("Private")

    return options


async def format_comprehensive_progress_message(
    job_data: Dict[str, Any],
    current_step: str,
    progress: Optional[Dict[str, Any]] = None
) -> str:
    """
    Format a comprehensive progress message with all status information.

    Args:
        job_data: Complete job data dictionary
        current_step: Current step description
        progress: Progress information

    Returns:
        Formatted progress message
    """
    # Generate progress bar
    progress_bar = generate_progress_bar(progress)

    # Calculate elapsed time with ARQ fallback
    arq_job_id = job_data.get("arq_job_id")
    fallback_time = None

    # Fetch ARQ job start time if job_data["started_at"] is missing
    if arq_job_id and not job_data.get("started_at"):
        fallback_time = await get_arq_start_time(arq_job_id)

    elapsed = calculate_elapsed_time(
        job_data.get("started_at"),
        fallback_started_at=fallback_time
    )

    # Determine status
    if progress and progress.get("percentage", 0) >= 100:
        status_emoji = "✅"
        status_text = "Firmware Dump Completed"
    elif progress and progress.get("current_step") == "Failed":
        status_emoji = "❌"
        status_text = "Firmware Dump Failed"
    else:
        status_emoji = "🚀"
        status_text = "Firmware Dump in Progress"

    # Format basic info
    url_display = format_url_display(job_data["dump_args"]["url"])
    job_id_display = job_data["job_id"]
    worker_id_display = job_data.get("worker_id", "arq_worker")

    # Build message
    message = f"{status_emoji} *{status_text}*\n\n"
    message += f"📥 *URL:* `{url_display}`\n"
    message += f"🆔 *Job ID:* `{job_id_display}`\n"

    # Format options
    options = format_dump_options(
        job_data["dump_args"],
        job_data.get("add_blacklist", False)
    )

    if options:
        message += f"⚙️ *Options:* {', '.join(options)}\n"

    message += f"\n{progress_bar}\n"
    message += f"{current_step}\n\n"
    message += f"⏱️ *Elapsed:* {elapsed}\n"
    message += f"👷 *Worker:* `{worker_id_display}`\n"

    if progress and progress.get("error_message"):
        error_display = progress['error_message']
        message += f"❌ *Error:* {error_display}\n"

    return message


def format_build_summary_info(
    job_name: str,
    build_number: int,
    result: Optional[str],
    timestamp_str: Optional[str] = None
) -> str:
    """
    Format build summary information for display.

    Args:
        job_name: Jenkins job name
        build_number: Build number
        result: Build result (SUCCESS, FAILURE, etc.)
        timestamp_str: Build timestamp string

    Returns:
        Formatted build summary
    """
    # Format result with emoji
    result_emoji = {
        "SUCCESS": "✅",
        "FAILURE": "❌",
        "UNSTABLE": "⚠️",
        "ABORTED": "⏹️",
    }.get(result, "❓")

    # Build summary parts
    escaped_job_name = escape_markdown(job_name)
    escaped_build_number = str(build_number)

    summary_parts = [
        f"**Job:** `{escaped_job_name}`",
        f"**Build:** `#{escaped_build_number}`",
        f"**Result:** {result_emoji} {result or 'Unknown'}"
    ]

    if timestamp_str:
        summary_parts.append(f"**Date:** {timestamp_str}")

    return "\n".join(summary_parts)


def format_device_properties_message(device_props: Dict[str, Any]) -> str:
    """
    Format device properties for display.

    Args:
        device_props: Device properties dictionary

    Returns:
        Formatted device properties message
    """
    brand = escape_markdown(device_props.get("brand", "Unknown"))
    codename = escape_markdown(device_props.get("codename", "Unknown"))
    release = escape_markdown(device_props.get("release", "Unknown"))
    fingerprint = escape_markdown(device_props.get("fingerprint", "Unknown"))
    platform = escape_markdown(device_props.get("platform", "Unknown"))

    return f"""*Brand*: `{brand}`
*Device*: `{codename}`
*Version*: `{release}`
*Fingerprint*: `{fingerprint}`
*Platform*: `{platform}`"""


def format_channel_notification_message(
    device_props: Dict[str, Any],
    repo_url: str,
    download_url: Optional[str] = None
) -> str:
    """
    Format a channel notification message.

    Args:
        device_props: Device properties
        repo_url: Repository URL
        download_url: Optional firmware download URL

    Returns:
        Formatted notification message
    """
    device_info = format_device_properties_message(device_props)

    # Format firmware link
    firmware_link = f"[[firmware]({download_url})]" if download_url else ""

    return f"""{device_info}
[[repo]({repo_url})] {firmware_link}"""


def format_error_message(
    error_type: str,
    error_details: str,
    job_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None
) -> str:
    """
    Format an error message with consistent styling.

    Args:
        error_type: Type of error (e.g., "Network Error", "Extraction Failed")
        error_details: Detailed error message
        job_id: Optional job ID for tracking
        context: Optional context information

    Returns:
        Formatted error message
    """
    message = f"❌ *{error_type}*\n\n"

    if job_id:
        message += f"🆔 *Job ID:* `{job_id}`\n\n"

    message += f"**Details:** {error_details}\n"

    if context:
        for key, value in context.items():
            if key not in ["job_id"]:  # Avoid duplicating job_id
                formatted_key = key.replace("_", " ").title()
                message += f"**{formatted_key}:** `{value}`\n"

    return message


def format_success_message(
    title: str,
    details: Optional[str] = None,
    links: Optional[Dict[str, str]] = None
) -> str:
    """
    Format a success message with consistent styling.

    Args:
        title: Success message title
        details: Optional additional details
        links: Optional dictionary of link names to URLs

    Returns:
        Formatted success message
    """
    message = f"✅ *{title}*\n\n"

    if details:
        message += f"{details}\n\n"

    if links:
        for link_name, url in links.items():
            message += f"🔗 [{link_name}]({url})\n"

    return message


def format_status_update_message(
    status: str,
    job_id: str,
    details: Optional[str] = None,
    progress_percent: Optional[float] = None
) -> str:
    """
    Format a status update message.

    Args:
        status: Current status
        job_id: Job identifier
        details: Optional status details
        progress_percent: Optional progress percentage

    Returns:
        Formatted status message
    """
    # Choose emoji based on status
    status_emojis = {
        "queued": "⏳",
        "processing": "🚀",
        "completed": "✅",
        "failed": "❌",
        "cancelled": "⏹️",
    }

    emoji = status_emojis.get(status.lower(), "ℹ️")
    message = f"{emoji} *Status: {status.title()}*\n\n"
    message += f"🆔 *Job ID:* `{job_id}`\n"

    if progress_percent is not None:
        progress_data = {"percentage": progress_percent, "current_step_number": 0, "total_steps": 10}
        progress_bar = generate_progress_bar(progress_data)
        message += f"{progress_bar}\n"

    if details:
        message += f"\n{details}\n"

    return message