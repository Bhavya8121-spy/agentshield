from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from app.categorization.rules import (
    DEBT_CATEGORIES, ESSENTIAL_CATEGORIES, FIXED_CATEGORIES, is_discretionary,
)
from app.recurring.detector import RecurringReport


@dataclass
class FinancialFeatures:
    months_covered: float = 0.0
    complete_months: int = 0
    start_date: date | None = None
    end_date: date | None = None

    monthly_income_mean: float = 0.0
    monthly_income_median: float = 0.0
    monthly_income_std: float = 0.0
    income_cv: float = 0.0
    income_stability: float = 0.0        # 0..1

    monthly_outflow_mean: float = 0.0
    monthly_outflow_std: float = 0.0
    expense_cv: float = 0.0
    expense_stability: float = 0.0       # 0..1

    fixed_monthly: float = 0.0
    variable_monthly_mean: float = 0.0
    variable_monthly_std: float = 0.0
    essential_monthly: float = 0.0
    discretionary_monthly: float = 0.0
    debt_service_monthly: float = 0.0
    recurring_monthly: float = 0.0

    net_monthly_mean: float = 0.0
    net_monthly_median: float = 0.0
    net_monthly_std: float = 0.0
    savings_rate: float = 0.0
    trend_slope_monthly: float = 0.0

    current_balance: float = 0.0
    liquid_savings: float = 0.0
    balance_source: str = "estimated"
    emergency_runway_months: float = 0.0

    monthly_table: pd.DataFrame = field(default_factory=pd.DataFrame)
    net_history: list[float] = field(default_factory=list)
    category_monthly: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        skip = {"monthly_table"}
        payload = {
            key: (round(value, 4) if isinstance(value, float) else value)
            for key, value in self.__dict__.items() if key not in skip
        }
        payload["start_date"] = self.start_date.isoformat() if self.start_date else None
        payload["end_date"] = self.end_date.isoformat() if self.end_date else None
        payload["category_monthly"] = {k: round(v, 2) for k, v in self.category_monthly.items()}
        payload["net_history"] = [round(v, 2) for v in self.net_history]
        return payload


def _stability(cv: float) -> float:
    """Coefficient of variation -> 0..1 stability. CV 0 => 1.0, CV 0.5 => ~0.5."""
    return float(np.clip(1.0 / (1.0 + max(cv, 0.0) * 2.0), 0.0, 1.0))


def _monthly_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Per-calendar-month aggregates with a `complete` flag."""
    frame = df.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame["month"] = frame["date"].dt.to_period("M")
    start, end = frame["date"].min(), frame["date"].max()

    grouped = frame.groupby("month").apply(
        lambda g: pd.Series({
            "income": g.loc[g["amount"] > 0, "amount"].sum(),
            "outflow": g.loc[g["amount"] < 0, "amount"].abs().sum(),
            "fixed": g.loc[g["category"].isin(FIXED_CATEGORIES) & (g["amount"] < 0), "amount"].abs().sum(),
            "debt": g.loc[g["category"].isin(DEBT_CATEGORIES) & (g["amount"] < 0), "amount"].abs().sum(),
            "essential": g.loc[g["category"].isin(ESSENTIAL_CATEGORIES) & (g["amount"] < 0), "amount"].abs().sum(),
            "discretionary": g.loc[g["category"].map(is_discretionary) & (g["amount"] < 0), "amount"].abs().sum(),
            "transactions": len(g),
        }),
        include_groups=False,
    ).reset_index()

    grouped["variable"] = (grouped["outflow"] - grouped["fixed"]).clip(lower=0)
    grouped["net"] = grouped["income"] - grouped["outflow"]
    grouped["month_start"] = grouped["month"].dt.to_timestamp()
    grouped["month_end"] = grouped["month"].dt.to_timestamp(how="end").dt.normalize()
    grouped["complete"] = (grouped["month_start"] >= start.normalize()) & (grouped["month_end"] <= end.normalize())
    return grouped


def build_features(
    df: pd.DataFrame,
    recurring: RecurringReport | None = None,
    liquid_savings_override: float | None = None,
) -> FinancialFeatures:
    features = FinancialFeatures()
    if df is None or df.empty:
        features.warnings.append("No transactions available.")
        return features

    frame = df.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    features.start_date = frame["date"].min().date()
    features.end_date = frame["date"].max().date()
    span_days = max((features.end_date - features.start_date).days, 1)
    features.months_covered = round(span_days / 30.44, 2)

    table = _monthly_frame(frame)
    features.monthly_table = table
    complete = table[table["complete"]]
    features.complete_months = int(len(complete))

    if len(complete) >= 2:
        basis = complete
    else:
        # Prorate everything to a monthly rate rather than reporting partial sums.
        features.warnings.append(
            "Fewer than two complete calendar months; monthly figures are prorated and less reliable."
        )
        scale = 30.44 / span_days
        basis = table.copy()
        for column in ("income", "outflow", "fixed", "debt", "essential", "discretionary", "variable", "net"):
            basis[column] = basis[column].sum() * scale / max(len(table), 1)

    income = basis["income"].to_numpy(dtype=float)
    outflow = basis["outflow"].to_numpy(dtype=float)
    net = basis["net"].to_numpy(dtype=float)
    variable = basis["variable"].to_numpy(dtype=float)

    features.monthly_income_mean = float(np.mean(income))
    features.monthly_income_median = float(np.median(income))
    features.monthly_income_std = float(np.std(income, ddof=1)) if len(income) > 1 else 0.0
    features.income_cv = features.monthly_income_std / features.monthly_income_mean if features.monthly_income_mean else 0.0
    features.income_stability = _stability(features.income_cv)

    features.monthly_outflow_mean = float(np.mean(outflow))
    features.monthly_outflow_std = float(np.std(outflow, ddof=1)) if len(outflow) > 1 else 0.0
    features.expense_cv = features.monthly_outflow_std / features.monthly_outflow_mean if features.monthly_outflow_mean else 0.0
    features.expense_stability = _stability(features.expense_cv)

    features.fixed_monthly = float(np.mean(basis["fixed"]))
    features.variable_monthly_mean = float(np.mean(variable))
    features.variable_monthly_std = float(np.std(variable, ddof=1)) if len(variable) > 1 else 0.0
    features.essential_monthly = float(np.mean(basis["essential"]))
    features.discretionary_monthly = float(np.mean(basis["discretionary"]))
    features.debt_service_monthly = float(np.mean(basis["debt"]))

    features.net_monthly_mean = float(np.mean(net))
    features.net_monthly_median = float(np.median(net))
    features.net_monthly_std = float(np.std(net, ddof=1)) if len(net) > 1 else 0.0
    features.savings_rate = features.net_monthly_mean / features.monthly_income_mean if features.monthly_income_mean else 0.0
    features.net_history = [float(v) for v in complete["net"]] if len(complete) >= 2 else [features.net_monthly_mean]

    if len(net) >= 3:
        features.trend_slope_monthly = float(np.polyfit(np.arange(len(net)), net, 1)[0])

    # Recurring detector supersedes averages for debt/fixed where it is confident.
    if recurring is not None:
        features.recurring_monthly = recurring.monthly_total
        if recurring.debt_monthly > 0:
            features.debt_service_monthly = max(features.debt_service_monthly, recurring.debt_monthly)
        if recurring.fixed_monthly > 0:
            features.fixed_monthly = max(features.fixed_monthly, recurring.fixed_monthly)

    # Balance / liquidity
    if liquid_savings_override is not None:
        features.current_balance = float(liquid_savings_override)
        features.balance_source = "user_provided"
    elif "balance" in frame and frame["balance"].notna().any():
        latest = frame.loc[frame["balance"].notna()].sort_values("date").iloc[-1]
        features.current_balance = float(latest["balance"])
        features.balance_source = "statement_balance"
    else:
        features.current_balance = max(0.0, float(frame["amount"].sum()))
        features.balance_source = "estimated_from_net_flow"
        features.warnings.append(
            "No balance column found. Liquid savings estimated from net cash flow — "
            "supply your real balance for accurate runway and forecasts."
        )

    features.liquid_savings = max(0.0, features.current_balance)
    essential_burn = features.essential_monthly or features.monthly_outflow_mean
    features.emergency_runway_months = (
        features.liquid_savings / essential_burn if essential_burn > 0 else 0.0
    )

    spend = frame[frame["amount"] < 0]
    divisor = max(len(complete), 1) if len(complete) >= 2 else max(features.months_covered, 1e-6)
    features.category_monthly = (
        spend.groupby("category")["amount"].apply(lambda s: float(s.abs().sum()) / divisor)
        .sort_values(ascending=False).to_dict()
    )
    return features