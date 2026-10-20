import numpy as np
import pytest

from app.core.exceptions import InsufficientHistory
from app.forecasting.model import BaselineForecaster, forecast_dataset


def test_horizons_returned(active, features):
    result = forecast_dataset(active, features, (30, 60, 90))
    assert set(result.horizons) == {"30_day", "60_day", "90_day"}


def test_intervals_widen_with_horizon(active, features):
    result = forecast_dataset(active, features, (30, 60, 90))
    widths = [h.upper - h.lower for h in result.horizons.values()]
    assert widths == sorted(widths), "uncertainty must grow with horizon"


def test_expected_lies_inside_interval(active, features):
    result = forecast_dataset(active, features, (30, 90))
    for horizon in result.horizons.values():
        assert horizon.lower <= horizon.balance <= horizon.upper


def test_forecast_starts_from_reported_balance(active, features):
    result = forecast_dataset(active, features, (30,))
    assert result.starting_balance == pytest.approx(features.liquid_savings)


def test_surplus_household_grows(active, features):
    if features.net_monthly_mean <= 0:
        pytest.skip("fixture household is not in surplus")
    result = forecast_dataset(active, features, (90,))
    assert result.horizons["90_day"].balance > features.liquid_savings


def test_probability_of_negative_is_a_probability(active, features):
    result = forecast_dataset(active, features, (30, 90))
    for horizon in result.horizons.values():
        assert 0.0 <= horizon.probability_negative <= 1.0


def test_method_reported_honestly(active, features):
    result = forecast_dataset(active, features)
    assert result.method in {"bootstrap_monthly_net", "parametric_normal"}
    if features.complete_months >= 4:
        assert result.method == "bootstrap_monthly_net"


def test_assumptions_always_present(active, features):
    assert forecast_dataset(active, features).assumptions


def test_sigma_never_zero(active, features):
    forecaster = BaselineForecaster().fit(active, features)
    assert forecaster._sigma > 0


def test_trend_is_capped(active, features):
    """A single anomalous month must not run away over 90 days."""
    inflated = features
    inflated.trend_slope_monthly = 50_000.0
    result = BaselineForecaster().fit(active, inflated).forecast((90,))
    change = result.horizons["90_day"].expected_net
    assert abs(change) < abs(inflated.net_monthly_mean) * 12 + 5000


def test_daily_path_monotonic_dates(active, features):
    path = BaselineForecaster().fit(active, features).daily_path(90)
    days = [point["day"] for point in path]
    assert days == sorted(days)
    assert path[0]["day"] == 0 and path[-1]["day"] <= 90


def test_path_fan_widens(active, features):
    path = BaselineForecaster().fit(active, features).daily_path(90)
    first = path[1]["upper"] - path[1]["lower"]
    last = path[-1]["upper"] - path[-1]["lower"]
    assert last > first


def test_higher_confidence_widens_interval(active, features):
    narrow = forecast_dataset(active, features, (90,), confidence=0.50).horizons["90_day"]
    wide = forecast_dataset(active, features, (90,), confidence=0.95).horizons["90_day"]
    assert (wide.upper - wide.lower) > (narrow.upper - narrow.lower)


def test_empty_input_raises():
    import pandas as pd

    with pytest.raises(InsufficientHistory):
        forecast_dataset(pd.DataFrame(), None)


def test_deterministic_given_same_input(active, features):
    first = forecast_dataset(active, features, (90,)).horizons["90_day"]
    second = forecast_dataset(active, features, (90,)).horizons["90_day"]
    assert first.balance == pytest.approx(second.balance)
    assert first.lower == pytest.approx(second.lower)