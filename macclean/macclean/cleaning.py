from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Sequence

from .cleaners import build_cleaners
from .models import CleanableItem, CleanResult


def clean_items(
    items: Sequence[CleanableItem],
    home: Optional[Path] = None,
    *,
    dry_run: bool,
) -> CleanResult:
    """Hand each item to the cleaner that found it and combine the results."""
    combined = CleanResult()
    for category in sorted({item.category for item in items}):
        cleaner = build_cleaners(home, only=[category])[0]
        combined.merge(cleaner.clean(_in_category(items, category), dry_run=dry_run))
    return combined


def _in_category(items: Sequence[CleanableItem], category: str) -> List[CleanableItem]:
    return [item for item in items if item.category == category]
