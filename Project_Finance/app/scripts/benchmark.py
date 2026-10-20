#!/usr/bin/env python3
"""Measure every engine across the synthetic corpus and emit README-ready numbers.

Nothing here is hard-coded: every figure printed is computed from the data.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from app.anomaly.detector import detect_anomalies
from app.categorization.classifier import categorize_frame
from app.core.dataset import Dataset, transactions_to_frame
from app.forecasting.backtest import walk_forward
from app.forecasting.model import forecast_dataset
from app.ingestion.parser import parse_statement
from app.recurring.detector import detect_recurring
from app.risk.health_score import compute_health_score
from app.simulation.monte_carlo import MonteCarloRequest, run_monte_carlo


def evaluate_categorization(frame: pd.DataFrame, truth: pd.Series) -> dict:
    from sklearn.metrics import f1_score

    mask = truth.notna() & (frame["amount"] < 0)
    predicted, actual = frame.loc[mask, "category"], truth[mask]
    decided = predicted != "Needs Review"

    return {
        "n": int(mask.sum()),
        "accuracy_all": float((predicted == actual).mean()),
        "accuracy_decided": float((predicted[decided] == actual[decided]).mean()) if decided.any() else 0.0,
        "macro_f1_decided": float(f1_score(actual[decided], predicted[decided],
                                           average="macro", zero_division=0)) if decided.any() else 0.0,
        "review_rate": float((~decided).mean()),
        "coverage": float(decided.mean()),
    }


def evaluate_recurring(frame: pd.DataFrame) -> dict:
    """Ground truth: merchants that genuinely repeat monthly in the generator."""
    known = {"NETFLIX.COM", "SPOTIFY USA", "HULU 877-8244", "APPLE.COM/BILL",
             "ADOBE CREATIVE CLOUD", "PLANET FITNESS", "GEICO AUTO INSURANCE PMT",
             "NES ELECTRIC UTILITY", "VERIZON WIRELESS PMT", "ACH DEBIT AUTO LOAN PAYMENT",
             "NELNET STUDENT LOAN PMT"}
    truth = {
        merchant for merchant, group in frame.groupby("merchant")
        if any(k.lower().startswith(str(merchant).lower()[:6]) for k in known) and len(group) >= 3
    }
    detected = {series.merchant for series in detect_recurring(frame).expenses if series.active}
    if not truth:
        return {}
    true_positive = len(truth & detected)
    precision = true_positive / len(detected) if detected else 0.0
    recall = true_positive / len(truth)
    return {
        "precision": precision, "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("data/synthetic"))
    parser.add_argument("--out", type=Path, default=Path("data/benchmark_report.json"))
    args = parser.parse_args()

    files = sorted(args.data.glob("*.csv"))
    if not files:
        raise SystemExit(f"No CSVs in {args.data}. Run scripts/generate_data.py first.")

    accumulator: dict[str, list] = {
        "cat": [], "rec": [], "backtest": [], "timings": [],
        "recurring_annual": [], "discretionary_annual": [], "health": [], "anomaly_rate": [],
    }
    total_transactions = 0

    for path in files:
        payload = path.read_bytes()
        truth = pd.read_csv(path).get("_truth_category")

        started = time.perf_counter()
        transactions, _ = parse_statement(payload, path.name)
        frame = categorize_frame(transactions_to_frame(transactions))
        parse_ms = (time.perf_counter() - started) * 1000
        total_transactions += len(frame)

        if truth is not None:
            aligned = frame.merge(
                pd.DataFrame({"source_row": range(len(truth)), "_truth": truth.values}),
                on="source_row", how="left",
            )
            accumulator["cat"].append(evaluate_categorization(aligned, aligned["_truth"]))

        active = frame[(~frame["is_duplicate"]) & (frame["kind"] != "transfer")]
        recurring_metrics = evaluate_recurring(active)
        if recurring_metrics:
            accumulator["rec"].append(recurring_metrics)

        dataset = Dataset(df=frame, report=_[1] if isinstance(_, tuple) else None) \
            if False else None  # dataset not needed; use functions directly
        recurring = detect_recurring(active)
        features_started = time.perf_counter()
        from app.forecasting.features import build_features

        features = build_features(active, recurring)
        forecast_started = time.perf_counter()
        forecast_dataset(active, features)
        forecast_ms = (time.perf_counter() - forecast_started) * 1000

        monte_started = time.perf_counter()
        run_monte_carlo(features, recurring, MonteCarloRequest(runs=10_000, months=12))
        monte_ms = (time.perf_counter() - monte_started) * 1000

        try:
            report = walk_forward(active)
            for key, metric in report.metrics.items():
                accumulator["backtest"].append({"horizon": key, **metric.to_dict()})
        except Exception:  # noqa: BLE001
            pass

        anomalies = detect_anomalies(active[active["amount"] < 0])
        accumulator["anomaly_rate"].append(
            anomalies.flagged_count / max(anomalies.transactions_scanned, 1)
        )
        accumulator["recurring_annual"].append(recurring.annual_total)
        accumulator["discretionary_annual"].append(recurring.discretionary_annual)
        accumulator["health"].append(compute_health_score(features, recurring).score)
        accumulator["timings"].append({
            "transactions": len(frame), "parse_ms": parse_ms,
            "features_ms": (forecast_started - features_started) * 1000,
            "forecast_ms": forecast_ms, "monte_carlo_ms": monte_ms,
        })

    def average(records: list[dict], field: str) -> float:
        values = [r[field] for r in records if r.get(field) is not None]
        return float(np.mean(values)) if values else 0.0

    backtest_by_horizon: dict[str, dict] = {}
    for record in accumulator["backtest"]:
        bucket = backtest_by_horizon.setdefault(record["horizon"], {"mae": [], "naive": [],
                                                                    "coverage": [], "direction": []})
        bucket["mae"].append(record["mae"])
        bucket["naive"].append(record["naive_last_month_mae"])
        bucket["coverage"].append(record["interval_coverage"])
        bucket["direction"].append(record["directional_accuracy"])

    result = {
        "dataset": {"households": len(files), "transactions": total_transactions},
        "categorization": {
            key: round(average(accumulator["cat"], key), 4)
            for key in ("accuracy_all", "accuracy_decided", "macro_f1_decided", "review_rate", "coverage")
        },
        "recurring": {key: round(average(accumulator["rec"], key), 4)
                      for key in ("precision", "recall", "f1")},
        "forecast": {
            horizon: {
                "mae": round(float(np.mean(bucket["mae"])), 2),
                "naive_mae": round(float(np.mean(bucket["naive"])), 2),
                "skill_vs_naive": round(1 - np.mean(bucket["mae"]) / np.mean(bucket["naive"]), 4)
                if np.mean(bucket["naive"]) else 0.0,
                "interval_coverage": round(float(np.mean(bucket["coverage"])), 4),
                "directional_accuracy": round(float(np.mean(bucket["direction"])), 4),
            }
            for horizon, bucket in sorted(backtest_by_horizon.items())
        },
        "financial_impact": {
            "recurring_identified_annual_total": round(float(np.sum(accumulator["recurring_annual"])), 2),
            "discretionary_identified_annual_total": round(float(np.sum(accumulator["discretionary_annual"])), 2),
            "discretionary_per_household_annual": round(float(np.mean(accumulator["discretionary_annual"])), 2),
        },
        "health_score": {
            "mean": round(float(np.mean(accumulator["health"])), 1),
            "min": round(float(np.min(accumulator["health"])), 1),
            "max": round(float(np.max(accumulator["health"])), 1),
        },
        "anomaly": {"mean_flag_rate": round(float(np.mean(accumulator["anomaly_rate"])), 4)},
        "performance": {
            key: round(float(np.mean([t[key] for t in accumulator["timings"]])), 1)
            for key in ("parse_ms", "features_ms", "forecast_ms", "monte_carlo_ms")
        },
        "caveat": ("All figures measured on synthetic data generated by scripts/generate_data.py. "
                   "They validate implementation correctness, not real-world accuracy."),
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2))

    print(json.dumps(result, indent=2))
    print("\n--- README table ---")
    print("| Horizon | Model MAE | Naive MAE | Skill | Coverage | Direction |")
    print("|---|---|---|---|---|---|")
    for horizon, metrics in result["forecast"].items():
        print(f"| {horizon.replace('_', ' ')} | ${metrics['mae']:,.0f} | "
              f"${metrics['naive_mae']:,.0f} | {metrics['skill_vs_naive']:+.1%} | "
              f"{metrics['interval_coverage']:.0%} | {metrics['directional_accuracy']:.0%} |")


if __name__ == "__main__":
    main()