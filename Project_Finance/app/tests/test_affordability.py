import pytest

from app.core.exceptions import ValidationFailure
from app.risk.affordability import (
    AffordabilityRequest, evaluate_affordability, monthly_payment, total_interest,
)


# --------------------------------------------------------------- amortisation
def test_known_amortisation_value():
    # $30,000 @ 6% over 60 months ≈ $579.98/mo
    assert monthly_payment(30_000, 6.0, 60) == pytest.approx(579.98, abs=0.05)


def test_zero_interest_is_straight_division():
    assert monthly_payment(12_000, 0.0, 24) == pytest.approx(500.0)


def test_zero_principal_is_zero_payment():
    assert monthly_payment(0, 6.0, 60) == 0.0


def test_longer_term_lowers_payment_raises_interest():
    short = monthly_payment(30_000, 6.0, 36)
    long = monthly_payment(30_000, 6.0, 72)
    assert long < short
    assert total_interest(30_000, 6.0, 72) > total_interest(30_000, 6.0, 36)


def test_zero_term_rejected():
    with pytest.raises(ValidationFailure):
        monthly_payment(10_000, 5.0, 0)


# -------------------------------------------------------------------- scoring
def test_evaluation_shape(features):
    result = evaluate_affordability(features, AffordabilityRequest(
        loan_amount=35_000, down_payment=5_000, annual_rate_percent=6.9, term_months=60))
    assert 0 <= result.explanation.score <= 100
    assert result.explanation.band in {"Strong", "Moderate", "Stretched", "High Risk"}
    assert len(result.explanation.factors) == 5


def test_weights_sum_to_one():
    from app.risk.affordability import WEIGHTS

    assert sum(WEIGHTS.values()) == pytest.approx(1.0)


def test_points_earned_never_exceed_possible(features):
    result = evaluate_affordability(features, AffordabilityRequest(loan_amount=25_000))
    for factor in result.explanation.factors:
        assert 0 <= factor.points_earned <= factor.points_possible + 1e-9


def test_larger_loan_scores_lower(features):
    small = evaluate_affordability(features, AffordabilityRequest(loan_amount=10_000))
    large = evaluate_affordability(features, AffordabilityRequest(loan_amount=90_000))
    assert large.explanation.score < small.explanation.score
    assert large.dti_after > small.dti_after


def test_dti_rises_by_new_payment_only(features):
    result = evaluate_affordability(features, AffordabilityRequest(
        loan_amount=30_000, annual_rate_percent=6.0, term_months=60))
    expected = (result.existing_debt_service + result.new_payment) / result.monthly_income
    assert result.dti_after == pytest.approx(expected, abs=1e-6)


def test_down_payment_reduces_reserves(features):
    no_down = evaluate_affordability(features, AffordabilityRequest(loan_amount=30_000))
    with_down = evaluate_affordability(features, AffordabilityRequest(
        loan_amount=30_000, down_payment=8_000))
    assert with_down.savings_after_down_payment < no_down.savings_after_down_payment
    assert with_down.new_payment < no_down.new_payment


def test_down_payment_cannot_exceed_price():
    with pytest.raises(ValueError):
        AffordabilityRequest(loan_amount=10_000, down_payment=20_000)


def test_zero_income_raises_clearly(features):
    features.monthly_income_mean = 0.0
    with pytest.raises(ValidationFailure, match="income"):
        evaluate_affordability(features, AffordabilityRequest(loan_amount=20_000))


def test_income_override_accepted(features):
    features.monthly_income_mean = 0.0
    result = evaluate_affordability(features, AffordabilityRequest(
        loan_amount=20_000, monthly_income_override=6_000))
    assert result.monthly_income == 6_000


# --------------------------------------------------------- improvement levers
def test_improvements_offered_when_below_target(features):
    result = evaluate_affordability(features, AffordabilityRequest(
        loan_amount=140_000, term_months=60, target_score=85))
    assert result.improvements
    assert {o["lever"] for o in result.improvements} <= {
        "reduce_loan_amount", "increase_down_payment", "reduce_monthly_debt",
        "increase_income", "increase_savings",
    }
    assert all(o["amount"] > 0 for o in result.improvements)


def test_no_improvements_when_target_met(features):
    result = evaluate_affordability(features, AffordabilityRequest(
        loan_amount=1_500, term_months=36, target_score=10))
    assert result.improvements == []


def test_suggested_loan_reduction_actually_reaches_target(features):
    request = AffordabilityRequest(loan_amount=120_000, term_months=60, target_score=80)
    result = evaluate_affordability(features, request)
    option = next((o for o in result.improvements if o["lever"] == "reduce_loan_amount"), None)
    if option is None:
        pytest.skip("lever unreachable for this household")
    verified = evaluate_affordability(features, request.model_copy(
        update={"loan_amount": request.loan_amount - option["amount"]}))
    assert verified.explanation.score >= 79.0     # allow rounding slack


def test_explanation_lists_assumptions_not_lender_claims(features):
    result = evaluate_affordability(features, AffordabilityRequest(loan_amount=30_000))
    text = " ".join(result.explanation.assumptions).lower()
    assert "educational" in text or "not the underwriting policy" in text
    assert "will deny" not in text
    assert "most banks" not in text