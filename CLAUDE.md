# Claude Code Together — Project Constitution

> This is the **single source of truth** for the project's data schemas, behavioral rules, and architectural invariants.
> Any schema change, rule addition, or architecture modification **must** be reflected here.

---

## Project Purpose

Automate the manual MLS data workflow for **Brentwood Park, Burnaby North** real estate market analysis.
Primary data source: Paragon MLS (`bcres.paragonrels.com`). Secondary: BC Assessment.
Target workbook: `1VBN - Brentwood Park.xlsx`.

The workflow covers four search types run separately:
| Type | Paragon Status | Search Date field | Notes |
|------|---------------|-------------------|-------|
| Solds | Sold | Last 12 months | Populate A.S.PRINTOUT sold sections |
| Actives | Active | No date filter | Populate A.S.PRINTOUT active section |
| Expired | Expired | begin=last scraped date, end=today | Populate E.DETACHED + A.S.PRINTOUT expired section |
| Terminated/CP | Terminated, Cancel Protected | No date filter | Populate A.S.PRINTOUT T/CP section |

"Search Date" in Paragon = expiry date when status=Expired, sold date when status=Sold.

---

## Data Schemas

### Paragon Scraper — Output Schema (`tools/output/paragon_detached.json`)
```json
[
  {
    "mls_number":       "string  — e.g. R2911387",
    "address":          "string  — e.g. 4824 FAIRLAWN DRIVE",
    "expiry_date":      "string  — e.g. 11/14/2024",
    "list_price":       "string  — e.g. $2,558,000",
    "list_date":        "string  — e.g. 01/15/2024",
    "dom":              "string  — Days on Market",
    "year_built":       "string  — e.g. 1968",
    "lot_size":         "string  — e.g. 6200 sq ft",
    "bedrooms":         "string",
    "bathrooms":        "string",
    "sqft":             "string",
    "kitchens":         "string",
    "sold_price":       "string  — e.g. $2,100,000 (Sold type only; empty for other types)",
    "sold_date":        "string  — e.g. 02/10/2026 (Sold type only; empty for other types)",
    "land_assessment":  "string  — populated by bcassessment_scraper",
    "total_assessment": "string  — populated by bcassessment_scraper",
    "scraped_at":       "ISO 8601 datetime"
  }
]
```

Note: `list_agent` field removed — the S/A code (char10_5__1) is not the agent name.
Owner name/title data is scraped per-listing from the title document link inside each Paragon listing detail page.

**jqGrid field name candidates for sold fields** (confirmed on first Sold scrape run via log):
- `sold_price`: tries `SellingPrice__1`, `SoldPrice__1`, `SalePrice__1` in order
- `sold_date`: tries `SellerAcceptanceDate__1`, `SoldDate__1`, `ClosingDate__1`, `f_865__1` in order
- Check `"jqGrid first row keys"` log line on first Sold run to confirm actual field names.

### Flyer Scraper — Raw Output Schema (`tools/output/flyer_raw_[store].json`)
```json
[
  {
    "store":          "string  — e.g. Save-on-Foods",
    "store_key":      "string  — e.g. saveon",
    "item_name":      "string  — full name from flyer",
    "raw_price_text": "string  — exact DOM text, e.g. '$2.99/lb'",
    "price_per_lb":   "float or null",
    "price_per_kg":   "float or null",
    "unit_raw":       "string  — 'lb', 'kg', '100g', 'each', 'unknown'",
    "sale_end_date":  "string  — ISO date (YYYY-MM-DD) or empty string",
    "flyer_url":      "string",
    "scraped_at":     "ISO 8601 datetime"
  }
]
```

### Flyer Scraper — Classified Output Schema (`tools/output/flyer_classified.json`)
Same as raw schema plus:
```json
[
  {
    "...":         "all fields from raw schema",
    "category":    "string  — Meat/Fish | Vegetables | Fruits | Other",
    "subcategory": "string  — e.g. Beef, Leafy Greens, Citrus (empty string if Other)"
  }
]
```

### BC Assessment Scraper — Output Schema (`tools/output/bcassessment_results.json`)
```json
[
  {
    "address":              "string  — input address passed to the script",
    "land_value":           "string  — e.g. $1,200,000",
    "total_assessed_value": "string  — e.g. $2,150,000",
    "error":                "string  — empty string if successful"
  }
]
```

### Excel — `A.S.PRINTOUT` Sheet Structure

**Row 1:** `A1=Last Scraped Date`, `B1=MM.DD.YY` (e.g. `03.20.26`) — drives all date filters.

**SOLD section (rows 1–23)**
- Rows 5–14: Solds in last 12 months, sorted most-recent-first by Sold Date (`x - S.Date`)
- Row 13: Bold red number = count of solds in last 12 months (cross-reference with MLS)
- Rows 17–23: Solds 12–18 months back (limit: 18 months from last scraped date)
- `List#` column: manual (ignore for automation — not worth the effort)

| Col | Field |
|-----|-------|
| A   | sort flag (`-`) |
| B   | address |
| C   | sold price |
| D   | list price |
| E   | sold date (`x - S.Date`) |
| F   | DOM |
| G   | List# (manual — omit) |
| H   | year built |
| I   | lot size |
| J   | bedrooms |
| K   | bathrooms |
| L   | sqft |
| M   | kitchens (Kitch) |
| N   | land assessment |
| O   | total assessment |
| P   | S vs ASS (sold minus total assessment) |

**ACTIVE section (rows 26–51)**
- All current active detached listings in Brentwood Park, sorted alphabetically by address
- Row 25 (green number): count of active listings
- `D.EXP` = days until listing expires (from today's scrape date); "Expired" if past
- `List#` = manual (omit)

| Col | Field |
|-----|-------|
| A   | sort flag (`-`) |
| B   | address (`x - Address`) |
| C   | expiry date |
| D   | list price |
| E   | list date (L.Date) |
| F   | DOM |
| G   | List# (manual — omit) |
| H   | year built |
| I   | lot size |
| J   | bedrooms |
| K   | bathrooms |
| L   | sqft |
| M   | kitchens |
| N   | land assessment |
| O   | total assessment |
| P   | D.EXP |

**EXPIRED section (rows 54–62)**
- Row 54 (`B54`): Section header — "EXPIRED last 30days", date range based on last scraped date
- Row 55: Column headers
- Rows 56–62: Expired listings in last 30 days

**TERMINATED/CP section (rows 64–70)**
- Row 64: "TERMINATED/CP" header
- Rows 65–70: Terminated and Cancel Protected listings

Expired + T/CP column layout:

| Col | Field |
|-----|-------|
| A   | sort flag (`-`) |
| B   | address |
| C   | expiry date |
| D   | list price |
| E   | list date (L.Date) |
| F   | DOM |
| G   | List# (manual — omit) |
| H   | year built |
| I   | lot size |
| J   | bedrooms |
| K   | bathrooms |
| L   | sqft |
| M   | kitchens |
| N   | land assessment |
| O   | total assessment |
| P   | D.EXP |
| Q   | Contact (manual — leave blank) |
| R   | ML# |
| S   | NAME (owner, from title doc) |
| T   | ADDRESS1 (owner address line 1, from title doc) |
| U   | ADDRESS2 (owner address line 2, from title doc) |
| V   | OCCUP — occupancy: v=vacant, o=owner, t=tenant, ot=owner+tenant (manual — leave blank) |

### Excel — `E.DETACHED` Sheet Structure

Two sections separated by a header row:

**Section 1 — Last 30 Days (dynamic row count)**
- Row 1: Sheet title
- Row 2: Column headers
- Row 3: Section label "EXPIRED: Date Range: [last 30 days range]"
- Rows 4+: Expired listings from last scraped date to today (dynamic — insert however many fit)

**Section 2 — Historical (rows start after section 1)**
- Header row (col headers, same layout)
- Section label "EXPIRED: Date Range: [historical range]"
- All other expired listings sorted by address

Column layout (same as A.S.PRINTOUT expired section plus Notes):

| Col | Field |
|-----|-------|
| A   | sort flag (`-`) |
| B   | Subject Property (address) |
| C   | expiry date |
| D   | list price |
| E   | list date (L.Date) |
| F   | DOM |
| G   | List# (manual — omit) |
| H   | year built (Build) |
| I   | lot size |
| J   | bedrooms |
| K   | bathrooms |
| L   | sqft |
| M   | kitchens |
| N   | land assessment |
| O   | total assessment |
| P   | D.EXP (days until expiry; "Expired" if past) |
| Q   | Contact (manual — leave blank for new rows) |
| R   | ML# |
| S   | NAME (owner, from title doc) |
| T   | ADDRESS1 |
| U   | ADDRESS2 |
| V   | OCCUP (manual — leave blank) |
| W   | Notes (manual — preserve existing; leave blank for new rows) |

---

## Paragon Form Field IDs (Residential Detached)

| Field | Preset select | Low/begin input | High/end input |
|-------|--------------|-----------------|----------------|
| Search Date (= expiry for Expired, sold date for Sold) | `fo_f_476__1` | `f_476_Low__1` | `f_476_High__1` |
| List Date | `fo_f_33__1` | `f_33_Low__1` | `f_33_High__1` |
| Seller's Acceptance Date | `fo_f_865__1` | `f_865_Low` | `f_865_High` |
| Status (autocomplete, acfb pill) | — | `f_11__1` | — |
| Area | — | `f_4__1` | — |
| Sub-Area | — | `f_76__1` | — |
| Search button | `#Search` (class `SearchBtn`, outside `<form>`) | — | — |

**Known form submission rule:** Setting `fo_f_33__1 = '1'` (List Date 24 months) is the required anchor for form submission. Setting `fo_f_476__1` to any value, or using jQuery `datepicker('setDate')` on date inputs, breaks form submission (tab1_1_2 stays about:blank).

**Date filter strategy for Expired search:** Set `fo_f_33__1 = '1'` to anchor submission; scrape all results; post-filter in Python by expiry date >= begin_date.

---

## Behavioral Rules

1. **Deduplicate by MLS#** — `update_sheet.py` must never write a row whose MLS# already exists in the target sheet.
2. **Delay between BC Assessment requests** — minimum 2.5 seconds (configurable via `BCASSESSMENT_DELAY` in `.env`).
3. **Never commit `.env`** — credentials live in `.env` only; `.env.example` is the committed template.
4. **headless=False** for all Playwright scripts until the user explicitly opts into headless mode — manual CAPTCHA / 2FA handling is required. **Exception:** The grocery flyer scrapers (`tools/flyer_scraper_*.py`) respect the `FLYER_HEADLESS` env var (default `true`), as the user has explicitly opted into headless mode for that workflow. Paragon and BC Assessment scrapers remain headless=False.
5. **Outputs are ephemeral** — `tools/output/` is gitignored; JSON files are intermediates, not source of truth.
6. **Manual fields are never overwritten** — Contact, OCCUP, Notes, List# are entered by the user. Automation leaves them blank on new rows and never touches existing values.
7. **D.EXP is calculated at write time** — computed as `(expiry_date - scrape_date).days`; write "Expired" if negative.
8. **Owner/title data** — scraped from the title document linked inside each Paragon listing detail page (turquoise "D" icon). Populated into NAME, ADDRESS1, ADDRESS2 columns.

---

## Architectural Invariants

1. **3-Layer Separation:** Architecture SOPs (`architecture/`) → Navigation (decision routing) → Tools (`tools/`)
2. **Data-First:** No tool is built until its input/output schema is defined in this file
3. **Self-Annealing:** Every error results in a fix, a test, and an architecture SOP update
4. **Deterministic Tools:** Business logic in `tools/` must be deterministic Python — no LLM calls inside tool scripts
5. **Intermediates are ephemeral:** `.tmp/` contents are disposable; only the final payload matters
