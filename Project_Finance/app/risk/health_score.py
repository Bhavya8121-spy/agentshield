from __future__ import annotations

from dataclasses import dataclass

from app.forecasting.features import FinancialFeatures
from app.recurring.detector import RecurringReport
from app.risk.explainability import (
    Explanation, Factor, build_explanation, classify_factor, linear_score,
)

BANDS = [(80.0, "Good"), (65.0, "Fair"), (45.0, "Needs Attention"), (0.0, "At Risk")]

WEIGHTS = {
    "cash_flow": 0.20,
    "debt": 0.25,
    "emergency_fund": 0.20,
    "savings_rate": 0.15,
    "income_stability": 0.10,
    "expense_stability": 0.10,
}
assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9

DTI_HEALTHY = 0.20
DTI_STRESSED = 0.45
SAVINGS_RATE_TARGET = 0.20
RESERVE_TARGET_MONTHS = 6.0


@dataclass
class HealthScore:
    score: float
    explanation: Explanation

    def to_dict(self) -> dict:
        return {
            "score": round(self.score, 1),
            "band": self.explanation.band,
            "components": [
                {
                    "key": f.key, "label": f.label, "display": f.display,
                    "earned": round(f.points_earned, 1),
                    "possible": round(f.points_possible, 1),
                    "sub_score": round(f.score, 1),
                }
                for f in self.explanation.factors
            ],
            "explanation": self.explanation.to_dict(),
        }


def compute_health_score(
    features: FinancialFeatures,
    recurring: RecurringReport | None = None,
) -> HealthScore:
    income = features.monthly_income_mean
    dti = features.debt_service_monthly / income if income > 0 else 1.0
    net_ratio = features.net_monthly_mean / income if income > 0 else -1.0

    scores = {
        "cash_flow": linear_score(net_ratio, -0.15, 0.25),
        "debt": linear_score(dti, DTI_STRESSED, DTI_HEALTHY),
        "emergency_fund": linear_score(features.emergency_runway_months, 0.0, RESERVE_TARGET_MONTHS),
        "savings_rate": linear_score(features.savings_rate, -0.05, SAVINGS_RATE_TARGET),
        "income_stability": features.income_stability * 100,
        "expense_stability": features.expense_stability * 100,
    }

    displays = {
        "cash_flow": f"${features.net_monthly_mean:,.0f}/mo net",
        "debt": f"{dti:.1%} of income to debt",
        "emergency_fund": f"{features.emergency_runway_months:.1f} months of essentials",
        "savings_rate": f"{features.savings_rate:.1%} of income saved",
        "income_stability": f"{features.income_stability:.0%} consistent",
        "expense_stability": f"{features.expense_stability:.0%} consistent",
    }
    labels = {
        "cash_flow": "Monthly cash flow",
        "debt": "Debt burden",
        "emergency_fund": "Emergency fund",
        "savings_rate": "Savings rate",
        "income_stability": "Income stability",
        "expense_stability": "Expense stability",
    }
    details = {
        "cash_flow": f"income ${income:,.0f} less spending ${features.monthly_outflow_mean:,.0f}",
        "debt": f"${features.debt_service_monthly:,.0f}/mo in housing, loan and card payments",
        "emergency_fund": f"${features.liquid_savings:,.0f} against ${features.essential_monthly:,.0f}/mo essentials",
        "savings_rate": f"target {SAVINGS_RATE_TARGET:.0%}",
        "income_stability": f"month-to-month variation of {features.income_cv:.0%}",
        "expense_stability": f"month-to-month variation of {features.expense_cv:.0%}",
    }

    factors = [
        Factor(key, labels[key], scores[key], displays[key], scores[key], WEIGHTS[key],
               scores[key] * WEIGHTS[key], 100 * WEIGHTS[key],
               classify_factor(scores[key]), details[key])
        for key in WEIGHTS
    ]
    total = sum(f.points_earned for f in factors)

    assumptions = [
        "Weights: debt 25%, cash flow 20%, emergency fund 20%, savings rate 15%, "
        "income stability 10%, expense stability 10%.",
        f"Full marks require {RESERVE_TARGET_MONTHS:.0f} months of reserves, a "
        f"{SAVINGS_RATE_TARGET:.0%} savings rate, and debt below {DTI_HEALTHY:.0%} of income.",
        "These are this tool's documented targets, not lender criteria.",
    ] + features.warnings

    if recurring and recurring.discretionary_annual > 0:
        assumptions.append(
            f"${recurring.discretionary_annual:,.0f}/yr of the recurring total is discretionary "
            "and is the most reducible component."
        )

    return HealthScore(score=total, explanation=build_explanation(total, factors, BANDS, assumptions))