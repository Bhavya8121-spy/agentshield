from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from app.categorization import merchants
from app.categorization.feedback import merchant_overrides
from app.categorization.rules import category_kind, match_rules
from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

REFUND_HINTS = ("refund", "return", "reversal", "credit adj", "chargeback", "cashback")


class CategorizationEngine:
    """Hybrid classifier: user overrides -> catalog -> rules -> fuzzy -> ML -> review."""

    def __init__(self, model_path: str | None = None, min_confidence: float | None = None):
        self.model_path = Path(model_path or settings.classifier_path)
        self.min_confidence = min_confidence if min_confidence is not None else settings.classifier_min_confidence
        self.model = None
        self.classes_: list[str] = []
        self._load_model()

    def _load_model(self) -> None:
        if not self.model_path.exists():
            log.info("No ML model at %s; running rules + fuzzy only.", self.model_path)
            return
        try:
            import joblib

            self.model = joblib.load(self.model_path)
            self.classes_ = list(self.model.classes_)
            log.info("Loaded classifier (%d classes) from %s", len(self.classes_), self.model_path)
        except Exception as exc:  # noqa: BLE001
            log.warning("Failed to load classifier: %s", exc)
            self.model = None

    # ------------------------------------------------------------------ tiers
    def _deterministic(self, row: pd.Series, overrides: dict[str, str]) -> tuple[str, str | None, float, str] | None:
        merchant_key = str(row.get("merchant") or "").lower()
        if merchant_key in overrides:
            return overrides[merchant_key], None, 1.0, "override"

        clean = str(row.get("clean_description") or "")
        raw = str(row.get("raw_description") or "")

        match = merchants.lookup_exact(clean)
        if match:
            return match.category, match.subcategory, match.confidence, "catalog"

        rule = match_rules(clean, raw)
        if rule:
            category, subcategory, confidence = rule
            return category, subcategory, confidence, "rules"

        fuzzy = merchants.lookup_fuzzy(clean)
        if fuzzy:
            return fuzzy.category, fuzzy.subcategory, fuzzy.confidence, "fuzzy"
        return None

    def _ml_batch(self, frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray] | None:
        if self.model is None or frame.empty:
            return None
        try:
            probabilities = self.model.predict_proba(build_model_frame(frame))
        except Exception as exc:  # noqa: BLE001
            log.warning("ML inference failed: %s", exc)
            return None
        best = probabilities.argmax(axis=1)
        return np.array(self.classes_, dtype=object)[best], probabilities.max(axis=1)

    # ------------------------------------------------------------------ public
    def categorize(self, df: pd.DataFrame) -> pd.DataFrame:
        """Fill category / subcategory / kind / confidence / classifier in place."""
        if df.empty:
            return df

        overrides = merchant_overrides()
        out = df.copy()
        categories: list[str | None] = [None] * len(out)
        subcategories: list[str | None] = [None] * len(out)
        confidences = np.zeros(len(out))
        sources: list[str] = ["none"] * len(out)

        needs_ml: list[int] = []

        for position, (_, row) in enumerate(out.iterrows()):
            # Inflows are income unless they look like a refund or a transfer.
            if row["amount"] > 0 and row.get("kind") != "transfer":
                text = f"{row.get('clean_description','')} {row.get('raw_description','')}".lower()
                if any(hint in text for hint in REFUND_HINTS):
                    categories[position], subcategories[position] = "Income", "Refund"
                else:
                    hit = self._deterministic(row, overrides)
                    if hit and hit[0] == "Income":
                        categories[position], subcategories[position] = hit[0], hit[1]
                    else:
                        categories[position], subcategories[position] = "Income", "Deposit"
                confidences[position], sources[position] = 0.92, "sign"
                continue

            if row.get("kind") == "transfer":
                categories[position] = "Transfer"
                confidences[position], sources[position] = 0.95, "rules"
                continue

            hit = self._deterministic(row, overrides)
            if hit:
                categories[position], subcategories[position], confidences[position], sources[position] = hit
            else:
                needs_ml.append(position)

        if needs_ml:
            ml_result = self._ml_batch(out.iloc[needs_ml])
            if ml_result is not None:
                labels, scores = ml_result
                for slot, position in enumerate(needs_ml):
                    categories[position] = str(labels[slot])
                    confidences[position] = float(scores[slot])
                    sources[position] = "ml"
            else:
                for position in needs_ml:
                    categories[position] = "Uncategorized"
                    confidences[position] = 0.20
                    sources[position] = "fallback"

        out["category"] = categories
        out["subcategory"] = subcategories
        out["confidence"] = np.round(confidences, 3)
        out["classifier"] = sources

        # Review gate: low confidence never ships a hard label.
        gate = (out["confidence"] < self.min_confidence) & (~out["classifier"].isin(["override", "user"]))
        out.loc[gate, "subcategory"] = out.loc[gate, "category"].where(
            out.loc[gate, "subcategory"].isna(), out.loc[gate, "subcategory"]
        )
        out.loc[gate, "category"] = "Needs Review"

        out["kind"] = out["category"].map(category_kind)
        # Canonicalize merchant names where the catalog recognised them.
        out["merchant"] = [
            (merchants.lookup_exact(c).merchant if merchants.lookup_exact(c) else m)
            for c, m in zip(out["clean_description"].fillna(""), out["merchant"].fillna("Unknown"))
        ]
        return out


def build_model_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Feature frame consumed by the sklearn pipeline (kept in one place so
    training and inference cannot drift apart)."""
    dates = pd.to_datetime(df["date"])
    amount = df["amount"].astype(float)
    return pd.DataFrame({
        "text": (df["clean_description"].fillna("").astype(str) + " "
                 + df["merchant"].fillna("").astype(str)).str.lower(),
        "amount_abs": amount.abs(),
        "amount_log": np.log1p(amount.abs()),
        "is_round": (amount.abs() % 5 == 0).astype(int),
        "day_of_week": dates.dt.dayofweek,
        "day_of_month": dates.dt.day,
        "is_weekend": (dates.dt.dayofweek >= 5).astype(int),
    })


_engine: CategorizationEngine | None = None


def get_engine() -> CategorizationEngine:
    global _engine
    if _engine is None:
        _engine = CategorizationEngine()
    return _engine


def reset_engine() -> None:
    """Force a reload — used after training or when corrections change overrides."""
    global _engine
    _engine = None


def categorize_frame(df: pd.DataFrame) -> pd.DataFrame:
    return get_engine().categorize(df)