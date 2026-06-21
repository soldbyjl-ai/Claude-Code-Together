"""
flyer_report.py — Generate a self-contained HTML price-comparison report from
                  the classified flyer data in tools/output/flyer_classified.json.

Output: tools/output/flyer_report_YYYY-MM-DD.html
Usage:  python tools/flyer_report.py [--open]
"""

import argparse
import json
import sys
import webbrowser
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

TOOLS_DIR = Path(__file__).parent
OUTPUT_DIR = TOOLS_DIR / "output"
CLASSIFIED_FILE = OUTPUT_DIR / "flyer_classified.json"

# Store display names and badge colours (background, text)
STORE_STYLES = {
    "saveon":       ("Save-On-Foods",          "#00843D", "#fff"),
    "safeway":      ("Safeway",                "#C8102E", "#fff"),
    "walmart":      ("Walmart",                "#0071CE", "#fff"),
    "tnt":          ("T&T",                    "#E31837", "#fff"),
    "superstore":   ("Real Cdn Superstore",    "#CC0000", "#fff"),
    "cocowest":     ("Costco",                 "#005DAA", "#fff"),
}

CATEGORIES = ["Meat/Fish", "Vegetables", "Fruits"]
CATEGORY_ICONS = {"Meat/Fish": "🥩", "Vegetables": "🥦", "Fruits": "🍎"}

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: #f5f5f5; color: #222; font-size: 14px; }
.page-wrap { max-width: 1100px; margin: 0 auto; padding: 16px; }

/* Header */
.report-header { background: #1a1a2e; color: #fff; padding: 24px 28px;
                 border-radius: 8px; margin-bottom: 20px; }
.report-header h1 { font-size: 22px; font-weight: 700; }
.report-header .meta { margin-top: 6px; font-size: 13px; opacity: 0.75; }

/* Tab system (pure CSS, no JS) */
.tab-input { display: none; }
.tab-bar { display: flex; gap: 6px; margin-bottom: 16px; flex-wrap: wrap; }
.tab-label { padding: 8px 18px; border-radius: 6px; cursor: pointer;
             background: #ddd; font-weight: 600; font-size: 13px;
             border: 2px solid transparent; user-select: none; }
.tab-label:hover { background: #ccc; }
#tab-all:checked   ~ .tab-bar label[for="tab-all"],
#tab-meat:checked  ~ .tab-bar label[for="tab-meat"],
#tab-veg:checked   ~ .tab-bar label[for="tab-veg"],
#tab-fruit:checked ~ .tab-bar label[for="tab-fruit"] {
  background: #1a1a2e; color: #fff; border-color: #1a1a2e; }

/* Tab content visibility */
.tab-content { display: none; }
#tab-all:checked   ~ .tab-content.all   { display: block; }
#tab-meat:checked  ~ .tab-content.meat  { display: block; }
#tab-veg:checked   ~ .tab-content.veg   { display: block; }
#tab-fruit:checked ~ .tab-content.fruit { display: block; }

/* Category sections */
.category-section { margin-bottom: 28px; }
.category-title { font-size: 17px; font-weight: 700; padding: 10px 14px;
                  background: #2d2d2d; color: #fff; border-radius: 6px 6px 0 0; }

/* Subcategory */
.subcat-block { background: #fff; border: 1px solid #e0e0e0;
                border-top: none; margin-bottom: 1px; }
.subcat-title { padding: 8px 14px; font-weight: 600; font-size: 13px;
                background: #f0f0f0; border-bottom: 1px solid #e0e0e0; color: #444; }

/* Comparison table */
.compare-table { width: 100%; border-collapse: collapse; }
.compare-table th { padding: 7px 10px; text-align: left; font-size: 12px;
                    text-transform: uppercase; letter-spacing: 0.03em;
                    background: #fafafa; border-bottom: 2px solid #e0e0e0;
                    color: #666; white-space: nowrap; }
.compare-table td { padding: 8px 10px; border-bottom: 1px solid #f0f0f0;
                    vertical-align: middle; }
.compare-table tr:last-child td { border-bottom: none; }
.compare-table tr:hover td { background: #fafff8; }
.compare-table td.price-lb, .compare-table td.price-kg { font-weight: 600; white-space: nowrap; }
.compare-table td.na { color: #bbb; }
.compare-table tr.best-price td.price-kg { color: #1a7a3c; }
.compare-table tr.best-price td { background: #f0fff4; }
.compare-table .item-name { max-width: 240px; }

/* Store badge */
.store-badge { display: inline-block; padding: 2px 8px; border-radius: 4px;
               font-size: 11px; font-weight: 700; white-space: nowrap; }

/* Flyer link */
.flyer-link { color: #0057b8; text-decoration: none; font-size: 13px; }
.flyer-link:hover { text-decoration: underline; }

/* End date */
.end-date { font-size: 12px; color: #777; white-space: nowrap; }

/* Footer */
.report-footer { margin-top: 24px; padding: 16px 20px; background: #fff;
                 border-radius: 6px; border: 1px solid #e0e0e0; font-size: 12px;
                 color: #666; }
.report-footer h3 { font-size: 13px; margin-bottom: 8px; color: #333; }
.footer-row { display: flex; gap: 24px; flex-wrap: wrap; }
.footer-item { min-width: 160px; }
.scrape-ok { color: #1a7a3c; font-weight: 600; }
.scrape-err { color: #c0392b; font-weight: 600; }

/* No items message */
.no-items { padding: 16px; color: #999; font-style: italic; font-size: 13px; }

@media print {
  .tab-bar { display: none; }
  .tab-content { display: block !important; }
  .report-header { background: #fff; color: #000; border: 2px solid #000; }
  body { background: #fff; }
}
"""

# ---------------------------------------------------------------------------
# Build report
# ---------------------------------------------------------------------------

def _fmt_price(val) -> str:
    if val is None:
        return "—"
    return f"${val:.2f}"


def _store_badge(store_key: str, store_name: str) -> str:
    bg, fg = STORE_STYLES.get(store_key, ("#555", "#fff"))[1:]
    display = STORE_STYLES.get(store_key, (store_name,))[0]
    return f'<span class="store-badge" style="background:{bg};color:{fg}">{display}</span>'


def _build_table(item_group: list[dict]) -> str:
    """Build a <table> comparing items with the same item_name across stores."""
    # Sort by price_per_kg asc (None / each items go to bottom)
    def sort_key(it):
        kg = it.get("price_per_kg")
        return (1 if kg is None else 0, kg or 0)

    sorted_items = sorted(item_group, key=sort_key)

    # Find best (lowest) per-kg price
    best_kg = None
    for it in sorted_items:
        kg = it.get("price_per_kg")
        if kg is not None:
            best_kg = kg if best_kg is None else min(best_kg, kg)

    rows = []
    for it in sorted_items:
        store_key = it.get("store_key", "")
        store_name = it.get("store", store_key)
        item_name = it.get("item_name", "")
        per_lb = it.get("price_per_lb")
        per_kg = it.get("price_per_kg")
        unit = it.get("unit_raw", "")
        end_date = it.get("sale_end_date", "")
        flyer_url = it.get("flyer_url", "#")

        is_best = (per_kg is not None and best_kg is not None and
                   abs(per_kg - best_kg) < 0.01)
        row_class = ' class="best-price"' if is_best else ""

        lb_cell = (f'<td class="price-lb">{_fmt_price(per_lb)}/lb</td>'
                   if per_lb is not None else '<td class="price-lb na">—</td>')
        kg_cell = (f'<td class="price-kg">{_fmt_price(per_kg)}/kg</td>'
                   if per_kg is not None else '<td class="price-kg na">—</td>')
        if unit == "each":
            # Show a combined "each" price in the lb column, kg stays —
            raw = it.get("raw_price_text", "")
            lb_cell = f'<td class="price-lb">{raw or "each"}</td>'
            kg_cell = '<td class="price-kg na">each</td>'

        end_cell = (f'<td class="end-date">{end_date}</td>'
                    if end_date else '<td class="end-date na">—</td>')

        badge = _store_badge(store_key, store_name)
        link = f'<a class="flyer-link" href="{flyer_url}" target="_blank">View ↗</a>'

        rows.append(
            f'<tr{row_class}>'
            f'<td class="item-name">{item_name}</td>'
            f'<td>{badge}</td>'
            f'{lb_cell}{kg_cell}'
            f'{end_cell}'
            f'<td>{link}</td>'
            f'</tr>'
        )

    header = (
        '<thead><tr>'
        '<th>Item</th><th>Store</th>'
        '<th>$/lb</th><th>$/kg</th>'
        '<th>Sale Ends</th><th>Link</th>'
        '</tr></thead>'
    )
    return f'<table class="compare-table">{header}<tbody>{"".join(rows)}</tbody></table>'


def _build_category_html(category: str, items: list[dict]) -> str:
    if not items:
        return ""

    # Group by subcategory, then by normalised item name within each subcat
    subcat_groups: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for it in items:
        sub = it.get("subcategory") or "Other"
        name_key = it.get("item_name", "").lower().strip()
        subcat_groups[sub][name_key].append(it)

    subcat_html = []
    for subcat, name_groups in subcat_groups.items():
        tables = []
        for name_key, group in name_groups.items():
            tables.append(_build_table(group))
        subcat_html.append(
            f'<div class="subcat-block">'
            f'<div class="subcat-title">{subcat}</div>'
            + "".join(tables) +
            f'</div>'
        )

    icon = CATEGORY_ICONS.get(category, "")
    return (
        f'<div class="category-section">'
        f'<div class="category-title">{icon} {category}</div>'
        + "".join(subcat_html) +
        f'</div>'
    )


def _build_footer(all_items: list[dict]) -> str:
    # Per-store scrape stats
    store_stats: dict[str, dict] = {}
    for it in all_items:
        sk = it.get("store_key", "unknown")
        sn = it.get("store", sk)
        if sk not in store_stats:
            store_stats[sk] = {"name": sn, "count": 0, "scraped_at": it.get("scraped_at", ""),
                               "error": it.get("scrape_error", "")}
        if not it.get("scrape_error"):
            store_stats[sk]["count"] += 1

    rows = []
    for sk, st in store_stats.items():
        badge = _store_badge(sk, st["name"])
        if st["error"]:
            status = f'<span class="scrape-err">Error: {st["error"]}</span>'
        else:
            ts = st["scraped_at"][:16].replace("T", " ") if st["scraped_at"] else "—"
            status = f'<span class="scrape-ok">{st["count"]} items</span> · scraped {ts}'
        rows.append(f'<div class="footer-item">{badge}<br>{status}</div>')

    return (
        '<div class="report-footer">'
        '<h3>Scrape Summary</h3>'
        '<div class="footer-row">' + "".join(rows) + '</div>'
        '</div>'
    )


def generate_report(classified_file: Path = CLASSIFIED_FILE,
                    output_file: Path | None = None) -> Path:
    """
    Read flyer_classified.json, build and write the HTML report.
    Returns the path of the written file.
    """
    if not classified_file.exists():
        print(f"[ERROR] {classified_file} not found. Run flyer_run_all.py first.", file=sys.stderr)
        sys.exit(1)

    all_items = json.loads(classified_file.read_text(encoding="utf-8"))
    today = date.today().isoformat()

    if output_file is None:
        output_file = OUTPUT_DIR / f"flyer_report_{today}.html"

    # Split by category
    cat_items: dict[str, list] = {c: [] for c in CATEGORIES}
    for it in all_items:
        cat = it.get("category", "Other")
        if cat in cat_items:
            cat_items[cat].append(it)

    total_items = sum(len(v) for v in cat_items.values())
    store_count = len({it.get("store_key") for it in all_items if not it.get("scrape_error")})
    generated_at = datetime.now().strftime("%A %b %d, %Y at %H:%M")

    # Build content for each category tab + the combined "All" tab
    meat_html  = _build_category_html("Meat/Fish",   cat_items["Meat/Fish"])
    veg_html   = _build_category_html("Vegetables",  cat_items["Vegetables"])
    fruit_html = _build_category_html("Fruits",      cat_items["Fruits"])
    all_html   = meat_html + veg_html + fruit_html
    footer_html = _build_footer(all_items)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Metro Vancouver Grocery Deals — {today}</title>
<style>{CSS}</style>
</head>
<body>
<div class="page-wrap">

  <div class="report-header">
    <h1>Metro Vancouver Grocery Deals</h1>
    <div class="meta">Week of {today} &nbsp;·&nbsp; {store_count} stores &nbsp;·&nbsp; {total_items} sale items found &nbsp;·&nbsp; Generated {generated_at}</div>
  </div>

  <input type="radio" class="tab-input" name="tabs" id="tab-all" checked>
  <input type="radio" class="tab-input" name="tabs" id="tab-meat">
  <input type="radio" class="tab-input" name="tabs" id="tab-veg">
  <input type="radio" class="tab-input" name="tabs" id="tab-fruit">

  <div class="tab-bar">
    <label class="tab-label" for="tab-all">All ({total_items})</label>
    <label class="tab-label" for="tab-meat">🥩 Meat / Fish ({len(cat_items["Meat/Fish"])})</label>
    <label class="tab-label" for="tab-veg">🥦 Vegetables ({len(cat_items["Vegetables"])})</label>
    <label class="tab-label" for="tab-fruit">🍎 Fruits ({len(cat_items["Fruits"])})</label>
  </div>

  <div class="tab-content all">
    {all_html if all_html.strip() else '<p class="no-items">No items found in any focus category.</p>'}
  </div>
  <div class="tab-content meat">
    {meat_html if meat_html.strip() else '<p class="no-items">No Meat/Fish items found this week.</p>'}
  </div>
  <div class="tab-content veg">
    {veg_html if veg_html.strip() else '<p class="no-items">No Vegetable items found this week.</p>'}
  </div>
  <div class="tab-content fruit">
    {fruit_html if fruit_html.strip() else '<p class="no-items">No Fruit items found this week.</p>'}
  </div>

  {footer_html}

</div>
</body>
</html>"""

    output_file.write_text(html, encoding="utf-8")
    print(f"[flyer_report] Wrote report -> {output_file}")
    return output_file


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate HTML grocery flyer report")
    parser.add_argument("--open", action="store_true", help="Open report in default browser after generating")
    args = parser.parse_args()

    report_path = generate_report()
    if args.open:
        webbrowser.open(report_path.as_uri())
