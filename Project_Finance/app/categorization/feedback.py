from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.core.exceptions import ValidationFailure
from app.core.logging import get_logger

log = get_logger(__name__)
_lock = threading.Lock()
_cache: dict[str, str] | None = None


def _path() -> Path:
    return Path(settings.feedback_path)


def record_correction(
    merchant: str,
    clean_description: str,
    amount: float,
    predicted_category: str,
    corrected_category: str,
    subcategory: str | None = None,
) -> dict:
    """Append a correction. Stores merchant + cleaned text only — never raw
    descriptions, account numbers, or balances."""
    from app.categorization.rules import CATEGORIES

    if corrected_category not in CATEGORIES:
        raise ValidationFailure(f"Unknown category '{corrected_category}'.",
                                {"allowed": list(CATEGORIES)})

    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "merchant": str(merchant or "").strip(),
        "clean_description": str(clean_description or "").strip(),
        "amount_bucket": _bucket(amount),
        "predicted": predicted_category,
        "corrected": corrected_category,
        "subcategory": subcategory,
    }
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        global _cache
        _cache = None
    log.info("Correction recorded: %s -> %s", predicted_category, corrected_category)
    return record


def _bucket(amount: float) -> str:
    value = abs(float(amount))
    for edge in (10, 25, 50, 100, 250, 500, 1000, 2500):
        if value < edge:
            return f"<{edge}"
    return ">=2500"


def load_corrections() -> list[dict]:
    path = _path()
    if not path.exists():
        return []
    records: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def merchant_overrides() -> dict[str, str]:
    """merchant(lowercased) -> category, using the most recent correction per merchant."""
    global _cache
    if _cache is not None:
        return _cache
    overrides: dict[str, str] = {}
    for record in load_corrections():
        merchant = str(record.get("merchant", "")).lower().strip()
        category = record.get("corrected")
        if merchant and category:
            overrides[merchant] = category
    _cache = overrides
    return overrides


def training_examples() -> list[dict]:
    """Corrections reshaped as supervised rows for the next training run."""
    return [
        {"clean_description": r.get("clean_description", ""),
         "merchant": r.get("merchant", ""),
         "category": r["corrected"]}
        for r in load_corrections() if r.get("corrected")
    ]


def stats() -> dict:
    records = load_corrections()
    return {
        "total_corrections": len(records),
        "unique_merchants": len({r.get("merchant", "").lower() for r in records if r.get("merchant")}),
        "most_corrected_from": _top(records, "predicted"),
        "most_corrected_to": _top(records, "corrected"),
    }


def _top(records: list[dict], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        value = record.get(field)
        if value:
            counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1])[:5])