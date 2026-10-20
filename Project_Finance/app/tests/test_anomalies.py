import pandas as pd
import pytest

from app.anomaly.detector import detect_anomalies


def _spending(rows):
    return pd.DataFrame([{
        "transaction_id": f"t{i}", "date": pd.Timestamp(d), "merchant": m,
        "clean_description": m.upper(), "category": c, "amount": -abs(a),
        "direction": "debit", "kind": "variable",
    } for i, (d, m, c, a) in enumerate(rows)])


def test_extreme_merchant_outlier_flagged():
    rows = [(f"2025-01-{day:02d}", "Best Buy", "Shopping", amount)
            for day, amount in zip(range(1, 13), [120, 137, 145, 130, 128, 141,
                                                  133, 139, 126, 135, 142, 131])]
    rows.append(("2025-02-01", "Best Buy", "Shopping", 1_420.0))
    report = detect_anomalies(_spending(rows))
    assert report.flagged_count >= 1
    top = report.anomalies[0]
    assert top.amount == pytest.approx(1_420.0)
    assert top.deviation_multiple > 5
    assert "1,420" in top.reason or "1420" in top.reason


def test_consistent_spending_produces_no_flags():
    rows = [(f"2025-01-{day:02d}", "Kroger", "Groceries", 80 + day)
            for day in range(1, 25)]
    report = detect_anomalies(_spending(rows))
    assert report.flagged_count == 0
    assert report.notes


def test_thin_merchant_history_not_flagged():
    """Two visits cannot establish a baseline — flagging here is a false positive."""
    rows = [("2025-01-05", "New Shop", "Shopping", 20.0),
            ("2025-01-20", "New Shop", "Shopping", 900.0)]
    report = detect_anomalies(_spending(rows))
    assert report.flagged_count == 0


def test_small_amounts_ignored_even_if_statistically_odd():
    rows = [(f"2025-01-{day:02d}", "Coffee", "Dining", 4.0) for day in range(1, 15)]
    rows.append(("2025-01-20", "Coffee", "Dining", 18.0))
    report = detect_anomalies(_spending(rows))
    assert report.flagged_count == 0     # $18 is below the absolute floor


def test_scores_bounded_and_sorted():
    rows = [(f"2025-01-{day:02d}", "Shop", "Shopping", 100.0) for day in range(1, 16)]
    rows += [("2025-02-01", "Shop", "Shopping", 2_000.0),
             ("2025-02-02", "Shop", "Shopping", 1_500.0)]
    report = detect_anomalies(_spending(rows))
    scores = [a.score for a in report.anomalies]
    assert all(0 <= s <= 1 for s in scores)
    assert scores == sorted(scores, reverse=True)


def test_top_n_respected():
    rows = [(f"2025-01-{day:02d}", "Shop", "Shopping", 100.0) for day in range(1, 20)]
    rows += [(f"2025-02-{day:02d}", "Shop", "Shopping", 1_000.0 + day * 50) for day in range(1, 10)]
    report = detect_anomalies(_spending(rows), top_n=3)
    assert len(report.anomalies) <= 3


def test_output_disclaims_fraud():
    rows = [(f"2025-01-{day:02d}", "Shop", "Shopping", 100.0) for day in range(1, 15)]
    payload = detect_anomalies(_spending(rows)).to_dict()
    assert "not verified fraud" in payload["disclaimer"]
    assert "no fraud claim" in payload["disclaimer"].lower()


def test_method_labels_are_reported():
    rows = [(f"2025-01-{day:02d}", "Shop", "Shopping", 100.0) for day in range(1, 16)]
    rows.append(("2025-02-01", "Shop", "Shopping", 2_500.0))
    report = detect_anomalies(_spending(rows))
    assert report.anomalies[0].method.startswith(("merchant_", "category_", "isolation_"))


def test_empty_input_safe():
    report = detect_anomalies(pd.DataFrame())
    assert report.flagged_count == 0
    assert report.transactions_scanned == 0
    assert report.notes


def test_flag_rate_reasonable_on_real_statement(dataset):
    report = detect_anomalies(dataset.spending)
    rate = report.flagged_count / max(report.transactions_scanned, 1)
    assert rate < 0.10, f"flag rate {rate:.1%} is too noisy to be useful"


def test_small_sample_warning(dataset):
    subset = dataset.spending.head(20)
    assert any("Fewer than 50" in note for note in detect_anomalies(subset).notes)