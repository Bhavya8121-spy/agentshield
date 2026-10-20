from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from app.categorization.rules import DEBT_CATEGORIES, category_kind, is_discretionary

# frequency -> (expected interval days, tolerance days)
FREQUENCIES: list[tuple[str, float, float]] = [
    ("weekly", 7, 2.0),
    ("biweekly", 14, 3.0),
    ("semimonthly", 15.2, 3.0),
    ("monthly", 30.44, 5.0),
    ("bimonthly", 60.9, 8.0),
    ("quarterly", 91.3, 12.0),
    ("semiannual", 182.6, 20.0),
    ("annual", 365.25, 30.0),
]
PER_MONTH = {"weekly": 4.33, "biweekly": 2.17, "semimonthly": 2.0, "monthly": 1.0,
             "bimonthly": 0.5, "quarterly": 1 / 3, "semiannual": 1 / 6, "annual": 1 / 12}

MIN_OCCURRENCES = 3
MIN_CONFIDENCE = 0.55
AMOUNT_CLUSTER_TOLERANCE = 0.35   # relative gap that splits an amount cluster


@dataclass
class RecurringSeries:
    merchant: str
    category: str
    kind: str
    direction: str
    frequency: str
    interval_days: float
    occurrences: int
    amount_median: float
    amount_std: float
    amount_cv: float
    monthly_amount: float
    annual_amount: float
    first_date: date
    last_date: date
    next_expected: date | None
    confidence: float
    discretionary: bool
    debt_obligation: bool
    active: bool
    transaction_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        payload = asdict(self)
        for key in ("first_date", "last_date", "next_expected"):
            payload[key] = payload[key].isoformat() if payload[key] else None
        return payload


@dataclass
class RecurringReport:
    series: list[RecurringSeries] = field(default_factory=list)
    monthly_total: float = 0.0
    annual_total: float = 0.0
    fixed_monthly: float = 0.0
    debt_monthly: float = 0.0
    discretionary_monthly: float = 0.0
    discretionary_annual: float = 0.0
    income_monthly: float = 0.0
    outflow_coverage: float = 0.0     # share of outflow explained by recurring series
    detected_count: int = 0

    @property
    def expenses(self) -> list[RecurringSeries]:
        return [s for s in self.series if s.direction == "debit"]

    @property
    def income(self) -> list[RecurringSeries]:
        return [s for s in self.series if s.direction == "credit"]

    def to_dict(self) -> dict:
        return {
            "summary": {
                "monthly_total": round(self.monthly_total, 2),
                "annual_total": round(self.annual_total, 2),
                "fixed_monthly": round(self.fixed_monthly, 2),
                "debt_monthly": round(self.debt_monthly, 2),
                "discretionary_monthly": round(self.discretionary_monthly, 2),
                "discretionary_annual": round(self.discretionary_annual, 2),
                "recurring_income_monthly": round(self.income_monthly, 2),
                "outflow_coverage": round(self.outflow_coverage, 3),
                "series_detected": self.detected_count,
            },
            "expenses": [s.to_dict() for s in self.expenses],
            "income": [s.to_dict() for s in self.income],
        }


# --------------------------------------------------------------------- helpers
def _cluster_amounts(amounts: np.ndarray) -> np.ndarray:
    """Split sorted amounts where the relative gap exceeds the tolerance.
    Returns a cluster label per input position."""
    order = np.argsort(amounts)
    labels = np.zeros(len(amounts), dtype=int)
    current = 0
    for index in range(1, len(order)):
        previous, this = amounts[order[index - 1]], amounts[order[index]]
        reference = max(abs(previous), 1.0)
        if abs(this - previous) / reference > AMOUNT_CLUSTER_TOLERANCE:
            current += 1
        labels[order[index]] = current
    return labels


def _classify_interval(intervals: np.ndarray) -> tuple[str | None, float, float]:
    """Return (frequency, median interval, regularity in 0..1)."""
    if len(intervals) == 0:
        return None, 0.0, 0.0
    median = float(np.median(intervals))
    deviation = float(np.median(np.abs(intervals - median)))  # MAD, outlier-robust

    best, best_score = None, 0.0
    for name, expected, tolerance in FREQUENCIES:
        offset = abs(median - expected)
        if offset <= tolerance:
            score = 1.0 - offset / tolerance
            if score > best_score:
                best, best_score = name, score

    regularity = 1.0 / (1.0 + deviation / max(median * 0.15, 1.0))
    if best is None:
        return None, median, regularity
    return best, median, min(1.0, 0.5 * best_score + 0.5 * regularity)


def _confidence(occurrences: int, regularity: float, amount_cv: float) -> float:
    count_factor = min(1.0, (occurrences - MIN_OCCURRENCES + 1) / 4.0) * 0.35 + 0.65
    amount_factor = 1.0 / (1.0 + amount_cv * 4.0)
    return round(float(np.clip(regularity * count_factor * (0.55 + 0.45 * amount_factor), 0, 0.99)), 3)


# ------------------------------------------------------------------ entrypoint
def detect_recurring(df: pd.DataFrame, as_of: date | None = None) -> RecurringReport:
    report = RecurringReport()
    if df is None or df.empty:
        return report

    frame = df.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    as_of = as_of or frame["date"].max().date()
    total_outflow = float(frame.loc[frame["amount"] < 0, "amount"].abs().sum())

    for (merchant, direction), group in frame.groupby(
        [frame["merchant"].fillna("Unknown"), frame["direction"]], sort=False
    ):
        if len(group) < MIN_OCCURRENCES:
            continue

        group = group.sort_values("date")
        amounts = group["amount"].abs().to_numpy(dtype=float)
        for cluster in np.unique(_cluster_amounts(amounts)):
            subset = group[_cluster_amounts(amounts) == cluster]
            if len(subset) < MIN_OCCURRENCES:
                continue

            # Collapse same-day duplicates before measuring intervals.
            days = np.array(sorted({d.date() for d in subset["date"]}))
            if len(days) < MIN_OCCURRENCES:
                continue
            intervals = np.array([(days[i] - days[i - 1]).days for i in range(1, len(days))], dtype=float)

            frequency, median_interval, regularity = _classify_interval(intervals)
            if frequency is None:
                continue

            values = subset["amount"].abs().to_numpy(dtype=float)
            median_amount = float(np.median(values))
            std_amount = float(np.std(values, ddof=1)) if len(values) > 1 else 0.0
            amount_cv = std_amount / median_amount if median_amount else 0.0
            confidence = _confidence(len(days), regularity, amount_cv)
            if confidence < MIN_CONFIDENCE:
                continue

            last_seen = days[-1]
            next_expected = last_seen + timedelta(days=round(median_interval))
            # A series is stale if it has missed roughly two cycles.
            active = (as_of - last_seen).days <= median_interval * 2 + 7

            category = str(subset["category"].mode().iat[0]) if not subset["category"].isna().all() else "Uncategorized"
            monthly = median_amount * PER_MONTH.get(frequency, 1.0)

            report.series.append(RecurringSeries(
                merchant=str(merchant),
                category=category,
                kind=category_kind(category),
                direction=str(direction),
                frequency=frequency,
                interval_days=round(median_interval, 1),
                occurrences=len(days),
                amount_median=round(median_amount, 2),
                amount_std=round(std_amount, 2),
                amount_cv=round(amount_cv, 3),
                monthly_amount=round(monthly, 2),
                annual_amount=round(monthly * 12, 2),
                first_date=days[0],
                last_date=last_seen,
                next_expected=next_expected if active else None,
                confidence=confidence,
                discretionary=is_discretionary(category),
                debt_obligation=category in DEBT_CATEGORIES,
                active=active,
                transaction_ids=subset["transaction_id"].tolist(),
            ))

    report.series.sort(key=lambda s: -s.monthly_amount)
    report.detected_count = len(report.series)

    active_expenses = [s for s in report.expenses if s.active]
    report.monthly_total = sum(s.monthly_amount for s in active_expenses)
    report.annual_total = report.monthly_total * 12
    report.fixed_monthly = sum(s.monthly_amount for s in active_expenses if s.kind == "fixed")
    report.debt_monthly = sum(s.monthly_amount for s in active_expenses if s.debt_obligation)
    report.discretionary_monthly = sum(s.monthly_amount for s in active_expenses if s.discretionary)
    report.discretionary_annual = report.discretionary_monthly * 12
    report.income_monthly = sum(s.monthly_amount for s in report.income if s.active)

    explained = sum(sum(abs(a) for a in [s.amount_median] * s.occurrences) for s in active_expenses)
    report.outflow_coverage = min(1.0, explained / total_outflow) if total_outflow else 0.0
    return report