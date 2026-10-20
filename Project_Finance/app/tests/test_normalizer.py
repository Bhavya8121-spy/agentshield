import pandas as pd
import pytest

from app.ingestion.normalizer import (
    clean_description, merchant_guess, parse_dates, parse_money,
)


@pytest.mark.parametrize("raw,expected", [
    ("$1,234.56", 1234.56), ("(89.10)", -89.10), ("-45", -45.0), ("45.00-", -45.0),
    ("1.234,56", 1234.56), ("2,50", 2.50), ("1,234", 1234.0), ("USD 12.00", 12.0),
    ("", None), ("--", None), ("n/a", None), (None, None), (float("nan"), None),
])
def test_parse_money(raw, expected):
    result = parse_money(raw)
    assert result is None if expected is None else result == pytest.approx(expected)


@pytest.mark.parametrize("raw,expected", [
    ("POS DEBIT STARBUCKS 1234 NASHVILLE TN", "STARBUCKS"),
    ("SQ *STARBUCKS", "STARBUCKS"),
    ("STARBUCKS 800-782-7282", "STARBUCKS"),
    ("PURCHASE AUTHORIZED ON 03/14 WAL-MART #1843 AUSTIN TX", "WAL-MART"),
    ("ACH DEBIT NETFLIX.COM XXXX1234", "NETFLIX COM"),
    ("", ""),
])
def test_clean_description(raw, expected):
    assert clean_description(raw) == expected


def test_starbucks_variants_converge():
    variants = ["POS DEBIT STARBUCKS 04231", "STARBUCKS STORE #19283",
                "SQ *STARBUCKS", "STARBUCKS 800-782-7282"]
    assert len({clean_description(v) for v in variants}) == 1


def test_merchant_guess_drops_noise():
    assert merchant_guess("KROGER STORE 4471") == "Kroger"


import pandas as pd
import pytest

from app.ingestion.normalizer import (
    clean_description, merchant_guess, parse_dates, parse_money,
)


@pytest.mark.parametrize("raw,expected", [
    ("$1,234.56", 1234.56), ("(89.10)", -89.10), ("-45", -45.0), ("45.00-", -45.0),
    ("1.234,56", 1234.56), ("2,50", 2.50), ("1,234", 1234.0), ("USD 12.00", 12.0),
    ("", None), ("--", None), ("n/a", None), (None, None), (float("nan"), None),
])
def test_parse_money(raw, expected):
    result = parse_money(raw)
    assert result is None if expected is None else result == pytest.approx(expected)


@pytest.mark.parametrize("raw,expected", [
    ("POS DEBIT STARBUCKS 1234 NASHVILLE TN", "STARBUCKS"),
    ("SQ *STARBUCKS", "STARBUCKS"),
    ("STARBUCKS 800-782-7282", "STARBUCKS"),
    ("PURCHASE AUTHORIZED ON 03/14 WAL-MART #1843 AUSTIN TX", "WAL-MART"),
    ("ACH DEBIT NETFLIX.COM XXXX1234", "NETFLIX COM"),
    ("", ""),
])
def test_clean_description(raw, expected):
    assert clean_description(raw) == expected


def test_starbucks_variants_converge():
    variants = ["POS DEBIT STARBUCKS 04231", "STARBUCKS STORE #19283",
                "SQ *STARBUCKS", "STARBUCKS 800-782-7282"]
    assert len({clean_description(v) for v in variants}) == 1


def test_merchant_guess_drops_noise():
    assert merchant_guess("KROGER STORE 4471") == "Kroger"


def test_parse_dates_full_format():
    series = pd.Series(["01/15/2025", "02/20/2025", "03/25/2025"])
    parsed, inferred = parse_dates(series)
    assert not inferred
    assert parsed.not