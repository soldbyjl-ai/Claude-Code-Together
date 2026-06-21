"""
flyer_scraper_saveon.py — Scrape current Save-on-Foods flyer

URL: https://www.saveonfoods.com/sm/planning/rsid/1982/circular
     rsid=1982 = Brentwood / Burnaby area store

Strategy:
  1. Intercept XHR/fetch responses during page load for JSON flyer data
  2. Fallback: DOM scrape of product tiles if no JSON captured

Output: tools/output/flyer_raw_saveon.json
Usage:  python tools/flyer_scraper_saveon.py [--force]
"""

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, Response

TOOLS_DIR = Path(__file__).parent
OUTPUT_DIR = TOOLS_DIR / "output"
OUTPUT_FILE = OUTPUT_DIR / "flyer_raw_saveon.json"
LOG_FILE = OUTPUT_DIR / "flyer_scraper.log"
STORE_KEY = "saveon"
STORE_NAME = "Save-on-Foods"
FLYER_URL = "https://www.saveonfoods.com/sm/planning/rsid/1982/circular"

OUTPUT_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [saveon] %(levelname)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


def _skip_if_today(force: bool) -> bool:
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


def _is_flyer_json(url: str, body_text: str) -> bool:
    """Heuristic: does this response look like flyer product data?"""
    url_lower = url.lower()
    # Exclude known non-product endpoints
    exclude = ["fetchproductcategories", "algolia", "analytics", "config", "bootstrap",
               "nav-data", "token", "auth", "gtm", "segment", "crazy", "font", "css"]
    if any(x in url_lower for x in exclude):
        return False
    # Prioritise Flipp API (Save-on-Foods uses Flipp embedded circular)
    flipp = "flippenterprise.net" in url_lower
    keywords = ["item", "product", "flyer", "circular", "deal", "offer", "sale",
                "publication", "flyerkit"]
    if not flipp and not any(k in url_lower for k in keywords):
        return False
    stripped = body_text.strip()
    if not (stripped.startswith("[") or stripped.startswith("{")):
        return False
    return len(stripped) >= 1000


def _extract_items_from_json(payload: list | dict, scraped_at: str) -> list[dict]:
    """
    Try to extract item records from a captured JSON payload.
    Handles both array-of-items and nested object formats.
    """
    items_raw = []
    if isinstance(payload, list):
        items_raw = payload
    elif isinstance(payload, dict):
        # Common wrapper keys: "items", "products", "flyer_items", "data", "results"
        for key in ("items", "products", "flyer_items", "data", "results", "entries"):
            if key in payload and isinstance(payload[key], list):
                items_raw = payload[key]
                break

    results = []
    for it in items_raw:
        if not isinstance(it, dict):
            continue
        # Try common name fields
        name = (it.get("name") or it.get("title") or it.get("description") or
                it.get("product_name") or it.get("item_name") or "").strip()
        if not name:
            continue

        # Try common price fields
        # price_text is the Flipp API's formatted price string (e.g. "$3.49/lb", "2 for $5")
        price_text = (str(it.get("price_text") or it.get("current_price") or
                     it.get("sale_price") or it.get("price") or it.get("priceStr") or "")).strip()

        # Try common date fields
        end_date = (str(it.get("valid_to") or it.get("end_date") or
                    it.get("expiry_date") or it.get("sale_end") or "")).strip()
        # Normalise to YYYY-MM-DD if possible
        if end_date and len(end_date) > 10:
            end_date = end_date[:10]

        results.append({
            "store": STORE_NAME,
            "store_key": STORE_KEY,
            "item_name": name,
            "raw_price_text": price_text,
            "price_per_lb": None,
            "price_per_kg": None,
            "unit_raw": "",
            "sale_end_date": end_date,
            "flyer_url": FLYER_URL,
            "scraped_at": scraped_at,
        })
    return results


def _dom_scrape(page, scraped_at: str) -> list[dict]:
    """
    Fallback: scrape product tiles directly from the rendered DOM.
    Tries multiple CSS selector patterns used by flyer SPAs.
    """
    log.info("Attempting DOM fallback scrape...")
    results = []

    # Wait for any product container to appear
    selectors_to_try = [
        "[data-testid*='product']",
        "[class*='product-tile']",
        "[class*='flyer-item']",
        "[class*='circular-item']",
        "[class*='item-card']",
        "li[class*='item']",
    ]

    found_selector = None
    for sel in selectors_to_try:
        try:
            page.wait_for_selector(sel, timeout=8000)
            found_selector = sel
            log.info(f"DOM: found product elements with selector: {sel!r}")
            break
        except Exception:
            continue

    if not found_selector:
        log.warning("DOM fallback: no product tile selectors matched")
        return results

    tiles = page.query_selector_all(found_selector)
    log.info(f"DOM: found {len(tiles)} product tiles")

    for tile in tiles:
        # Item name: largest text block in the tile
        name_el = (tile.query_selector("[class*='name']") or
                   tile.query_selector("[class*='title']") or
                   tile.query_selector("h3") or tile.query_selector("h4") or
                   tile.query_selector("p"))
        name = (name_el.inner_text() if name_el else tile.inner_text()).strip()
        name = name.split("\n")[0].strip()
        if not name or len(name) < 3:
            continue

        # Price: element containing "$"
        price_el = (tile.query_selector("[class*='price']") or
                    tile.query_selector("[class*='cost']"))
        price_text = ""
        if price_el:
            price_text = price_el.inner_text().strip()
        else:
            # Scan all text for a $X.XX pattern
            full = tile.inner_text()
            import re
            m = re.search(r'\$[\d.]+(?:/(?:lb|kg|100g))?', full, re.IGNORECASE)
            if m:
                price_text = m.group(0)

        results.append({
            "store": STORE_NAME,
            "store_key": STORE_KEY,
            "item_name": name,
            "raw_price_text": price_text,
            "price_per_lb": None,
            "price_per_kg": None,
            "unit_raw": "",
            "sale_end_date": "",
            "flyer_url": FLYER_URL,
            "scraped_at": scraped_at,
        })

    return results


def _apply_prices(items: list[dict]) -> list[dict]:
    sys.path.insert(0, str(TOOLS_DIR))
    from flyer_normalize import normalize_price
    for item in items:
        if item["raw_price_text"]:
            r = normalize_price(item["raw_price_text"])
            item["price_per_lb"] = r["price_per_lb"]
            item["price_per_kg"] = r["price_per_kg"]
            item["unit_raw"] = r["unit_raw"]
    return items


def main():
    parser = argparse.ArgumentParser(description=f"Scrape {STORE_NAME} flyer")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if _skip_if_today(args.force):
        sys.exit(0)

    headless = os.getenv("FLYER_HEADLESS", "true").lower() == "true"
    log.info(f"Starting {STORE_NAME} scraper (headless={headless})")

    items = []
    captured_jsons: list = []
    scraped_at = datetime.now().isoformat(timespec="seconds")

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

        # Intercept responses to capture JSON flyer data
        def handle_response(response: Response):
            try:
                url = response.url
                ct = response.headers.get("content-type", "")
                if "json" not in ct:
                    return
                body = response.text()
                if _is_flyer_json(url, body):
                    log.info(f"Captured JSON response from: {url}")
                    captured_jsons.append(json.loads(body))
            except Exception:
                pass

        page.on("response", handle_response)

        try:
            # Use domcontentloaded — the /sm/ SPA never reaches networkidle.
            # Then wait for the Flipp widget to fire its API requests.
            page.goto(FLYER_URL, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            log.warning(f"Page load issue ({e}), will still attempt capture")
        page.wait_for_timeout(12000)

        if captured_jsons:
            best = max(captured_jsons, key=lambda x: len(json.dumps(x)))
            items = _extract_items_from_json(best, scraped_at)
            log.info(f"Extracted {len(items)} items from {len(captured_jsons)} captured responses")

        if not items:
            items = _dom_scrape(page, scraped_at)

        browser.close()

    if not items:
        log.warning("No items extracted — writing empty result with scrape_error")
        items = [{"scrape_error": "no items found", "store_key": STORE_KEY}]
    else:
        items = _apply_prices(items)

    OUTPUT_FILE.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info(f"Wrote {len(items)} items -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
