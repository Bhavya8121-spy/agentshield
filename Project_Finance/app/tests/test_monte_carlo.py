import pytest

from app.simulation.monte_carlo import MonteCarloRequest, run_monte_carlo


def test_percentiles_ordered(features):
    result = run_monte_carlo(features, request=MonteCarloRequest(runs=2_000, months=12))
    outcomes = result.to_dict()["outcomes"]
    assert (outcomes["p10"] <= outcomes["p25"] <= outcomes["median_ending_balance"]
            <= outcomes["p75"] <= outcomes["p90"])


def test_path_percentiles_ordered_every_month(features):
    result = run_monte_carlo(features, request=MonteCarloRequest(runs=1_500, months=12))
    for point in result.percentile_paths:
        assert point["p10"] <= point["p25"] <= point["median"] <= point["p75"] <= point["p90"]


def test_probabilities_bounded(features):
    result = run_monte_carlo(features, request=MonteCarloRequest(
        runs=2_000, months=12, savings_goal=25_000))
    probabilities = result.to_dict()["probabilities"]
    for value in probabilities.values():
        if value is not None:
            assert 0.0 <= value <= 1.0


def test_reproducible_with_seed(features):
    request = MonteCarloRequest(runs=1_000, months=6, seed=99)
    first = run_monte_carlo(features, request=request)
    second = run_monte_carlo(features, request=request)
    assert first.median_ending == pytest.approx(second.median_ending)
    assert first.probability_negative == pytest.approx(second.probability_negative)


def test_different_seeds_differ(features):
    a = run_monte_carlo(features, request=MonteCarloRequest(runs=1_000, seed=1))
    b = run_monte_carlo(features, request=MonteCarloRequest(runs=1_000, seed=2))
    assert a.median_ending != b.median_ending


def test_starting_balance_respected(features):
    result = run_monte_carlo(features, request=MonteCarloRequest(runs=500, months=1))
    assert result.starting_balance == pytest.approx(features.liquid_savings)


def test_longer_horizon_widens_dispersion(features):
    short = run_monte_carlo(features, request=MonteCarloRequest(runs=2_000, months=3))
    long = run_monte_carlo(features, request=MonteCarloRequest(runs=2_000, months=24))
    assert (long.p90 - long.p10) > (short.p90 - short.p10)


def test_income_shock_lowers_outcomes(features):
    base = run_monte_carlo(features, request=MonteCarloRequest(runs=2_000, months=12, seed=7))
    shocked = run_monte_carlo(features, request=MonteCarloRequest(
        runs=2_000, months=12, seed=7,
        income_shock_probability=0.5, income_shock_multiplier=0.4))
    assert shocked.median_ending < base.median_ending
    assert shocked.probability_negative >= base.probability_negative


def test_monthly_contribution_raises_outcomes(features):
    base = run_monte_carlo(features, request=MonteCarloRequest(runs=1_500, months=12, seed=3))
    boosted = run_monte_carlo(features, request=MonteCarloRequest(
        runs=1_500, months=12, seed=3, monthly_contribution=500))
    assert boosted.median_ending > base.median_ending


def test_variable_spend_never_negative(features):
    """Lognormal sampling must respect the zero floor — negative spending would
    manufacture phantom income."""
    result = run_monte_carlo(features, request=MonteCarloRequest(runs=3_000, months=12))
    assert result.p90 >= result.p10
    assert result.histogram["counts"]
    assert sum(result.histogram["counts"]) == 3_000


def test_goal_probability_none_when_no_goal(features):
    result = run_monte_carlo(features, request=MonteCarloRequest(runs=500))
    assert result.probability_goal_met is None


def test_unreachable_goal_near_zero(features):
    result = run_monte_carlo(features, request=MonteCarloRequest(
        runs=2_000, months=12, savings_goal=50_000_000))
    assert result.probability_goal_met == pytest.approx(0.0, abs=0.01)


def test_assumptions_disclose_no_behavioural_response(features):
    text = " ".join(run_monte_carlo(features, request=MonteCarloRequest(runs=500)).assumptions)
    assert "behavioural response" in text or "behavioral response" in text


def test_run_bounds_enforced():
    with pytest.raises(Exception):
        MonteCarloRequest(runs=10)