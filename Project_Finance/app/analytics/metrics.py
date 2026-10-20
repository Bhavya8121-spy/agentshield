from __future__ import annotations

from collections import Counter

from app.analytics.events import read_events
from app.categorization.feedback import stats as feedback_stats


def usage_summary() -> dict:
    events = read_events()
    counts = Counter(event["event"] for event in events)
    sessions = {event["session"] for event in events if event.get("session")}

    def total(event_name: str, prop: str) -> float:
        return sum(
            event["props"].get(prop, 0)
            for event in events if event["event"] == event_name
        )

    latencies = [
        event["props"]["duration_ms"] for event in events
        if "duration_ms" in event.get("props", {})
    ]
    latencies.sort()

    def percentile(data: list[float], q: float) -> float | None:
        if not data:
            return None
        index = min(int(q * len(data)), len(data) - 1)
        return round(float(data[index]), 1)

    return {
        "usage": {
            "unique_sessions": len(sessions),
            "statements_analyzed": counts.get("csv_uploaded", 0),
            "transactions_analyzed": int(total("transactions_processed", "transaction_count")),
            "forecasts_generated": counts.get("forecast_generated", 0),
            "simulations_completed": counts.get("monte_carlo_completed", 0),
            "stress_tests_completed": counts.get("stress_test_completed", 0),
            "affordability_checks": counts.get("affordability_calculated", 0),
            "anomalies_surfaced": int(total("anomaly_detected", "anomaly_count")),
            "category_corrections": counts.get("category_corrected", 0),
        },
        "quality": {
            "correction_rate_per_upload": round(
                counts.get("category_corrected", 0) / max(counts.get("csv_uploaded", 1), 1), 4
            ),
            **feedback_stats(),
        },
        "performance": {
            "requests_measured": len(latencies),
            "p50_latency_ms": percentile(latencies, 0.50),
            "p95_latency_ms": percentile(latencies, 0.95),
            "p99_latency_ms": percentile(latencies, 0.99),
        },
        "event_counts": dict(counts),
        "note": (
            "Derived from local instrumentation. Contains no transaction data, "
            "merchant names, amounts or balances."
        ),
    }