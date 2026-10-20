from __future__ import annotations

import hashlib
import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)
_lock = threading.Lock()

ALLOWED_EVENTS = {
    "session_started", "demo_started", "csv_uploaded", "csv_rejected",
    "transactions_processed", "category_corrected", "recurring_detected",
    "forecast_generated", "backtest_run", "affordability_calculated",
    "monte_carlo_completed", "stress_test_completed", "anomaly_detected",
    "health_score_viewed", "balance_provided",
}

# Only these keys are ever persisted; anything else is dropped.
ALLOWED_PROPERTIES = {
    "transaction_count", "months_covered", "category_count", "recurring_count",
    "horizon_days", "runs", "scenario", "score_band", "anomaly_count",
    "duration_ms", "flag_rate", "columns_strategy", "error_code", "review_rate",
}


def new_session_id() -> str:
    return uuid.uuid4().hex[:16]


def _hash(value: str) -> str:
    return hashlib.sha256(f"ff::{value}".encode()).hexdigest()[:16]


def track(event: str, session_id: str | None = None, **properties) -> None:
    if not settings.analytics_enabled:
        return
    if event not in ALLOWED_EVENTS:
        log.warning("Dropped unknown analytics event: %s", event)
        return

    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "session": _hash(session_id) if session_id else None,
        "props": {
            key: value for key, value in properties.items()
            if key in ALLOWED_PROPERTIES and value is not None
        },
    }
    path = Path(settings.analytics_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with _lock, path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
    except OSError as exc:
        log.warning("Analytics write failed: %s", exc)


def read_events() -> list[dict]:
    path = Path(settings.analytics_path)
    if not path.exists():
        return []
    events: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return events