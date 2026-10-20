from __future__ import annotations

import math
import re
from calendar import monthrange
from datetime import date, timedelta

import pandas as pd

# ---------------------------------------------------------------- money

_MONEY_STRIP = re.compile(r"[^\d,.\-()]")
_NULLS = {"", "-", "--", "–", "na", "n/a", "null", "none", "nan"}


def parse_money(value) -> float | None:
    """Parse currency text into a float. Handles $, commas, (parens), trailing minus,
    and European 1.234,56 notation."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return None if (isinstance(value, float) and math.isnan(value)) else float(value)

    s = str(value).strip()
    if s.lower() in _NULLS:
        return None

    negative = (s.startswith("(") and s.endswith(")")) or s.startswith("-") or s.endswith("-")
    s = _MONEY_STRIP.sub("", s).strip("()").strip("-")
    if not s:
        return None

    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        s = s.replace(",", ".") if len(parts) == 2 and len(parts[-1]) == 2 else s.replace(",", "")

    try:
        amount = float(s)
    except ValueError:
        return None
    return -amount if negative else amount


# ---------------------------------------------------------------- dates

_DATE_FORMATS = [
    "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%m-%d-%Y", "%d-%m-%Y",
    "%Y/%m/%d", "%d %b %Y", "%b %d, %Y", "%d-%b-%Y", "%m/%d/%y", "%d.%m.%Y",
]
_MD_ONLY = re.compile(r"^\s*(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*$")


def looks_like_month_day(series: pd.Series) -> bool:
    sample = series.dropna().astype(str).head(50)
    return len(sample) > 0 and sample.str.match(_MD_ONLY).mean() > 0.8


def _dayfirst_hint(series: pd.Series) -> bool:
    """If the first component exceeds 12 anywhere, it must be a day."""
    first, second = [], []
    for raw in series.dropna().astype(str).head(200):
        parts = re.split(r"[/\-.]", raw.strip())
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            first.append(int(parts[0]))
            second.append(int(parts[1]))
    if not first:
        return False
    return max(first) > 12 and max(second) <= 12


def parse_dates(series: pd.Series, reference: date | None = None) -> tuple[pd.Series, bool]:
    """Returns (datetime series, year_was_inferred)."""
    reference = reference or date.today()

    if looks_like_month_day(series):
        return _infer_years(series, reference), True

    dayfirst = _dayfirst_hint(series)
    best, best_score = None, -1.0
    for fmt in _DATE_FORMATS:
        parsed = pd.to_datetime(series, format=fmt, errors="coerce")
        score = parsed.notna().mean()
        if score > best_score:
            best, best_score = parsed, score
        if score > 0.99:
            break

    if best_score < 0.9:
        fallback = pd.to_datetime(series, errors="coerce", dayfirst=dayfirst, format="mixed")
        if fallback.notna().mean() > best_score:
            best = fallback
    return best, False


def _infer_years(series: pd.Series, reference: date) -> pd.Series:
    """Assign years to MM/DD values by walking backwards through the (assumed
    chronologically ascending) file and decrementing on month rollover."""
    pairs: list[tuple[int, int] | None] = []
    for raw in series.astype(str):
        m = _MD_ONLY.match(raw)
        pairs.append((int(m.group(1)), int(m.group(2))) if m else None)

    year, prev_month, out = reference.year, None, []
    for pair in reversed(pairs):
        if pair is None:
            out.append(pd.NaT)
            continue
        month, day = pair
        if prev_month is not None and month > prev_month:
            year -= 1
        prev_month = month
        day = min(day, monthrange(year, month)[1])
        out.append(pd.Timestamp(year, month, day))
    out.reverse()

    result = pd.Series(out, index=series.index)
    valid = result.dropna()
    if not valid.empty and valid.max().date() > reference + timedelta(days=1):
        result = result - pd.DateOffset(years=1)
    return result


# ---------------------------------------------------------------- text

_NOISE_PREFIXES = [
    "pos debit", "pos purchase", "pos withdrawal", "debit card purchase",
    "purchase authorized on", "checkcard", "check card", "visa debit", "visa purchase",
    "ach debit", "ach credit", "ach withdrawal", "ach deposit", "electronic withdrawal",
    "electronic deposit", "preauthorized debit", "preauthorized credit",
    "recurring payment", "online payment to", "online transfer to", "web pmt",
    "bill payment", "external withdrawal", "external deposit", "card purchase",
    "point of sale", "direct dep", "direct deposit",
]
_WRAPPERS = ["sq *", "sq*", "tst*", "tst *", "pp*", "paypal *", "paypal*",
             "pyp*", "in *", "in*", "ext *", "cknd*", "amzn mktp"]

_NOISE_PATTERNS = [
    re.compile(r"\b\d{1,2}[/\-]\d{1,2}(?:[/\-]\d{2,4})?\b"),   # embedded dates
    re.compile(r"\bx{2,}\d+\b", re.I),                          # masked card numbers
    re.compile(r"#\s*\d+"),                                     # store numbers
    re.compile(r"\b\d{3}[-.]\d{3}[-.]\d{4}\b"),                 # phone numbers
    re.compile(r"\b\d{6,}\b"),                                  # long reference ids
    re.compile(r"\bid\s*[:#]?\s*\w+\b", re.I),
    re.compile(r"\bref\s*[:#]?\s*\w+\b", re.I),
    re.compile(r"\bconf\s*[:#]?\s*\w+\b", re.I),
    re.compile(r"\b(?:usd|amt)\b", re.I),
]
_US_STATES = {
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA","KS",
    "KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ","NM","NY",
    "NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT","VA","WA","WV",
    "WI","WY","DC",
}
_TRAILING_JUNK = {"purchase", "payment", "pmt", "debit", "credit", "card", "co", "com",
                  "inc", "llc", "the", "of", "on", "www"}


def clean_description(raw: str) -> str:
    """POS DEBIT STARBUCKS 1234 NASHVILLE TN -> 'STARBUCKS NASHVILLE'"""
    text = str(raw or "").strip().lower()
    if not text:
        return ""

    for wrapper in _WRAPPERS:
        if wrapper in text:
            text = text.split(wrapper, 1)[1] if text.startswith(wrapper) else text.replace(wrapper, " ")

    changed = True
    while changed:
        changed = False
        for prefix in _NOISE_PREFIXES:
            if text.startswith(prefix):
                text, changed = text[len(prefix):].strip(" -*#:"), True

    for pattern in _NOISE_PATTERNS:
        text = pattern.sub(" ", text)

    text = re.sub(r"[^a-z0-9&'\- ]+", " ", text)
    tokens = [t for t in text.split() if t]

    while tokens and (tokens[-1].upper() in _US_STATES or tokens[-1] in _TRAILING_JUNK
                      or tokens[-1].isdigit()):
        tokens.pop()

    return " ".join(tokens).upper().strip()


_STOP_TOKENS = {"STORE", "SUPERCENTER", "MARKET", "SHOP", "CENTER", "LOCATION", "MOBILE"}


def merchant_guess(clean: str) -> str:
    """First 1-3 meaningful tokens, title-cased. Refined later by the merchant catalog."""
    if not clean:
        return "Unknown"
    tokens = [t for t in clean.split() if t not in _STOP_TOKENS and not t.isdigit()]
    if not tokens:
        return "Unknown"
    take = tokens[:3] if len(tokens[0]) <= 3 else tokens[:2]
    return " ".join(w.capitalize() if not w.isupper() or len(w) > 3 else w for w in take).strip()