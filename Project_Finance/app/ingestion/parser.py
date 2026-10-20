from __future__ import annotations

import hashlib
import io
import re
from datetime import date

import pandas as pd

from app.core.config import settings
from app.core.exceptions import IngestionError
from app.core.logging import get_logger
from app.ingestion.normalizer import clean_description, merchant_guess, parse_dates, parse_money
from app.ingestion.schemas import ColumnMapping, Direction, IngestionReport, Transaction

log = get_logger(__name__)

SYNONYMS: dict[str, set[str]] = {
    "date": {"date", "transaction date", "trans date", "posted date", "post date",
             "posting date", "effective date", "date posted", "value date", "booking date"},
    "description": {"description", "memo", "details", "detail", "payee", "name",
                    "narrative", "transaction", "transaction description",
                    "original description", "reference", "particulars"},
    "amount": {"amount", "transaction amount", "amt", "value", "net amount"},
    "debit": {"debit", "debits", "withdrawal", "withdrawals", "money out", "paid out",
              "debit amount", "amount debited", "outflow"},
    "credit": {"credit", "credits", "deposit", "deposits", "money in", "paid in",
               "credit amount", "amount credited", "inflow"},
    "balance": {"balance", "running balance", "ledger balance", "balance amount",
                "closing balance", "available balance"},
    "type": {"type", "transaction type", "debit/credit", "dr/cr", "cr/dr",
             "indicator", "credit debit indicator"},
}

INCOME_HINTS = re.compile(
    r"\b(payroll|salary|direct dep|dir dep|deposit|refund|reimburs|interest|dividend"
    r"|cashback|rebate|tax ref|venmo cashout|transfer in|credit)\b", re.I
)
TRANSFER_HINTS = re.compile(
    r"\b(transfer to|transfer from|xfer|to savings|from savings|internal transfer"
    r"|online transfer|zelle to|move money)\b", re.I
)


def _norm_header(name: str) -> str:
    return re.sub(r"[\s_\-]+", " ", str(name)).strip().lower()


def detect_schema(columns: list[str]) -> ColumnMapping:
    lookup = {_norm_header(c): c for c in columns}
    resolved: dict[str, str | None] = {}

    for field, options in SYNONYMS.items():
        hit = next((lookup[k] for k in lookup if k in options), None)
        if hit is None:  # substring fallback
            hit = next((lookup[k] for k in lookup for o in options if o in k), None)
        resolved[field] = hit

    mapping = ColumnMapping(**resolved)

    if mapping.debit and mapping.credit:
        mapping.strategy = "debit_credit"
    elif mapping.amount and mapping.type:
        mapping.strategy = "typed_amount"
    elif mapping.amount:
        mapping.strategy = "signed_amount"
    elif mapping.debit or mapping.credit:
        mapping.strategy = "debit_credit"
    else:
        raise IngestionError(
            "Could not find an amount column. Expected one of: Amount, or Debit/Credit.",
            {"columns_seen": list(columns)},
        )

    if not mapping.date:
        raise IngestionError("Could not find a date column.", {"columns_seen": list(columns)})
    if not mapping.description:
        raise IngestionError("Could not find a description column.", {"columns_seen": list(columns)})

    found = sum(1 for f in ("date", "description", "balance") if getattr(mapping, f))
    mapping.confidence = round(min(1.0, 0.6 + 0.13 * found), 2)
    return mapping


def _read_csv(payload: bytes) -> pd.DataFrame:
    if len(payload) > settings.max_upload_bytes:
        raise IngestionError(f"File exceeds {settings.max_upload_bytes // (1024*1024)} MB limit.")
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        for skiprows in (0, 1, 2, 3):   # some exports prepend preamble lines
            try:
                df = pd.read_csv(
                    io.BytesIO(payload), encoding=encoding, skipinitialspace=True,
                    skiprows=skiprows, dtype=str, on_bad_lines="skip",
                )
            except Exception as exc:      # noqa: BLE001
                last_error = exc
                continue
            if df.empty or df.shape[1] < 2:
                continue
            df.columns = [str(c).strip() for c in df.columns]
            try:
                detect_schema(list(df.columns))
                return df
            except IngestionError as exc:
                last_error = exc
    raise IngestionError(
        "Unable to read this CSV. Ensure it has a header row with date, description and amount columns.",
        {"underlying": str(last_error) if last_error else None},
    )


def _resolve_amounts(df: pd.DataFrame, m: ColumnMapping, warnings: list[str]) -> pd.Series:
    if m.strategy == "debit_credit":
        debit = df[m.debit].map(parse_money).fillna(0.0).abs() if m.debit else 0.0
        credit = df[m.credit].map(parse_money).fillna(0.0).abs() if m.credit else 0.0
        return pd.Series(credit, index=df.index) - pd.Series(debit, index=df.index)

    amounts = df[m.amount].map(parse_money)

    if m.strategy == "typed_amount":
        marker = df[m.type].astype(str).str.strip().str.lower()
        is_debit = marker.str.startswith(("d", "dr", "w")) | marker.str.contains("debit|withdraw")
        return amounts.abs() * is_debit.map({True: -1.0, False: 1.0})

    # signed_amount
    if (amounts.dropna() < 0).any():
        return amounts

    # All-positive single amount column: sign must be inferred.
    if m.balance:
        balances = df[m.balance].map(parse_money)
        if balances.notna().mean() > 0.9:
            warnings.append("Amount signs inferred from balance movement.")
            delta = balances.diff()
            delta.iloc[0] = -amounts.iloc[0] if len(amounts) else 0.0
            return amounts.abs() * delta.apply(lambda d: 1.0 if (d or 0) > 0 else -1.0)

    warnings.append(
        "Amount column had no negative values; direction inferred from description keywords. "
        "Verify the transaction table."
    )
    looks_income = df[m.description].astype(str).str.contains(INCOME_HINTS)
    return amounts.abs() * looks_income.map({True: 1.0, False: -1.0})


def _make_id(row_date, description: str, amount: float, occurrence: int) -> str:
    payload = f"{row_date}|{description}|{amount:.2f}|{occurrence}"
    return "txn_" + hashlib.sha1(payload.encode()).hexdigest()[:16]


def parse_statement(
    payload: bytes,
    filename: str = "upload.csv",
    reference_date: date | None = None,
    keep_duplicates: bool = False,
) -> tuple[list[Transaction], IngestionReport]:
    raw = _read_csv(payload)
    if len(raw) > settings.max_rows:
        raise IngestionError(f"File exceeds {settings.max_rows:,} row limit.")

    mapping = detect_schema(list(raw.columns))
    warnings: list[str] = []
    rows_in_file = len(raw)

    work = pd.DataFrame(index=raw.index)
    work["source_row"] = range(len(raw))
    work["raw_description"] = raw[mapping.description].fillna("").astype(str).str.strip()
    work["amount"] = _resolve_amounts(raw, mapping, warnings).astype(float)
    parsed_dates, year_inferred = parse_dates(raw[mapping.date], reference_date)
    work["date"] = parsed_dates
    work["balance"] = raw[mapping.balance].map(parse_money) if mapping.balance else None

    # -- validation
    before = len(work)
    work = work[work["date"].notna() & work["amount"].notna()]
    work = work[work["amount"].abs() > 0.004]
    work = work[work["raw_description"].str.len() > 0]
    dropped = before - len(work)
    if dropped:
        warnings.append(f"{dropped} row(s) dropped: missing date, amount, or description.")
    if work.empty:
        raise IngestionError("No valid transactions found after parsing.")

    work = work.sort_values(["date", "source_row"], kind="stable").reset_index(drop=True)
    work["clean_description"] = work["raw_description"].map(clean_description)
    work["merchant"] = work["clean_description"].map(merchant_guess)

    # -- duplicates: exact (date, cleaned text, amount) repeats beyond the first
    dup_key = (
        work["date"].dt.strftime("%Y-%m-%d") + "|" + work["clean_description"] + "|"
        + work["amount"].round(2).astype(str)
    )
    work["is_duplicate"] = dup_key.duplicated(keep="first") & (not keep_duplicates)
    duplicates = int(work["is_duplicate"].sum())
    if duplicates:
        warnings.append(
            f"{duplicates} exact duplicate row(s) flagged and excluded. "
            "Pass keep_duplicates=true if these are genuinely separate purchases."
        )

    transactions: list[Transaction] = []
    seen: dict[str, int] = {}
    for row in work.itertuples(index=False):
        key = f"{row.date}|{row.clean_description}|{row.amount:.2f}"
        seen[key] = seen.get(key, 0) + 1
        is_transfer = bool(TRANSFER_HINTS.search(row.raw_description))
        transactions.append(
            Transaction(
                transaction_id=_make_id(row.date.date(), row.clean_description, row.amount, seen[key]),
                source_row=int(row.source_row),
                date=row.date.date(),
                raw_description=row.raw_description,
                clean_description=row.clean_description,
                merchant=row.merchant,
                amount=round(float(row.amount), 2),
                direction=Direction.credit if row.amount > 0 else Direction.debit,
                balance=None if row.balance is None or pd.isna(row.balance) else float(row.balance),
                kind="transfer" if is_transfer else "variable",
                category="Transfer" if is_transfer else "Uncategorized",
                is_duplicate=bool(row.is_duplicate),
            )
        )

    dmin, dmax = work["date"].min().date(), work["date"].max().date()
    months = max((dmax - dmin).days / 30.44, 1 / 30.44)
    if months < 2:
        warnings.append("Under two months of history: forecasts and volatility metrics will be weak.")

    report = IngestionReport(
        filename=filename,
        detected_columns=mapping,
        rows_in_file=rows_in_file,
        rows_parsed=len(transactions),
        rows_dropped=dropped,
        duplicates_flagged=duplicates,
        date_min=dmin,
        date_max=dmax,
        months_covered=round(months, 2),
        year_inferred=year_inferred,
        balance_available=bool(mapping.balance) and work["balance"].notna().any(),
        warnings=warnings,
    )
    log.info("Parsed %s: %d txns, strategy=%s", filename, len(transactions), mapping.strategy)
    return transactions, report