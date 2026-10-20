import pandas as pd
import pytest

from app.categorization.classifier import CategorizationEngine, categorize_frame
from app.categorization.merchants import lookup_exact, lookup_fuzzy, resolve
from app.categorization.rules import DEBT_CATEGORIES, category_kind, match_rules
from app.core.dataset import transactions_to_frame
from app.ingestion.parser import parse_statement


def _row(description, amount=-25.0, date="2025-01-15"):
    payload = f"Date,Description,Amount\n{date},{description},{amount}\n".encode()
    transactions, _ = parse_statement(payload)
    return categorize_frame(transactions_to_frame(transactions)).iloc[0]


# ---------------------------------------------------------------- catalog tier
@pytest.mark.parametrize("description,expected", [
    ("STARBUCKS STORE #19283", "Dining"),
    ("SQ *STARBUCKS", "Dining"),
    ("NETFLIX.COM", "Subscriptions"),
    ("SPOTIFY USA", "Subscriptions"),
    ("KROGER #4471", "Groceries"),
    ("SHELL OIL 5774", "Fuel"),
    ("UBER TRIP 8HG2K", "Transportation"),
    ("CVS/PHARMACY #2201", "Health"),
])
def test_known_merchants_classified(description, expected):
    row = _row(description)
    assert row["category"] == expected
    assert row["confidence"] >= 0.65


def test_walmart_variants_normalize_to_one_merchant():
    merchants = {_row(d)["merchant"] for d in
                 ["WAL-MART #1843", "WALMART SUPERCENTER 2201", "WAL MART 4410"]}
    assert merchants == {"Walmart"}


def test_fuzzy_match_survives_typo():
    match = lookup_fuzzy("STARBUKS COFFEE")
    assert match is not None
    assert match.merchant == "Starbucks"
    assert 0.65 <= match.confidence <= 0.88


def test_fuzzy_confidence_never_reaches_certainty():
    """A fuzzy match must never claim catalog-level confidence."""
    assert lookup_fuzzy("STARBUKS")3 if False else True
    exact = lookup_exact("STARBUCKS")
    fuzzy = lookup_fuzzy("STARBUKS COFFE")
    assert fuzzy.confidence < exact.confidence


def test_unrelated_text_does_not_fuzzy_match():
    assert lookup_fuzzy("ZZQX PLUMBING SUPPLY CO") is None


# ------------------------------------------------------------------ rules tier
def test_rules_match_on_raw_when_cleaning_strips_token():
    row = _row("ATM WITHDRAWAL 1420 MAIN ST")
    assert row["category"] == "Cash Withdrawal"


def test_debt_categories_are_marked_for_dti():
    for description in ["ACH DEBIT AUTO LOAN PAYMENT", "NELNET STUDENT LOAN PMT",
                        "CHASE CARD PAYMENT"]:
        assert _row(description)["category"] in DEBT_CATEGORIES


def test_insurance_is_fixed_but_not_debt():
    """The original app lumped insurance into the DTI numerator; it is a living
    cost, not a debt obligation."""
    row = _row("GEICO AUTO INSURANCE PMT")
    assert row["category"] == "Insurance"
    assert row["kind"] == "fixed"
    assert row["category"] not in DEBT_CATEGORIES


# ------------------------------------------------------- the check-guess fix
def test_paper_check_routes_to_review_not_rent():
    """A bare check is genuinely ambiguous. Silently calling it rent corrupts DTI."""
    row = _row("CHECK #1042")
    assert row["category"] == "Needs Review"
    assert row["subcategory"] == "Paper Check"


def test_check_with_payee_still_classified():
    row = _row("CHECK #1042 PROPERTY MGMT LLC")
    assert row["category"] == "Rent/Mortgage"


# ------------------------------------------------------------- sign handling
def test_inflow_is_income_by_sign():
    row = _row("DIRECT DEP PAYROLL ACME", amount=2400.0)
    assert row["category"] == "Income"
    assert row["kind"] == "income"


def test_refund_inflow_labelled_as_refund_not_paycheck():
    row = _row("AMAZON REFUND", amount=45.00)
    assert row["category"] == "Income"
    assert row["subcategory"] == "Refund"


def test_transfer_excluded_from_income_and_spending():
    row = _row("ONLINE TRANSFER TO SAVINGS", amount=-500.0)
    assert row["category"] == "Transfer"
    assert row["kind"] == "transfer"


# ------------------------------------------------------------- review gating
def test_low_confidence_becomes_needs_review():
    engine = CategorizationEngine(min_confidence=0.99)
    frame = pd.DataFrame([{
        "transaction_id": "t1", "date": pd.Timestamp("2025-01-15"),
        "raw_description": "ZZQX HOLDINGS LLC", "clean_description": "ZZQX HOLDINGS",
        "merchant": "Zzqx", "amount": -42.0, "direction": "debit", "kind": "variable",
        "category": "Uncategorized", "subcategory": None, "confidence": 0.0,
        "classifier": "none",
    }])
    assert engine.categorize(frame).iloc[0]["category"] == "Needs Review"


def test_unknown_merchant_is_not_confidently_labelled():
    row = _row("QZWX UNKNOWN VENDOR 77")
    assert row["category"] in {"Needs Review", "Uncategorized"}
    assert row["confidence"] < 0.65


def test_kind_always_matches_category():
    frame = categorize_frame(transactions_to_frame(parse_statement(
        b"Date,Description,Amount\n"
        b"01/15/2025,NETFLIX.COM,-22.99\n"
        b"01/16/2025,PAYROLL ACME,2400.00\n"
        b"01/17/2025,CHECK #1099 PROPERTY MGMT,-1500.00\n"
    )[0]))
    for row in frame.itertuples():
        assert row.kind == category_kind(row.category)


def test_full_statement_review_rate_is_reasonable(frame):
    review_rate = (frame["category"] == "Needs Review").mean()
    assert review_rate < 0.20, f"review rate too high: {review_rate:.1%}"


def test_no_uncategorized_leaks_into_output(frame):
    assert not frame["category"].isna().any()