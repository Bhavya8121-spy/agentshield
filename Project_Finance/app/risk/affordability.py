from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field, field_validator

from app.core.exceptions import ValidationFailure
from app.forecasting.features import FinancialFeatures
from app.risk.explainability import (
    Explanation, Factor, build_explanation, classify_factor, linear_score,
)

BANDS = [(80.0, "Strong"), (65.0, "Moderate"), (45.0, "Stretched"), (0.0, "High Risk")]

# Documented, editable assumptions — NOT universal underwriting rules.
DTI_COMFORTABLE = 0.28
DTI_LIMIT = 0.43
PTI_COMFORTABLE = 0.10
PTI_LIMIT = 0.20
RESERVE_TARGET_MONTHS = 6.0
RESERVE_MINIMUM_MONTHS = 3.0

WEIGHTS = {
    "dti": 0.30,
    "payment_to_income": 0.15,
    "disposable": 0.20,
    "liquidity": 0.20,
    "stability": 0.15,
}


class AffordabilityRequest(BaseModel):
    loan_amount: float = Field(gt=0)
    annual_rate_percent: float = Field(default=6.9, ge=0, le=40)
    term_months: int = Field(default=60, gt=0, le=480)
    down_payment: float = Field(default=0.0, ge=0)
    extra_monthly_debt: float = Field(default=0.0, ge=0)
    extra_monthly_cost: float = Field(default=0.0, ge=0)   # insurance, upkeep — not debt
    liquid_savings: float | None = Field(default=None, ge=0)
    monthly_income_override: float | None = Field(default=None, ge=0)
    target_score: float = Field(default=80.0, ge=0, le=100)
    goal_name: str = "New Purchase"

    @field_validator("down_payment")
    @classmethod
    def _down_below_price(cls, v, info):
        loan = info.data.get("loan_amount")
        if loan is not None and v > loan:
            raise ValueError("down_payment cannot exceed loan_amount")
        return v

    @property
    def financed(self) -> float:
        return max(self.loan_amount - self.down_payment, 0.0)


def monthly_payment(principal: float, annual_rate_percent: float, term_months: int) -> float:
    """Standard amortising payment. Zero-interest degrades to straight division."""
    if term_months <= 0:
        raise ValidationFailure("term_months must be positive.")
    if principal <= 0:
        return 0.0
    rate = annual_rate_percent / 100.0 / 12.0
    if rate <= 1e-12:
        return principal / term_months
    factor = (1 + rate) ** term_months
    return principal * rate * factor / (factor - 1)


def total_interest(principal: float, annual_rate_percent: float, term_months: int) -> float:
    return monthly_payment(principal, annual_rate_percent, term_months) * term_months - principal


@dataclass
class AffordabilityResult:
    goal_name: str
    new_payment: float
    financed_amount: float
    total_interest: float
    total_cost: float
    monthly_income: float
    existing_debt_service: float
    projected_debt_service: float
    dti_before: float
    dti_after: float
    payment_to_income: float
    disposable_before: float
    disposable_after: float
    runway_before: float
    runway_after: float
    savings_after_down_payment: float
    verdict: str
    explanation: Explanation
    improvements: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "goal_name": self.goal_name,
            "loan": {
                "monthly_payment": round(self.new_payment, 2),
                "financed_amount": round(self.financed_amount, 2),
                "total_interest": round(self.total_interest, 2),
                "total_cost": round(self.total_cost, 2),
            },
            "ratios": {
                "monthly_income": round(self.monthly_income, 2),
                "existing_debt_service": round(self.existing_debt_service, 2),
                "projected_debt_service": round(self.projected_debt_service, 2),
                "dti_before": round(self.dti_before, 4),
                "dti_after": round(self.dti_after, 4),
                "payment_to_income": round(self.payment_to_income, 4),
                "disposable_before": round(self.disposable_before, 2),
                "disposable_after": round(self.disposable_after, 2),
                "runway_before_months": round(self.runway_before, 2),
                "runway_after_months": round(self.runway_after, 2),
                "savings_after_down_payment": round(self.savings_after_down_payment, 2),
            },
            "verdict": self.verdict,
            "score": round(self.explanation.score, 1),
            "band": self.explanation.band,
            "explanation": self.explanation.to_dict(),
            "improvements": self.improvements,
        }


def _score_components(
    features: FinancialFeatures,
    request: AffordabilityRequest,
    payment: float,
    income: float,
    savings: float,
) -> tuple[float, list[Factor], dict]:
    existing_debt = features.debt_service_monthly
    projected_debt = existing_debt + payment + request.extra_monthly_debt

    dti_before = existing_debt / income if income > 0 else 0.0
    dti_after = projected_debt / income if income > 0 else 0.0
    pti = payment / income if income > 0 else 0.0

    non_debt_outflow = max(features.monthly_outflow_mean - existing_debt, 0.0)
    disposable_before = income - existing_debt - non_debt_outflow
    disposable_after = disposable_before - payment - request.extra_monthly_debt - request.extra_monthly_cost

    essential_burn = (features.essential_monthly or features.monthly_outflow_mean) or 1.0
    savings_after = max(savings - request.down_payment, 0.0)
    runway_before = savings / essential_burn if essential_burn else 0.0
    runway_after = savings_after / (essential_burn + payment + request.extra_monthly_cost) \
        if essential_burn else 0.0

    dti_score = linear_score(dti_after, DTI_LIMIT + 0.12, DTI_COMFORTABLE)
    pti_score = linear_score(pti, PTI_LIMIT + 0.10, PTI_COMFORTABLE)
    disposable_score = linear_score(
        disposable_after / income if income > 0 else 0.0, -0.05, 0.20
    )
    liquidity_score = linear_score(runway_after, 0.0, RESERVE_TARGET_MONTHS)
    stability_score = (features.income_stability * 60 + features.expense_stability * 40)

    raw = {
        "dti": dti_score,
        "payment_to_income": pti_score,
        "disposable": disposable_score,
        "liquidity": liquidity_score,
        "stability": stability_score,
    }
    total = sum(raw[k] * WEIGHTS[k] for k in WEIGHTS)

    factors = [
        Factor("dti", "Projected debt-to-income", dti_after, f"{dti_after:.1%}",
               dti_score, WEIGHTS["dti"], dti_score * WEIGHTS["dti"], 100 * WEIGHTS["dti"],
               classify_factor(dti_score),
               f"assumes a comfort ceiling of {DTI_COMFORTABLE:.0%} and a stress point near {DTI_LIMIT:.0%}"),
        Factor("payment_to_income", "New payment vs. income", pti, f"{pti:.1%}",
               pti_score, WEIGHTS["payment_to_income"], pti_score * WEIGHTS["payment_to_income"],
               100 * WEIGHTS["payment_to_income"], classify_factor(pti_score),
               f"${payment:,.0f}/mo against ${income:,.0f}/mo income"),
        Factor("disposable", "Disposable income after purchase", disposable_after,
               f"${disposable_after:,.0f}/mo", disposable_score, WEIGHTS["disposable"],
               disposable_score * WEIGHTS["disposable"], 100 * WEIGHTS["disposable"],
               classify_factor(disposable_score),
               f"down from ${disposable_before:,.0f}/mo today"),
        Factor("liquidity", "Emergency reserves after purchase", runway_after,
               f"{runway_after:.1f} months", liquidity_score, WEIGHTS["liquidity"],
               liquidity_score * WEIGHTS["liquidity"], 100 * WEIGHTS["liquidity"],
               classify_factor(liquidity_score),
               f"${savings_after:,.0f} left after a ${request.down_payment:,.0f} down payment; "
               f"target is {RESERVE_TARGET_MONTHS:.0f} months"),
        Factor("stability", "Income and spending consistency", features.income_stability,
               f"{features.income_stability:.0%} income / {features.expense_stability:.0%} expense",
               stability_score, WEIGHTS["stability"], stability_score * WEIGHTS["stability"],
               100 * WEIGHTS["stability"], classify_factor(stability_score),
               f"based on {features.complete_months} complete month(s)"),
    ]

    context = {
        "existing_debt": existing_debt, "projected_debt": projected_debt,
        "dti_before": dti_before, "dti_after": dti_after, "pti": pti,
        "disposable_before": disposable_before, "disposable_after": disposable_after,
        "runway_before": runway_before, "runway_after": runway_after,
        "savings_after": savings_after,
    }
    return total, factors, context


def _score_only(features, request: AffordabilityRequest, payment, income, savings) -> float:
    return _score_components(features, request, payment, income, savings)[0]


def _solve_lever(objective, low: float, high: float, target: float, iterations: int = 40):
    """Binary search the smallest change that reaches `target`. Returns None if
    the lever cannot reach it within bounds."""
    if objective(low) >= target:
        return low
    if objective(high) < target:
        return None
    for _ in range(iterations):
        mid = (low + high) / 2
        if objective(mid) >= target:
            high = mid
        else:
            low = mid
    return high


def _improvement_paths(features, request, income, savings, current_score) -> list[dict]:
    """Reverse the scoring function along one lever at a time."""
    target = request.target_score
    if current_score >= target:
        return []
    options: list[dict] = []

    # A) smaller loan
    def by_loan(reduction: float) -> float:
        trial = request.model_copy(update={"loan_amount": max(request.loan_amount - reduction, 1.0)})
        payment = monthly_payment(trial.financed, trial.annual_rate_percent, trial.term_months)
        return _score_only(features, trial, payment, income, savings)

    reduction = _solve_lever(by_loan, 0.0, request.financed, target)
    if reduction:
        options.append({
            "lever": "reduce_loan_amount", "label": "Reduce the amount financed",
            "amount": round(reduction, -1),
            "statement": f"Finance ${reduction:,.0f} less (≈${request.loan_amount - reduction:,.0f} total).",
        })

    # B) larger down payment
    def by_down(extra: float) -> float:
        trial = request.model_copy(update={"down_payment": request.down_payment + extra})
        payment = monthly_payment(trial.financed, trial.annual_rate_percent, trial.term_months)
        return _score_only(features, trial, payment, income, savings)

    extra_down = _solve_lever(by_down, 0.0, min(request.financed, savings), target)
    if extra_down:
        options.append({
            "lever": "increase_down_payment", "label": "Increase the down payment",
            "amount": round(extra_down, -1),
            "statement": f"Put down ${extra_down:,.0f} more — note this also reduces your cash reserves.",
        })

    # C) pay down existing debt service
    base_payment = monthly_payment(request.financed, request.annual_rate_percent, request.term_months)

    def by_debt(cut: float) -> float:
        trimmed = features.__class__(**{**features.__dict__,
                                        "debt_service_monthly": max(features.debt_service_monthly - cut, 0.0)})
        return _score_only(trimmed, request, base_payment, income, savings)

    debt_cut = _solve_lever(by_debt, 0.0, max(features.debt_service_monthly, 1.0), target)
    if debt_cut:
        options.append({
            "lever": "reduce_monthly_debt", "label": "Retire existing monthly debt",
            "amount": round(debt_cut, 0),
            "statement": f"Clear ${debt_cut:,.0f}/mo of current debt payments before borrowing.",
        })

    # D) higher income
    def by_income(increase: float) -> float:
        return _score_only(features, request, base_payment, income + increase, savings)

    income_gain = _solve_lever(by_income, 0.0, income * 2 + 1000, target)
    if income_gain:
        options.append({
            "lever": "increase_income", "label": "Increase monthly income",
            "amount": round(income_gain, 0),
            "statement": f"Add ${income_gain:,.0f}/mo (≈${income_gain * 12:,.0f}/yr) of income.",
        })

    # E) build reserves
    def by_savings(extra: float) -> float:
        return _score_only(features, request, base_payment, income, savings + extra)

    savings_gain = _solve_lever(by_savings, 0.0, 100_000.0, target)
    if savings_gain:
        options.append({
            "lever": "increase_savings", "label": "Build cash reserves first",
            "amount": round(savings_gain, -1),
            "statement": f"Save ${savings_gain:,.0f} more before purchasing.",
        })

    for index, option in enumerate(options):
        option["option"] = chr(ord("A") + index)
        option["target_score"] = target
    return options


def evaluate_affordability(features: FinancialFeatures, request: AffordabilityRequest) -> AffordabilityResult:
    income = request.monthly_income_override or features.monthly_income_mean
    if income <= 0:
        raise ValidationFailure(
            "No monthly income detected. Provide monthly_income_override to run an affordability check.",
            {"detected_income": income},
        )
    savings = request.liquid_savings if request.liquid_savings is not None else features.liquid_savings
    payment = monthly_payment(request.financed, request.annual_rate_percent, request.term_months)

    score, factors, context = _score_components(features, request, payment, income, savings)
    explanation = build_explanation(
        score, factors, BANDS,
        assumptions=[
            "Debt-to-income counts housing, loan and credit-card payments only. "
            "Insurance, utilities and groceries are treated as living costs, not debt.",
            f"Thresholds ({DTI_COMFORTABLE:.0%} comfortable / {DTI_LIMIT:.0%} stressed) are educational "
            "defaults used by this tool, not the underwriting policy of any specific lender.",
            f"Emergency-reserve target of {RESERVE_TARGET_MONTHS:.0f} months of essential expenses.",
            f"Income of ${income:,.0f}/mo derived from {features.complete_months} complete month(s) of history.",
        ] + features.warnings,
    )

    interest = total_interest(request.financed, request.annual_rate_percent, request.term_months)
    verdict = (
        "Comfortable" if score >= 80 else
        "Feasible with trade-offs" if score >= 65 else
        "Tight — revisit the terms" if score >= 45 else
        "Not advisable on current cash flow"
    )

    return AffordabilityResult(
        goal_name=request.goal_name,
        new_payment=payment,
        financed_amount=request.financed,
        total_interest=interest,
        total_cost=request.financed + interest + request.down_payment,
        monthly_income=income,
        existing_debt_service=context["existing_debt"],
        projected_debt_service=context["projected_debt"],
        dti_before=context["dti_before"],
        dti_after=context["dti_after"],
        payment_to_income=context["pti"],
        disposable_before=context["disposable_before"],
        disposable_after=context["disposable_after"],
        runway_before=context["runway_before"],
        runway_after=context["runway_after"],
        savings_after_down_payment=context["savings_after"],
        verdict=verdict,
        explanation=explanation,
        improvements=_improvement_paths(features, request, income, savings, score),
    )