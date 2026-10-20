from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from pydantic import BaseModel, Field

from app.core.config import settings
from app.forecasting.features import FinancialFeatures
from app.recurring.detector import RecurringReport

SHOCK_MONTHLY_PROBABILITY = 0.04     # ~1 unexpected expense every 2 years
SHOCK_MEAN = 1_800.0
SHOCK_SIGMA = 0.7                    # lognormal shape


class MonteCarloRequest(BaseModel):
    months: int = Field(default=12, ge=1, le=120)
    runs: int = Field(default=settings.monte_carlo_runs, ge=200, le=settings.monte_carlo_max_runs)
    savings_goal: float | None = Field(default=None, ge=0)
    income_shock_probability: float = Field(default=0.0, ge=0, le=1)
    income_shock_multiplier: float = Field(default=1.0, ge=0, le=1)
    monthly_contribution: float = Field(default=0.0)
    seed: int | None = 42


@dataclass
class MonteCarloResult:
    months: int
    runs: int
    starting_balance: float
    median_ending: float
    mean_ending: float
    p10: float
    p25: float
    p75: float
    p90: float
    probability_negative: float
    probability_below_three_months: float
    probability_goal_met: float | None
    worst_case_month: int
    percentile_paths: list[dict] = field(default_factory=list)
    histogram: dict = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "months": self.months,
            "runs": self.runs,
            "starting_balance": round(self.starting_balance, 2),
            "outcomes": {
                "median_ending_balance": round(self.median_ending, 2),
                "mean_ending_balance": round(self.mean_ending, 2),
                "p10": round(self.p10, 2),
                "p25": round(self.p25, 2),
                "p75": round(self.p75, 2),
                "p90": round(self.p90, 2),
            },
            "probabilities": {
                "negative_balance_at_any_point": round(self.probability_negative, 4),
                "reserves_below_three_months": round(self.probability_below_three_months, 4),
                "savings_goal_met": (
                    round(self.probability_goal_met, 4) if self.probability_goal_met is not None else None
                ),
            },
            "most_likely_shortfall_month": self.worst_case_month,
            "percentile_paths": self.percentile_paths,
            "histogram": self.histogram,
            "assumptions": self.assumptions,
        }


def _sample_income(rng, features: FinancialFeatures, shape: tuple[int, int]) -> np.ndarray:
    mean = features.monthly_income_mean
    sigma = max(features.monthly_income_std, mean * 0.03)
    if len(features.net_history) >= 4 and mean > 0:
        # Bootstrap preserves real-world skew (bonuses, missed paychecks).
        observed = np.array(features.monthly_table["income"], dtype=float)
        observed = observed[observed > 0]
        if len(observed) >= 4:
            return rng.choice(observed, size=shape, replace=True)
    return np.maximum(rng.normal(mean, sigma, size=shape), 0.0)


def _sample_variable(rng, features: FinancialFeatures, shape: tuple[int, int]) -> np.ndarray:
    mean = max(features.variable_monthly_mean, 0.0)
    if mean <= 0:
        return np.zeros(shape)
    sigma = max(features.variable_monthly_std, mean * 0.10)
    # Lognormal: variable spend has a floor of zero and a long right tail.
    variance_ratio = (sigma / mean) ** 2
    mu = np.log(mean) - 0.5 * np.log1p(variance_ratio)
    shape_param = np.sqrt(np.log1p(variance_ratio))
    return rng.lognormal(mu, shape_param, size=shape)


def run_monte_carlo(
    features: FinancialFeatures,
    recurring: RecurringReport | None = None,
    request: MonteCarloRequest | None = None,
) -> MonteCarloResult:
    request = request or MonteCarloRequest()
    rng = np.random.default_rng(request.seed)
    runs, months = request.runs, request.months
    shape = (runs, months)

    income = _sample_income(rng, features, shape)
    if request.income_shock_probability > 0:
        hit = rng.random(shape) < request.income_shock_probability
        income = np.where(hit, income * request.income_shock_multiplier, income)

    fixed = float(recurring.fixed_monthly if recurring and recurring.fixed_monthly > 0
                  else features.fixed_monthly)
    variable = _sample_variable(rng, features, shape)

    shocks = (rng.random(shape) < SHOCK_MONTHLY_PROBABILITY) * rng.lognormal(
        np.log(SHOCK_MEAN) - 0.5 * SHOCK_SIGMA ** 2, SHOCK_SIGMA, size=shape
    )

    net = income - fixed - variable - shocks + request.monthly_contribution
    balances = features.liquid_savings + np.cumsum(net, axis=1)

    ending = balances[:, -1]
    essential = features.essential_monthly or features.monthly_outflow_mean or 1.0
    percentiles = np.percentile(balances, [10, 25, 50, 75, 90], axis=0)

    counts, edges = np.histogram(ending, bins=30)

    return MonteCarloResult(
        months=months,
        runs=runs,
        starting_balance=features.liquid_savings,
        median_ending=float(np.median(ending)),
        mean_ending=float(np.mean(ending)),
        p10=float(np.percentile(ending, 10)),
        p25=float(np.percentile(ending, 25)),
        p75=float(np.percentile(ending, 75)),
        p90=float(np.percentile(ending, 90)),
        probability_negative=float((balances.min(axis=1) < 0).mean()),
        probability_below_three_months=float((ending < essential * 3).mean()),
        probability_goal_met=(
            float((ending >= request.savings_goal).mean()) if request.savings_goal is not None else None
        ),
        worst_case_month=int(np.argmin(percentiles[0]) + 1),
        percentile_paths=[
            {
                "month": index + 1,
                "p10": round(float(percentiles[0][index]), 2),
                "p25": round(float(percentiles[1][index]), 2),
                "median": round(float(percentiles[2][index]), 2),
                "p75": round(float(percentiles[3][index]), 2),
                "p90": round(float(percentiles[4][index]), 2),
            }
            for index in range(months)
        ],
        histogram={
            "bin_edges": [round(float(e), 2) for e in edges],
            "counts": [int(c) for c in counts],
        },
        assumptions=[
            f"{runs:,} simulated {months}-month paths.",
            "Income resampled from your observed monthly totals where enough history exists, "
            "otherwise drawn from a normal distribution.",
            "Variable spending drawn from a lognormal distribution (zero floor, long right tail).",
            f"Fixed commitments held at ${fixed:,.0f}/mo.",
            f"Unexpected expenses occur with {SHOCK_MONTHLY_PROBABILITY:.0%} monthly probability, "
            f"averaging ${SHOCK_MEAN:,.0f}.",
            "Assumes no behavioural response to a shortfall — real people cut spending, so "
            "downside probabilities are deliberately pessimistic.",
        ] + features.warnings,
    )