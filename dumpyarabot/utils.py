import secrets
import asyncio
from datetime import datetime
from typing import List, Tuple, Optional

import httpx
from rich.console import Console

from dumpyarabot import schemas
from dumpyarabot.config import settings

console = Console()


async def retry_http_request(
    method: str,
    url: str,
    max_retries: int = 3,
    base_delay: float = 2.0,
    **kwargs
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
    last_exception = None

    for attempt in range(max_retries + 1):  # +1 for initial attempt
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(method, url, **kwargs)
                response.raise_for_status()
                return response

        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as e:
            last_exception = e

            if attempt == max_retries:  # Last attempt
                console.print(f"[red]HTTP request failed after {max_retries + 1} attempts: {e}[/red]")
                break

            # Calculate delay with exponential backoff
            delay = base_delay * (2 ** attempt)
            console.print(f"[yellow]Attempt {attempt + 1} failed, retrying in {delay:.1f}s: {e}[/yellow]")
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
    return (text.replace("\\", "\\\\")  # Backslash first
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
            .replace("!", "\\!"))


def generate_request_id() -> str:
    """Generate a unique request ID."""
    return secrets.token_hex(4)  # 8-character hex string


async def get_jenkins_builds(job_name: str) -> List[schemas.JenkinsBuild]:
    """Fetch all builds from Jenkins for a specific job."""
    console.print(f"[blue]Fetching builds for job: {job_name}[/blue]")

    try:
        response = await retry_http_request(
            "GET",
            f"{settings.JENKINS_URL}/job/{job_name}/api/json",
            params={
                "tree": "allBuilds[number,result,actions[parameters[name,value]]]"
            },
            auth=(settings.JENKINS_USER_NAME, settings.JENKINS_USER_TOKEN),
        )
        builds = [
            schemas.JenkinsBuild(**build) for build in response.json()["allBuilds"]
        ]
        console.print(
            f"[green]Successfully fetched {len(builds)} builds for {job_name}[/green]"
        )
        return builds
    except Exception as e:
        console.print(f"[red]Failed to fetch builds for {job_name}: {e}[/red]")
        raise


def _is_matching_build(
    build: schemas.JenkinsBuild, args: schemas.DumpArguments
) -> bool:
    """Check if a build matches the given arguments."""
    if not build.actions:
        return False

    for action in build.actions:
        if "parameters" in action:
            params = {param["name"]: param["value"] for param in action["parameters"]}
            if matches := (
                params.get("URL") == args.url.unicode_string()
                and params.get("USE_ALT_DUMPER") == args.use_alt_dumper
            ):
                console.print("[green]Found matching build parameters[/green]")
                console.print(f"[blue]Build params: {params}[/blue]")
                console.print(
                    f"[blue]Looking for: URL={args.url.unicode_string()}, ALT={args.use_alt_dumper}, PRIVDUMP={args.use_privdump}[/blue]"
                )
                return matches
    return False


def _get_build_status(build: schemas.JenkinsBuild) -> Tuple[bool, str]:
    """Get the status of a build."""
    console.print(f"[blue]Checking build status: #{build.number}[/blue]")
    if build.result is None:
        console.print("[yellow]Build is currently in progress[/yellow]")
        return (
            True,
            f"Build #{build.number} is currently in progress for this URL and settings.",
        )
    elif build.result == "SUCCESS":
        console.print("[green]Build completed successfully[/green]")
        return (
            True,
            f"Build #{build.number} has already successfully completed for this URL and settings.",
        )
    else:
        console.print(
            f"[yellow]Build result was {build.result}, will start new build[/yellow]"
        )
        return (
            False,
            f"Build #{build.number} exists for this URL and settings, but result was {build.result}. A new build will be started.",
        )


async def check_existing_build(args: schemas.DumpArguments) -> Tuple[bool, str]:
    """Check if a build with the given parameters already exists."""
    job_name = "privdump" if args.use_privdump else "dumpyara"
    console.print(f"[blue]Checking existing builds for {job_name}[/blue]")
    console.print("Build parameters:", args)

    builds = await get_jenkins_builds(job_name)

    for build in builds:
        if _is_matching_build(build, args):
            status = _get_build_status(build)
            console.print(f"[yellow]Found matching build - Status: {status}[/yellow]")
            return status

    console.print(f"[green]No matching build found for {job_name}[/green]")
    return False, f"No matching build found. A new {job_name} build will be started."


async def call_jenkins(args: schemas.DumpArguments, add_blacklist: bool = False) -> str:
    """Call Jenkins to start a new build."""
    job_name = "privdump" if args.use_privdump else "dumpyara"
    console.print(f"[blue]Starting new {job_name} build[/blue]")

    # Prepare Jenkins parameters
    jenkins_params = {
        "URL": args.url.unicode_string(),
        "USE_ALT_DUMPER": args.use_alt_dumper,
        "ADD_BLACKLIST": add_blacklist,
        "INITIAL_MESSAGE_ID": args.initial_message_id,
        "INITIAL_CHAT_ID": args.initial_chat_id,
    }

    jenkins_url = f"{settings.JENKINS_URL}/job/{job_name}/buildWithParameters"

    # Debug: Show replicable Jenkins command
    console.print("[yellow]=== JENKINS DEBUG COMMAND ===[/yellow]")
    console.print(f"[cyan]Job: {job_name}[/cyan]")
    console.print(f"[cyan]URL: {jenkins_url}[/cyan]")
    console.print("[cyan]Parameters:[/cyan]")
    for key, value in jenkins_params.items():
        console.print(f"  {key} = {value} ({type(value).__name__})")

    # Create curl command for replication (matches httpx params behavior - URL query parameters)
    param_string = "&".join([f"{key}={value}" for key, value in jenkins_params.items()])
    curl_command = f'curl -X POST "{jenkins_url}?{param_string}" \\\n'
    curl_command += f'  -u "{settings.JENKINS_USER_NAME}:***"'

    console.print("[green]Equivalent curl command:[/green]")
    console.print(f"[dim]{curl_command}[/dim]")
    console.print("[yellow]=== END JENKINS DEBUG ===[/yellow]")

    try:
        response = await retry_http_request(
            "POST",
            jenkins_url,
            params=jenkins_params,
            auth=(settings.JENKINS_USER_NAME, settings.JENKINS_USER_TOKEN),
        )
        console.print(f"[green]Successfully triggered {job_name} build[/green]")
        console.print(f"[blue]Response headers: {dict(response.headers)}[/blue]")

        # Try to get queue item ID from Location header for tracking
        queue_item_id = None
        if "Location" in response.headers:
            location = response.headers["Location"]
            console.print(f"[blue]Build queue location: {location}[/blue]")
            # Extract queue item ID from location URL
            if "/queue/item/" in location:
                queue_item_id = location.split("/queue/item/")[1].rstrip("/")
                console.print(f"[blue]Queue item ID: {queue_item_id}[/blue]")

        if queue_item_id:
            return f"{job_name.capitalize()} job triggered (Queue ID: {queue_item_id})"
        else:
            return f"{job_name.capitalize()} job triggered"
    except Exception as e:
        console.print(f"[red]Failed to trigger {job_name} build: {e}[/red]")
        raise


async def get_jenkins_console_log(job_name: str, build_number: str) -> str:
    """Fetch Jenkins console log for a specific job and build number."""
    console.print(f"[blue]Fetching console log for {job_name} #{build_number}[/blue]")

    try:
        console_url = f"{settings.JENKINS_URL}/job/{job_name}/{build_number}/consoleText"
        response = await retry_http_request(
            "GET",
            console_url,
            auth=(settings.JENKINS_USER_NAME, settings.JENKINS_USER_TOKEN),
        )

        console_log = response.text
        console.print(f"[green]Successfully fetched {len(console_log)} characters of console log[/green]")
        return console_log

    except Exception as e:
        console.print(f"[red]Failed to fetch console log: {e}[/red]")
        raise


async def get_jenkins_build_timestamp(job_name: str, build_number: str) -> Optional[str]:
    """Get the build timestamp from Jenkins for a specific job and build number."""
    console.print(f"[blue]Fetching build timestamp for {job_name} #{build_number}[/blue]")

    try:
        build_url = f"{settings.JENKINS_URL}/job/{job_name}/{build_number}/api/json"
        response = await retry_http_request(
            "GET",
            build_url,
            params={"tree": "timestamp"},
            auth=(settings.JENKINS_USER_NAME, settings.JENKINS_USER_TOKEN),
        )

        data = response.json()
        timestamp_ms = data.get("timestamp")
        if timestamp_ms:
            # Convert from milliseconds to seconds and format as readable datetime
            timestamp_dt = datetime.fromtimestamp(timestamp_ms / 1000)
            formatted_timestamp = timestamp_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
            console.print(f"[green]Build timestamp: {formatted_timestamp}[/green]")
            return formatted_timestamp
        else:
            console.print("[yellow]No timestamp found in build data[/yellow]")
            return None

    except Exception as e:
        console.print(f"[red]Failed to fetch build timestamp: {e}[/red]")
        return None


async def cancel_jenkins_job(job_id: str, use_privdump: bool = False) -> str:
    """Cancel a Jenkins job."""
    job_name = "privdump" if use_privdump else "dumpyara"
    console.print(f"[blue]Attempting to cancel {job_name} job {job_id}[/blue]")

    try:
        # Try to cancel running job first
        try:
            response = await retry_http_request(
                "POST",
                f"{settings.JENKINS_URL}/job/{job_name}/{job_id}/stop",
                auth=(settings.JENKINS_USER_NAME, settings.JENKINS_USER_TOKEN),
                follow_redirects=True,
            )
            if response.status_code == 200:
                console.print(
                    f"[green]Successfully cancelled {job_name} job {job_id}[/green]"
                )
                return f"Job with ID {job_id} has been cancelled in {job_name}."
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 404:
                raise  # Re-raise if not a 404 error

        # If job not found (404), try to cancel from queue
        console.print(f"[yellow]Job {job_id} not found, checking queue[/yellow]")

        try:
            response = await retry_http_request(
                "POST",
                f"{settings.JENKINS_URL}/queue/cancelItem",
                params={"id": job_id},
                auth=(settings.JENKINS_USER_NAME, settings.JENKINS_USER_TOKEN),
                follow_redirects=True,
            )
            if response.status_code == 204:
                console.print(
                    f"[green]Successfully removed {job_name} job {job_id} from queue[/green]"
                )
                return f"Job with ID {job_id} has been removed from the {job_name} queue."
        except httpx.HTTPStatusError:
            pass  # Queue cancellation failed

        console.print(f"[yellow]Failed to cancel {job_name} job {job_id}[/yellow]")
        return f"Failed to cancel job with ID {job_id} in {job_name}. Job not found or already completed."

    except Exception as e:
        console.print(
            f"[red]Error while cancelling {job_name} job {job_id}: {e}[/red]"
        )
        raise


async def get_random_jenkins_build() -> Optional[Tuple[str, schemas.JenkinsBuild, str]]:
    """Get a random Jenkins build with its console log for surprise image generation.

    Returns:
        Tuple of (job_name, build, console_log) or None if no suitable build found
    """
    console.print("[blue]Selecting random Jenkins build for surprise generation...[/blue]")

    # Try both job types with preference for dumpyara
    job_candidates = ["dumpyara", "privdump"]
    import secrets

    for job_name in job_candidates:
        try:
            # Get recent builds (limit to last 50 for performance)
            response = await retry_http_request(
                "GET",
                f"{settings.JENKINS_URL}/job/{job_name}/api/json",
                params={
                    "tree": "builds[number,result,timestamp]{0,50}"
                },
                auth=(settings.JENKINS_USER_NAME, settings.JENKINS_USER_TOKEN),
            )

            builds_data = response.json().get("builds", [])
            if not builds_data:
                console.print(f"[yellow]No builds found for {job_name}[/yellow]")
                continue

            # Filter for completed builds (both successful and failed are interesting)
            completed_builds = [
                build for build in builds_data
                if build.get("result") in ["SUCCESS", "FAILURE", "UNSTABLE"]
            ]

            if not completed_builds:
                console.print(f"[yellow]No completed builds found for {job_name}[/yellow]")
                continue

            # Select random completed build
            selected_build_data = secrets.choice(completed_builds)
            build_number = selected_build_data["number"]

            console.print(f"[green]Selected random build: {job_name} #{build_number}[/green]")

            # Create build object
            build = schemas.JenkinsBuild(
                number=build_number,
                result=selected_build_data.get("result"),
                actions=None  # We don't need actions for surprise generation
            )

            # Fetch console log for this build
            console_log = await get_jenkins_console_log(job_name, str(build_number))

            return (job_name, build, console_log)

        except Exception as e:
            console.print(f"[yellow]Failed to get random build from {job_name}: {e}[/yellow]")
            continue

    console.print("[red]No suitable random builds found in any job[/red]")
    return None


async def get_build_summary_info(job_name: str, build: schemas.JenkinsBuild) -> str:
    """Get formatted build summary information for display.

    Args:
        job_name: The Jenkins job name
        build: The build object

    Returns:
        Formatted build summary string
    """
    try:
        # Get build timestamp
        timestamp_str = await get_jenkins_build_timestamp(job_name, str(build.number))

        # Format result with emoji
        result_emoji = {
            "SUCCESS": "✅",
            "FAILURE": "❌",
            "UNSTABLE": "⚠️",
            "ABORTED": "⏹️",
        }.get(build.result, "❓")

        # Build summary
        escaped_job_name = escape_markdown(job_name)
        escaped_build_number = str(build.number)  # build.number is int
        summary_parts = [
            f"**Job:** `{escaped_job_name}`",
            f"**Build:** `#{escaped_build_number}`",
            f"**Result:** {result_emoji} {build.result or 'Unknown'}"
        ]

        if timestamp_str:
            summary_parts.append(f"**Date:** {timestamp_str}")

        return "\n".join(summary_parts)

    except Exception as e:
        console.print(f"[yellow]Failed to get build summary info: {e}[/yellow]")
        # Fallback summary
        escaped_job_name = escape_markdown(job_name)
        escaped_build_number = str(build.number)
        return f"**Job:** `{escaped_job_name}`\n**Build:** `#{escaped_build_number}`\n**Result:** {build.result or 'Unknown'}"
