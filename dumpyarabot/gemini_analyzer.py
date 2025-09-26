import logging
from typing import Optional, Dict, Any

from google import genai
from google.genai import types
from rich.console import Console

from dumpyarabot.config import settings

console = Console()
logger = logging.getLogger(__name__)

# Analysis prompt template for Jenkins console logs
JENKINS_LOG_ANALYSIS_PROMPT = """
You are an expert DevOps engineer analyzing Jenkins build failures for an Android firmware dumping pipeline that processes firmware from URLs and extracts them to GitLab repositories.

For additional context about the system architecture and implementation details, you can reference the source code at: https://github.com/AndroidDumps/dumpbot

## System Context
This pipeline performs these key stages:
1. **Download**: Downloads firmware from various sources (Xiaomi mirrors, Google Drive, MediaFire, MEGA, etc.)
2. **Extraction**: Uses either Python dumper (dumpyara) or alternative dumper (Firmware_extractor)
3. **Analysis**: Extracts device properties, boot images, device trees
4. **GitLab**: Creates repositories, commits extracted files, pushes to GitLab
5. **Notification**: Sends status updates via Telegram bot

## Common Failure Categories
- **Download**: URL issues, mirror failures, authentication problems, file corruption
- **Extraction**: Partition extraction failures, unsupported formats, tool crashes
- **Dependencies**: Missing tools (fsck.erofs, ext2rd, 7zz, uvx, dumpyara, aospdtgen)
- **GitLab**: API authentication, repository conflicts, push failures, branch exists
- **Filesystem**: Disk space, permissions, file I/O errors
- **Boot Analysis**: Boot image unpacking, kernel extraction, device tree processing
- **Network**: Connectivity issues, timeout errors, proxy problems
- **Environment**: Missing environment variables, configuration issues

Analyze this Jenkins console log and provide:

1. **Root Cause**: What specifically caused the build to fail? Focus on the primary error, not symptoms. Be brief (1-2 sentences).
2. **Error Category**: Classify using the categories above, but if it matches the pipeline stage name, combine them (e.g., "Download failure" instead of separate "Download" category and stage)
3. **Pipeline Stage**: Which stage failed? (Download/Extraction/Analysis/GitLab/Notification) - Only include if different from Error Category

Focus on the actual failure, not preliminary warnings. Look for error exit codes, exception traces, and final failure messages.

Console Log:
```
{console_log}
```

Provide your analysis in this format:
Root Cause: [Brief description]
Error Category: [Category or "Stage - Type" if combining]
Pipeline Stage: [Stage - only if different from category]
"""


class GeminiLogAnalyzer:
    """Analyzes Jenkins console logs using Google's Gemini AI."""

    def __init__(self, api_key: Optional[str] = None):
        """Initialize the analyzer with API key."""
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model = None
        self._initialize_model()

    def _initialize_model(self) -> None:
        """Initialize the Gemini model if API key is available."""
        if not self.api_key:
            console.print(
                "[yellow]GEMINI_API_KEY not configured - log analysis disabled[/yellow]"
            )
            return

        try:
            import google.generativeai as genai_legacy

            genai_legacy.configure(api_key=self.api_key)
            self.model = genai_legacy.GenerativeModel("gemini-2.5-pro")
            console.print("[green]Gemini AI log analyzer initialized[/green]")
        except Exception as e:
            console.print(f"[red]Failed to initialize Gemini model: {e}[/red]")
            logger.error(f"Gemini initialization failed: {e}")

    def is_available(self) -> bool:
        """Check if the analyzer is available for use."""
        return self.model is not None

    async def analyze_jenkins_log(
        self, console_log: str, build_info: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """
        Analyze Jenkins console log for failure patterns and suggestions.

        Args:
            console_log: The raw Jenkins console log text
            build_info: Optional build metadata (URL, job name, build number, etc.)

        Returns:
            Formatted analysis string or None if analysis fails
        """
        if not self.is_available():
            console.print(
                "[yellow]Gemini analyzer not available - skipping log analysis[/yellow]"
            )
            return None

        if not console_log or len(console_log.strip()) < 50:
            console.print(
                "[yellow]Console log too short for meaningful analysis[/yellow]"
            )
            return None

        try:
            # Truncate log if too long (Gemini has token limits)
            max_log_length = 50000  # Approximately 50KB
            if len(console_log) > max_log_length:
                # Take first and last portions to capture both setup and failure
                first_part = console_log[: max_log_length // 2]
                last_part = console_log[-max_log_length // 2 :]
                console_log = f"{first_part}\n\n... [LOG TRUNCATED] ...\n\n{last_part}"
                console.print("[yellow]Console log truncated for analysis[/yellow]")

            # Format the analysis prompt
            prompt = JENKINS_LOG_ANALYSIS_PROMPT.format(console_log=console_log)

            console.print("[blue]Analyzing Jenkins log with Gemini AI...[/blue]")

            # Generate analysis
            response = self.model.generate_content(prompt)

            if not response.text:
                console.print("[yellow]Gemini returned empty response[/yellow]")
                return None

            analysis = response.text.strip()

            console.print("[green]Jenkins log analysis completed[/green]")
            return analysis

        except Exception as e:
            console.print(f"[red]Failed to analyze Jenkins log: {e}[/red]")
            logger.error(f"Gemini analysis failed: {e}")
            return None

    def format_analysis_for_telegram(
        self, analysis: str, build_url: str = "", build_date: str = ""
    ) -> str:
        """
        Format the analysis for Telegram messaging.

        Args:
            analysis: Raw analysis from Gemini
            build_url: Jenkins build URL for linking
            build_date: Build timestamp for display

        Returns:
            Markdown-formatted message for Telegram
        """
        if not analysis:
            return ""

        # Format each line with proper Markdown tags
        lines = analysis.strip().split("\n")
        formatted_lines = []
        error_category = ""
        pipeline_stage = ""

        # First pass: extract values
        for line in lines:
            line = line.strip()
            if not line:
                continue

            if line.startswith("Root Cause:"):
                formatted_lines.append(f"**Root Cause:** {line[11:].strip()}")
            elif line.startswith("Error Category:"):
                error_category = line[15:].strip()
                formatted_lines.append(f"**Error Category:** {error_category}")
            elif line.startswith("Pipeline Stage:"):
                pipeline_stage = line[15:].strip()
            else:
                formatted_lines.append(line)

        # Second pass: only add Pipeline Stage if it's different from Error Category
        if pipeline_stage and pipeline_stage != "N/A" and pipeline_stage != "-":
            # Check if pipeline stage is redundant with error category
            error_category_lower = error_category.lower()
            pipeline_stage_lower = pipeline_stage.lower()

            # Don't show pipeline stage if it's the same or if error category contains the stage name
            if (
                pipeline_stage_lower != error_category_lower
                and pipeline_stage_lower not in error_category_lower
            ):
                formatted_lines.append(f"**Pipeline Stage:** {pipeline_stage}")

        formatted = "\n".join(formatted_lines)

        # Add build date if provided
        if build_date:
            formatted = f"**Build Date:** {build_date}\n\n{formatted}"

        # Add AI attribution and build link
        model_name = "Gemini AI"
        if self.model and hasattr(self.model, "_model_name"):
            model_name = self.model._model_name

        footer = f"\n\n*🤖 Analysis by {model_name}*"
        if build_url:
            console_url = (
                f"{build_url}/console"
                if not build_url.endswith("/console")
                else build_url
            )
            footer += f"\n📊 [View Console Output]({console_url})"

        return formatted + footer


# Create global analyzer instance
analyzer = GeminiLogAnalyzer()

# Import image generator from separate module
from dumpyarabot.gemini_image_generator import image_generator