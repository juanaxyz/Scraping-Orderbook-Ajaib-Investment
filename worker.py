import argparse
import asyncio
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
JOBS = [
    ("pangdat", SCRIPT_DIR / "pangdat-scraping.py"),
    ("ipot", SCRIPT_DIR / "ipot_scrapping.py"),
]

# FIXME: args not working man

async def run_job(name: str, script: Path, interval: float):
    while True:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-u", str(script),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        print(f"[{name}] started pid={proc.pid}")
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                print(f"[{name}] {line.decode(errors='replace').rstrip()}")
        finally:
            rc = await proc.wait()
            print(f"[{name}] finished with code {rc}")
        print(f"[{name}] sleeping {interval}s before next run...")
        await asyncio.sleep(interval)

def parse_args():
    parser = argparse.ArgumentParser(description="Run pangdat and ipot scrapers on a fixed interval.")
    parser.add_argument(
        "-i", "--interval",
        type=float,
        default=900.0,
        help="Seconds to wait between runs (default: 900)",
    )
    return parser.parse_args()

async def main():
    args = parse_args()
    await asyncio.gather(*(run_job(name, path, args.interval) for name, path in JOBS))

if __name__ == "__main__":
    asyncio.run(main())