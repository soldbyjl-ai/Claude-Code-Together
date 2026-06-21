"""
paragon_scraper.py
------------------
Logs into Paragon MLS (bcres.paragonrels.com), searches for detached listings
in Brentwood Park, Burnaby North, and scrapes listing details.

Output: JSON file  tools/output/paragon_detached.json

Usage:
    python tools/paragon_scraper.py --type expired      # default
    python tools/paragon_scraper.py --type active
    python tools/paragon_scraper.py --type sold
    python tools/paragon_scraper.py --type terminated

Post-scrape date filters applied per type:
    expired:    expiry_date  in [last_scraped_date, today]
    sold:       sold_date    in [today-18months, today]
    active:     no filter
    terminated: no filter

Notes:
- headless=False so you can handle 2FA / CAPTCHA manually on first run.
- Script pauses at any 2FA prompt and waits for you to complete it.
- Selectors were mapped against Paragon 5.x (BC). If the UI has changed,
  search for TODO comments and update the selectors accordingly.
- On the first Sold run, check the "jqGrid first row keys" log line to confirm
  the actual field names for sold_price and sold_date (see CLAUDE.md).
"""

import argparse
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
load_dotenv()

PARAGON_URL = "https://bcres.paragonrels.com/publink/default.aspx"
PARAGON_LOGIN_URL = "https://bcres.paragonrels.com/ParagonLS/default.mvc"
USERNAME = os.getenv("PARAGON_USERNAME", "")
PASSWORD = os.getenv("PARAGON_PASSWORD", "")

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE = OUTPUT_DIR / "paragon_detached.json"

# How long (seconds) to wait for the 2FA / CAPTCHA page before timing out.
# Set high — you need time to act manually.
MFA_WAIT_SECONDS = 600

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(OUTPUT_DIR / "paragon_scraper.log", mode="a"),
    ],
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def wait_for_manual_step(page, prompt: str, condition_selector: str, timeout: int = MFA_WAIT_SECONDS):
    """Pause and display a prompt; resume when condition_selector appears or timeout."""
    log.warning("=== MANUAL ACTION REQUIRED ===")
    log.warning(prompt)
    log.warning(f"Waiting up to {timeout}s for selector: {condition_selector}")
    try:
        page.wait_for_selector(condition_selector, timeout=timeout * 1000)
        log.info("Manual step completed — continuing.")
    except PWTimeout:
        log.error("Timed out waiting for manual step. Exiting.")
        raise


def clean_text(val) -> str:
    if val is None:
        return ""
    return str(val).strip()


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

def login(page):
    import time as _time

    log.info("Navigating to Paragon…")
    try:
        page.goto(PARAGON_LOGIN_URL, wait_until="domcontentloaded", timeout=45_000)
    except Exception:
        pass

    credentials_submitted = False
    deadline = _time.time() + MFA_WAIT_SECONDS

    log.warning(">>> WATCH THE BROWSER WINDOW — complete any login or SMS prompt <<<")

    while _time.time() < deadline:
        current_url = page.url

        # Success — landed on the dashboard (URL check)
        if "paragonrels.com" in current_url and "auth.realtor.ca" not in current_url:
            log.info(f"Logged in — on {current_url}")
            _time.sleep(2)
            return

        # Success — SAML handoff: URL still on auth.realtor.ca but Paragon UI is loaded.
        # Detect by presence of a Paragon nav/dashboard element.
        try:
            paragon_loaded = page.evaluate("""
                () => {
                    // Paragon nav bar or search form is present
                    return !!(
                        document.querySelector('#pMenu, .pMenu, img[alt*="Paragon"], #divNav') ||
                        document.querySelector('a.SearchByClass1, form.f-form-search') ||
                        (document.title && document.title.toLowerCase().includes('paragon'))
                    );
                }
            """)
            if paragon_loaded:
                log.info(f"Logged in — Paragon UI detected on {current_url}")
                _time.sleep(2)
                return
        except Exception:
            pass

        # Login form visible — fill credentials once
        if not credentials_submitted and "auth.realtor.ca" in current_url:
            try:
                username_input = page.query_selector(
                    'input[name="username"], input[id*="username"], input[id*="Username"]'
                )
                if username_input:
                    page.fill('input[name="username"], input[id*="username"], input[id*="Username"]', USERNAME)
                    page.fill('input[name="password"], input[id*="password"], input[id*="Password"]', PASSWORD)
                    page.click('button[type="submit"], input[type="submit"], #btnLogin')
                    log.info("Credentials submitted.")
                    credentials_submitted = True
            except Exception:
                pass  # page is mid-navigation — keep polling

        _time.sleep(1)

    log.error(f"Login timed out after {MFA_WAIT_SECONDS}s. Current URL: {page.url}")
    raise PWTimeout(f"Login timed out after {MFA_WAIT_SECONDS}s")


# ---------------------------------------------------------------------------
# Search — Expired Detached, Brentwood Park, Burnaby North
# ---------------------------------------------------------------------------

def navigate_to_search(page):
    """
    Navigate via the top nav: hover SEARCH tab -> click Residential Detached.
    The form loads in a Paragon tab (iframe). Stashes the frame on page._search_frame.
    """
    import time as _time

    # The nav bar lives in the outer frame (not HomeTab).
    # Try main page first, then any frame.
    nav_contexts = [page] + [f for f in page.frames if f is not page]

    # Dump all elements in outer frame that contain "Residential Detached" text
    log.info("Scanning outer frame for Residential Detached elements…")
    try:
        rd_elements = page.evaluate("""
            () => {
                const results = [];
                for (const el of document.querySelectorAll('*')) {
                    const t = (el.innerText || el.textContent || '').trim();
                    if (t === 'Residential Detached') {
                        results.push({
                            tag: el.tagName,
                            id: el.id || '',
                            cls: (el.className || '').substring(0, 60),
                            href: el.href || '',
                            rel: el.getAttribute('rel') || '',
                            onclick: (el.getAttribute('onclick') || '').substring(0, 80)
                        });
                    }
                }
                return results;
            }
        """)
        log.info(f"Outer frame RD elements: {rd_elements}")
    except Exception as e:
        log.debug(f"RD scan failed: {e}")
        rd_elements = []

    # Try each found element: navigate via rel URL or JS click
    navigated = False
    for el in (rd_elements or []):
        rel = el.get('rel', '')
        href = el.get('href', '')
        target_url = rel or href
        if target_url and target_url != '#' and 'javascript' not in target_url.lower():
            log.info(f"Navigating to RD URL: {target_url!r}")
            page.goto(target_url, wait_until="domcontentloaded", timeout=20_000)
            navigated = True
            break

    if not navigated:
        # The Residential Detached nav link has class "SearchByClass1" in Paragon.
        # It uses a jQuery click handler (no href/onclick attributes).
        log.info("Attempting JS click on SearchByClass1 (Residential Detached)…")
        try:
            result = page.evaluate("""
                () => {
                    // Prefer the A element with SearchByClass1 class
                    const byClass = document.querySelector('a.SearchByClass1, .SearchByClass1');
                    if (byClass) {
                        byClass.click();
                        return 'SearchByClass1 clicked: ' + byClass.tagName;
                    }
                    // Fallback: any A element with text exactly 'Residential Detached'
                    for (const a of document.querySelectorAll('a')) {
                        if ((a.innerText || a.textContent || '').trim() === 'Residential Detached') {
                            a.click();
                            return 'A clicked by text';
                        }
                    }
                    return null;
                }
            """)
            log.info(f"JS click result: {result!r}")
            navigated = bool(result)
        except Exception as e:
            log.warning(f"JS click failed: {e}")

    if not navigated:
        # Final fallback: hover the SEARCH icon then Playwright-click after 2s
        log.info("Hover + delayed click fallback…")
        for ctx in nav_contexts:
            try:
                ctx.hover('img[alt*="SEARCH"], img[alt*="Search"]', timeout=4_000)
                log.info(f"Hovered SEARCH icon.")
                break
            except Exception:
                continue
        _time.sleep(2)  # wait for dropdown CSS transition
        page.screenshot(path=str(OUTPUT_DIR / "debug_search_menu.png"))
        for ctx in nav_contexts:
            try:
                ctx.click('a:has-text("Residential Detached")', timeout=3_000)
                log.info("Clicked Residential Detached (hover fallback).")
                navigated = True
                break
            except Exception:
                continue
        if not navigated:
            log.error("All nav strategies failed.")
            page.screenshot(path=str(OUTPUT_DIR / "debug_search_menu_fail.png"))

    # Poll for tab1_1_1 to load the search form URL (up to 10s).
    # If tab1_1_1 doesn't load in time, the fallback (unnamed frame with same URL) works fine.
    search_frame = None
    deadline = _time.time() + 10
    log.info("Waiting for tab1_1_1 to load search form (up to 10s)…")
    while _time.time() < deadline:
        for f in page.frames:
            if f.name == 'tab1_1_1' and 'Search/Property' in f.url and 'Index' in f.url:
                search_frame = f
                log.info(f"tab1_1_1 loaded: {f.url!r}")
                break
        if search_frame:
            break
        _time.sleep(1)

    if not search_frame:
        log.warning("tab1_1_1 still not loaded after 60s — logging all frames and using fallback:")
        for f in page.frames:
            log.info(f"  frame name={f.name!r} url={f.url!r}")
        best = max(
            page.frames,
            key=lambda f: len(f.query_selector_all('select[id^="fo_f_"]')),
            default=page
        )
        search_frame = best
        log.warning(f"Using fallback frame: {getattr(best, 'url', 'main')!r} — Search may not submit correctly")

    # Wait for Paragon's autocomplete plugin and jQuery to fully initialize.
    # Without this wait, typing into the autocomplete inputs produces no dropdown.
    log.info("Waiting 3s for Paragon JS to initialize autocomplete…")
    _time.sleep(3)

    page.screenshot(path=str(OUTPUT_DIR / "debug_search_form.png"))
    page._search_frame = search_frame
    log.info(f"Search frame ready: {getattr(search_frame, 'url', 'main')!r}")


def get_printout_date() -> str:
    """
    Read the "Last Scraped Date" from A.S.PRINTOUT!B1 in the Excel file.
    Returns the date as 'MM/DD/YY' (2-digit year) for Paragon's datepicker format.
    Falls back to empty string if unavailable.
    """
    import openpyxl
    from datetime import datetime
    excel_path = Path(__file__).parent.parent / os.getenv("EXCEL_FILE", "1VBN - Brentwood Park.xlsx")
    try:
        wb = openpyxl.load_workbook(str(excel_path), data_only=True)
        ws = wb['A.S.PRINTOUT']
        val = ws['B1'].value
        if not val:
            return ""
        val = str(val).strip()  # e.g. '03.20.26'
        # Parse MM.DD.YY format
        parts = val.split('.')
        if len(parts) == 3:
            mm, dd, yy = parts
            year = int(yy) + 2000 if int(yy) < 100 else int(yy)
            dt = datetime(year, int(mm), int(dd))
            result = dt.strftime('%m/%d/%Y')  # 4-digit year for JS new Date() compat
            log.info(f"Printout date from B1: {val!r} -> {result!r}")
            return result
    except Exception as e:
        log.warning(f"Could not read printout date: {e}")
    return ""


def set_search_filters(page):
    """Fill in status=Expired, area=Burnaby North, neighbourhood=Brentwood Park."""
    frame = getattr(page, '_search_frame', page)
    log.info(f"Setting search filters in frame: {getattr(frame, 'url', 'main')!r}")

    # Dump all selects in the search frame for selector confirmation
    selects = frame.query_selector_all('select')
    log.info(f"Found {len(selects)} select elements in search frame:")
    for s in selects:
        sid   = s.get_attribute('id') or ''
        sname = s.get_attribute('name') or ''
        opts  = [o.get_attribute('value') or '' for o in s.query_selector_all('option')][:8]
        log.info(f"  select id={sid!r} name={sname!r} options={opts}")

    def clear_acfb_pills(field_id: str, label: str):
        """Remove any pre-filled autocomplete pills from an acfb field."""
        try:
            removed = frame.evaluate("""
                (fid) => {
                    const removed = [];
                    // Pills are <li class="acfb-data"> inside <ul class="acfb-holder fid">
                    const holder = document.querySelector('ul.acfb-holder.' + fid + ', ul[class*="acfb-holder"].' + fid);
                    if (!holder) return removed;
                    const pills = holder.querySelectorAll('li.acfb-data');
                    for (const pill of pills) {
                        const text = pill.querySelector('span') ? pill.querySelector('span').textContent.trim() : '';
                        const delBtn = pill.querySelector('img.p');
                        if (delBtn) { delBtn.click(); removed.push(text); }
                    }
                    return removed;
                }
            """, field_id)
            if removed:
                log.info(f"[{label}] Cleared pre-filled pills: {removed}")
                frame.wait_for_timeout(300)
        except Exception as e:
            log.debug(f"[{label}] clear_acfb_pills failed: {e}")

    def autocomplete_fill(field_id: str, value: str, label: str):
        """
        Type into a Paragon autocomplete field and click the first matching suggestion.
        Field IDs use the short form without suffix (e.g. f_11__1, f_76__1).
        """
        inp = f'#{field_id}'
        try:
            frame.click(inp, timeout=5_000, force=True)
            frame.type(inp, value, delay=80)
            frame.wait_for_timeout(1500)  # give the async autocomplete time to render

            page.screenshot(path=str(OUTPUT_DIR / f"debug_{label}.png"))

            # --- 1. Dump visible dropdown items for diagnostics ---
            try:
                dom_items = frame.evaluate("""
                    (search) => {
                        const els = document.querySelectorAll('li.ac_even, li.ac_odd, li[class*="ac_"]');
                        return Array.from(els)
                            .filter(el => el.offsetHeight > 0 &&
                                         el.textContent.trim().toLowerCase().includes(search.toLowerCase()))
                            .map(el => ({
                                tag: el.tagName,
                                cls: el.className.substring(0, 80),
                                text: el.textContent.trim().substring(0, 100)
                            }))
                            .slice(0, 15);
                    }
                """, value)
                if dom_items:
                    log.info(f"[{label}] matching dropdown items: {dom_items}")
                else:
                    log.warning(f"[{label}] no dropdown items found after typing {value!r}")
            except Exception as de:
                log.debug(f"[{label}] DOM dump failed: {de}")

            # --- 2. JS click on ac_even/ac_odd items in the frame ---
            try:
                clicked_text = frame.evaluate("""
                    (search) => {
                        const acItems = document.querySelectorAll('li.ac_even, li.ac_odd, li[class*="ac_"]');
                        for (const el of acItems) {
                            if (el.offsetHeight > 0 &&
                                el.textContent.trim().toLowerCase().includes(search.toLowerCase())) {
                                el.click();
                                return el.textContent.trim();
                            }
                        }
                        return null;
                    }
                """, value)
                if clicked_text:
                    log.info(f"{label} set via JS click (ac_item) -> {clicked_text!r}")
                    frame.wait_for_timeout(400)
                    return True
            except Exception as je:
                log.debug(f"[{label}] JS click in frame failed: {je}")

            # --- 3. JS click in the main page document ---
            try:
                clicked_text = page.evaluate("""
                    (search) => {
                        const acItems = document.querySelectorAll('li.ac_even, li.ac_odd, li[class*="ac_"]');
                        for (const el of acItems) {
                            if (el.offsetHeight > 0 &&
                                el.textContent.trim().toLowerCase().includes(search.toLowerCase())) {
                                el.click();
                                return el.textContent.trim();
                            }
                        }
                        return null;
                    }
                """, value)
                if clicked_text:
                    log.info(f"{label} set via JS click in main page -> {clicked_text!r}")
                    frame.wait_for_timeout(400)
                    return True
            except Exception as je:
                log.debug(f"[{label}] JS click in main page failed: {je}")

            log.warning(f"Could not set {label} = {value!r} — dropdown not found")
            return False

        except Exception as e:
            log.warning(f"Could not set {label}: {e}")
            page.screenshot(path=str(OUTPUT_DIR / f"debug_{label}_fail.png"))
            return False

    # --- Status ---
    # The Status field (f_11__1) is pre-filled with "Active" — always clear first.
    clear_acfb_pills('f_11__1', 'Status')

    search_type = getattr(page, '_search_type', 'expired')
    status_map = {
        'expired':    ['Expired'],
        'active':     ['Active'],
        'sold':       ['Sold'],
        'terminated': ['Terminated', 'Cancel Protected'],
    }
    for status_val in status_map.get(search_type, ['Expired']):
        autocomplete_fill('f_11__1', status_val, f'Status({status_val})')
        frame.wait_for_timeout(300)

    # --- Area = VBN (Burnaby North), SubArea = VBNBP (Brentwood Park) ---
    autocomplete_fill('f_4__1', 'VBN', 'Area')
    frame.wait_for_timeout(500)
    autocomplete_fill('f_76__1', 'VBNBP', 'SubArea')

    # --- Date setup ---
    # Required form submission anchor: fo_f_33__1 = '1' (List Date 24 months).
    # Do NOT set f_476 datepicker — it breaks form submission for fallback frames.
    # All date filtering is done in Python post-scrape.
    frame.wait_for_timeout(500)
    try:
        frame.evaluate("""
            () => {
                const sel = document.querySelector('#fo_f_33__1');
                if (sel) { sel.value = '1'; sel.dispatchEvent(new Event('change', {bubbles: true})); }
            }
        """)
        log.info("List Date preset set to 24 months (form submission anchor).")
    except Exception as e:
        log.warning(f"List Date preset failed: {e}")

    begin_date = get_printout_date()
    end_date   = datetime.now().strftime('%m/%d/%Y')
    log.info(f"Date filter will be applied post-scrape: [{begin_date}, {end_date}]")
    log.info("Search filters set.")



def run_search(page):
    """Click Search and wait for results."""
    import time as _t
    import re as _re
    frame = getattr(page, '_search_frame', page)
    log.info("Running search…")

    # Save search form HTML for button inspection
    try:
        form_html = frame.content()
        with open(OUTPUT_DIR / "search_form.html", "w", encoding="utf-8") as fh:
            fh.write(form_html)
        log.info(f"Search form HTML saved ({len(form_html)} bytes)")

        # Dump all clickable elements that might be Run Search
        run_elements = frame.evaluate("""
            () => {
                const results = [];
                for (const el of document.querySelectorAll('a, button, input[type="submit"], input[type="button"]')) {
                    const t = (el.innerText || el.value || el.textContent || '').trim();
                    if (t.toLowerCase().includes('search') || t.toLowerCase().includes('run')) {
                        results.push({
                            tag: el.tagName, id: el.id || '', cls: (el.className || '').substring(0,60),
                            text: t.substring(0,40), href: el.href || '',
                            type: el.type || '', name: el.name || ''
                        });
                    }
                }
                return results;
            }
        """)
        log.info(f"Run Search candidate elements: {run_elements}")
    except Exception as e:
        log.debug(f"Form HTML dump failed: {e}")

    # "Search" button (id="Search", class="SearchBtn") is outside the form;
    # Paragon's jQuery submits form.f-form-search when it is clicked.
    # Use Playwright's real click (dispatches full mouse events) so jQuery fires.
    clicked = False
    try:
        frame.locator('#Search').scroll_into_view_if_needed(timeout=5_000)
        frame.locator('#Search').click(timeout=5_000, force=True)
        log.info("Search button clicked via Playwright locator (force=True).")
        clicked = True
    except Exception as e:
        log.debug(f"Playwright locator click failed: {e}")

    if not clicked:
        # Fallback: trigger jQuery submit directly on the form
        try:
            result = frame.evaluate("""
                () => {
                    const form = document.querySelector('form.f-form-search');
                    if (!form) return 'form not found';
                    // Try jQuery submit if available
                    if (window.$ && $(form).length) {
                        $(form).submit();
                        return 'jQuery form submitted';
                    }
                    form.submit();
                    return 'native form submitted';
                }
            """)
            log.info(f"Form submit fallback: {result}")
            clicked = True
        except Exception as e:
            log.debug(f"Form submit fallback failed: {e}")

    if not clicked:
        log.error("Could not click Run Search button.")
        page.screenshot(path=str(OUTPUT_DIR / "search_screenshot.png"))
        raise RuntimeError("Run Search button not found.")

    # Wait for search results to load (poll up to 60s)
    # Paragon loads results in frame tab1_1_2 (sibling to search form tab1_1_1)
    context = page.context
    results_context = None
    deadline = _t.time() + 60
    search_id = 'tab1_1'  # derived from search form URL ?searchID=tab1_1

    while _t.time() < deadline:
        _t.sleep(1)
        for f in page.frames:
            url = f.url
            name = f.name or ''
            # Best: ifSpreadsheet frame = the actual jqGrid data frame
            if name == 'ifSpreadsheet' and 'Spreadsheet' in url:
                log.info(f"ifSpreadsheet frame found: name={name!r} url={url!r}")
                results_context = f
                break
            # Good: tab1_1_2 Results.mvc frame
            if name == f'{search_id}_2' and url and url != 'about:blank':
                log.info(f"Results in sibling frame: name={name!r} url={url!r}")
                results_context = f
                break
            # General: any Results frame
            if ('Results' in url or 'Spreadsheet' in url) and 'Index' not in url:
                log.info(f"Results in frame: name={name!r} url={url!r}")
                results_context = f
                break
        if results_context:
            break

    # Log all frame URLs
    log.info(f"Post-search main page URL: {page.url}")
    for f in page.frames:
        log.info(f"  Post-search frame: name={f.name!r} url={f.url!r}")
    log.info(f"Context has {len(context.pages)} page(s).")
    for p in context.pages:
        log.info(f"  Context page: {p.url!r}")

    if not results_context:
        log.warning("No results frame found after 60s — search may have returned 0 results.")
        results_context = page

    page.screenshot(path=str(OUTPUT_DIR / "search_screenshot.png"))
    log.info("Screenshot saved -> tools/output/search_screenshot.png")
    page._results_context = results_context


# ---------------------------------------------------------------------------
# Scrape results
# ---------------------------------------------------------------------------

def get_total_pages(page) -> int:
    """Return number of result pages (1 if pagination not found)."""
    try:
        pager = page.query_selector('.pager, [class*="pagination"], [id*="pager"]')
        if pager:
            text = pager.inner_text()
            # Common Paragon format: "Page 1 of 12"
            import re
            m = re.search(r'of\s+(\d+)', text)
            if m:
                return int(m.group(1))
    except Exception:
        pass
    return 1


def scrape_jqgrid_data(frame) -> list[dict]:
    """
    Use jqGrid's data API (via jQuery) to extract all row data by column name.
    Returns a list of dicts with raw jqGrid column names as keys.
    Falls back to empty list if jqGrid is not available.
    """
    try:
        rows = frame.evaluate("""
            () => {
                if (!window.$ || !$.fn.jqGrid) return null;
                const grid = $('#grid');
                if (!grid.length) return null;
                const ids = grid.jqGrid('getDataIDs');
                return ids.map(id => grid.jqGrid('getRowData', id));
            }
        """)
        if rows:
            log.info(f"jqGrid returned {len(rows)} rows via API")
            if rows:
                log.info(f"jqGrid first row keys: {list(rows[0].keys())}")
                log.info(f"jqGrid first row sample: {dict(list(rows[0].items())[:8])}")
            return rows
    except Exception as e:
        log.debug(f"jqGrid API failed: {e}")
    return []


def map_jqgrid_row(raw: dict) -> dict:
    """
    Map jqGrid field names to the schema fields.
    jqGrid field names from Paragon ML Default Spreadsheet (confirmed from live data).
    Some fields contain HTML — strip tags before returning.
    """
    import re as _re

    def g(key: str) -> str:
        val = raw.get(key, "") or ""
        # Strip any HTML tags (some fields have <a> links wrapping values)
        val = _re.sub(r'<[^>]+>', '', str(val)).strip()
        return clean_text(val)

    # sold_price: Paragon jqGrid field for selling price (confirmed name may vary —
    # logged on first sold run via "jqGrid first row keys" log line above)
    sold_price = (
        g("SellingPrice__1")
        or g("SoldPrice__1")
        or g("SalePrice__1")
    )
    # sold_date: Seller's Acceptance Date — the "Search Date" for Sold status
    sold_date = (
        g("SellerAcceptanceDate__1")
        or g("SoldDate__1")
        or g("ClosingDate__1")
        or g("f_865__1")
    )
    return {
        "mls_number":       g("_DisplayId"),
        "address":          g("Address__1"),
        "expiry_date":      g("ExpirationDate__1"),
        "list_price":       g("AskingPrice__1"),
        "list_date":        g("ListingDate__1"),
        "dom":              g("F_DOM__1"),
        "year_built":       g("int2_2__1"),
        "lot_size":         g("dec_11__1"),
        "bedrooms":         g("int1_4__1"),
        "bathrooms":        g("int1_19__1"),
        "sqft":             g("dec_7__1"),
        "kitchens":         g("int1_8__1"),
        "sold_price":       sold_price,
        "sold_date":        sold_date,
        "land_assessment":  "",
        "total_assessment": "",
        "scraped_at":       datetime.now().isoformat(),
    }


def scrape_listing_row(row) -> dict:
    """Fallback: extract fields from a jqGrid TR element by cell title attributes."""
    cells = row.query_selector_all('td')

    def cell(idx: int) -> str:
        try:
            # jqGrid puts the value in the title attribute or as innerText
            el = cells[idx]
            title = el.get_attribute('title') or ""
            if title:
                return clean_text(title)
            return clean_text(el.inner_text())
        except IndexError:
            return ""

    # Column order from Paragon ML Default Spreadsheet (jqGrid thead th order):
    # 0:? 1:ID 2:DisplayId 3:Status 4:PicCount 5:ML# 6:Pics 7:ListPrice
    # 8:Address 9:DOM 10:ExpiryDate 11:Price 12:YrBlt 13:LotSz 14:TotBR
    # 15:TotBaths 16:TotFlArea 17:#Kitchens 18:ListDate 19:S/A
    return {
        "mls_number":       cell(5),
        "address":          cell(8),
        "expiry_date":      cell(10),
        "list_price":       cell(7),
        "list_date":        cell(18),
        "dom":              cell(9),
        "year_built":       cell(12),
        "lot_size":         cell(13),
        "bedrooms":         cell(14),
        "bathrooms":        cell(15),
        "sqft":             cell(16),
        "kitchens":         cell(17),
        "sold_price":       "",   # not available in TR fallback — use jqGrid API
        "sold_date":        "",
        "land_assessment":  "",
        "total_assessment": "",
        "scraped_at":       datetime.now().isoformat(),
    }


def scrape_listing_detail(page, mls_url: str) -> dict:
    """
    Optionally navigate to the individual listing page to grab fields not
    available in the grid (year_built, lot_size, kitchens, assessments, etc.).
    Returns a dict of extra fields to merge into the row dict.
    """
    extras = {}
    try:
        page.goto(mls_url, wait_until="networkidle", timeout=20_000)

        def field(label: str) -> str:
            """Find a label cell and return the adjacent value cell."""
            try:
                el = page.locator(f'td:has-text("{label}")').first
                sibling = el.locator('xpath=following-sibling::td[1]')
                return clean_text(sibling.inner_text())
            except Exception:
                return ""

        # TODO: verify label strings match your Paragon detail page
        extras["year_built"]  = field("Year Built")
        extras["lot_size"]    = field("Lot Size")
        extras["kitchens"]    = field("Kitchens")
        extras["bedrooms"]    = extras.get("bedrooms") or field("Bedrooms")
        extras["bathrooms"]   = extras.get("bathrooms") or field("Bathrooms")
        extras["sqft"]        = extras.get("sqft") or field("Floor Area")
    except Exception as e:
        log.warning(f"Could not scrape detail page {mls_url}: {e}")
    return extras


def scrape_results_page(page) -> list[dict]:
    """Scrape all listing rows from the jqGrid results page."""
    listings = []

    # --- Strategy 1: jqGrid data API (most reliable — column names, not indices) ---
    raw_rows = scrape_jqgrid_data(page)
    if raw_rows:
        for raw in raw_rows:
            try:
                data = map_jqgrid_row(raw)
                if data.get("mls_number"):
                    listings.append(data)
            except Exception as e:
                log.warning(f"Error mapping jqGrid row: {e}")
        if listings:
            log.info(f"Scraped {len(listings)} listings via jqGrid API.")
            return listings
        else:
            log.warning("jqGrid API returned rows but mapping produced no valid listings.")

    # --- Strategy 2: TR element scraping with corrected column indices ---
    log.info("Falling back to TR element scraping…")
    rows = page.query_selector_all('table[id*="grid"] tbody tr, #grid tbody tr, tbody tr')
    if not rows:
        log.warning("No rows found with any selector.")
        return listings
    log.info(f"Using TR fallback -> {len(rows)} rows")
    for row in rows:
        try:
            data = scrape_listing_row(row)
            if data.get("mls_number") and not data["mls_number"].isdigit():
                listings.append(data)
        except Exception as e:
            log.warning(f"Error scraping row: {e}")

    log.info(f"Scraped {len(listings)} listings from {len(rows)} rows.")
    return listings


def scrape_all_pages(page) -> list[dict]:
    """Iterate through all result pages and collect listings."""
    ctx = getattr(page, '_results_context', page)
    log.info(f"Scraping results from context: {getattr(ctx, 'url', 'main page')!r}")

    # The results frame (tab1_1_2 / Results.mvc) wraps an ifSpreadsheet child frame
    # that contains the actual listing data. Prefer that child frame.
    spreadsheet_frame = None
    for f in page.frames:
        if f.name == 'ifSpreadsheet' and 'Spreadsheet' in f.url:
            spreadsheet_frame = f
            log.info(f"ifSpreadsheet frame found: {f.url!r}")
            # Save it for inspection
            try:
                ss_html = f.content()
                with open(OUTPUT_DIR / "spreadsheet.html", "w", encoding="utf-8") as fh:
                    fh.write(ss_html)
                log.info(f"Spreadsheet HTML saved ({len(ss_html)} bytes)")
            except Exception:
                pass
            break
    if spreadsheet_frame:
        ctx = spreadsheet_frame

    all_listings = []
    total_pages = get_total_pages(ctx)
    log.info(f"Total result pages: {total_pages}")

    for page_num in range(1, total_pages + 1):
        log.info(f"Scraping page {page_num}/{total_pages}…")
        listings = scrape_results_page(ctx)
        all_listings.extend(listings)

        if page_num < total_pages:
            try:
                ctx.click('a:has-text("Next"), [aria-label="Next page"], .next-page', timeout=10_000)
                ctx.wait_for_load_state("networkidle", timeout=20_000)
            except PWTimeout:
                log.warning("Could not navigate to next page — stopping pagination.")
                break

    log.info(f"Total listings scraped: {len(all_listings)}")
    return all_listings


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

PROFILE_DIR = Path(__file__).parent / "browser_profile"


def main():
    parser = argparse.ArgumentParser(description="Scrape Paragon MLS listings.")
    parser.add_argument(
        "--type",
        choices=["expired", "active", "sold", "terminated"],
        default="expired",
        help="Search type (default: expired)",
    )
    args = parser.parse_args()
    search_type = args.type

    if not USERNAME or not PASSWORD:
        log.error("PARAGON_USERNAME and PARAGON_PASSWORD must be set in .env")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    first_run = not any(PROFILE_DIR.iterdir())
    if first_run:
        log.info("First run — browser profile is empty. You will need to complete 2FA once.")
        log.info("After that, the session is saved and 2FA won't be needed again.")
    else:
        log.info("Reusing saved browser session (no 2FA expected).")

    log.info(f"Search type: {search_type}")

    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            slow_mo=200,
            viewport={"width": 1400, "height": 900},
        )
        page = context.new_page()
        page._search_type = search_type   # stash for set_search_filters()

        try:
            login(page)
            navigate_to_search(page)
            set_search_filters(page)
            run_search(page)
            listings = scrape_all_pages(page)
        except Exception as e:
            log.error(f"Fatal error: {e}")
            try:
                page.screenshot(path=str(OUTPUT_DIR / "error_screenshot.png"))
                log.info("Screenshot saved to tools/output/error_screenshot.png")
            except Exception:
                pass
            raise
        finally:
            context.close()

    # Post-scrape date filter — applied differently per type:
    # expired:    expiry_date  in [last_scraped_date, today]
    # sold:       sold_date    in [today-18months, today]
    # active:     no filter
    # terminated: no filter
    begin_str = get_printout_date()   # 'MM/DD/YYYY' from A.S.PRINTOUT!B1
    end_str   = datetime.now().strftime('%m/%d/%Y')

    if search_type == "expired":
        log.info(f"Post-scrape filter: expiry_date in [{begin_str}, {end_str}]")
        filtered = filter_by_expiry_date(listings, begin_str, end_str)
    elif search_type == "sold":
        # Keep last 18 months of solds
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=548)).strftime('%m/%d/%Y')  # ~18 months
        log.info(f"Post-scrape filter: sold_date in [{cutoff}, {end_str}]")
        filtered = filter_by_sold_date(listings, cutoff, end_str)
    else:
        # active, terminated: no date filter
        filtered = listings

    log.info(f"Listings after filter: {len(filtered)} of {len(listings)}")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(filtered, f, indent=2, ensure_ascii=False)
    log.info(f"Saved {len(filtered)} listings -> {OUTPUT_FILE}")


def filter_by_sold_date(listings: list[dict], begin_str: str, end_str: str) -> list[dict]:
    """
    Return listings whose sold_date falls within [begin_str, end_str].
    Listings with no sold_date are kept (field may not be mapped yet on first run).
    """
    from datetime import datetime as _dt
    def parse(s):
        for fmt in ('%m/%d/%Y', '%m/%d/%y', '%Y-%m-%d'):
            try:
                return _dt.strptime(s.strip(), fmt)
            except Exception:
                pass
        return None

    begin = parse(begin_str)
    end   = parse(end_str)
    if not begin or not end:
        return listings

    result = []
    for row in listings:
        sd = parse(str(row.get('sold_date', '')))
        if sd is None:
            result.append(row)   # keep if sold_date unparseable / missing
            continue
        if begin <= sd <= end:
            result.append(row)
    return result


def filter_by_expiry_date(listings: list[dict], begin_str: str, end_str: str) -> list[dict]:
    """
    Return listings whose expiry_date falls on or after begin_str and on or before end_str.
    Both date strings are 'MM/DD/YYYY'. Listings with unparseable expiry dates are kept.
    """
    from datetime import datetime as _dt
    def parse(s):
        for fmt in ('%m/%d/%Y', '%m/%d/%y', '%Y-%m-%d'):
            try:
                return _dt.strptime(s.strip(), fmt)
            except Exception:
                pass
        return None

    begin = parse(begin_str)
    end   = parse(end_str)
    if not begin or not end:
        log.warning(f"Could not parse filter dates ({begin_str!r}, {end_str!r}) — returning all listings.")
        return listings

    result = []
    for row in listings:
        exp = parse(str(row.get('expiry_date', '')))
        if exp is None:
            result.append(row)  # keep unparseable
            continue
        if begin <= exp <= end:
            result.append(row)
    return result


if __name__ == "__main__":
    main()
