"""
flyer_scraper_tnt.py — Scrape current T&T Supermarket flyer

URL: https://www.tntsupermarket.com/eng/store-flyer

T&T flyers are sometimes image-based PDFs rather than structured data.
If no product tiles are found, the scraper records a graceful error with
the flyer URL and exits (no crash).

Output: tools/output/flyer_raw_tnt.json
Usage:  python tools/flyer_scraper_tnt.py [--force]
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
OUTPUT_FILE = OUTPUT_DIR / "flyer_raw_tnt.json"
LOG_FILE = OUTPUT_DIR / "flyer_scraper.log"
STORE_KEY = "tnt"
STORE_NAME = "T&T Supermarket"
FLYER_URL = "https://www.tntsupermarket.com/eng/store-flyer"

OUTPUT_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [tnt] %(levelname)s — %(message)s",
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
    tnt_keywords = ["tnt", "flyer", "item", "product", "sale", "deal", "weekly"]
    if not any(k in url_lower for k in tnt_keywords):
        return False
    stripped = body_text.strip()
    if not (stripped.startswith("[") or stripped.startswith("{")):
        return False
    return len(stripped) >= 500


def _extract_items_from_json(payload, scraped_at: str) -> list[dict]:
    items_raw = []
    if isinstance(payload, list):
        items_raw = payload
    elif isinstance(payload, dict):
        for key in ("items", "products", "flyer_items", "data", "results", "entries"):
            if key in payload and isinstance(payload[key], list):
                items_raw = payload[key]
                break

    results = []
    for it in items_raw:
        if not isinstance(it, dict):
            continue
        name = (it.get("name") or it.get("title") or it.get("en_name") or
                it.get("product_name") or "").strip()
        if not name:
            continue
        price_text = str(it.get("current_price") or it.get("sale_price") or
                         it.get("price") or "").strip()
        end_date = str(it.get("valid_to") or it.get("end_date") or "").strip()[:10]
        results.append({
            "store": STORE_NAME, "store_key": STORE_KEY,
            "item_name": name, "raw_price_text": price_text,
            "price_per_lb": None, "price_per_kg": None, "unit_raw": "",
            "sale_end_date": end_date, "flyer_url": FLYER_URL,
            "scraped_at": scraped_at,
        })
    return results


def _dom_scrape(page, scraped_at: str) -> list[dict]:
    """
    T&T DOM scrape. The site is slow — uses an extended wait.
    Items are bilingual (Chinese + English); we target elements adjacent to "$" prices.
    Falls back gracefully if the flyer is image-based.
    """
    log.info("Waiting for T&T page to settle (5s)...")
    try:
        page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:
        pass
    page.wait_for_timeout(5000)

    results = []

    # Check for a PDF link — indicates image-based flyer
    pdf_links = page.query_selector_all("a[href$='.pdf'], a[href*='.pdf?']")
    if pdf_links:
        pdf_url = pdf_links[0].get_attribute("href") or ""
        log.warning(f"T&T flyer appears to be a PDF: {pdf_url}")
        return [{
            "store": STORE_NAME, "store_key": STORE_KEY,
            "item_name": "T&T Flyer (PDF — manual review required)",
            "raw_price_text": "",
            "price_per_lb": None, "price_per_kg": None, "unit_raw": "",
            "sale_end_date": "",
            "flyer_url": pdf_url or FLYER_URL,
            "scraped_at": scraped_at,
            "scrape_error": "image-based flyer — manual review required",
        }]

    selectors = [
        "[class*='item']", "[class*='product']",
        "[class*='flyer']", "[class*='deal']", "[class*='sale']",
        "li", "article",
    ]
    found_sel = None
    for sel in selectors:
        try:
            elements = page.query_selector_all(sel)
            # Only consider it found if at least one element contains a "$"
            has_price = any("$" in (el.inner_text() or "") for el in elements[:30])
            if has_price:
                found_sel = sel
                log.info(f"DOM: found elements with prices using selector {sel!r}")
                break
        except Exception:
            continue

    if not found_sel:
        log.warning("DOM: no product elements with prices found — T&T flyer may be image-based")
        return [{
            "store": STORE_NAME, "store_key": STORE_KEY,
            "item_name": "T&T Flyer",
            "raw_price_text": "",
            "price_per_lb": None, "price_per_kg": None, "unit_raw": "",
            "sale_end_date": "", "flyer_url": FLYER_URL,
            "scraped_at": scraped_at,
            "scrape_error": "image-based flyer — manual review required",
        }]

    tiles = page.query_selector_all(found_sel)
    for tile in tiles:
        text = tile.inner_text().strip()
        if "$" not in text:
            continue
        lines = [l.strip() for l in text.split("\n") if l.strip() and not re.match(r'^[\u4e00-\u9fff]+$', l.strip())]
        if not lines:
            continue
        # Take the first line that looks like an English name (has at least 2 Latin chars)
        name = ""
        for line in lines:
            if re.search(r'[a-zA-Z]{2,}', line) and "$" not in line:
                name = line
                break
        if not name:
            name = lines[0]

        price_text = ""
        m = re.search(r'\$[\d.]+(?:/(?:lb|kg|100g))?', text, re.IGNORECASE)
        if m:
            price_text = m.group(0)

        if name and len(name) >= 3:
            results.append({
                "store": STORE_NAME, "store_key": STORE_KEY,
                "item_name": name.title(), "raw_price_text": price_text,
                "price_per_lb": None, "price_per_kg": None, "unit_raw": "",
                "sale_end_date": "", "flyer_url": FLYER_URL,
                "scraped_at": scraped_at,
            })

    # Deduplicate by name
    seen = set()
    unique = []
    for it in results:
        k = it["item_name"].lower()
        if k not in seen:
            seen.add(k)
            unique.append(it)
    return unique


def _apply_prices(items):
    sys.path.insert(0, str(TOOLS_DIR))
    from flyer_normalize import normalize_price
    for item in items:
        if item.get("raw_price_text") and not item.get("scrape_error"):
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
    captured_json = None
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
            nonlocal captured_json
            if captured_json:
                return
            try:
                ct = response.headers.get("content-type", "")
                if "json" not in ct:
                    return
                body = response.text()
                if _is_flyer_json(response.url, body):
                    log.info(f"Captured JSON from: {response.url}")
                    captured_json = json.loads(body)
            except Exception:
                pass

        page.on("response", handle_response)
        try:
            page.goto(FLYER_URL, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            log.warning(f"Page load issue: {e}")

        if captured_json:
            items = _extract_items_from_json(captured_json, scraped_at)
            log.info(f"JSON extraction: {len(items)} items")
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
