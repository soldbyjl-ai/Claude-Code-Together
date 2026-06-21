"""
flyer_scraper_cocowest.py — Scrape current Costco West flyer items from cocowest.ca

Cocowest.ca is a WordPress blog that posts weekly Costco Canada West sale items.
It is server-rendered HTML (no JS required), making it the most reliable scraper.

Output: tools/output/flyer_raw_cocowest.json
Usage:  python tools/flyer_scraper_cocowest.py [--force]
"""

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, date
from pathlib import Path

from playwright.sync_api import sync_playwright

# ---------------------------------------------------------------------------
# Paths & config
# ---------------------------------------------------------------------------
TOOLS_DIR = Path(__file__).parent
OUTPUT_DIR = TOOLS_DIR / "output"
OUTPUT_FILE = OUTPUT_DIR / "flyer_raw_cocowest.json"
LOG_FILE = OUTPUT_DIR / "flyer_scraper.log"
STORE_KEY = "cocowest"
STORE_NAME = "Costco (Cocowest)"
FLYER_BASE_URL = "https://cocowest.ca/"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
OUTPUT_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [cocowest] %(levelname)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _skip_if_today(force: bool) -> bool:
    """Return True if output was already scraped today and --force not set."""
    if force or not OUTPUT_FILE.exists():
        return False
    try:
        data = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
        if data and data[0].get("scraped_at", "")[:10] == date.today().isoformat():
            log.info("[SKIP] already scraped today. Use --force to re-scrape.")
            return True
    except Exception:
        pass
    return False


def _find_current_flyer_url(page) -> str | None:
    """
    Navigate to cocowest.ca homepage and find the URL of the current week's
    Costco flyer post. Looks for a post whose title contains 'Costco' and
    whose URL contains the current or recent year/month.
    """
    log.info("Loading cocowest.ca homepage to find current flyer post...")
    page.goto(FLYER_BASE_URL, wait_until="domcontentloaded", timeout=30000)

    # All post titles are in <h2 class="entry-title"> or similar heading tags
    # with an <a> inside linking to the post.
    # We want the most recent post whose title mentions "Costco" or "flyer".
    candidates = page.query_selector_all("article h2 a, article h3 a, .entry-title a")
    today = date.today()

    for el in candidates:
        title = (el.inner_text() or "").strip()
        href = el.get_attribute("href") or ""
        title_lower = title.lower()
        if "costco" in title_lower or "flyer" in title_lower or "sale" in title_lower:
            # Prefer posts from this year/month or the immediately prior month
            year_str = str(today.year)
            prev_month_str = f"{today.year}/{today.month - 1:02d}" if today.month > 1 else f"{today.year - 1}/12"
            this_month_str = f"{today.year}/{today.month:02d}"
            if year_str in href:
                log.info(f"Found candidate flyer post: {title!r} -> {href}")
                return href

    # Fallback: return first post link regardless of title
    if candidates:
        href = candidates[0].get_attribute("href")
        log.warning(f"No obvious 'Costco flyer' title found; using first post: {href}")
        return href

    return None


def _parse_price_from_caption(text: str) -> tuple[str, str]:
    """
    Extract (raw_price_text, sale_end_date) from a Cocowest figcaption.

    Cocowest figcaption formats vary:
      "1234567 ITEM NAME ($X.XX OFF, EXPIRES ON YYYY-MM-DD) $XX.XX"
      "1234567 ITEM NAME $XX.XX"
      "1234567 ITEM NAME, $XX.XX/lb"

    Returns (raw_price_text, sale_end_date_iso_or_empty).
    """
    # Look for sale end date — two formats used by Cocowest:
    # 1. "EXPIRES ON YYYY-MM-DD" (in the SKU figcaption)
    # 2. "Expires In N Days" / "Expires Today" / "Expires Tomorrow" (JS overlay)
    sale_end = ""
    iso_match = re.search(r'expires?\s+on\s+(\d{4}-\d{2}-\d{2})', text, re.IGNORECASE)
    if iso_match:
        sale_end = iso_match.group(1)
    else:
        from datetime import date, timedelta
        today = date.today()
        if re.search(r'expires?\s+today', text, re.IGNORECASE):
            sale_end = today.isoformat()
        elif re.search(r'expires?\s+tomorrow', text, re.IGNORECASE):
            sale_end = (today + timedelta(days=1)).isoformat()
        else:
            days_match = re.search(r'expires?\s+in\s+(\d+)\s+days?', text, re.IGNORECASE)
            if days_match:
                sale_end = (today + timedelta(days=int(days_match.group(1)))).isoformat()

    # Remove the parenthetical savings block before extracting final price
    clean = re.sub(r'\([^)]*\)', '', text)

    # Extract last price expression (handles "$XX.XX", "$XX.XX/lb", "$XX.XX/kg")
    price_matches = re.findall(r'\$[\d]+(?:\.[\d]{1,2})?(?:/(?:lb|kg|100g))?', clean, re.IGNORECASE)
    if price_matches:
        raw_price = price_matches[-1]  # take the last price (the sale price)
    else:
        raw_price = ""

    return raw_price, sale_end


def _parse_item_name_from_caption(text: str) -> str:
    """
    Extract item name from Cocowest figcaption.
    Format: "[SKU] ITEM NAME (savings info) $price"
    or:     "[SKU] ITEM NAME $price"
    The SKU is an optional leading integer.

    Cocowest injects overlay text into figcaptions via JS:
    "View Price History", "add To List", "sale Alert",
    "Expires Today", "Expires Tomorrow", "Expires In N Days"
    These are stripped before returning the clean product name.
    """
    # Strip JS-injected overlay strings (case-insensitive)
    overlay_patterns = [
        r'view\s+price\s+history',
        r'add\s+to\s+list',
        r'sale\s+alert',
        r'expires?\s+(today|tomorrow|in\s+\d+\s+days?)',
        r'price\s+history',
    ]
    clean = text.strip()
    for pat in overlay_patterns:
        clean = re.sub(pat, ' ', clean, flags=re.IGNORECASE)

    # Strip leading SKU number (up to 8 digits)
    clean = re.sub(r'^\d{4,8}\s+', '', clean.strip())
    # Remove trailing price expressions and parentheticals
    clean = re.sub(r'\([^)]*\)', ' ', clean)
    clean = re.sub(r'\$[\d.]+(?:/(?:lb|kg|100g))?', '', clean, flags=re.IGNORECASE)
    # Remove leftover punctuation and excess whitespace
    clean = re.sub(r'[,\s]+$', '', clean.strip())
    clean = re.sub(r'\s{2,}', ' ', clean)
    return clean.strip().title()


def _scrape_flyer_page(page, flyer_url: str) -> list[dict]:
    """
    Scrape product items from a single Cocowest flyer post page.
    Returns a list of raw item dicts.
    """
    log.info(f"Scraping flyer page: {flyer_url}")
    page.goto(flyer_url, wait_until="domcontentloaded", timeout=30000)

    scraped_at = datetime.now().isoformat(timespec="seconds")
    items = []

    # Cocowest posts embed product images in <figure> blocks with <figcaption>
    figures = page.query_selector_all("figure")
    log.info(f"Found {len(figures)} <figure> elements on page")

    for fig in figures:
        caption_el = fig.query_selector("figcaption")
        if not caption_el:
            continue
        caption_text = (caption_el.inner_text() or "").strip()
        if not caption_text or "$" not in caption_text:
            continue

        item_name = _parse_item_name_from_caption(caption_text)
        raw_price_text, sale_end_date = _parse_price_from_caption(caption_text)

        if not item_name or len(item_name) < 3:
            continue

        items.append({
            "store": STORE_NAME,
            "store_key": STORE_KEY,
            "item_name": item_name,
            "raw_price_text": raw_price_text,
            "price_per_lb": None,
            "price_per_kg": None,
            "unit_raw": "",
            "sale_end_date": sale_end_date,
            "flyer_url": flyer_url,
            "scraped_at": scraped_at,
        })

    log.info(f"Extracted {len(items)} items with price data")
    return items


def _apply_prices(items: list[dict]) -> list[dict]:
    """Run flyer_normalize on each item's raw_price_text."""
    # Import here to keep this file runnable standalone
    sys.path.insert(0, str(TOOLS_DIR))
    from flyer_normalize import normalize_price

    for item in items:
        if item["raw_price_text"]:
            result = normalize_price(item["raw_price_text"])
            item["price_per_lb"] = result["price_per_lb"]
            item["price_per_kg"] = result["price_per_kg"]
            item["unit_raw"] = result["unit_raw"]
    return items


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Scrape Costco West flyer from cocowest.ca")
    parser.add_argument("--force", action="store_true", help="Re-scrape even if already done today")
    args = parser.parse_args()

    if _skip_if_today(args.force):
        sys.exit(0)

    headless = os.getenv("FLYER_HEADLESS", "true").lower() == "true"
    log.info(f"Starting Cocowest scraper (headless={headless})")

    items = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()

        try:
            flyer_url = _find_current_flyer_url(page)
            if not flyer_url:
                log.error("Could not locate current flyer post on cocowest.ca")
                OUTPUT_FILE.write_text(
                    json.dumps([{"scrape_error": "flyer post not found", "store_key": STORE_KEY}],
                               indent=2, ensure_ascii=False),
                    encoding="utf-8"
                )
                sys.exit(1)

            items = _scrape_flyer_page(page, flyer_url)
            items = _apply_prices(items)

        except Exception as e:
            log.error(f"Scrape failed: {e}", exc_info=True)
            OUTPUT_FILE.write_text(
                json.dumps([{"scrape_error": str(e), "store_key": STORE_KEY}],
                           indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            sys.exit(1)
        finally:
            browser.close()

    OUTPUT_FILE.write_text(
        json.dumps(items, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    log.info(f"Wrote {len(items)} items -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
