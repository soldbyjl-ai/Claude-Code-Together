"""
flyer_debug_urls.py — Diagnostic: log all JSON response URLs from a flyer page.
Usage: python tools/flyer_debug_urls.py <url>
"""
import sys
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, Response

url = sys.argv[1] if len(sys.argv) > 1 else "https://www.saveonfoods.com/sm/planning/rsid/1982/circular"

print(f"Loading: {url}")
print("Waiting 25s after domcontentloaded to capture all API calls...\n")

captured = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
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
            stripped = body.strip()
            if not (stripped.startswith("[") or stripped.startswith("{")):
                return
            size = len(stripped)
            captured.append((size, response.url))
            print(f"  [{size:>8} bytes] {response.url}")
        except Exception:
            pass

    page.on("response", handle_response)

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        print(f"  [WARN] page load: {e}")

    page.wait_for_timeout(25000)

    # Try scrolling to trigger lazy loading
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(5000)

    browser.close()

print(f"\nTotal JSON responses captured: {len(captured)}")
if captured:
    biggest = max(captured, key=lambda x: x[0])
    print(f"Largest response: {biggest[0]} bytes — {biggest[1]}")
