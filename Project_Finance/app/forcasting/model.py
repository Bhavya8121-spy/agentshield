from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from app.core.config import settings
from app.core.exceptions import InsufficientHistory
from app.forecasting.features import FinancialFeatures, build_features
from app.recurring.detector import detect_recurring

Z_SCORES = {0.50: 0.674, 0.68: 1.0, 0.80: 1.282, 0.90: 1.645, 0.95: 1.96}
TREND_DAMPING = 0.6          # trend is unreliable on short history; shrink it
MIN_SIGMA_FRACTION = 0.06    # never claim near-zero uncertainty
BOOTSTRAP_MIN_MONTHS = 4
BOOTSTRAP_DRAWS = 4000


@dataclass
class HorizonForecast:
    days: int
    months: float
    expected_net: float
    balance: float
    lower: float
    upper: float
    p10: float
    p90: float
    probability_negative: float

    def to_dict(self) -> dict:
        return {
            "days": self.days,
            "expected_net_change": round(self.expected_net, 2),
            "balance": round(self.balance, 2),
            "lower": round(self.lower, 2),
            "upper": round(self.upper, 2),
            "p10": round(self.p10, 2),
            "p90": round(self.p90, 2),
            "probability_negative_balance": round(self.probability_negative, 4),
        }


@dataclass
class ForecastResult:
    horizons: dict[str, HorizonForecast] = field(default_factory=dict)
    method: str = "baseline"
    confidence_level: float = 0.80
    starting_balance: float = 0.0
    monthly_net_expected: float = 0.0
    monthly_net_sigma: float = 0.0
    daily_path: list[dict] = field(default_factory=list)
    drivers: dict = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "confidence_level": self.confidence_level,
            "starting_balance": round(self.starting_balance, 2),
            "monthly_net_expected": round(self.monthly_net_expected, 2),
            "monthly_net_sigma": round(self.monthly_net_sigma, 2),
            "horizons": {k: v.to_dict() for k, v in self.horizons.items()},
            "daily_path": self.daily_path,
            "drivers": self.drivers,
            "assumptions": self.assumptions,
        }


class BaselineForecaster:
    """Additive cash-flow model:

        net_month = recurring_income + irregular_income - fixed - E[variable]

    Uncertainty is the dispersion of historical monthly nets, scaled by sqrt(h)
    under an independent-months assumption.
    """

    def __init__(self, confidence: float | None = None, damping: float = TREND_DAMPING):
        self.confidence = confidence or settings.forecast_confidence
        self.damping = damping
        self.features: FinancialFeatures | None = None
        self._sigma: float = 0.0
        self._samples: np.ndarray | None = None

    def fit(self, df: pd.DataFrame, features: FinancialFeatures | None = None) -> "BaselineForecaster":
        if features is None:
            if df is None or df.empty:
                raise InsufficientHistory("No transactions to forecast from.")
            features = build_features(df, detect_recurring(df))
        self.features = features

        history = np.array(features.net_history, dtype=float)
        floor = max(abs(features.monthly_income_mean) * MIN_SIGMA_FRACTION, 25.0)

        if len(history) >= BOOTSTRAP_MIN_MONTHS:
            self._samples = history
            self._sigma = max(float(np.std(history, ddof=1)), floor)
        else:
            self._samples = None
            self._sigma = max(features.net_monthly_std, features.variable_monthly_std, floor)
        return self

    # -------------------------------------------------------------- internals
    def _expected_monthly_net(self, month_index: int) -> float:
        f = self.features
        base = f.net_monthly_mean
        if f.complete_months >= 3:
            base = 0.7 * f.net_monthly_mean + 0.3 * f.net_monthly_median
        trend = self.damping * f.trend_slope_monthly * month_index
        # Trend is capped so a single anomalous month cannot run away over 90 days.
        trend = float(np.clip(trend, -abs(base) * 0.5 - 200, abs(base) * 0.5 + 200))
        return base + trend

    def _horizon_distribution(self, months: float) -> tuple[float, float, np.ndarray | None]:
        steps = max(int(round(months)), 1)
        expected = sum(self._expected_monthly_net(i) for i in range(1, steps + 1))
        if months != steps:                                  # partial month
            expected += self._expected_monthly_net(steps + 1) * (months - steps)

        sigma = self._sigma * np.sqrt(months)

        draws = None
        if self._samples is not None and len(self._samples) >= BOOTSTRAP_MIN_MONTHS:
            rng = np.random.default_rng(17)
            resampled = rng.choice(self._samples, size=(BOOTSTRAP_DRAWS, steps), replace=True)
            drift = np.array([self._expected_monthly_net(i) - float(np.mean(self._samples))
                              for i in range(1, steps + 1)])
            draws = (resampled + drift).sum(axis=1)
            if months != steps:
                draws = draws + rng.choice(self._samples, size=BOOTSTRAP_DRAWS) * (months - steps)
        return expected, sigma, draws

    # ------------------------------------------------------------------ public
    def predict(self, days: int) -> HorizonForecast:
        if self.features is None:
            raise InsufficientHistory("Call fit() before predict().")
        months = days / 30.44
        expected, sigma, draws = self._horizon_distribution(months)
        start = self.features.liquid_savings
        z = Z_SCORES.get(round(self.confidence, 2), 1.282)

        if draws is not None:
            balances = start + draws
            lower_q, upper_q = (1 - self.confidence) / 2, 1 - (1 - self.confidence) / 2
            lower, upper = np.quantile(balances, [lower_q, upper_q])
            p10, p90 = np.quantile(balances, [0.10, 0.90])
            probability_negative = float((balances < 0).mean())
        else:
            balance = start + expected
            lower, upper = balance - z * sigma, balance + z * sigma
            p10, p90 = balance - 1.282 * sigma, balance + 1.282 * sigma
            probability_negative = float(_normal_cdf(-balance / sigma)) if sigma > 0 else float(balance < 0)

        return HorizonForecast(
            days=days, months=round(months, 2), expected_net=expected,
            balance=start + expected, lower=float(lower), upper=float(upper),
            p10=float(p10), p90=float(p90), probability_negative=probability_negative,
        )

    def daily_path(self, days: int, as_of: date | None = None) -> list[dict]:
        """Weekly-resolution expected balance with a fan, for charting."""
        f = self.features
        as_of = as_of or f.end_date or date.today()
        z = Z_SCORES.get(round(self.confidence, 2), 1.282)
        path = []
        for offset in range(0, days + 1, 7):
            months = offset / 30.44
            expected, sigma, _ = self._horizon_distribution(months) if months else (0.0, 0.0, None)
            balance = f.liquid_savings + expected
            path.append({
                "date": (as_of + timedelta(days=offset)).isoformat(),
                "day": offset,
                "expected": round(balance, 2),
                "lower": round(balance - z * sigma, 2),
                "upper": round(balance + z * sigma, 2),
            })
        return path

    def forecast(self, horizons: tuple[int, ...] = (30, 60, 90)) -> ForecastResult:
        f = self.features
        result = ForecastResult(
            method="bootstrap_monthly_net" if self._samples is not None else "parametric_normal",
            confidence_level=self.confidence,
            starting_balance=f.liquid_savings,
            monthly_net_expected=f.net_monthly_mean,
            monthly_net_sigma=self._sigma,
        )
        for days in horizons:
            result.horizons[f"{days}_day"] = self.predict(days)
        result.daily_path = self.daily_path(max(horizons))
        result.drivers = {
            "monthly_income": round(f.monthly_income_mean, 2),
            "fixed_expenses": round(f.fixed_monthly, 2),
            "variable_expenses": round(f.variable_monthly_mean, 2),
            "recurring_expenses": round(f.recurring_monthly, 2),
            "trend_per_month": round(f.trend_slope_monthly * self.damping, 2),
            "months_of_history": f.complete_months,
        }
        result.assumptions = [
            f"Starting balance ${f.liquid_savings:,.0f} ({f.balance_source.replace('_', ' ')}).",
            "Income and expense behaviour continues at recent levels.",
            "Monthly outcomes treated as independent; intervals scale with the square root of the horizon.",
            f"Trend damped to {self.damping:.0%} and capped to limit extrapolation.",
            f"Intervals are {self.confidence:.0%} ranges, not guarantees.",
        ] + f.warnings
        return result


def _normal_cdf(x: float) -> float:
    from math import erf, sqrt

    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def forecast_dataset(df: pd.DataFrame, features=None, horizons=(30, 60, 90),
                     confidence: float | None = None) -> ForecastResult:
    return BaselineForecaster(confidence=confidence).fit(df, features).forecast(horizons)