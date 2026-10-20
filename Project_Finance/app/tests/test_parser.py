import pytest

from app.core.exceptions import IngestionError
from app.ingestion.parser import detect_schema, parse_statement

CHASE = b"Transaction Date,Description,Amount\n01/15/2025,STARBUCKS #123,-7.42\n01/16/2025,PAYROLL ACME,2400.00\n"
WELLS = b"Date,Memo,Debit,Credit\n01/15/2025,POS DEBIT KROGER,84.20,\n01/16/2025,DIRECT DEP PAYROLL,,2400.00\n"
TYPED = b"Posted Date,Details,Amount,Type\n01/15/2025,KROGER,84.20,DEBIT\n01/16/2025,PAYROLL,2400.00,CREDIT\n"
WITH_BALANCE = (b"Date,Description,Amount,Running Balance\n"
                b"01/15/2025,KROGER,84.20,4915.80\n01/16/2025,PAYROLL,2400.00,7315.80\n")
EUROPEAN = b"Booking Date,Narrative,Amount\n15.01.2025,SUPERMARKT,\"-84,20\"\n"


def test_detects_signed_amount_schema():
    mapping = detect_schema(["Transaction Date", "Description", "Amount"])
    assert mapping.strategy == "signed_amount"
    assert mapping.date == "Transaction Date"


def test_detects_debit_credit_schema():
    mapping = detect_schema(["Date", "Memo", "Debit", "Credit"])
    assert mapping.strategy == "debit_credit"
    assert mapping.description == "Memo"


def test_missing_amount_column_is_rejected():
    with pytest.raises(IngestionError, match="amount column"):
        detect_schema(["Date", "Description"])


def test_missing_date_column_is_rejected():
    with pytest.raises(IngestionError, match="date column"):
        detect_schema(["Description", "Amount"])


@pytest.mark.parametrize("payload", [CHASE, WELLS, TYPED, WITH_BALANCE])
def test_sign_convention_is_consistent_across_schemas(payload):
    """Spending is always negative and income always positive, regardless of
    how the bank chose to encode it."""
    transactions, _ = parse_statement(payload)
    assert len(transactions) == 2
    spending = [t for t in transactions if t.amount < 0]
    income = [t for t in transactions if t.amount > 0]
    assert len(spending) == 1 and len(income) == 1
    assert spending[0].direction == "debit"
    assert income[0].direction == "credit"
    assert income[0].amount == pytest.approx(2400.0)


def test_european_decimal_comma():
    transactions, _ = parse_statement(EUROPEAN)
    assert transactions[0].amount == pytest.approx(-84.20)


def test_balance_column_captured():
    transactions, report = parse_statement(WITH_BALANCE)
    assert report.balance_available
    assert transactions[-1].balance == pytest.approx(7315.80)


def test_all_positive_amounts_inferred_from_balance():
    payload = (b"Date,Description,Amount,Balance\n"
               b"01/15/2025,KROGER,84.20,4915.80\n"
               b"01/16/2025,PAYROLL,2400.00,7315.80\n")
    transactions, report = parse_statement(payload)
    assert transactions[0].amount < 0 and transactions[1].amount > 0
    assert any("balance movement" in w for w in report.warnings)


def test_duplicates_flagged_not_deleted():
    payload = (b"Date,Description,Amount\n01/15/2025,KROGER,-84.20\n"
               b"01/15/2025,KROGER,-84.20\n01/15/2025,KROGER,-84.20\n")
    transactions, report = parse_statement(payload)
    assert len(transactions) == 3
    assert report.duplicates_flagged == 2
    assert sum(t.is_duplicate for t in transactions) == 2


def test_keep_duplicates_flag_respected():
    payload = b"Date,Description,Amount\n01/15/2025,KROGER,-84.20\n01/15/2025,KROGER,-84.20\n"
    transactions, report = parse_statement(payload, keep_duplicates=True)
    assert report.duplicates_flagged == 0
    assert not any(t.is_duplicate for t in transactions)


def test_transaction_ids_unique_even_for_identical_rows():
    payload = b"Date,Description,Amount\n01/15/2025,KROGER,-84.20\n01/15/2025,KROGER,-84.20\n"
    transactions, _ = parse_statement(payload, keep_duplicates=True)
    assert len({t.transaction_id for t in transactions}) == 2


def test_malformed_rows_dropped_with_warning():
    payload = (b"Date,Description,Amount\n01/15/2025,KROGER,-84.20\n"
               b"garbage,,\n01/17/2025,,-10.00\n01/18/2025,ZERO,0.00\n")
    transactions, report = parse_statement(payload)
    assert len(transactions) == 1
    assert report.rows_dropped == 3
    assert report.warnings


def test_empty_file_raises():
    with pytest.raises(IngestionError):
        parse_statement(b"")


def test_header_only_file_raises():
    with pytest.raises(IngestionError):
        parse_statement(b"Date,Description,Amount\n")


def test_preamble_rows_are_skipped():
    payload = (b"Account Summary Export\nGenerated 2025-01-20\n\n"
               b"Date,Description,Amount\n01/15/2025,KROGER,-84.20\n")
    transactions, _ = parse_statement(payload)
    assert len(transactions) == 1


def test_transfers_flagged_as_transfer_kind():
    payload = b"Date,Description,Amount\n01/15/2025,ONLINE TRANSFER TO SAVINGS,-500.00\n"
    transactions, _ = parse_statement(payload)
    assert transactions[0].kind == "transfer"


def test_synthetic_statement_parses_cleanly(parsed):
    transactions, report = parsed
    assert report.rows_parsed == len(transactions)
    assert report.months_covered > 10
    assert report.date_min < report.date_max