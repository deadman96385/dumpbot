#!/usr/bin/env python3
"""
Script to run dump workers that process firmware extraction jobs.

Usage:
    python run_worker.py [worker_id]

The worker will continuously poll the Redis job queue and process dump jobs.
"""

import asyncio
import signal
import sys
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from dumpyarabot.dump_worker import ExtractAndPushWorker
from rich.console import Console

console = Console()


async def main():
    """Main worker function."""
    worker_id = sys.argv[1] if len(sys.argv) > 1 else None
    worker = ExtractAndPushWorker(worker_id)

    # Handle shutdown signals
    def signal_handler(signum, frame):
        console.print(f"\n[yellow]Received signal {signum}, shutting down worker...[/yellow]")
        asyncio.create_task(worker.stop())

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        console.print(f"[green]Starting dump worker: {worker.worker_id}[/green]")
        console.print("[blue]Worker will process firmware dump jobs from the Redis queue[/blue]")
        console.print("[yellow]Press Ctrl+C to stop[/yellow]")

        await worker.start()
    except KeyboardInterrupt:
        console.print("\n[yellow]Worker interrupted by user[/yellow]")
    except Exception as e:
        console.print(f"\n[red]Worker crashed: {e}[/red]")
        raise
    finally:
        await worker.stop()
        console.print("[blue]Worker stopped[/blue]")


if __name__ == "__main__":
    asyncio.run(main())