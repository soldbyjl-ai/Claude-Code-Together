"""
bcassessment_scraper.py
-----------------------
Takes a list of BC addresses and looks up each one on bcassessment.ca,
returning land value and total assessed value.

Input:  list of address strings  (or reads tools/output/paragon_detached.json)
Output: tools/output/bcassessment_results.json

Usage:
    # Look up addresses from paragon output:
    python tools/bcassessment_scraper.py

    # Or pass addresses directly:
    python tools/bcassessment_scraper.py "1740 BETA AVENUE BURNABY BC" "4824 FAIRLAWN DRIVE BURNABY BC"

Notes:
- 2–3 second delay between lookups (configurable via BCASSESSMENT_DELAY in .env).
- headless=False so you can handle CAPTCHA manually if BC Assessment triggers one.
- Script pauses and waits if it detects a CAPTCHA.
"""

import json
import logging
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
load_dotenv()

DELAY = float(os.getenv("BCASSESSMENT_DELAY", "2.5"))
BASE_URL = "https://www.bcassessment.ca"
SEARCH_URL = f"{BASE_URL}/Property/AssessmentSearch"

INPUT_FILE  = Path(__file__).parent / "output" / "paragon_detached.json"
OUTPUT_DIR  = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE = OUTPUT_DIR / "bcassessment_results.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(OUTPUT_DIR / "bcassessment_scraper.log", mode="a"),
    ],
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def clean(val) -> str:
    if val is None:
        return ""
    return str(val).strip().replace("\xa0", " ")


def detect_captcha(page) -> bool:
    """Return True if a CAPTCHA widget is visible."""
    try:
        return page.is_visible('.g-recaptcha, iframe[src*="recaptcha"], #captcha', timeout=2_000)
    except Exception:
        return False


def wait_for_captcha(page, timeout: int = 120):
    """Block until the CAPTCHA is solved (detected by its disappearance) or timeout."""
    log.warning("CAPTCHA detected — please solve it in the browser window.")
    log.warning(f"Waiting up to {timeout}s…")
    try:
        page.wait_for_selector(
            '.g-recaptcha, iframe[src*="recaptcha"], #captcha',
            state="hidden",
            timeout=timeout * 1000,
        )
        log.info("CAPTCHA cleared — resuming.")
    except PWTimeout:
        log.error("CAPTCHA timed out. Exiting.")
        raise


# ---------------------------------------------------------------------------
# Core lookup
# ---------------------------------------------------------------------------

def lookup_address(page, address: str) -> dict:
    """
    Search bcassessment.ca for one address and return
    {"address": ..., "land_value": ..., "total_assessed_value": ...}
    """
    result = {
        "address": address,
        "land_value": "",
        "total_assessed_value": "",
        "error": "",
    }

    try:
        log.info(f"Looking up: {address}")
        page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=30_000)

        if detect_captcha(page):
            wait_for_captcha(page)

        # Type into the address autocomplete input character-by-character to fire
        # keyup events that trigger the jQuery UI autocomplete suggestions.
        page.wait_for_selector('#rsbSearch', timeout=10_000)
        page.click('#rsbSearch')
        page.type('#rsbSearch', address, delay=80)
        time.sleep(2)  # wait for autocomplete suggestions to appear

        if detect_captcha(page):
            wait_for_captcha(page)

        # Click first autocomplete suggestion
        try:
            page.wait_for_selector('ul.ui-autocomplete li:first-child', timeout=8_000)
            page.click('ul.ui-autocomplete li:first-child')
            # Wait for the property detail page to render assessment values
            page.wait_for_selector('#lblTotalAssessedValue', timeout=20_000)
        except PWTimeout:
            log.warning(f"No autocomplete results or property page for: {address}")
            result["error"] = "no results"
            return result

        if detect_captcha(page):
            wait_for_captcha(page)

        # --- Extract assessed values ---
        # Current year values: #lblTotalAssessedLand, #lblTotalAssessedValue
        try:
            land = clean(page.locator('#lblTotalAssessedLand').inner_text(timeout=5_000))
        except Exception:
            land = ""
        try:
            total = clean(page.locator('#lblTotalAssessedValue').inner_text(timeout=5_000))
        except Exception:
            total = ""

        result["land_value"]           = land
        result["total_assessed_value"] = total
        log.info(f"  Land: {land}  |  Total: {total}")

    except Exception as e:
        log.error(f"Error looking up {address}: {e}")
        result["error"] = str(e)

    return result


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------

def load_addresses_from_paragon() -> list[str]:
    """Read addresses from the paragon scraper output JSON."""
    if not INPUT_FILE.exists():
        log.warning(f"Paragon output not found at {INPUT_FILE}")
        return []
    with open(INPUT_FILE, encoding="utf-8") as f:
        listings = json.load(f)
    # Normalise: append BURNABY BC if address looks bare
    addresses = []
    for item in listings:
        addr = item.get("address", "").strip()
        if addr:
            if "burnaby" not in addr.lower():
                addr = f"{addr} BURNABY"
            addresses.append(addr)
    log.info(f"Loaded {len(addresses)} addresses from paragon output.")
    return addresses


def run(addresses: list[str]) -> list[dict]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, slow_mo=100)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()

        for i, address in enumerate(addresses):
            result = lookup_address(page, address)
            results.append(result)

            # Polite delay between requests
            if i < len(addresses) - 1:
                sleep_time = DELAY + (0.5 if i % 10 == 9 else 0)   # extra pause every 10
                log.info(f"Sleeping {sleep_time}s before next lookup…")
                time.sleep(sleep_time)

        browser.close()

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) > 1:
        # Addresses passed as command-line arguments
        addresses = [a.strip() for a in sys.argv[1:] if a.strip()]
        log.info(f"Using {len(addresses)} address(es) from command line.")
    else:
        addresses = load_addresses_from_paragon()

    if not addresses:
        log.error("No addresses to process. Provide addresses as arguments or run paragon_scraper.py first.")
        return

    log.info(f"Starting BC Assessment lookup for {len(addresses)} addresses (delay={DELAY}s)…")
    results = run(addresses)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    log.info(f"Saved {len(results)} results -> {OUTPUT_FILE}")

    # Summary
    ok  = sum(1 for r in results if not r["error"])
    err = sum(1 for r in results if r["error"])
    log.info(f"Done. Success: {ok}  |  Errors: {err}")


if __name__ == "__main__":
    main()
