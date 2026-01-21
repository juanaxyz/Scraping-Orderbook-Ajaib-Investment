"""Scraper Worker Scheduler

This script runs multiple scraper scripts (Ajaib and IPOT) in parallel on a fixed interval.
It acts as a job scheduler that continuously executes each scraper, captures their output,
and automatically restarts them after a configurable wait period.

Key Features:
- Parallel execution of multiple scraper jobs using asyncio
- Configurable interval between scraper runs
- Live output streaming from each job with labeled prefixes
- Automatic job restart after completion
- Graceful error handling and process management

Usage:
    python worker.py                    # Run with default 900s (15min) interval
    python worker.py -i 300             # Run with 5min interval
    python worker.py --interval 1800    # Run with 30min interval
"""

import argparse
import asyncio
import sys
from pathlib import Path

# =============================================================================
# CONFIGURATION
# =============================================================================

SCRIPT_DIR = Path(__file__).parent

# List of scraper jobs to run in parallel
# Each tuple: (job_name, script_path)
JOBS = [
    ("ajaib", SCRIPT_DIR / "main.py"),           # Ajaib/Pangdat scraper
    ("ipot", SCRIPT_DIR / "ipot_scrapping.py"),  # IPOT scraper
]


async def run_job(name: str, script: Path, interval: float):
    """Run a scraper script continuously with a fixed interval between executions.
    
    This function runs indefinitely, executing the specified script, waiting for it
    to complete, then sleeping for the configured interval before running again.
    All output from the script is captured and printed with a job name prefix.
    
    Args:
        name: Job identifier used in log messages (e.g., 'ajaib', 'ipot')
        script: Path to the Python script to execute
        interval: Seconds to wait between job completions and next start
        
    Note:
        - Uses '-u' flag for unbuffered Python output (real-time logging)
        - Stderr is redirected to stdout for unified output stream
        - Runs in infinite loop; only stops if parent process terminates
    """
    while True:  # Infinite loop - continuously run the job
        # Start the scraper script as a subprocess
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-u", str(script),  # -u = unbuffered output
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,   # Merge stderr into stdout
        )
        print(f"[{name}] started pid={proc.pid}")
        
        try:
            # Stream output line by line in real-time
            while True:
                line = await proc.stdout.readline()
                if not line:  # EOF - process finished
                    break
                # Print with job name prefix for identification
                print(f"[{name}] {line.decode(errors='replace').rstrip()}")
        finally:
            # Wait for process to fully terminate and get exit code
            rc = await proc.wait()
            print(f"[{name}] finished with code {rc}")
        
        # Wait before starting next run
        print(f"[{name}] sleeping {interval}s before next run...")
        await asyncio.sleep(interval)

def parse_args():
    """Parse command-line arguments.
    
    Returns:
        argparse.Namespace: Parsed arguments with 'interval' attribute
        
    Example:
        python worker.py -i 600  # 10 minute interval
    """
    parser = argparse.ArgumentParser(
        description="Run pangdat and ipot scrapers on a fixed interval."
    )
    parser.add_argument(
        "-i", "--interval",
        type=float,
        default=900.0,
        help="Seconds to wait between runs (default: 900 = 15 minutes)",
    )
    return parser.parse_args()

async def main():
    """Main entry point for the worker scheduler.
    
    Parses command-line arguments and launches all configured scraper jobs
    in parallel. Each job runs independently in its own async task.
    
    The function will run indefinitely until interrupted (Ctrl+C).
    """
    args = parse_args()
    
    # Launch all jobs in parallel - each runs in its own infinite loop
    # asyncio.gather runs all tasks concurrently and waits for all to complete
    # (which they never will, since each runs forever)
    await asyncio.gather(*(run_job(name, path, args.interval) for name, path in JOBS))

# =============================================================================
# SCRIPT ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    # Run the main async function
    # This will block until Ctrl+C or process termination
    asyncio.run(main())