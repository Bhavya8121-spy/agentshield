import pytest

from app.simulation.stress_test import PRESETS, ScenarioSpec, run_all_presets, run_stress_test


def test_all_presets_execute(features):
    results = run_all_presets(features)
    assert len(results) == len(PRESETS)
    for result in results:
        assert result["risk_level"] in {"Low", "Moderate", "High", "Severe"}
        assert result["recommendations"]


def test_job_loss_is_worse_than_baseline(features):
    stressed = run_stress_test(features, PRESETS["job_loss"])
    assert stressed.stressed_ending < stressed.baseline_ending
    assert stressed.impact < 0


def test_longer_job_loss_is_worse(features):
    three = run_stress_test(features, PRESETS["job_loss"].model_copy(update={"duration_months": 3}))
    six = run_stress_test(features, PRESETS["job_loss"].model_copy(update={"duration_months": 6}))
    assert six.stressed_ending < three.stressed_ending


def test_path_length_matches_horizon(features):
    result = run_stress_test(features, ScenarioSpec(horizon_months=18))
    assert len(result.monthly_path) == 18
    assert result.monthly_path[-1]["month"] == 18


def test_stress_flag_only_during_duration(features):
    result = run_stress_test(features, ScenarioSpec(duration_months=4, horizon_months=12,
                                                   income_multiplier=0.5))
    stressed_months = [p["month"] for p in result.monthly_path if p["under_stress"]]
    assert stressed_months == [1, 2, 3, 4]


def test_one_time_expense_applied_once(features):
    result = run_stress_test(features, PRESETS["emergency_expense"].model_copy(
        update={"horizon_months": 6}))
    expenses = [p["expenses"] for p in result.monthly_path]
    assert expenses[0] > expenses[1]


def test_down_payment_reduces_starting_position(features):
    result = run_stress_test(features, PRESETS["new_car"])
    assert result.monthly_path[0]["balance"] < features.liquid_savings


def test_depletion_month_detected(features):
    result = run_stress_test(features, ScenarioSpec(
        income_multiplier=0.0, duration_months=24, horizon_months=24))
    assert result.months_to_depletion is not None
    assert not result.survives_horizon
    assert result.risk_level in {"High", "Severe"}


def test_neutral_scenario_survives(features):
    result = run_stress_test(features, ScenarioSpec(horizon_months=12))
    if features.net_monthly_mean > 0:
        assert result.survives_horizon
        assert "positive" in result.recommendations[0].lower()


def test_discretionary_cut_softens_impact(features):
    without = run_stress_test(features, ScenarioSpec(
        income_multiplier=0.0, duration_months=3, horizon_months=12, discretionary_cut=0.0))
    with_cut = run_stress_test(features, ScenarioSpec(
        income_multiplier=0.0, duration_months=3, horizon_months=12, discretionary_cut=1.0))
    assert with_cut.stressed_ending >= without.stressed_ending


def test_lowest_balance_tracked(features):
    result = run_stress_test(features, PRESETS["job_loss"])
    balances = [p["balance"] for p in result.monthly_path]
    assert result.lowest_balance == pytest.approx(min(balances), abs=0.01)


def test_recommendation_quantifies_gap(features):
    result = run_stress_test(features, ScenarioSpec(
        income_multiplier=0.0, duration_months=12, horizon_months=12))
    assert any("$" in r for r in result.recommendations)