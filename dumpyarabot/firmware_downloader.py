import asyncio
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse

import httpx
from rich.console import Console

from dumpyarabot.schemas import DumpJob

console = Console()


class FirmwareDownloader:
    """Handles firmware downloading with mirror optimization and special URL handling."""

    def __init__(self, work_dir: str):
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)

    async def download_firmware(self, job: DumpJob) -> Tuple[str, str]:
        """Download firmware and return (file_path, file_name)."""
        url = str(job.dump_args.url)

        # Check if it's a local file
        if os.path.isfile(url):
            console.print(f"[green]Found local file: {url}[/green]")
            # Copy to work directory
            import shutil
            file_name = Path(url).name
            dest_path = self.work_dir / file_name
            shutil.copy2(url, dest_path)
            return str(dest_path), file_name

        # Optimize URL with mirrors
        optimized_url = await self._optimize_url(url)
        console.print(f"[blue]Downloading from: {optimized_url}[/blue]")

        # Download based on URL type
        file_path = await self._download_by_type(optimized_url)
        file_name = Path(file_path).name

        console.print(f"[green]Downloaded: {file_name} ({self._format_file_size(file_path)})[/green]")
        return file_path, file_name

    async def _optimize_url(self, url: str) -> str:
        """Optimize URL with best available mirrors."""
        # Xiaomi mirror optimization
        if "d.miui.com" in url:
            return await self._optimize_xiaomi_url(url)

        # Pixeldrain optimization
        if "pixeldrain.com/u" in url:
            file_id = url.split("/")[-1]
            return f"https://pd.cybar.xyz/{file_id}"

        if "pixeldrain.com/d" in url:
            file_id = url.split("/")[-1]
            return f"https://pixeldrain.com/api/filesystem/{file_id}"

        return url

    async def _optimize_xiaomi_url(self, url: str) -> str:
        """Find best Xiaomi mirror."""
        # Skip if already using recommended mirror
        if any(mirror in url for mirror in ["cdnorg", "bkt-sgp-miui-ota-update-alisgp"]):
            return url

        # Extract file path
        parsed = urlparse(url)
        original_host = f"{parsed.scheme}://{parsed.netloc}"
        file_path = url.replace("https://d.miui.com/", "")

        # Test mirrors in order of preference
        mirrors = [
            "https://cdnorg.d.miui.com",
            "https://bkt-sgp-miui-ota-update-alisgp.oss-ap-southeast-1.aliyuncs.com",
            "https://bn.d.miui.com",
            original_host
        ]

        async with httpx.AsyncClient(verify=False) as client:
            for mirror in mirrors:
                test_url = f"{mirror}/{file_path}"
                try:
                    console.print(f"[blue]Testing mirror: {mirror}[/blue]")
                    response = await client.head(test_url, timeout=10.0)
                    if response.status_code != 404:
                        console.print(f"[green]Using mirror: {mirror}[/green]")
                        return test_url
                except Exception as e:
                    console.print(f"[yellow]Mirror {mirror} failed: {e}[/yellow]")
                    continue

        console.print("[yellow]All mirrors failed, using original URL[/yellow]")
        return url

    async def _download_by_type(self, url: str) -> str:
        """Download file based on URL type."""
        if "drive.google.com" in url:
            return await self._download_google_drive(url)
        elif "mediafire.com" in url:
            return await self._download_mediafire(url)
        elif "mega.nz" in url:
            return await self._download_mega(url)
        else:
            return await self._download_default(url)

    async def _download_google_drive(self, url: str) -> str:
        """Download from Google Drive using gdown."""
        console.print("[blue]Downloading from Google Drive...[/blue]")

        # Run gdown
        result = await asyncio.create_subprocess_exec(
            "uvx", "gdown@5.2.0", "-q", url, "--fuzzy",
            cwd=self.work_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await result.communicate()

        if result.returncode != 0:
            raise Exception(f"Google Drive download failed: {stderr.decode()}")

        # Find downloaded file
        downloaded_files = list(self.work_dir.glob("*"))
        if not downloaded_files:
            raise Exception("No file found after Google Drive download")

        return str(downloaded_files[-1])  # Return most recent file

    async def _download_mediafire(self, url: str) -> str:
        """Download from MediaFire using mediafire-dl."""
        console.print("[blue]Downloading from MediaFire...[/blue]")

        result = await asyncio.create_subprocess_exec(
            "uvx", "--from", "git+https://github.com/Juvenal-Yescas/mediafire-dl@master",
            "mediafire-dl", url,
            cwd=self.work_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await result.communicate()

        if result.returncode != 0:
            raise Exception(f"MediaFire download failed: {stderr.decode()}")

        # Find downloaded file
        downloaded_files = list(self.work_dir.glob("*"))
        if not downloaded_files:
            raise Exception("No file found after MediaFire download")

        return str(downloaded_files[-1])

    async def _download_mega(self, url: str) -> str:
        """Download from MEGA using megatools."""
        console.print("[blue]Downloading from MEGA...[/blue]")

        result = await asyncio.create_subprocess_exec(
            "megatools", "dl", url,
            cwd=self.work_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await result.communicate()

        if result.returncode != 0:
            raise Exception(f"MEGA download failed: {stderr.decode()}")

        # Find downloaded file
        downloaded_files = list(self.work_dir.glob("*"))
        if not downloaded_files:
            raise Exception("No file found after MEGA download")

        return str(downloaded_files[-1])

    async def _download_default(self, url: str) -> str:
        """Download using aria2c with wget fallback."""
        console.print("[blue]Downloading with aria2c...[/blue]")

        # Try aria2c first
        result = await asyncio.create_subprocess_exec(
            "aria2c", "-q", "-s16", "-x16", "--check-certificate=false", url,
            cwd=self.work_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await result.communicate()

        if result.returncode == 0:
            # Success with aria2c
            downloaded_files = list(self.work_dir.glob("*"))
            if downloaded_files:
                return str(downloaded_files[-1])

        console.print("[yellow]aria2c failed, trying wget...[/yellow]")

        # Clean up any partial downloads
        for file in self.work_dir.glob("*"):
            if file.is_file():
                file.unlink()

        # Try wget fallback
        result = await asyncio.create_subprocess_exec(
            "wget", "-q", "--no-check-certificate", url,
            cwd=self.work_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await result.communicate()

        if result.returncode != 0:
            raise Exception(f"Both aria2c and wget failed. Last error: {stderr.decode()}")

        # Find downloaded file
        downloaded_files = list(self.work_dir.glob("*"))
        if not downloaded_files:
            raise Exception("No file found after wget download")

        return str(downloaded_files[-1])

    def _format_file_size(self, file_path: str) -> str:
        """Format file size in human readable format."""
        size = os.path.getsize(file_path)
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"

    async def validate_url(self, url: str) -> bool:
        """Validate if URL is accessible."""
        try:
            async with httpx.AsyncClient(verify=False) as client:
                response = await client.head(url, timeout=10.0, follow_redirects=True)
                return response.status_code < 400
        except Exception:
            return False