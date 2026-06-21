"""
flyer_schedule_setup.py — Register a Windows Task Scheduler task that runs
                           the grocery flyer pipeline every Wednesday at 8:00 AM.

Run once to register. No need to re-run unless you move the project.

Usage:  python tools/flyer_schedule_setup.py [--remove]
"""

import argparse
import subprocess
import sys
from pathlib import Path

TASK_NAME = "GroceryFlyerScraper"
TOOLS_DIR = Path(__file__).parent
SCRIPT = str(TOOLS_DIR / "flyer_run_all.py")
PYTHON = sys.executable


def _run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    print(f"  > {' '.join(cmd)}")
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def register_task():
    """Create (or replace) the weekly Task Scheduler entry."""
    # /F = force overwrite if it already exists
    # /SC WEEKLY /D WED = every Wednesday
    # /ST 08:00 = 8:00 AM
    # /TR = action (Python script)
    # /RL HIGHEST = run with highest available privileges (avoids UAC popups)
    # /IT = only run when user is logged in (required since we open a browser)
    cmd = [
        "schtasks", "/Create",
        "/TN", TASK_NAME,
        "/SC", "WEEKLY",
        "/D", "WED",
        "/ST", "08:00",
        "/TR", f'"{PYTHON}" "{SCRIPT}"',
        "/RL", "HIGHEST",
        "/IT",
        "/F",
    ]
    result = _run(cmd, check=False)
    if result.returncode == 0:
        print(f"\nTask '{TASK_NAME}' registered successfully.")
        print("It will run every Wednesday at 8:00 AM.")
        print(f"Script: {SCRIPT}")
        print(f"Python: {PYTHON}")
        print("\nTo verify in Task Scheduler:")
        print("  1. Press Win + R, type 'taskschd.msc', press Enter")
        print(f"  2. Look for '{TASK_NAME}' in the Task Scheduler Library")
        print("\nTo run it manually right now:")
        print(f"  python {SCRIPT}")
    else:
        print(f"\nERROR: schtasks returned {result.returncode}")
        print(result.stderr)
        print("\nTroubleshooting:")
        print("  - Run this script as Administrator if the error mentions permissions")
        print("  - Or manually create the task in Windows Task Scheduler UI")
        sys.exit(1)


def remove_task():
    """Delete the scheduled task."""
    cmd = ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"]
    result = _run(cmd, check=False)
    if result.returncode == 0:
        print(f"Task '{TASK_NAME}' removed.")
    else:
        print(f"Could not remove task (may not exist): {result.stderr}")


def main():
    parser = argparse.ArgumentParser(
        description="Register weekly Task Scheduler task for the flyer scraper"
    )
    parser.add_argument("--remove", action="store_true",
                        help="Remove the scheduled task instead of creating it")
    args = parser.parse_args()

    if args.remove:
        remove_task()
    else:
        register_task()


if __name__ == "__main__":
    main()
