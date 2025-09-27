import asyncio
import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

from rich.console import Console

from dumpyarabot.schemas import DumpJob

console = Console()


class FirmwareExtractor:
    """Handles firmware extraction using both Python dumper and alternative methods."""

    def __init__(self, work_dir: str):
        self.work_dir = Path(work_dir)
        self.firmware_extractor_path = Path.home() / "Firmware_extractor"

    async def extract_firmware(self, job: DumpJob, firmware_path: str) -> str:
        """Extract firmware and return extraction directory."""
        console.print(f"[blue]Extracting firmware: {firmware_path}[/blue]")

        if job.dump_args.use_alt_dumper:
            return await self._extract_with_alternative_dumper(firmware_path)
        else:
            return await self._extract_with_python_dumper(firmware_path)

    async def _extract_with_python_dumper(self, firmware_path: str) -> str:
        """Extract using the modern Python dumpyara tool."""
        console.print("[blue]Using Python dumper (dumpyara)...[/blue]")

        result = await asyncio.create_subprocess_exec(
            "uvx", "dumpyara", firmware_path, "-o", str(self.work_dir),
            cwd=self.work_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await result.communicate()

        if result.returncode != 0:
            raise Exception(f"Python dumper extraction failed: {stderr.decode()}")

        console.print("[green]Python dumper extraction completed[/green]")
        return str(self.work_dir)

    async def _extract_with_alternative_dumper(self, firmware_path: str) -> str:
        """Extract using the alternative Firmware_extractor toolkit."""
        console.print("[blue]Using alternative dumper (Firmware_extractor)...[/blue]")

        # Clone/update Firmware_extractor
        await self._setup_firmware_extractor()

        # Run the extractor script
        extractor_script = self.firmware_extractor_path / "extractor.sh"
        result = await asyncio.create_subprocess_exec(
            "bash", str(extractor_script), firmware_path, str(self.work_dir),
            cwd=self.work_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await result.communicate()

        if result.returncode != 0:
            raise Exception(f"Alternative dumper extraction failed: {stderr.decode()}")

        # Extract individual partitions
        await self._extract_partitions()

        console.print("[green]Alternative dumper extraction completed[/green]")
        return str(self.work_dir)

    async def _setup_firmware_extractor(self):
        """Clone or update the Firmware_extractor repository."""
        if not self.firmware_extractor_path.exists():
            console.print("[blue]Cloning Firmware_extractor...[/blue]")
            result = await asyncio.create_subprocess_exec(
                "git", "clone", "-q",
                "https://github.com/AndroidDumps/Firmware_extractor",
                str(self.firmware_extractor_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await result.communicate()
        else:
            console.print("[blue]Updating Firmware_extractor...[/blue]")
            result = await asyncio.create_subprocess_exec(
                "git", "-C", str(self.firmware_extractor_path), "pull", "-q", "--rebase",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await result.communicate()

    async def _extract_partitions(self):
        """Extract individual partition images using alternative dumper tools."""
        partitions = [
            "system", "systemex", "system_ext", "system_other",
            "vendor", "cust", "odm", "odm_ext", "oem", "factory", "product", "modem",
            "xrom", "oppo_product", "opproduct", "reserve", "india", "my_preload",
            "my_odm", "my_stock", "my_operator", "my_country", "my_product", "my_company",
            "my_engineering", "my_heytap", "my_custom", "my_manifest", "my_carrier", "my_region",
            "my_bigball", "my_version", "special_preload", "vendor_dlkm", "odm_dlkm", "system_dlkm",
            "mi_ext", "radio", "product_h", "preas", "preavs", "preload"
        ]

        fsck_erofs = self.firmware_extractor_path / "tools" / "fsck.erofs"
        ext2rd = self.firmware_extractor_path / "tools" / "ext2rd"

        for partition in partitions:
            img_file = self.work_dir / f"{partition}.img"
            if not img_file.exists():
                continue

            partition_dir = self.work_dir / partition
            partition_dir.mkdir(exist_ok=True)

            # Try extraction methods in order
            success = False

            # Method 1: fsck.erofs
            if fsck_erofs.exists():
                console.print(f"[blue]Extracting '{partition}' via fsck.erofs...[/blue]")
                result = await asyncio.create_subprocess_exec(
                    str(fsck_erofs), f"--extract={partition_dir}", str(img_file),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL
                )
                await result.communicate()
                if result.returncode == 0:
                    success = True

            # Method 2: ext2rd
            if not success and ext2rd.exists():
                console.print(f"[blue]Extracting '{partition}' via ext2rd...[/blue]")
                result = await asyncio.create_subprocess_exec(
                    str(ext2rd), str(img_file), f"./{partition}",
                    cwd=self.work_dir,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL
                )
                await result.communicate()
                if result.returncode == 0:
                    success = True

            # Method 3: 7zip
            if not success:
                console.print(f"[blue]Extracting '{partition}' via 7zz...[/blue]")
                result = await asyncio.create_subprocess_exec(
                    "7zz", "-snld", "x", str(img_file), "-y", f"-o{partition_dir}/",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL
                )
                await result.communicate()
                if result.returncode == 0:
                    success = True

            if success:
                # Clean up the image file
                img_file.unlink()
                console.print(f"[green]Successfully extracted {partition}[/green]")
            else:
                console.print(f"[yellow]Failed to extract {partition}[/yellow]")
                # Only abort on first partition failure
                if partition == partitions[0]:
                    raise Exception(f"Critical partition extraction failed: {partition}")

        # Extract fsg.mbn from radio.img if present
        await self._extract_fsg_partition()

    async def _extract_fsg_partition(self):
        """Extract fsg.mbn partition if present."""
        fsg_file = self.work_dir / "fsg.mbn"
        if not fsg_file.exists():
            return

        console.print("[blue]Extracting fsg.mbn via 7zz...[/blue]")

        fsg_dir = self.work_dir / "radio" / "fsg"
        fsg_dir.mkdir(parents=True, exist_ok=True)

        result = await asyncio.create_subprocess_exec(
            "7zz", "-snld", "x", str(fsg_file), f"-o{fsg_dir}",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await result.communicate()

        if result.returncode == 0:
            fsg_file.unlink()
            console.print("[green]Successfully extracted fsg.mbn[/green]")

    async def process_boot_images(self) -> None:
        """Process boot images (boot.img, vendor_boot.img, etc.)."""
        boot_images = ["init_boot.img", "vendor_kernel_boot.img", "vendor_boot.img", "boot.img", "dtbo.img"]

        # Move boot images to work directory root if they're in subdirectories
        for image_name in boot_images:
            found_images = list(self.work_dir.rglob(image_name))
            if found_images and not (self.work_dir / image_name).exists():
                src = found_images[0]
                dst = self.work_dir / image_name
                console.print(f"[blue]Moving {image_name} to root directory[/blue]")
                shutil.move(str(src), str(dst))

        # Process each boot image
        for image_name in boot_images:
            image_path = self.work_dir / image_name
            if image_path.exists():
                await self._process_single_boot_image(image_path)

        # Process Oppo/Realme/OnePlus images in special directories
        await self._process_oppo_images()

    async def _process_single_boot_image(self, image_path: Path):
        """Process a single boot image file."""
        image_name = image_path.name
        output_dir = self.work_dir / image_path.stem

        console.print(f"[blue]Processing {image_name}...[/blue]")

        if image_name == "boot.img":
            await self._process_boot_img(image_path, output_dir)
        elif image_name in ["vendor_boot.img", "vendor_kernel_boot.img", "init_boot.img"]:
            await self._process_vendor_boot_img(image_path, output_dir)
        elif image_name == "dtbo.img":
            await self._process_dtbo_img(image_path, output_dir)

    async def _process_boot_img(self, image_path: Path, output_dir: Path):
        """Process boot.img with comprehensive analysis."""
        output_dir.mkdir(exist_ok=True)

        # Extract kernel, ramdisk, etc. if using alternative dumper
        if self.firmware_extractor_path.exists():
            await self._unpack_boot_image(image_path, output_dir)

        # Extract ikconfig (kernel configuration)
        await self._extract_ikconfig(image_path)

        # Generate kallsyms.txt (kernel symbols)
        await self._extract_kallsyms(image_path)

        # Generate analyzable ELF
        await self._extract_boot_elf(image_path)

        # Extract and process device tree blobs
        await self._extract_device_trees(image_path, output_dir)

    async def _process_vendor_boot_img(self, image_path: Path, output_dir: Path):
        """Process vendor_boot.img or similar images."""
        output_dir.mkdir(exist_ok=True)

        # Extract contents if using alternative dumper
        if self.firmware_extractor_path.exists():
            await self._unpack_boot_image(image_path, output_dir)

        # Extract device tree blobs
        await self._extract_device_trees(image_path, output_dir)

    async def _process_dtbo_img(self, image_path: Path, output_dir: Path):
        """Process dtbo.img."""
        output_dir.mkdir(exist_ok=True)

        # Extract device tree overlays
        await self._extract_device_trees(image_path, output_dir, is_dtbo=True)

    async def _unpack_boot_image(self, image_path: Path, output_dir: Path):
        """Unpack boot image using unpackbootimg."""
        unpackbootimg = self.firmware_extractor_path / "tools" / "unpackbootimg"
        if not unpackbootimg.exists():
            return

        console.print(f"[blue]Unpacking {image_path.name}...[/blue]")

        ramdisk_dir = output_dir / "ramdisk"
        ramdisk_dir.mkdir(exist_ok=True)

        result = await asyncio.create_subprocess_exec(
            str(unpackbootimg), "-i", str(image_path), "-o", str(output_dir),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await result.communicate()

        # Extract ramdisk if present
        await self._extract_ramdisk(output_dir, ramdisk_dir)

    async def _extract_ramdisk(self, output_dir: Path, ramdisk_dir: Path):
        """Extract ramdisk from boot image."""
        ramdisk_files = list(output_dir.glob("*-ramdisk*"))
        if not ramdisk_files:
            return

        ramdisk_file = ramdisk_files[0]

        # Check if it's compressed
        result = await asyncio.create_subprocess_exec(
            "file", str(ramdisk_file),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await result.communicate()
        file_info = stdout.decode()

        if "LZ4" in file_info or "gzip" in file_info:
            console.print("[blue]Extracting compressed ramdisk...[/blue]")

            # Decompress with unlz4
            temp_ramdisk = output_dir / "ramdisk.lz4"
            result = await asyncio.create_subprocess_exec(
                "unlz4", str(ramdisk_file), str(temp_ramdisk),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await result.communicate()

            if temp_ramdisk.exists():
                # Extract with 7zip
                result = await asyncio.create_subprocess_exec(
                    "7zz", "-snld", "x", str(temp_ramdisk), f"-o{ramdisk_dir}",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL
                )
                await result.communicate()
                temp_ramdisk.unlink()

    async def _extract_ikconfig(self, image_path: Path):
        """Extract kernel configuration."""
        console.print("[blue]Extracting ikconfig...[/blue]")

        ikconfig_path = self.work_dir / "ikconfig"

        result = await asyncio.create_subprocess_exec(
            "extract-ikconfig", str(image_path),
            stdout=open(ikconfig_path, 'w'),
            stderr=asyncio.subprocess.DEVNULL
        )
        await result.communicate()

        if result.returncode == 0 and ikconfig_path.exists():
            console.print("[green]ikconfig extracted successfully[/green]")
        else:
            console.print("[yellow]Failed to extract ikconfig[/yellow]")
            if ikconfig_path.exists():
                ikconfig_path.unlink()

    async def _extract_kallsyms(self, image_path: Path):
        """Extract kernel symbols."""
        console.print("[blue]Generating kallsyms.txt...[/blue]")

        kallsyms_path = self.work_dir / "kallsyms.txt"

        result = await asyncio.create_subprocess_exec(
            "uvx", "--from", "git+https://github.com/marin-m/vmlinux-to-elf@master",
            "kallsyms-finder", str(image_path),
            stdout=open(kallsyms_path, 'w'),
            stderr=asyncio.subprocess.DEVNULL
        )
        await result.communicate()

        if result.returncode == 0 and kallsyms_path.exists():
            console.print("[green]kallsyms.txt generated successfully[/green]")
        else:
            console.print("[yellow]Failed to generate kallsyms.txt[/yellow]")
            if kallsyms_path.exists():
                kallsyms_path.unlink()

    async def _extract_boot_elf(self, image_path: Path):
        """Extract analyzable ELF file."""
        console.print("[blue]Extracting boot.elf...[/blue]")

        elf_path = self.work_dir / "boot.elf"

        result = await asyncio.create_subprocess_exec(
            "uvx", "--from", "git+https://github.com/marin-m/vmlinux-to-elf@master",
            "vmlinux-to-elf", str(image_path), str(elf_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await result.communicate()

        if result.returncode == 0 and elf_path.exists():
            console.print("[green]boot.elf extracted successfully[/green]")
        else:
            console.print("[yellow]Failed to extract boot.elf[/yellow]")

    async def _extract_device_trees(self, image_path: Path, output_dir: Path, is_dtbo: bool = False):
        """Extract and decompile device tree blobs."""
        if is_dtbo:
            dtb_dir = output_dir
            dts_dir = output_dir / "dts"
        else:
            dtb_dir = output_dir / "dtb"
            dts_dir = output_dir / "dts"

        dtb_dir.mkdir(exist_ok=True)
        dts_dir.mkdir(exist_ok=True)

        console.print(f"[blue]{image_path.name}: Extracting device-tree blobs...[/blue]")

        # Extract DTBs
        result = await asyncio.create_subprocess_exec(
            "extract-dtb", str(image_path), "-o", str(dtb_dir),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await result.communicate()

        if result.returncode != 0:
            console.print("[yellow]No device-tree blobs found[/yellow]")
            return

        # Remove kernel directory if present
        kernel_dir = dtb_dir / "00_kernel"
        if kernel_dir.exists():
            shutil.rmtree(kernel_dir)

        # Decompile DTBs to DTS
        dtb_files = list(dtb_dir.glob("*.dtb"))
        if dtb_files:
            console.print("[blue]Decompiling device-tree blobs...[/blue]")

            for dtb_file in dtb_files:
                dts_file = dts_dir / f"{dtb_file.stem}.dts"

                result = await asyncio.create_subprocess_exec(
                    "dtc", "-q", "-I", "dtb", "-O", "dts", str(dtb_file),
                    stdout=open(dts_file, 'w'),
                    stderr=asyncio.subprocess.DEVNULL
                )
                await result.communicate()

                if result.returncode == 0:
                    console.print(f"[green]Decompiled {dtb_file.name}[/green]")
                else:
                    console.print(f"[yellow]Failed to decompile {dtb_file.name}[/yellow]")
                    if dts_file.exists():
                        dts_file.unlink()

    async def _process_oppo_images(self):
        """Process Oppo/Realme/OnePlus images in special directories."""
        special_dirs = ["vendor/euclid", "system/system/euclid", "reserve/reserve"]

        for dir_path in special_dirs:
            full_dir = self.work_dir / dir_path
            if not full_dir.exists():
                continue

            console.print(f"[blue]Processing images in {dir_path}...[/blue]")

            for img_file in full_dir.glob("*.img"):
                if not img_file.is_file():
                    continue

                console.print(f"[blue]Extracting {img_file.name}...[/blue]")

                extract_dir = img_file.parent / img_file.stem
                extract_dir.mkdir(exist_ok=True)

                result = await asyncio.create_subprocess_exec(
                    "7zz", "-snld", "x", str(img_file), f"-o{extract_dir}",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL
                )
                await result.communicate()

                if result.returncode == 0:
                    img_file.unlink()
                    console.print(f"[green]Extracted {img_file.name}[/green]")
                else:
                    console.print(f"[yellow]Failed to extract {img_file.name}[/yellow]")