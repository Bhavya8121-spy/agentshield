from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from app.ingestion.schemas import IngestionReport, Transaction

FRAME_COLUMNS = [
    "transaction_id", "source_row", "date", "raw_description", "clean_description",
    "merchant", "amount", "direction", "balance", "category", "subcategory", "kind",
    "recurring", "recurring_frequency", "confidence", "classifier", "is_duplicate",
    "anomaly_score", "is_anomaly",
]


def transactions_to_frame(transactions: list[Transaction]) -> pd.DataFrame:
    if not transactions:
        return pd.DataFrame(columns=FRAME_COLUMNS)
    df = pd.DataFrame([t.model_dump() for t in transactions])
    df["date"] = pd.to_datetime(df["date"])
    for col in FRAME_COLUMNS:
        if col not in df.columns:
            df[col] = None
    df = df[FRAME_COLUMNS].sort_values("date", kind="stable").reset_index(drop=True)
    df["outflow"] = df["amount"].clip(upper=0).abs()
    df["inflow"] = df["amount"].clip(lower=0)
    return df


@dataclass
class Dataset:
    """Holds one uploaded statement plus lazily-computed analytics artifacts."""

    df: pd.DataFrame
    report: IngestionReport
    dataset_id: str = field(default_factory=lambda: f"ds_{uuid.uuid4().hex[:12]}")
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    liquid_savings_override: float | None = None
    _cache: dict[str, Any] = field(default_factory=dict)

    # -- active view -----------------------------------------------------
    @property
    def active(self) -> pd.DataFrame:
        """Non-duplicate, non-transfer rows: the analytical population."""
        return self.df[(~self.df["is_duplicate"]) & (self.df["kind"] != "transfer")]

    @property
    def spending(self) -> pd.DataFrame:
        return self.active[self.active["amount"] < 0]

    def invalidate(self, *keys: str) -> None:
        if keys:
            for k in keys:
                self._cache.pop(k, None)
        else:
            self._cache.clear()

    def cached(self, key: str, producer):
        if key not in self._cache:
            self._cache[key] = producer()
        return self._cache[key]

    # -- artifacts -------------------------------------------------------
    def recurring(self):
        from app.recurring.detector import detect_recurring

        return self.cached("recurring", lambda: detect_recurring(self.active))

    def features(self):
        from app.forecasting.features import build_features

        return self.cached(
            "features",
            lambda: build_features(
                self.active,
                self.recurring(),
                liquid_savings_override=self.liquid_savings_override,
            ),
        )

    def anomalies(self):
        from app.anomaly.detector import detect_anomalies

        return self.cached("anomalies", lambda: detect_anomalies(self.spending))

    def apply_correction(self, transaction_id: str, category: str, subcategory: str | None):
        from app.categorization.rules import category_kind

        mask = self.df["transaction_id"] == transaction_id
        if not mask.any():
            return None
        self.df.loc[mask, "category"] = category
        self.df.loc[mask, "subcategory"] = subcategory
        self.df.loc[mask, "kind"] = category_kind(category)
        self.df.loc[mask, "confidence"] = 1.0
        self.df.loc[mask, "classifier"] = "user"
        self.invalidate()
        return self.df.loc[mask].iloc[0]