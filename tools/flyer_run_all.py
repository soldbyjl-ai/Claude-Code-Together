"""
flyer_run_all.py — Orchestrator for the weekly grocery flyer pipeline.

Runs all 6 store scrapers sequentially, then classifies items and generates
the HTML price-comparison report. Opens the report in the default browser.

Usage:
    python tools/flyer_run_all.py              # Normal run (skip if scraped today)
    python tools/flyer_run_all.py --force      # Re-scrape all stores
    python tools/flyer_run_all.py --report-only # Skip scrapers, just regenerate report

Steps:
  1. flyer_scraper_saveon.py
  2. flyer_scraper_safeway.py
  3. flyer_scraper_walmart.py
  4. flyer_scraper_tnt.py
  5. flyer_scraper_superstore.py
  6. flyer_scraper_cocowest.py
  7. Merge all flyer_raw_*.json + run classify
  8. flyer_report.py -> flyer_report_YYYY-MM-DD.html
  9. Open report in browser
"""

import argparse
import json
import subprocess
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

TOOLS_DIR = Path(__file__).parent
OUTPUT_DIR = TOOLS_DIR / "output"
CLASSIFIED_FILE = OUTPUT_DIR / "flyer_classified.json"

SCRAPERS = [
    "flyer_scraper_saveon.py",
    "flyer_scraper_safeway.py",
    "flyer_scraper_walmart.py",
    "flyer_scraper_tnt.py",
    "flyer_scraper_superstore.py",
    "flyer_scraper_cocowest.py",
]

RAW_FILES = [
    OUTPUT_DIR / "flyer_raw_saveon.json",
    OUTPUT_DIR / "flyer_raw_safeway.json",
    OUTPUT_DIR / "flyer_raw_walmart.json",
    OUTPUT_DIR / "flyer_raw_tnt.json",
    OUTPUT_DIR / "flyer_raw_superstore.json",
    OUTPUT_DIR / "flyer_raw_cocowest.json",
]


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def run_scraper(script: str, force: bool) -> bool:
    """Run a scraper subprocess. Returns True on success."""
    cmd = [sys.executable, str(TOOLS_DIR / script)]
    if force:
        cmd.append("--force")
    log(f"Running {script}...")
    result = subprocess.run(cmd, capture_output=False)
    if result.returncode != 0:
        log(f"  WARNING: {script} exited with code {result.returncode}")
        return False
    return True


def merge_and_classify() -> int:
    """
    Merge all flyer_raw_*.json files, classify each item, write flyer_classified.json.
    Returns count of classified items (excluding Other category).
    """
    sys.path.insert(0, str(TOOLS_DIR))
    from flyer_classify import classify_items

    all_items: list[dict] = []
    for raw_file in RAW_FILES:
        if not raw_file.exists():
            log(f"  MISSING: {raw_file.name} — store will not appear in report")
            continue
        try:
            data = json.loads(raw_file.read_text(encoding="utf-8"))
            # Skip files that contain only an error record
            if data and isinstance(data[0], dict) and "scrape_error" in data[0] and len(data) == 1:
                log(f"  SCRAPE ERROR in {raw_file.name}: {data[0].get('scrape_error')}")
                # Still include the error record so the report footer can show it
                all_items.extend(data)
            else:
                all_items.extend(data)
                log(f"  Loaded {len(data)} items from {raw_file.name}")
        except Exception as e:
            log(f"  ERROR reading {raw_file.name}: {e}")

    classify_items(all_items)

    OUTPUT_DIR.mkdir(exist_ok=True)
    CLASSIFIED_FILE.write_text(
        json.dumps(all_items, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    focused = [it for it in all_items if it.get("category") in ("Meat/Fish", "Vegetables", "Fruits")]
    log(f"Classified {len(focused)} items in focus categories (out of {len(all_items)} total)")
    return len(focused)


def generate_report() -> Path:
    """Generate HTML report and return its path."""
    sys.path.insert(0, str(TOOLS_DIR))
    from flyer_report import generate_report as _gen
    return _gen()


def main():
    parser = argparse.ArgumentParser(description="Run full grocery flyer pipeline")
    parser.add_argument("--force", action="store_true",
                        help="Force re-scrape all stores even if scraped today")
    parser.add_argument("--report-only", action="store_true",
                        help="Skip scraping, only regenerate report from existing data")
    parser.add_argument("--no-open", action="store_true",
                        help="Do not open the report in browser after generating")
    args = parser.parse_args()

    log("=" * 60)
    log("Metro Vancouver Grocery Flyer Pipeline")
    log("=" * 60)

    if not args.report_only:
        failures = 0
        for script in SCRAPERS:
            ok = run_scraper(script, args.force)
            if not ok:
                failures += 1

        if failures:
            log(f"\n{failures}/{len(SCRAPERS)} scrapers reported errors — partial report will be generated")
        else:
            log(f"\nAll {len(SCRAPERS)} scrapers completed successfully")

    log("\nMerging and classifying items...")
    count = merge_and_classify()

    log("\nGenerating HTML report...")
    report_path = generate_report()
    log(f"Report: {report_path}")

    if count == 0:
        log("\nWARNING: No items matched the focus categories (Meat/Fish, Vegetables, Fruits).")
        log("The scrapers may need selector updates — check flyer_scraper.log for details.")

    if not args.no_open:
        log("\nOpening report in browser...")
        webbrowser.open(report_path.as_uri())

    log("\nDone.")


if __name__ == "__main__":
    main()
