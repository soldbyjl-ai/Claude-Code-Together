"""
flyer_scraper_safeway.py — Scrape current Safeway Canada flyer

URL: https://www.safeway.ca/flyer

Output: tools/output/flyer_raw_safeway.json
Usage:  python tools/flyer_scraper_safeway.py [--force]
"""

import argparse
import json
import logging
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, Response

TOOLS_DIR = Path(__file__).parent
OUTPUT_DIR = TOOLS_DIR / "output"
OUTPUT_FILE = OUTPUT_DIR / "flyer_raw_safeway.json"
LOG_FILE = OUTPUT_DIR / "flyer_scraper.log"
STORE_KEY = "safeway"
STORE_NAME = "Safeway"
FLYER_URL = "https://www.safeway.ca/flyer"

OUTPUT_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [safeway] %(levelname)s — %(message)s",
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
    url_lower = url.lower()
    # Exclude known non-product endpoints
    exclude = ["fetchproductcategories", "algolia", "analytics", "config", "bootstrap",
               "nav-data", "token", "auth", "gtm", "segment", "crazy"]
    if any(x in url_lower for x in exclude):
        return False
    # Prioritise Flipp API and known flyer paths
    flipp = "flippenterprise.net" in url_lower
    keywords = ["item", "product", "flyer", "circular", "deal", "offer", "sale", "weekly",
                "publication", "flyerkit"]
    if not flipp and not any(k in url_lower for k in keywords):
        return False
    stripped = body_text.strip()
    if not (stripped.startswith("[") or stripped.startswith("{")):
        return False
    return len(stripped) >= 1000  # raised threshold to skip small config/category responses


def _extract_items_from_json(payload, scraped_at: str) -> list[dict]:
    items_raw = []
    if isinstance(payload, list):
        items_raw = payload
    elif isinstance(payload, dict):
        for key in ("items", "products", "flyer_items", "data", "results", "entries", "deals"):
            if key in payload and isinstance(payload[key], list):
                items_raw = payload[key]
                break

    results = []
    for it in items_raw:
        if not isinstance(it, dict):
            continue
        name = (it.get("name") or it.get("title") or it.get("description") or
                it.get("product_name") or "").strip()
        if not name:
            continue
        price_text = str(it.get("price_text") or it.get("current_price") or
                         it.get("sale_price") or it.get("price") or "").strip()
        end_date = str(it.get("valid_to") or it.get("end_date") or
                       it.get("expiry_date") or "").strip()[:10]
        results.append({
            "store": STORE_NAME, "store_key": STORE_KEY,
            "item_name": name, "raw_price_text": price_text,
            "price_per_lb": None, "price_per_kg": None, "unit_raw": "",
            "sale_end_date": end_date, "flyer_url": FLYER_URL,
            "scraped_at": scraped_at,
        })
    return results


def _dom_scrape(page, scraped_at: str) -> list[dict]:
    log.info("Attempting DOM fallback scrape...")
    results = []
    selectors = [
        "[class*='flyer-item']", "[class*='product-card']",
        "[class*='product-tile']", "[class*='item-card']",
        "[data-testid*='product']", "[class*='deal-card']",
    ]
    found_sel = None
    for sel in selectors:
        try:
            page.wait_for_selector(sel, timeout=8000)
            found_sel = sel
            log.info(f"DOM: matched selector {sel!r}")
            break
        except Exception:
            continue

    if not found_sel:
        log.warning("DOM fallback: no product selectors matched")
        return results

    tiles = page.query_selector_all(found_sel)
    log.info(f"DOM: found {len(tiles)} tiles")
    for tile in tiles:
        text = tile.inner_text().strip()
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if not lines:
            continue
        name = lines[0]
        price_text = ""
        m = re.search(r'\$[\d.]+(?:/(?:lb|kg|100g))?', text, re.IGNORECASE)
        if m:
            price_text = m.group(0)
        results.append({
            "store": STORE_NAME, "store_key": STORE_KEY,
            "item_name": name, "raw_price_text": price_text,
            "price_per_lb": None, "price_per_kg": None, "unit_raw": "",
            "sale_end_date": "", "flyer_url": FLYER_URL,
            "scraped_at": scraped_at,
        })
    return results


def _apply_prices(items):
    sys.path.insert(0, str(TOOLS_DIR))
    from flyer_normalize import normalize_price
    for item in items:
        if item.get("raw_price_text"):
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

        def handle_response(response: Response):
            try:
                ct = response.headers.get("content-type", "")
                if "json" not in ct:
                    return
                body = response.text()
                if _is_flyer_json(response.url, body):
                    log.info(f"Captured JSON from: {response.url}")
                    captured_jsons.append(json.loads(body))
            except Exception:
                pass

        page.on("response", handle_response)
        try:
            # Use domcontentloaded so we don't wait for network to go idle
            # (Safeway SPA never reaches networkidle). Then wait for flyer API calls.
            page.goto(FLYER_URL, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            log.warning(f"Page load issue: {e}")
        # Give the flyer widget time to fire its API requests
        page.wait_for_timeout(12000)

        if captured_jsons:
            # Use the largest JSON payload (most likely to be the product list)
            best = max(captured_jsons, key=lambda x: len(json.dumps(x)))
            items = _extract_items_from_json(best, scraped_at)
            log.info(f"JSON extraction: {len(items)} items from {len(captured_jsons)} captured responses")
        if not items:
            items = _dom_scrape(page, scraped_at)
        browser.close()

    if not items:
        log.warning("No items extracted")
        items = [{"scrape_error": "no items found", "store_key": STORE_KEY}]
    else:
        items = _apply_prices(items)

    OUTPUT_FILE.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info(f"Wrote {len(items)} items -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
