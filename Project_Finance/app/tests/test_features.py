import pandas as pd
import pytest

from app.forecasting.features import build_features


def _statement(rows):
    return pd.DataFrame([{
        "transaction_id": f"t{i}", "date": pd.Timestamp(d), "merchant": m,
        "clean_description": m.upper(), "category": c, "amount": a,
        "direction": "credit" if a > 0 else "debit", "kind": k,
        "balance": None, "outflow": max(-a, 0), "inflow": max(a, 0),
    } for i, (d, m, c, a, k) in enumerate(rows)])


def test_partial_final_month_excluded_from_averages():
    """A statement ending on the 8th must not drag the monthly income mean down."""
    rows = []
    for month in (1, 2, 3):
        rows.append((f"2025-{month:02d}-01", "Payroll", "Income", 4000.0, "income"))
        rows.append((f"2025-{month:02d}-05", "Rent", "Rent/Mortgage", -1500.0, "fixed"))
    rows.append(("2025-04-08", "Payroll", "Income", 1000.0, "income"))   # partial month

    features = build_features(_statement(rows))
    assert features.complete_months == 3
    assert features.monthly_income_mean == pytest.approx(4000.0, abs=1)


def test_dti_numerator_excludes_insurance_and_utilities():
    rows = [("2025-01-01", "Payroll", "Income", 5000.0, "income"),
            ("2025-01-05", "Rent", "Rent/Mortgage", -1500.0, "fixed"),
            ("2025-01-06", "Auto Loan", "Loan Payment", -400.0, "fixed"),
            ("2025-01-07", "Geico", "Insurance", -180.0, "fixed"),
            ("2025-01-08", "Electric", "Utilities", -120.0, "fixed"),
            ("2025-02-01", "Payroll", "Income", 5000.0, "income"),
            ("2025-02-05", "Rent", "Rent/Mortgage", -1500.0, "fixed"),
            ("2025-02-06", "Auto Loan", "Loan Payment", -400.0, "fixed"),
            ("2025-02-07", "Geico", "Insurance", -180.0, "fixed"),
            ("2025-02-08", "Electric", "Utilities", -120.0, "fixed"),
            ("2025-02-28", "Filler", "Groceries", -1.0, "variable")]
    features = build_features(_statement(rows))
    assert features.debt_service_monthly == pytest.approx(1900.0, abs=5)
    assert features.fixed_monthly == pytest.approx(2200.0, abs=5)
    dti = features.debt_service_monthly / features.monthly_income_mean
    assert dti == pytest.approx(0.38, abs=0.01)


def test_stability_high_for_constant_income():
    rows = []
    for month in range(1, 5):
        rows.append((f"2025-{month:02d}-01", "Payroll", "Income", 4000.0, "income"))
        rows.append((f"2025-{month:02d}-15", "Rent", "Rent/Mortgage", -1500.0, "fixed"))
    features = build_features(_statement(rows))
    assert features.income_cv < 0.01
    assert features.income_stability > 0.95


def test_stability_low_for_volatile_income():
    amounts = [1200.0, 6800.0, 2100.0, 7400.0]
    rows = [(f"2025-{m:02d}-01", "Client", "Income", a, "income")
            for m, a in enumerate(amounts, start=1)]
    rows += [(f"2025-{m:02d}-15", "Rent", "Rent/Mortgage", -1500.0, "fixed")
             for m in range(1, 5)]
    features = build_features(_statement(rows))
    assert features.income_cv > 0.4
    assert features.income_stability < 0.6


def test_balance_from_statement_column_preferred():
    frame = _statement([("2025-01-01", "Payroll", "Income", 4000.0, "income"),
                        ("2025-02-01", "Payroll", "Income", 4000.0, "income")])
    frame["balance"] = [10_000.0, 14_000.0]
    features = build_features(frame)
    assert features.balance_source == "statement_balance"
    assert features.liquid_savings == pytest.approx(14_000.0)


def test_missing_balance_warns_and_estimates():
    features = build_features(_statement([
        ("2025-01-01", "Payroll", "Income", 4000.0, "income"),
        ("2025-02-01", "Payroll", "Income", 4000.0, "income"),
    ]))
    assert features.balance_source == "estimated_from_net_flow"
    assert any("balance" in w.lower() for w in features.warnings)


def test_override_beats_everything():
    frame = _statement([("2025-01-01", "Payroll", "Income", 4000.0, "income")])
    frame["balance"] = [99_999.0]
    features = build_features(frame, liquid_savings_override=5_000.0)
    assert features.liquid_savings == 5_000.0
    assert features.balance_source == "user_provided"


def test_runway_uses_essential_expenses_only():
    rows = [("2025-01-01", "Payroll", "Income", 4000.0, "income"),
            ("2025-01-05", "Rent", "Rent/Mortgage", -1000.0, "fixed"),
            ("2025-01-10", "Dining", "Dining", -500.0, "variable"),
            ("2025-02-01", "Payroll", "Income", 4000.0, "income"),
            ("2025-02-05", "Rent", "Rent/Mortgage", -1000.0, "fixed"),
            ("2025-02-10", "Dining", "Dining", -500.0, "variable")]
    features = build_features(_statement(rows), liquid_savings_override=6_000.0)
    # Essentials are $1,000/mo (rent), not $1,500 — dining is discretionary.
    assert features.essential_monthly == pytest.approx(1000.0, abs=5)
    assert features.emergency_runway_months == pytest.approx(6.0, abs=0.1)


def test_single_month_prorated_with_warning():
    features = build_features(_statement([
        ("2025-01-05", "Payroll", "Income", 2000.0, "income"),
        ("2025-01-20", "Rent", "Rent/Mortgage", -800.0, "fixed"),
    ]))
    assert features.complete_months < 2
    assert any("complete calendar month" in w for w in features.warnings)
    assert features.monthly_income_mean > 0


def test_zero_income_does_not_divide_by_zero():
    features = build_features(_statement([
        ("2025-01-05", "Rent", "Rent/Mortgage", -800.0, "fixed"),
        ("2025-02-05", "Rent", "Rent/Mortgage", -800.0, "fixed"),
    ]))
    assert features.savings_rate == 0.0
    assert features.income_cv == 0.0


def test_empty_frame_safe():
    features = build_features(pd.DataFrame())
    assert features.monthly_income_mean == 0.0
    assert features.warnings


def test_synthetic_features_sane(features):
    assert features.monthly_income_mean > 1000
    assert features.monthly_outflow_mean > 0
    assert 0 <= features.income_stability <= 1
    assert features.complete_months >= 10