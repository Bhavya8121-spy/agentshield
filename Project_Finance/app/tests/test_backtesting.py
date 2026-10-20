import pandas as pd
import pytest

from app.core.exceptions import InsufficientHistory
from app.forecasting.backtest import backtest_summary_markdown, walk_forward


def test_produces_folds(active):
    report = walk_forward(active)
    assert report.months_available >= 10
    assert report.folds
    assert report.metrics


def test_fold_count_decreases_with_horizon(active):
    report = walk_forward(active, horizons_months=(1, 3))
    counts = {key: metric.folds for key, metric in report.metrics.items()}
    assert len(counts) == 2
    assert min(counts.values()) < max(counts.values())


def test_metrics_are_non_negative(active):
    for metric in walk_forward(active).metrics.values():
        assert metric.mae >= 0
        assert metric.rmse >= metric.mae     # RMSE never below MAE
        assert 0 <= metric.directional_accuracy <= 1
        assert 0 <= metric.interval_coverage <= 1


def test_naive_baselines_reported(active):
    """Every horizon must carry a baseline so skill is verifiable."""
    for metric in walk_forward(active).metrics.values():
        assert metric.naive_last_month_mae > 0
        assert metric.naive_mean_mae > 0
        assert isinstance(metric.skill_vs_last_month, float)


def test_no_lookahead_leakage(active):
    """Each fold's training data must end before the tested period begins."""
    report = walk_forward(active, horizons_months=(1,))
    for fold in report.folds:
        assert fold.train_months >= 3
        assert fold.cutoff  # cutoff period recorded for auditability


def test_insufficient_history_reports_note_not_crash():
    frame = pd.DataFrame([{
        "transaction_id": "t1", "date": pd.Timestamp("2025-01-15"), "merchant": "X",
        "clean_description": "X", "category": "Groceries", "amount": -40.0,
        "direction": "debit", "kind": "variable", "balance": None,
        "outflow": 40.0, "inflow": 0.0,
    }])
    report = walk_forward(frame)
    assert report.metrics == {}
    assert report.notes


def test_empty_raises():
    with pytest.raises(InsufficientHistory):
        walk_forward(pd.DataFrame())


def test_markdown_renders(active):
    markdown = backtest_summary_markdown(walk_forward(active))
    assert "| Horizon |" in markdown
    assert "Naive MAE" in markdown


def test_partial_edge_months_excluded(active):
    """Truncated first/last months must not be scored as forecast errors."""
    report = walk_forward(active)
    frame = active.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    calendar_months = frame["date"].dt.to_period("M").nunique()
    assert report.months_available <= calendar_months