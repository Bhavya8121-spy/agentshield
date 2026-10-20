from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

MIN_HISTORY_FOR_MERCHANT = 4
MIN_HISTORY_FOR_CATEGORY = 8
ROBUST_Z_THRESHOLD = 3.5        # MAD-based; ~3.5 is the conventional outlier cut
MIN_ABSOLUTE_AMOUNT = 25.0      # ignore trivial deviations
MAD_TO_SIGMA = 0.6745


@dataclass
class Anomaly:
    transaction_id: str
    date: str
    merchant: str
    category: str
    amount: float
    baseline: float
    deviation_multiple: float
    robust_z: float
    score: float
    method: str
    reason: str

    def to_dict(self) -> dict:
        return {
            "transaction_id": self.transaction_id,
            "date": self.date,
            "merchant": self.merchant,
            "category": self.category,
            "amount": round(self.amount, 2),
            "typical_amount": round(self.baseline, 2),
            "deviation_multiple": round(self.deviation_multiple, 2),
            "robust_z": round(self.robust_z, 2),
            "score": round(self.score, 3),
            "method": self.method,
            "reason": self.reason,
        }


@dataclass
class AnomalyReport:
    anomalies: list[Anomaly] = field(default_factory=list)
    transactions_scanned: int = 0
    flagged_count: int = 0
    flagged_value: float = 0.0
    methods_used: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    frame: pd.DataFrame = field(default_factory=pd.DataFrame)

    def to_dict(self) -> dict:
        return {
            "summary": {
                "transactions_scanned": self.transactions_scanned,
                "flagged_count": self.flagged_count,
                "flagged_value": round(self.flagged_value, 2),
                "flag_rate": round(self.flagged_count / self.transactions_scanned, 4)
                if self.transactions_scanned else 0.0,
                "methods_used": self.methods_used,
            },
            "anomalies": [a.to_dict() for a in self.anomalies],
            "notes": self.notes,
            "disclaimer": (
                "These are statistical outliers relative to your own history, not verified fraud. "
                "No labelled fraud data is used and no fraud claim is made."
            ),
        }


def _robust_stats(values: np.ndarray) -> tuple[float, float]:
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    sigma = mad / MAD_TO_SIGMA if mad > 0 else float(np.std(values, ddof=1)) if len(values) > 1 else 0.0
    return median, sigma


def _isolation_forest_scores(frame: pd.DataFrame) -> np.ndarray | None:
    """Multivariate second opinion. Optional — absence must not break detection."""
    if len(frame) < 40:
        return None
    try:
        from sklearn.ensemble import IsolationForest
    except ImportError:
        return None

    dates = pd.to_datetime(frame["date"])
    amount = frame["amount"].abs().to_numpy(dtype=float)
    merchant_frequency = frame.groupby("merchant")["merchant"].transform("size").to_numpy(dtype=float)
    features = np.column_stack([
        np.log1p(amount),
        dates.dt.dayofweek.to_numpy(dtype=float),
        dates.dt.day.to_numpy(dtype=float),
        np.log1p(merchant_frequency),
    ])
    try:
        model = IsolationForest(n_estimators=200, contamination=0.02, random_state=7)
        raw = model.fit(features).score_samples(features)
    except Exception:  # noqa: BLE001
        return None
    # score_samples: lower = more anomalous. Rescale to 0..1 where 1 = most anomalous.
    span = raw.max() - raw.min()
    return (raw.max() - raw) / span if span > 0 else np.zeros(len(raw))


def detect_anomalies(spending: pd.DataFrame, top_n: int = 25) -> AnomalyReport:
    report = AnomalyReport()
    if spending is None or spending.empty:
        report.notes.append("No spending transactions to scan.")
        return report

    frame = spending.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame["abs_amount"] = frame["amount"].abs()
    report.transactions_scanned = len(frame)

    scores = np.zeros(len(frame))
    z_values = np.zeros(len(frame))
    baselines = frame["abs_amount"].to_numpy(dtype=float).copy()
    methods: list[str] = ["none"] * len(frame)
    reasons: list[str] = [""] * len(frame)

    positions = {tid: index for index, tid in enumerate(frame["transaction_id"])}

    # --- Tier 1: within-merchant deviation (strongest signal) ---------------
    for merchant, group in frame.groupby("merchant"):
        if len(group) < MIN_HISTORY_FOR_MERCHANT:
            continue
        values = group["abs_amount"].to_numpy(dtype=float)
        median, sigma = _robust_stats(values)
        if sigma <= 0 or median <= 0:
            continue
        for transaction_id, amount in zip(group["transaction_id"], values):
            z = (amount - median) / sigma
            if z > ROBUST_Z_THRESHOLD and amount >= MIN_ABSOLUTE_AMOUNT:
                index = positions[transaction_id]
                z_values[index] = z
                baselines[index] = median
                scores[index] = min(0.99, 0.55 + 0.09 * (z - ROBUST_Z_THRESHOLD))
                methods[index] = "merchant_robust_z"
                reasons[index] = (
                    f"${amount:,.0f} against a typical ${median:,.0f} at {merchant} "
                    f"({amount / median:.1f}× usual across {len(values)} visits)"
                )

    # --- Tier 2: within-category deviation for unfamiliar merchants ---------
    for category, group in frame.groupby("category"):
        if len(group) < MIN_HISTORY_FOR_CATEGORY:
            continue
        values = group["abs_amount"].to_numpy(dtype=float)
        median, sigma = _robust_stats(values)
        if sigma <= 0 or median <= 0:
            continue
        for transaction_id, amount, merchant in zip(group["transaction_id"], values, group["merchant"]):
            index = positions[transaction_id]
            if methods[index] != "none":
                continue
            z = (amount - median) / sigma
            if z > ROBUST_Z_THRESHOLD and amount >= MIN_ABSOLUTE_AMOUNT:
                z_values[index] = z
                baselines[index] = median
                scores[index] = min(0.95, 0.50 + 0.08 * (z - ROBUST_Z_THRESHOLD))
                methods[index] = "category_robust_z"
                reasons[index] = (
                    f"${amount:,.0f} at {merchant} against a typical {category} spend of ${median:,.0f}"
                )

    # --- Tier 3: multivariate confirmation ---------------------------------
    forest = _isolation_forest_scores(frame)
    if forest is not None:
        report.methods_used.append("isolation_forest")
        for index in range(len(frame)):
            if forest[index] > 0.85 and frame["abs_amount"].iat[index] >= MIN_ABSOLUTE_AMOUNT:
                if methods[index] == "none":
                    methods[index] = "isolation_forest"
                    scores[index] = 0.50 + 0.35 * (forest[index] - 0.85) / 0.15
                    baselines[index] = float(frame["abs_amount"].median())
                    reasons[index] = (
                        "Unusual combination of amount, timing and merchant frequency "
                        "relative to the rest of your history"
                    )
                else:
                    # Agreement between methods raises confidence.
                    scores[index] = min(0.99, scores[index] + 0.08)
                    methods[index] += "+isolation_forest"

    report.methods_used = ["merchant_robust_z", "category_robust_z"] + report.methods_used

    frame["anomaly_score"] = np.round(scores, 3)
    frame["is_anomaly"] = scores > 0
    report.frame = frame[["transaction_id", "anomaly_score", "is_anomaly"]]

    flagged = frame[frame["is_anomaly"]].copy()
    flagged["_score"] = scores[frame["is_anomaly"].to_numpy()]
    flagged = flagged.sort_values("_score", ascending=False).head(top_n)

    for row in flagged.itertuples(index=False):
        index = positions[row.transaction_id]
        report.anomalies.append(Anomaly(
            transaction_id=row.transaction_id,
            date=row.date.date().isoformat(),
            merchant=str(row.merchant),
            category=str(row.category),
            amount=float(row.abs_amount),
            baseline=float(baselines[index]),
            deviation_multiple=float(row.abs_amount / baselines[index]) if baselines[index] else 0.0,
            robust_z=float(z_values[index]),
            score=float(scores[index]),
            method=methods[index],
            reason=reasons[index],
        ))

    report.flagged_count = int(frame["is_anomaly"].sum())
    report.flagged_value = float(frame.loc[frame["is_anomaly"], "abs_amount"].sum())

    if report.transactions_scanned < 50:
        report.notes.append(
            "Fewer than 50 transactions scanned — baselines are thin and false positives are likely."
        )
    if report.flagged_count == 0:
        report.notes.append("No statistical outliers found against your own spending baselines.")
    return report