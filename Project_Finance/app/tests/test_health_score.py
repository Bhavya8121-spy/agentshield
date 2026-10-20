import pytest

from app.risk.health_score import WEIGHTS, compute_health_score


def test_weights_sum_to_one():
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)


def test_score_bounded(features):
    score = compute_health_score(features)
    assert 0 <= score.score <= 100


def test_all_six_components_present(features):
    components = {c["key"] for c in compute_health_score(features).to_dict()["components"]}
    assert components == set(WEIGHTS)


def test_components_sum_to_headline(features):
    payload = compute_health_score(features).to_dict()
    assert sum(c["earned"] for c in payload["components"]) == pytest.approx(payload["score"], abs=0.2)


def test_possible_points_match_weights(features):
    for component in compute_health_score(features).to_dict()["components"]:
        assert component["possible"] == pytest.approx(WEIGHTS[component["key"]] * 100, abs=0.01)


def test_healthy_household_scores_higher_than_stressed(features):
    healthy = features
    healthy.monthly_income_mean = 8_000
    healthy.monthly_outflow_mean = 5_000
    healthy.net_monthly_mean = 3_000
    healthy.debt_service_monthly = 800
    healthy.liquid_savings = 40_000
    healthy.essential_monthly = 4_000
    healthy.emergency_runway_months = 10.0
    healthy.savings_rate = 0.375
    healthy.income_stability = 0.95
    healthy.expense_stability = 0.90
    good = compute_health_score(healthy).score

    stressed = features.__class__(**{**healthy.__dict__})
    stressed.net_monthly_mean = -600
    stressed.debt_service_monthly = 3_600
    stressed.liquid_savings = 500
    stressed.emergency_runway_months = 0.12
    stressed.savings_rate = -0.075
    stressed.income_stability = 0.30
    stressed.expense_stability = 0.35
    bad = compute_health_score(stressed).score

    assert good > 75 and bad < 45
    assert good - bad > 30


def test_deductions_explain_lost_points(features):
    features.emergency_runway_months = 0.5
    features.debt_service_monthly = features.monthly_income_mean * 0.5
    explanation = compute_health_score(features).explanation
    assert explanation.deductions
    assert all(d["points"] < 0 for d in explanation.deductions)
    keys = {d["key"] for d in explanation.deductions}
    assert "emergency_fund" in keys or "debt" in keys


def test_deductions_ordered_by_severity(features):
    deductions = compute_health_score(features).explanation.deductions
    points = [d["points"] for d in deductions]
    assert points == sorted(points)     # most negative first


def test_band_matches_score(features):
    result = compute_health_score(features)
    expected = ("Good" if result.score >= 80 else "Fair" if result.score >= 65
                else "Needs Attention" if result.score >= 45 else "At Risk")
    assert result.explanation.band == expected


def test_assumptions_document_weights(features):
    text = " ".join(compute_health_score(features).explanation.assumptions)
    assert "25%" in text and "20%" in text
    assert "not lender criteria" in text


def test_recurring_context_appended(features, active):
    from app.recurring.detector import detect_recurring

    recurring = detect_recurring(active)
    text = " ".join(compute_health_score(features, recurring).explanation.assumptions)
    if recurring.discretionary_annual > 0:
        assert "discretionary" in text