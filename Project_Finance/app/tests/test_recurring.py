import pandas as pd
import pytest

from app.recurring.detector import detect_recurring


def _series(merchant, dates, amounts, category="Subscriptions", direction="debit"):
    if isinstance(amounts, (int, float)):
        amounts = [amounts] * len(dates)
    return pd.DataFrame([{
        "transaction_id": f"t{i}", "date": pd.Timestamp(d), "merchant": merchant,
        "clean_description": merchant.upper(), "category": category,
        "amount": -abs(a) if direction == "debit" else abs(a),
        "direction": direction, "kind": "variable",
    } for i, (d, a) in enumerate(zip(dates, amounts))])


def test_perfect_monthly_subscription_detected():
    frame = _series("Netflix", ["2025-01-04", "2025-02-04", "2025-03-04",
                                "2025-04-04", "2025-05-04"], 22.99)
    report = detect_recurring(frame, as_of=pd.Timestamp("2025-05-10").date())
    assert report.detected_count == 1
    series = report.expenses[0]
    assert series.frequency == "monthly"
    assert series.confidence > 0.85
    assert series.monthly_amount == pytest.approx(22.99, abs=0.01)
    assert series.annual_amount == pytest.approx(275.88, abs=0.5)


def test_rent_with_day_drift_still_monthly():
    """Jan 1 / Feb 1 / Mar 3 / Apr 1 is obviously still rent."""
    frame = _series("Property Mgmt", ["2025-01-01", "2025-02-01", "2025-03-03", "2025-04-01"],
                    1500.0, category="Rent/Mortgage")
    report = detect_recurring(frame, as_of=pd.Timestamp("2025-04-10").date())
    assert report.expenses[0].frequency == "monthly"
    assert report.debt_monthly == pytest.approx(1500.0, abs=1)


@pytest.mark.parametrize("dates,expected", [
    (["2025-01-03", "2025-01-10", "2025-01-17", "2025-01-24", "2025-01-31"], "weekly"),
    (["2025-01-03", "2025-01-17", "2025-01-31", "2025-02-14"], "biweekly"),
    (["2025-01-05", "2025-04-05", "2025-07-05", "2025-10-05"], "quarterly"),
    (["2023-02-10", "2024-02-10", "2025-02-10"], "annual"),
])
def test_frequency_classification(dates, expected):
    report = detect_recurring(_series("Vendor", dates, 50.0),
                              as_of=pd.Timestamp(dates[-1]).date())
    assert report.expenses[0].frequency == expected


def test_random_one_off_purchases_not_recurring():
    frame = _series("Random Shop", ["2025-01-03", "2025-01-19", "2025-03-27", "2025-04-02"],
                    [12.0, 340.0, 8.5, 97.0], category="Shopping")
    assert detect_recurring(frame).detected_count == 0


def test_two_occurrences_insufficient():
    frame = _series("Netflix", ["2025-01-04", "2025-02-04"], 22.99)
    assert detect_recurring(frame).detected_count == 0


def test_amount_clustering_isolates_subscription_from_one_offs():
    """A $22.99 monthly subscription plus ad-hoc $60 purchases at the same
    merchant must not pollute the interval statistics."""
    subscription = _series("Amazon", ["2025-01-05", "2025-02-05", "2025-03-05", "2025-04-05"], 14.99)
    one_offs = _series("Amazon", ["2025-01-19", "2025-02-27", "2025-03-11"], [82.0, 143.0, 61.0])
    report = detect_recurring(pd.concat([subscription, one_offs], ignore_index=True),
                              as_of=pd.Timestamp("2025-04-10").date())
    monthly = [s for s in report.expenses if s.frequency == "monthly"]
    assert len(monthly) == 1
    assert monthly[0].amount_median == pytest.approx(14.99, abs=0.01)


def test_cancelled_subscription_marked_inactive():
    frame = _series("Old Gym", ["2024-01-05", "2024-02-05", "2024-03-05", "2024-04-05"], 35.0)
    report = detect_recurring(frame, as_of=pd.Timestamp("2025-06-01").date())
    series = report.series[0]
    assert not series.active
    assert series.next_expected is None
    assert report.monthly_total == 0.0     # inactive series excluded from totals


def test_next_expected_projected_forward():
    frame = _series("Netflix", ["2025-01-04", "2025-02-04", "2025-03-04"], 22.99)
    series = detect_recurring(frame, as_of=pd.Timestamp("2025-03-10").date()).expenses[0]
    assert series.next_expected.month == 4


def test_recurring_income_separated_from_expenses():
    frame = _series("Acme Payroll", ["2025-01-15", "2025-02-15", "2025-03-15"],
                    2400.0, category="Income", direction="credit")
    report = detect_recurring(frame, as_of=pd.Timestamp("2025-03-20").date())
    assert len(report.income) == 1
    assert len(report.expenses) == 0
    assert report.income_monthly == pytest.approx(2400.0, abs=1)


def test_discretionary_annual_computed(active):
    report = detect_recurring(active)
    assert report.discretionary_annual == pytest.approx(report.discretionary_monthly * 12, abs=1)
    assert report.discretionary_annual <= report.annual_total


def test_empty_frame_returns_empty_report():
    report = detect_recurring(pd.DataFrame())
    assert report.detected_count == 0
    assert report.monthly_total == 0.0


def test_synthetic_statement_finds_known_subscriptions(active):
    report = detect_recurring(active)
    merchants = {s.merchant.lower() for s in report.expenses}
    assert any("netflix" in m or "spotify" in m or "hulu" in m for m in merchants)
    assert report.monthly_total > 0