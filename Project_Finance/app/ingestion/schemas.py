from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Direction(str, Enum):
    debit = "debit"
    credit = "credit"


class Kind(str, Enum):
    income = "income"
    fixed = "fixed"
    variable = "variable"
    transfer = "transfer"


class Transaction(BaseModel):
    """Canonical internal transaction. Sign convention: negative = money out."""

    model_config = ConfigDict(use_enum_values=True)

    transaction_id: str
    source_row: int = -1
    date: date
    raw_description: str
    clean_description: str = ""
    merchant: str = "Unknown"
    amount: float
    direction: Direction
    balance: float | None = None

    category: str = "Uncategorized"
    subcategory: str | None = None
    kind: Kind = Kind.variable
    recurring: bool = False
    recurring_frequency: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    classifier: str = "none"

    is_duplicate: bool = False
    anomaly_score: float = 0.0
    is_anomaly: bool = False

    @field_validator("amount")
    @classmethod
    def _finite(cls, v: float) -> float:
        if v != v or v in (float("inf"), float("-inf")):
            raise ValueError("amount must be finite")
        return v


class ColumnMapping(BaseModel):
    date: str | None = None
    description: str | None = None
    amount: str | None = None
    debit: str | None = None
    credit: str | None = None
    balance: str | None = None
    type: str | None = None
    strategy: str = "unknown"          # debit_credit | signed_amount | typed_amount | heuristic_sign
    confidence: float = 0.0


class IngestionReport(BaseModel):
    filename: str = "upload.csv"
    detected_columns: ColumnMapping
    rows_in_file: int = 0
    rows_parsed: int = 0
    rows_dropped: int = 0
    duplicates_flagged: int = 0
    date_min: date | None = None
    date_max: date | None = None
    months_covered: float = 0.0
    year_inferred: bool = False
    balance_available: bool = False
    warnings: list[str] = Field(default_factory=list)