"""
flyer_scraper_walmart.py — Scrape current Walmart Canada flyer

Primary URL:   https://www.walmart.ca/en/flyer
Secondary URL: https://www.walmart.ca/en/cp/flyer-deals  (may have cleaner DOM)

Walmart returns HTTP 418 to static fetchers; requires a real browser session.
Uses persistent browser profile to benefit from stored cookies/fingerprint.

Output: tools/output/flyer_raw_walmart.json
Usage:  python tools/flyer_scraper_walmart.py [--force]
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
OUTPUT_FILE = OUTPUT_DIR / "flyer_raw_walmart.json"
LOG_FILE = OUTPUT_DIR / "flyer_scraper.log"
STORE_KEY = "walmart"
STORE_NAME = "Walmart"
FLYER_URL = "https://www.walmart.ca/en/flyer"
FLYER_URL_ALT = "https://www.walmart.ca/en/cp/flyer-deals"
PROFILE_DIR = str(TOOLS_DIR / "browser_profile" / "walmart")

OUTPUT_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [walmart] %(levelname)s — %(message)s",
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
    # Exclude non-product endpoints (bootstrap config, cart, nav, etc.)
    exclude = ["bootstrap", "getcart", "mergecart", "globalintent", "chatbot",
               "config?lang", "analytics", "segment", "gtm", "nav-data"]
    if any(x in url_lower for x in exclude):
        return False
    # Prioritise Flipp API
    flipp = "flippenterprise.net" in url_lower
    keywords = ["item", "product", "flyer", "deal", "offer", "sale", "weekly", "rollback",
                "publication", "flyerkit"]
    if not flipp and "walmart.ca" not in url_lower and not any(k in url_lower for k in keywords):
        return False
    stripped = body_text.strip()
    if not (stripped.startswith("[") or stripped.startswith("{")):
        return False
    return len(stripped) >= 1000


def _extract_items_from_json(payload, scraped_at: str) -> list[dict]:
    items_raw = []
    if isinstance(payload, list):
        items_raw = payload
    elif isinstance(payload, dict):
        for key in ("items", "products", "flyer_items", "data", "results",
                    "entries", "deals", "offers", "props"):
            if key in payload and isinstance(payload[key], list):
                items_raw = payload[key]
                break
        # Next.js pageProps nesting
        if not items_raw:
            try:
                items_raw = payload.get("pageProps", {}).get("initialData", {}).get("searchResult", {}).get("itemStacks", [{}])[0].get("items", [])
            except Exception:
                pass

    results = []
    for it in items_raw:
        if not isinstance(it, dict):
            continue
        name = (it.get("name") or it.get("title") or it.get("description") or
                it.get("product_name") or "").strip()
        if not name:
            continue
        # Walmart price structure varies by API version
        price_text = ""
        for price_key in ("priceInfo", "currentPrice", "salePrice", "price"):
            p = it.get(price_key)
            if isinstance(p, dict):
                val = p.get("price") or p.get("currentPrice") or p.get("value")
                unit = (p.get("unitOfMeasure") or p.get("unit") or "").lower()
                if val:
                    price_text = f"${val}/{unit}" if unit and unit not in ("each", "ea", "") else f"${val}"
                break
            elif isinstance(p, (int, float)):
                price_text = f"${p}"
                break

        if not price_text:
            # price_text is the Flipp API's formatted price string (e.g. "$3.49/lb", "2 for $5")
            price_text = str(it.get("price_text") or it.get("current_price") or
                             it.get("sale_price") or "").strip()

        end_date = str(it.get("validTo") or it.get("valid_to") or it.get("end_date") or "").strip()[:10]
        results.append({
            "store": STORE_NAME, "store_key": STORE_KEY,
            "item_name": name, "raw_price_text": price_text,
            "price_per_lb": None, "price_per_kg": None, "unit_raw": "",
            "sale_end_date": end_date, "flyer_url": FLYER_URL,
            "scraped_at": scraped_at,
        })
    return results


def _dom_scrape(page, scraped_at: str, url: str) -> list[dict]:
    log.info(f"DOM fallback scrape on {url}")
    results = []
    selectors = [
        "[data-testid*='product']", "[class*='product-tile']",
        "[class*='product-card']", "[class*='item-tile']",
        "[class*='deal-tile']", "[class*='sale-item']",
    ]
    found_sel = None
    for sel in selectors:
        try:
            page.wait_for_selector(sel, timeout=8000)
            found_sel = sel
            log.info(f"DOM: matched {sel!r}")
            break
        except Exception:
            continue

    if not found_sel:
        log.warning("DOM: no product selectors matched")
        return results

    tiles = page.query_selector_all(found_sel)
    log.info(f"DOM: {len(tiles)} tiles")
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
            "sale_end_date": "", "flyer_url": url,
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

    # Use a fresh (non-persistent) context on every run.
    # A persistent profile caches the Flipp API responses in localStorage/HTTP cache,
    # causing the Flipp widget to skip API calls on subsequent runs. A fresh context
    # guarantees the widget fetches fresh data from dam.flippenterprise.net each time.
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
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

        # Try primary URL first
        try:
            page.goto(FLYER_URL, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            log.warning(f"Primary URL load issue: {e}")
        # Wait for Flipp widget to fire its API requests (Walmart Flipp widget ~20-25s)
        page.wait_for_timeout(25000)

        if captured_jsons:
            best = max(captured_jsons, key=lambda x: len(json.dumps(x)))
            items = _extract_items_from_json(best, scraped_at)
            log.info(f"JSON extraction (primary): {len(items)} items")

        if not items:
            items = _dom_scrape(page, scraped_at, FLYER_URL)

        # If still no items, try alternate URL
        if not items:
            log.info(f"Trying alternate URL: {FLYER_URL_ALT}")
            captured_jsons.clear()
            try:
                page.goto(FLYER_URL_ALT, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                log.warning(f"Alt URL load issue: {e}")
            page.wait_for_timeout(15000)
            if captured_jsons:
                best = max(captured_jsons, key=lambda x: len(json.dumps(x)))
                items = _extract_items_from_json(best, scraped_at)
            if not items:
                items = _dom_scrape(page, scraped_at, FLYER_URL_ALT)

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
