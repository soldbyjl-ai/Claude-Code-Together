"""
flyer_normalize.py — Pure price parsing and unit normalization functions.
No I/O side effects. Safe to import and call in any context.

Conversion: 1 kg = 2.20462 lb
"""

import re

KG_PER_LB = 0.453592   # 1 lb in kg
LB_PER_KG = 2.20462    # 1 kg in lb

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def normalize_price(raw_price_text: str) -> dict:
    """
    Parse a raw price string from a grocery flyer and return normalized values.

    Returns a dict with keys:
        price_per_lb  : float | None
        price_per_kg  : float | None
        unit_raw      : str  ('lb', 'kg', '100g', 'each', 'unknown')
        parse_error   : bool

    Never raises. On any failure, price_per_lb and price_per_kg are None and
    parse_error is True.

    Examples:
        "$2.99/lb"          -> per_lb=2.99,  per_kg=6.59
        "$13.18/kg"         -> per_lb=5.98,  per_kg=13.18
        "$1.50/100g"        -> per_lb=3.03,  per_kg=15.00
        "2 for $5"          -> per_lb=None,  per_kg=None,  unit="each"  (no weight unit)
        "2 for $5.98/kg"    -> per_lb=1.36,  per_kg=2.99
        "$4.99"             -> per_lb=None,  per_kg=None,  unit="each"
        "$4.99 ea"          -> per_lb=None,  per_kg=None,  unit="each"
        "save $1 on $6.99/kg" -> per_lb=1.59, per_kg=6.99  (extracts first valid price)
    """
    try:
        return _parse(raw_price_text.strip())
    except Exception:
        return _error_result()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _error_result() -> dict:
    return {"price_per_lb": None, "price_per_kg": None, "unit_raw": "unknown", "parse_error": True}


def _result(per_lb, per_kg, unit_raw) -> dict:
    return {
        "price_per_lb": round(per_lb, 2) if per_lb is not None else None,
        "price_per_kg": round(per_kg, 2) if per_kg is not None else None,
        "unit_raw": unit_raw,
        "parse_error": False,
    }


def _parse(text: str) -> dict:
    # Normalise text: lowercase, collapse whitespace
    t = text.lower()
    t = re.sub(r'\s+', ' ', t)

    # -----------------------------------------------------------------------
    # 1. Extract multi-unit prefix: "2 for", "3/$", "2/$", "3 for", etc.
    # -----------------------------------------------------------------------
    multi_qty = 1
    multi_match = re.match(r'^(\d+)\s*(?:for|/)\s*\$?', t)
    if multi_match:
        multi_qty = int(multi_match.group(1))
        t = t[multi_match.end():]  # strip prefix, remainder is "X.XX/unit ..."

    # -----------------------------------------------------------------------
    # 2. Find price amount — first $X.XX or plain X.XX in the remaining text
    # -----------------------------------------------------------------------
    price_match = re.search(r'\$?([\d]+(?:\.[\d]{1,2})?)', t)
    if not price_match:
        return _error_result()
    price_value = float(price_match.group(1)) / multi_qty

    # -----------------------------------------------------------------------
    # 3. Detect unit after price or anywhere in string
    # -----------------------------------------------------------------------
    # Order matters: check /100g before /kg to avoid partial match
    if re.search(r'/\s*100\s*g', t):
        per_kg = price_value * 10
        return _result(per_kg * KG_PER_LB, per_kg, "100g")

    if re.search(r'/\s*kg', t):
        per_kg = price_value
        return _result(per_kg * KG_PER_LB, per_kg, "kg")

    if re.search(r'/\s*lb', t):
        per_lb = price_value
        return _result(per_lb, per_lb / KG_PER_LB, "lb")

    # No weight unit found -> treat as per-each
    return _result(None, None, "each")


# ---------------------------------------------------------------------------
# Quick smoke-test (run directly: python tools/flyer_normalize.py)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    cases = [
        ("$2.99/lb",            {"price_per_lb": 2.99,  "price_per_kg": 6.59,  "unit_raw": "lb"}),
        ("$13.18/kg",           {"price_per_lb": 5.98,  "price_per_kg": 13.18, "unit_raw": "kg"}),
        ("$1.50/100g",          {"price_per_lb": 6.80,  "price_per_kg": 15.00, "unit_raw": "100g"}),
        ("2 for $5.98/kg",      {"price_per_lb": 1.36,  "price_per_kg": 2.99,  "unit_raw": "kg"}),
        ("3 for $9.99/lb",      {"price_per_lb": 3.33,  "price_per_kg": 7.34,  "unit_raw": "lb"}),
        ("$4.99",               {"price_per_lb": None,  "price_per_kg": None,  "unit_raw": "each"}),
        ("$4.99 ea",            {"price_per_lb": None,  "price_per_kg": None,  "unit_raw": "each"}),
        ("2 for $5",            {"price_per_lb": None,  "price_per_kg": None,  "unit_raw": "each"}),
        ("garbage text !!",     {"price_per_lb": None,  "price_per_kg": None,  "unit_raw": "unknown"}),
        ("$19.99/kg save $2",   {"price_per_lb": 9.07,  "price_per_kg": 19.99, "unit_raw": "kg"}),
    ]

    passed = 0
    for raw, expected in cases:
        result = normalize_price(raw)
        def _matches(result_val, expected_val):
            if expected_val is None:
                return result_val is None
            if isinstance(expected_val, float):
                return abs((result_val or 0) - expected_val) < 0.02
            return result_val == expected_val

        ok = all(_matches(result.get(k), v) for k, v in expected.items())
        status = "PASS" if ok else "FAIL"
        if not ok:
            print(f"  {status}  {raw!r}")
            print(f"         expected: {expected}")
            print(f"         got:      {result}")
        else:
            print(f"  {status}  {raw!r}")
        passed += ok

    print(f"\n{passed}/{len(cases)} tests passed")
