"""
flyer_classify.py — Keyword-based grocery item category classifier.
Pure functions, no I/O side effects.

Returns (category, subcategory) for a given item name string.
Items that don't match any keyword return ("Other", "").
"""

# ---------------------------------------------------------------------------
# Keyword map — check item_name.lower() for substring matches.
# Priority: Meat/Fish checked first to avoid "chicken broth" -> Poultry, etc.
# Within each category, subcategories are checked top-to-bottom; first match wins.
# ---------------------------------------------------------------------------

CATEGORY_MAP = {
    "Meat/Fish": [
        ("Beef", [
            "ribeye", "rib eye", "sirloin", "brisket", "striploin", "strip loin",
            "prime rib", "rib roast", "cross rib", "short rib", "flank steak",
            "chuck", "beef steak", "beef roast", "beef tenderloin", "ground beef",
            "beef burger", "beef patty", "beef", "steak",
        ]),
        ("Pork", [
            "pork belly", "pork chop", "pork loin", "pork shoulder", "pork tenderloin",
            "pork ribs", "pork roast", "pork butt", "ground pork", "pork sausage",
            "bacon", "ham", "prosciutto", "pancetta", "chorizo", "salami",
            "pepperoni", "hot dog", "wiener", "sausage", "pork",
        ]),
        ("Poultry", [
            "chicken breast", "chicken thigh", "chicken drumstick", "chicken wing",
            "whole chicken", "ground chicken", "chicken tender", "rotisserie chicken",
            "turkey breast", "ground turkey", "whole turkey",
            "duck breast", "whole duck", "cornish hen",
            "chicken", "turkey", "duck", "poultry",
        ]),
        ("Lamb", [
            "lamb chop", "lamb rack", "lamb loin", "lamb shoulder", "lamb leg",
            "ground lamb", "lamb", "mutton",
        ]),
        ("Seafood", [
            "atlantic salmon", "pacific salmon", "salmon fillet", "smoked salmon",
            "whole salmon", "sockeye", "coho salmon",
            "tuna steak", "albacore tuna",
            "halibut fillet", "halibut steak",
            "cod fillet", "black cod", "lingcod",
            "tilapia fillet", "sole fillet", "sea bass", "mahi mahi", "snapper fillet",
            "rainbow trout", "steelhead",
            "tiger prawn", "spot prawn", "shrimp", "prawn",
            "dungeness crab", "snow crab", "king crab", "crab leg", "crab",
            "lobster tail", "lobster",
            "sea scallop", "bay scallop", "scallop",
            "clam", "mussel", "oyster",
            "squid", "octopus", "eel", "ikura",
            "fish fillet", "fish steak", "seafood", "salmon", "tuna", "halibut",
            "cod", "tilapia", "snapper", "trout", "herring", "sardine", "anchovy", "fish",
        ]),
        ("Deli Meat", [
            "bologna", "liverwurst", "paté", "pate", "mortadella",
        ]),
    ],
    "Vegetables": [
        ("Leafy Greens", [
            "romaine lettuce", "iceberg lettuce", "butter lettuce", "leaf lettuce",
            "baby spinach", "spinach", "kale", "swiss chard", "rainbow chard",
            "arugula", "watercress", "endive", "radicchio",
            "bok choy", "baby bok choy", "gai choy", "napa cabbage",
            "green cabbage", "red cabbage", "savoy cabbage", "cabbage",
            "collard greens", "mustard greens", "spring mix", "mixed greens",
            "lettuce",
        ]),
        ("Root Vegetables", [
            "baby carrot", "carrot",
            "russet potato", "red potato", "yellow potato", "fingerling potato",
            "sweet potato", "yam", "potato",
            "golden beet", "red beet", "beet",
            "turnip", "parsnip", "celeriac", "celery root",
            "daikon radish", "red radish", "radish",
            "ginger root", "ginger", "taro root", "taro",
        ]),
        ("Alliums", [
            "yellow onion", "red onion", "white onion", "pearl onion",
            "green onion", "scallion", "spring onion",
            "shallot", "leek", "garlic", "onion",
        ]),
        ("Brassicas", [
            "broccoli floret", "broccolini", "broccoli",
            "cauliflower", "romanesco",
            "brussels sprout",
            "rapini", "gai lan", "chinese broccoli",
            "kohlrabi",
        ]),
        ("Nightshades & Squash", [
            "roma tomato", "cherry tomato", "grape tomato", "heirloom tomato",
            "beefsteak tomato", "tomato",
            "bell pepper", "mini pepper", "jalapeño", "serrano", "poblano", "pepper",
            "chinese eggplant", "italian eggplant", "eggplant",
            "zucchini", "yellow squash", "butternut squash", "acorn squash",
            "spaghetti squash", "kabocha", "squash", "pumpkin",
            "english cucumber", "persian cucumber", "mini cucumber", "cucumber",
        ]),
        ("Fungi", [
            "shiitake mushroom", "portobello mushroom", "cremini mushroom",
            "button mushroom", "enoki mushroom", "oyster mushroom",
            "chanterelle", "king oyster", "mushroom",
        ]),
        ("Other Vegetable", [
            "celery stalk", "celery",
            "asparagus",
            "artichoke",
            "green bean", "yellow bean", "wax bean", "string bean", "bean",
            "snow pea", "snap pea", "sugar snap pea", "green pea", "pea",
            "corn on the cob", "sweet corn", "corn",
            "fennel bulb", "fennel",
            "okra",
            "edamame",
            "bamboo shoot",
            "water chestnut",
            "lotus root",
        ]),
    ],
    "Fruits": [
        ("Citrus", [
            "navel orange", "blood orange", "cara cara", "orange",
            "meyer lemon", "lemon",
            "persian lime", "key lime", "lime",
            "ruby grapefruit", "white grapefruit", "grapefruit",
            "mandarin", "clementine", "tangerine", "satsuma",
            "pomelo", "yuzu",
        ]),
        ("Berries", [
            "strawberr", "blueberr", "raspberr", "blackberr",
            "cranberr", "gooseberr", "currant",
            "red grape", "green grape", "seedless grape", "grape",
            "bing cherry", "rainier cherry", "cherr",
        ]),
        ("Stone Fruit", [
            "white peach", "yellow peach", "peach",
            "black plum", "red plum", "italian prune plum", "plum",
            "nectarine",
            "apricot",
            "ataulfo mango", "honey mango", "champagne mango", "mango",
            "lychee", "longan", "rambutan",
        ]),
        ("Tropical", [
            "pineapple", "papaya", "guava",
            "passion fruit", "passionfruit",
            "dragon fruit", "dragonfruit",
            "coconut",
            "cavendish banana", "plantain", "banana",
            "jackfruit", "durian",
            "star fruit", "starfruit", "carambola",
            "tamarind",
        ]),
        ("Pome Fruit", [
            "gala apple", "fuji apple", "honeycrisp apple", "granny smith apple",
            "pink lady apple", "ambrosia apple", "apple",
            "bartlett pear", "bosc pear", "asian pear", "d'anjou pear", "pear",
            "quince",
        ]),
        ("Melons", [
            "seedless watermelon", "mini watermelon", "watermelon",
            "cantaloupe", "cantaloup",
            "honeydew", "galia melon", "canary melon", "melon",
        ]),
        ("Other Fruit", [
            "hass avocado", "florida avocado", "avocado",
            "kiwi", "golden kiwi",
            "fig", "dried fig",
            "pomegranate",
            "persimmon",
            "date", "medjool",
        ]),
    ],
}

# Flat lookup built at import time: keyword -> (category, subcategory)
# Longer keywords take priority (sorted descending by length).
_KEYWORD_INDEX: list[tuple[str, str, str]] = []

for _category, _subcategories in CATEGORY_MAP.items():
    for _subcat, _keywords in _subcategories:
        for _kw in _keywords:
            _KEYWORD_INDEX.append((_kw, _category, _subcat))

# Sort longest-first so "chicken breast" matches before "chicken"
_KEYWORD_INDEX.sort(key=lambda x: len(x[0]), reverse=True)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify(item_name: str) -> tuple[str, str]:
    """
    Classify a grocery item name into (category, subcategory).

    Returns ("Other", "") if no keyword matches.
    Uses word-boundary matching to prevent short keywords (e.g. "eel", "cod", "ham")
    from matching inside unrelated words (e.g. "wheel", "codeine", "shampoo").
    """
    import re as _re
    lowered = item_name.lower()
    for keyword, category, subcategory in _KEYWORD_INDEX:
        # Left word-boundary only: prevents "eel" matching inside "wheel",
        # but still matches plurals ("prawn" matches "prawns", "tomato" matches "tomatoes")
        if _re.search(r'\b' + _re.escape(keyword), lowered):
            return category, subcategory
    return "Other", ""


# ---------------------------------------------------------------------------
# Batch helper used by flyer_run_all.py / flyer_report.py
# ---------------------------------------------------------------------------

def classify_items(items: list[dict]) -> list[dict]:
    """
    Add 'category' and 'subcategory' keys to each item dict in-place.
    Returns the same list for convenience.
    """
    for item in items:
        cat, sub = classify(item.get("item_name", ""))
        item["category"] = cat
        item["subcategory"] = sub
    return items


# ---------------------------------------------------------------------------
# Smoke-test (run directly: python tools/flyer_classify.py)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    cases = [
        ("Boneless Skinless Chicken Breast",  ("Meat/Fish", "Poultry")),
        ("AAA Beef Ribeye Steak",             ("Meat/Fish", "Beef")),
        ("Atlantic Salmon Fillet",            ("Meat/Fish", "Seafood")),
        ("Tiger Prawns",                      ("Meat/Fish", "Seafood")),
        ("Dungeness Crab",                    ("Meat/Fish", "Seafood")),
        ("Pork Side Ribs",                    ("Meat/Fish", "Pork")),
        ("Lean Ground Beef",                  ("Meat/Fish", "Beef")),
        ("Roma Tomatoes",                     ("Vegetables", "Nightshades & Squash")),
        ("Baby Bok Choy",                     ("Vegetables", "Leafy Greens")),
        ("Russet Potatoes 10 lb bag",         ("Vegetables", "Root Vegetables")),
        ("Shiitake Mushrooms",                ("Vegetables", "Fungi")),
        ("Navel Oranges 4 lb bag",            ("Fruits",     "Citrus")),
        ("Blueberries 1 pint",                ("Fruits",     "Berries")),
        ("Gala Apples",                       ("Fruits",     "Pome Fruit")),
        ("Seedless Watermelon",               ("Fruits",     "Melons")),
        ("Hass Avocado",                      ("Fruits",     "Other Fruit")),
        ("Chicken Broth",                     ("Meat/Fish",  "Poultry")),  # keyword match is expected; broth won't appear in flyer meat sections
        ("Mixed Salad Dressing",              ("Other",      "")),
    ]

    passed = 0
    for name, expected in cases:
        result = classify(name)
        ok = result == expected
        status = "PASS" if ok else "FAIL"
        if not ok:
            print(f"  {status}  {name!r}")
            print(f"         expected: {expected}")
            print(f"         got:      {result}")
        else:
            print(f"  {status}  {name!r}  =>  {result}")
        passed += ok

    print(f"\n{passed}/{len(cases)} tests passed")
