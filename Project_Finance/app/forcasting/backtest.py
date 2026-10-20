from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.core.exceptions import InsufficientHistory
from app.forecasting.features import build_features
from app.forecasting.model import BaselineForecaster
from app.recurring.detector import detect_recurring

MIN_TRAIN_MONTHS = 3


@dataclass
class FoldResult:
    cutoff: str
    horizon_days: int
    train_months: int
    predicted_net: float
    actual_net: float
    predicted_balance: float
    actual_balance: float
    lower: float
    upper: float

    @property
    def error(self) -> float:
        return self.predicted_net - self.actual_net

    @property
    def within_interval(self) -> bool:
        return self.lower <= self.actual_balance <= self.upper

    @property
    def direction_correct(self) -> bool:
        return np.sign(self.predicted_net) == np.sign(self.actual_net)


@dataclass
class HorizonMetrics:
    horizon_days: int
    folds: int
    mae: float
    rmse: float
    mape: float | None
    bias: float
    directional_accuracy: float
    interval_coverage: float
    naive_last_month_mae: float
    naive_mean_mae: float

    @property
    def skill_vs_last_month(self) -> float:
        """1 - (model MAE / naive MAE). Positive means the model adds value."""
        return round(1 - self.mae / self.naive_last_month_mae, 4) if self.naive_last_month_mae else 0.0

    def to_dict(self) -> dict:
        return {
            "horizon_days": self.horizon_days,
            "folds": self.folds,
            "mae": round(self.mae, 2),
            "rmse": round(self.rmse, 2),
            "mape": round(self.mape, 4) if self.mape is not None else None,
            "bias": round(self.bias, 2),
            "directional_accuracy": round(self.directional_accuracy, 4),
            "interval_coverage": round(self.interval_coverage, 4),
            "naive_last_month_mae": round(self.naive_last_month_mae, 2),
            "naive_mean_mae": round(self.naive_mean_mae, 2),
            "skill_vs_last_month": self.skill_vs_last_month,
        }


@dataclass
class BacktestReport:
    metrics: dict[str, HorizonMetrics] = field(default_factory=dict)
    folds: list[FoldResult] = field(default_factory=list)
    months_available: int = 0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "months_available": self.months_available,
            "metrics": {k: v.to_dict() for k, v in self.metrics.items()},
            "folds": [
                {
                    "cutoff": f.cutoff, "horizon_days": f.horizon_days,
                    "train_months": f.train_months,
                    "predicted_net": round(f.predicted_net, 2),
                    "actual_net": round(f.actual_net, 2),
                    "error": round(f.error, 2),
                    "within_interval": f.within_interval,
                }
                for f in self.folds
            ],
            "notes": self.notes,
        }


def _monthly_nets(df: pd.DataFrame) -> pd.Series:
    frame = df.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    monthly = frame.groupby(frame["date"].dt.to_period("M"))["amount"].sum()
    # Drop partial edge months so a truncated month is not scored as a bad forecast.
    start, end = frame["date"].min(), frame["date"].max()
    keep = [
        period for period in monthly.index
        if period.to_timestamp() >= start.normalize()
        and period.to_timestamp(how="end").normalize() <= end.normalize()
    ]
    return monthly.loc[keep]


def walk_forward(
    df: pd.DataFrame,
    horizons_months: tuple[int, ...] = (1, 2, 3),
    min_train_months: int = MIN_TRAIN_MONTHS,
    confidence: float = 0.80,
) -> BacktestReport:
    report = BacktestReport()
    if df is None or df.empty:
        raise InsufficientHistory("No transactions to backtest.")

    frame = df.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    nets = _monthly_nets(frame)
    periods = list(nets.index)
    report.months_available = len(periods)

    if len(periods) < min_train_months + 1:
        report.notes.append(
            f"Need at least {min_train_months + 1} complete months to backtest; found {len(periods)}."
        )
        return report

    for horizon_months in horizons_months:
        horizon_days = int(round(horizon_months * 30.44))
        errors, actuals, covered, directions = [], [], [], []
        naive_last, naive_mean = [], []

        for split in range(min_train_months, len(periods) - horizon_months + 1):
            train_periods = periods[:split]
            test_periods = periods[split:split + horizon_months]
            if len(test_periods) < horizon_months:
                break

            cutoff = train_periods[-1].to_timestamp(how="end")
            train = frame[frame["date"] <= cutoff]
            if train.empty:
                continue

            features = build_features(train, detect_recurring(train))
            try:
                forecaster = BaselineForecaster(confidence=confidence).fit(train, features)
                prediction = forecaster.predict(horizon_days)
            except InsufficientHistory:
                continue

            actual_net = float(nets.loc[test_periods].sum())
            actual_balance = features.liquid_savings + actual_net

            fold = FoldResult(
                cutoff=str(train_periods[-1]),
                horizon_days=horizon_days,
                train_months=len(train_periods),
                predicted_net=prediction.expected_net,
                actual_net=actual_net,
                predicted_balance=prediction.balance,
                actual_balance=actual_balance,
                lower=prediction.lower,
                upper=prediction.upper,
            )
            report.folds.append(fold)
            errors.append(fold.error)
            actuals.append(actual_net)
            covered.append(fold.within_interval)
            directions.append(fold.direction_correct)

            # --- baselines the model must beat to be worth anything -------
            last_month = float(nets.loc[train_periods[-1]])
            naive_last.append(last_month * horizon_months - actual_net)
            mean_month = float(nets.loc[train_periods].mean())
            naive_mean.append(mean_month * horizon_months - actual_net)

        if not errors:
            report.notes.append(f"No scorable folds at the {horizon_days}-day horizon.")
            continue

        error_array = np.array(errors, dtype=float)
        actual_array = np.array(actuals, dtype=float)
        scorable = np.abs(actual_array) > 1e-6
        mape = (
            float(np.mean(np.abs(error_array[scorable] / actual_array[scorable])))
            if scorable.any() else None
        )

        report.metrics[f"{horizon_days}_day"] = HorizonMetrics(
            horizon_days=horizon_days,
            folds=len(error_array),
            mae=float(np.mean(np.abs(error_array))),
            rmse=float(np.sqrt(np.mean(error_array ** 2))),
            mape=mape,
            bias=float(np.mean(error_array)),
            directional_accuracy=float(np.mean(directions)),
            interval_coverage=float(np.mean(covered)),
            naive_last_month_mae=float(np.mean(np.abs(naive_last))),
            naive_mean_mae=float(np.mean(np.abs(naive_mean))),
        )

    if report.metrics:
        best = max(report.metrics.values(), key=lambda m: m.skill_vs_last_month)
        if best.skill_vs_last_month <= 0:
            report.notes.append(
                "The model does not beat the naive last-month baseline on this dataset. "
                "Report the baseline alongside the model rather than hiding it."
            )
        target = report.metrics[next(iter(report.metrics))]
        if abs(target.interval_coverage - confidence) > 0.15:
            report.notes.append(
                f"Interval coverage ({target.interval_coverage:.0%}) deviates from the nominal "
                f"{confidence:.0%} level — intervals are likely mis-calibrated on this history length."
            )
    return report


def backtest_summary_markdown(report: BacktestReport) -> str:
    """Render a report table suitable for pasting into the README."""
    if not report.metrics:
        return "_Insufficient history to backtest._"
    lines = [
        "| Horizon | Folds | MAE | RMSE | MAPE | Dir. acc. | Coverage | Naive MAE | Skill |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for metric in report.metrics.values():
        mape = f"{metric.mape:.1%}" if metric.mape is not None else "n/a"
        lines.append(
            f"| {metric.horizon_days}d | {metric.folds} | ${metric.mae:,.0f} | "
            f"${metric.rmse:,.0f} | {mape} | {metric.directional_accuracy:.0%} | "
            f"{metric.interval_coverage:.0%} | ${metric.naive_last_month_mae:,.0f} | "
            f"{metric.skill_vs_last_month:+.1%} |"
        )
    return "\n".join(lines)