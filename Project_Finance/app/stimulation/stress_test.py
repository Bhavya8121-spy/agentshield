from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from app.core.exceptions import ValidationFailure
from app.forecasting.features import FinancialFeatures
from app.recurring.detector import RecurringReport


class ScenarioSpec(BaseModel):
    key: str = "custom"
    label: str = "Custom scenario"
    description: str = ""
    income_multiplier: float = Field(default=1.0, ge=0, le=5)
    duration_months: int = Field(default=3, ge=1, le=60)
    horizon_months: int = Field(default=12, ge=1, le=120)
    one_time_expense: float = Field(default=0.0, ge=0)
    fixed_expense_delta: float = Field(default=0.0)          # absolute $/mo
    fixed_expense_multiplier: float = Field(default=1.0, ge=0, le=5)
    variable_expense_multiplier: float = Field(default=1.0, ge=0, le=5)
    new_monthly_payment: float = Field(default=0.0, ge=0)
    down_payment: float = Field(default=0.0, ge=0)
    discretionary_cut: float = Field(default=0.0, ge=0, le=1)  # behavioural response


PRESETS: dict[str, ScenarioSpec] = {
    "job_loss": ScenarioSpec(
        key="job_loss", label="Job loss",
        description="All employment income stops for the stated duration.",
        income_multiplier=0.0, duration_months=3, discretionary_cut=0.5,
    ),
    "income_reduction": ScenarioSpec(
        key="income_reduction", label="Income cut 25%",
        description="Reduced hours or a lost client for six months.",
        income_multiplier=0.75, duration_months=6,
    ),
    "emergency_expense": ScenarioSpec(
        key="emergency_expense", label="$5,000 emergency",
        description="A single large unplanned expense, such as a medical bill or repair.",
        one_time_expense=5_000.0, duration_months=1,
    ),
    "rent_increase": ScenarioSpec(
        key="rent_increase", label="Housing costs +15%",
        description="Lease renewal at a higher rate, permanent for the horizon.",
        fixed_expense_multiplier=1.15, duration_months=12,
    ),
    "inflation_shock": ScenarioSpec(
        key="inflation_shock", label="Living costs +10%",
        description="Broad increase in variable spending that persists.",
        variable_expense_multiplier=1.10, duration_months=12,
    ),
    "new_car": ScenarioSpec(
        key="new_car", label="New car purchase",
        description="$5,000 down plus a $550/month payment.",
        new_monthly_payment=550.0, down_payment=5_000.0, duration_months=12,
    ),
    "rate_shock": ScenarioSpec(
        key="rate_shock", label="Variable debt costs +$250/mo",
        description="Rising rates on revolving balances.",
        fixed_expense_delta=250.0, duration_months=12,
    ),
}


@dataclass
class StressResult:
    scenario: ScenarioSpec
    starting_balance: float
    baseline_ending: float
    stressed_ending: float
    impact: float
    runway_months: float
    months_to_depletion: int | None
    lowest_balance: float
    lowest_balance_month: int
    survives_horizon: bool
    risk_level: str
    monthly_path: list[dict] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "scenario": {
                "key": self.scenario.key, "label": self.scenario.label,
                "description": self.scenario.description,
                "duration_months": self.scenario.duration_months,
                "horizon_months": self.scenario.horizon_months,
            },
            "starting_balance": round(self.starting_balance, 2),
            "baseline_ending_balance": round(self.baseline_ending, 2),
            "stressed_ending_balance": round(self.stressed_ending, 2),
            "impact": round(self.impact, 2),
            "runway_months": round(self.runway_months, 2),
            "months_to_depletion": self.months_to_depletion,
            "lowest_balance": round(self.lowest_balance, 2),
            "lowest_balance_month": self.lowest_balance_month,
            "survives_horizon": self.survives_horizon,
            "risk_level": self.risk_level,
            "monthly_path": self.monthly_path,
            "recommendations": self.recommendations,
        }


def _risk_level(months_to_depletion: int | None, runway: float, horizon: int) -> str:
    if months_to_depletion is None:
        return "Low" if runway >= 6 else "Moderate"
    if months_to_depletion <= 2:
        return "Severe"
    if months_to_depletion <= horizon / 2:
        return "High"
    return "Moderate"


def run_stress_test(
    features: FinancialFeatures,
    scenario: ScenarioSpec,
    recurring: RecurringReport | None = None,
) -> StressResult:
    if features.monthly_income_mean <= 0 and features.monthly_outflow_mean <= 0:
        raise ValidationFailure("Not enough cash-flow history to stress test.")

    income = features.monthly_income_mean
    fixed = float(recurring.fixed_monthly if recurring and recurring.fixed_monthly > 0
                  else features.fixed_monthly)
    variable = features.variable_monthly_mean
    discretionary = min(features.discretionary_monthly, variable)

    balance = features.liquid_savings - scenario.down_payment
    baseline_balance = features.liquid_savings
    starting = features.liquid_savings

    path: list[dict] = []
    depletion: int | None = None
    lowest, lowest_month = balance, 0

    for month in range(1, scenario.horizon_months + 1):
        active = month <= scenario.duration_months

        month_income = income * (scenario.income_multiplier if active else 1.0)
        month_fixed = fixed * scenario.fixed_expense_multiplier + scenario.fixed_expense_delta \
            + scenario.new_monthly_payment
        month_variable = variable * scenario.variable_expense_multiplier
        if active and scenario.discretionary_cut > 0:
            month_variable -= discretionary * scenario.discretionary_cut
        month_variable = max(month_variable, 0.0)

        one_time = scenario.one_time_expense if month == 1 else 0.0

        net = month_income - month_fixed - month_variable - one_time
        balance += net
        baseline_balance += income - fixed - variable

        if balance < lowest:
            lowest, lowest_month = balance, month
        if balance < 0 and depletion is None:
            depletion = month

        path.append({
            "month": month,
            "income": round(month_income, 2),
            "expenses": round(month_fixed + month_variable + one_time, 2),
            "net": round(net, 2),
            "balance": round(balance, 2),
            "baseline_balance": round(baseline_balance, 2),
            "under_stress": active,
        })

    essential = features.essential_monthly or features.monthly_outflow_mean or 1.0
    runway = (features.liquid_savings - scenario.down_payment) / essential if essential else 0.0
    risk = _risk_level(depletion, runway, scenario.horizon_months)

    recommendations: list[str] = []
    if depletion is not None:
        gap = abs(min(point["balance"] for point in path))
        recommendations.append(
            f"Reserves run out in month {depletion}. Closing the gap needs roughly "
            f"${gap:,.0f} more in savings or ${gap / max(depletion, 1):,.0f}/mo less outflow."
        )
    if runway < 3:
        recommendations.append(
            f"Reserves cover {runway:.1f} months of essentials; three months is the usual first milestone."
        )
    if discretionary > 0:
        recommendations.append(
            f"Pausing discretionary spending frees about ${discretionary:,.0f}/mo, "
            f"extending runway by roughly {discretionary / essential:.1f} months per month of cuts."
        )
    if scenario.new_monthly_payment > 0 and depletion is not None:
        recommendations.append(
            f"The ${scenario.new_monthly_payment:,.0f}/mo commitment is what drives the shortfall — "
            "a longer term or larger down payment materially changes this outcome."
        )
    if not recommendations:
        recommendations.append("Balances stay positive across the whole horizon under this scenario.")

    return StressResult(
        scenario=scenario,
        starting_balance=starting,
        baseline_ending=baseline_balance,
        stressed_ending=balance,
        impact=balance - baseline_balance,
        runway_months=runway,
        months_to_depletion=depletion,
        lowest_balance=lowest,
        lowest_balance_month=lowest_month,
        survives_horizon=depletion is None,
        risk_level=risk,
        monthly_path=path,
        recommendations=recommendations,
    )


def run_all_presets(features: FinancialFeatures, recurring: RecurringReport | None = None) -> list[dict]:
    return [run_stress_test(features, spec, recurring).to_dict() for spec in PRESETS.values()]