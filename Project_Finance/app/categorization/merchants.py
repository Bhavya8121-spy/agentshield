from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz, process

from app.categorization.rules import category_kind

FUZZY_FLOOR = 86        # below this we do not claim a match
FUZZY_CEILING = 0.88    # max confidence attainable from fuzzy matching


@dataclass(frozen=True)
class MerchantMatch:
    merchant: str
    category: str
    subcategory: str | None
    confidence: float
    method: str          # catalog | fuzzy


# canonical -> (category, subcategory, aliases)
CATALOG: dict[str, tuple[str, str | None, tuple[str, ...]]] = {
    "Starbucks":       ("Dining", "Coffee", ("starbucks", "starbucks store", "sbux")),
    "Dunkin'":         ("Dining", "Coffee", ("dunkin", "dunkin donuts")),
    "Chipotle":        ("Dining", "Fast Casual", ("chipotle", "chipotle mexican grill")),
    "McDonald's":      ("Dining", "Fast Food", ("mcdonalds", "mcdonald s", "mcd")),
    "DoorDash":        ("Dining", "Delivery", ("doordash", "dd doordash")),
    "Uber Eats":       ("Dining", "Delivery", ("uber eats", "ubereats")),
    "Kroger":          ("Groceries", None, ("kroger", "kroger fuel")),
    "Publix":          ("Groceries", None, ("publix", "publix super market")),
    "Trader Joe's":    ("Groceries", None, ("trader joes", "trader joe s")),
    "Whole Foods":     ("Groceries", None, ("whole foods", "whole foods market", "wholefds")),
    "Aldi":            ("Groceries", None, ("aldi",)),
    "Costco":          ("Shopping", "Warehouse", ("costco", "costco whse", "costco wholesale")),
    "Walmart":         ("Shopping", "General", ("walmart", "wal mart", "wal-mart", "walmart supercenter")),
    "Target":          ("Shopping", "General", ("target", "target t")),
    "Amazon":          ("Shopping", "Online", ("amazon", "amzn mktp", "amazon mktplace", "amazon com")),
    "Best Buy":        ("Shopping", "Electronics", ("best buy", "bestbuy")),
    "Netflix":         ("Subscriptions", "Streaming", ("netflix",)),
    "Spotify":         ("Subscriptions", "Music", ("spotify", "spotify usa")),
    "Hulu":            ("Subscriptions", "Streaming", ("hulu",)),
    "Disney+":         ("Subscriptions", "Streaming", ("disney plus", "disney+", "disneyplus")),
    "Apple":           ("Subscriptions", "Apple Services", ("apple com bill", "apple services", "itunes")),
    "Adobe":           ("Subscriptions", "Software", ("adobe", "adobe systems")),
    "OpenAI":          ("Subscriptions", "Software", ("openai", "chatgpt subscription")),
    "Shell":           ("Fuel", None, ("shell", "shell oil", "shell service")),
    "Exxon":           ("Fuel", None, ("exxon", "exxonmobil", "esso")),
    "Chevron":         ("Fuel", None, ("chevron",)),
    "Uber":            ("Transportation", "Rideshare", ("uber", "uber trip")),
    "Lyft":            ("Transportation", "Rideshare", ("lyft", "lyft ride")),
    "CVS":             ("Health", "Pharmacy", ("cvs", "cvs pharmacy")),
    "Walgreens":       ("Health", "Pharmacy", ("walgreens", "walgreen")),
    "Planet Fitness":  ("Fitness", "Gym", ("planet fitness", "planet fit")),
    "Peloton":         ("Fitness", "Equipment", ("peloton",)),
    "Verizon":         ("Phone/Internet", None, ("verizon", "verizon wireless", "vzwrlss")),
    "AT&T":            ("Phone/Internet", None, ("at t", "att", "at&t")),
    "T-Mobile":        ("Phone/Internet", None, ("t mobile", "tmobile")),
    "Comcast":         ("Phone/Internet", None, ("comcast", "xfinity")),
    "Geico":           ("Insurance", "Auto", ("geico",)),
    "State Farm":      ("Insurance", None, ("state farm",)),
    "Progressive":     ("Insurance", "Auto", ("progressive", "progressive ins")),
    "Home Depot":      ("Home/Garden", None, ("home depot", "the home depot")),
    "Lowe's":          ("Home/Garden", None, ("lowes", "lowe s")),
    "IKEA":            ("Home/Garden", None, ("ikea",)),
    "Delta Air Lines": ("Travel", "Airfare", ("delta air", "delta airlines")),
    "Southwest":       ("Travel", "Airfare", ("southwest air", "southwest airlines")),
    "Airbnb":          ("Travel", "Lodging", ("airbnb",)),
    "Marriott":        ("Travel", "Lodging", ("marriott", "courtyard marriott")),
    "Ticketmaster":    ("Entertainment", "Events", ("ticketmaster",)),
    "Steam":           ("Entertainment", "Gaming", ("steam games", "steampowered")),
    "AMC Theatres":    ("Entertainment", "Cinema", ("amc theatres", "amc online")),
    "Chewy":           ("Pets", None, ("chewy", "chewy com")),
    "PetSmart":        ("Pets", None, ("petsmart", "pet smart")),
}

_ALIAS_TO_CANON: dict[str, str] = {
    alias: canon for canon, (_, _, aliases) in CATALOG.items() for alias in aliases
}
_ALIAS_TO_CANON.update({canon.lower(): canon for canon in CATALOG})
_ALIAS_KEYS: list[str] = list(_ALIAS_TO_CANON)


def _normalize_key(text: str) -> str:
    return " ".join(str(text or "").lower().replace("&", " ").replace("-", " ").split())


def lookup_exact(clean_description: str) -> MerchantMatch | None:
    """Exact alias hit, or alias appearing as a prefix/substring of the description."""
    key = _normalize_key(clean_description)
    if not key:
        return None

    canon = _ALIAS_TO_CANON.get(key)
    if canon is None:
        # longest alias contained in the text wins (avoids "gap" matching "gap insurance")
        candidates = [a for a in _ALIAS_KEYS if a in key and len(a) >= 4]
        if candidates:
            canon = _ALIAS_TO_CANON[max(candidates, key=len)]

    if canon is None:
        return None
    category, subcategory, _ = CATALOG[canon]
    return MerchantMatch(canon, category, subcategory, 0.97, "catalog")


def lookup_fuzzy(clean_description: str, floor: int = FUZZY_FLOOR) -> MerchantMatch | None:
    key = _normalize_key(clean_description)
    if len(key) < 4:
        return None
    hit = process.extractOne(key, _ALIAS_KEYS, scorer=fuzz.token_set_ratio, score_cutoff=floor)
    if hit is None:
        return None
    alias, score, _ = hit
    canon = _ALIAS_TO_CANON[alias]
    category, subcategory, _ = CATALOG[canon]
    # map [floor, 100] -> [0.66, FUZZY_CEILING]
    confidence = 0.66 + (score - floor) / max(100 - floor, 1) * (FUZZY_CEILING - 0.66)
    return MerchantMatch(canon, category, subcategory, round(confidence, 3), "fuzzy")


def resolve(clean_description: str) -> MerchantMatch | None:
    return lookup_exact(clean_description) or lookup_fuzzy(clean_description)


def catalog_kind(category: str) -> str:
    return category_kind(category)