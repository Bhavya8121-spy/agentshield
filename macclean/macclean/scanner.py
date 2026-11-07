from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence

from .cleaners.base import Cleaner
from .models import CleanableItem, Safety


@dataclass
class ScanReport:
    items: List[CleanableItem] = field(default_factory=list)
    errors: Dict[str, str] = field(default_factory=dict)

    def total(self, *safeties: Safety, cleanable: Optional[bool] = None) -> int:
        total = 0
        for item in self.items:
            if safeties and item.safety not in safeties:
                continue
            if cleanable is not None and item.cleanable != cleanable:
                continue
            total += item.size
        return total

    @property
    def safe_total(self) -> int:
        return self.total(Safety.SAFE, cleanable=True)

    @property
    def review_total(self) -> int:
        return self.total(Safety.REVIEW, cleanable=True)

    @property
    def report_only_total(self) -> int:
        return self.total(cleanable=False)


def scan(
    cleaners: Sequence[Cleaner],
    on_done: Optional[Callable[[Cleaner], None]] = None,
) -> ScanReport:
    """Run every cleaner's scan() in parallel (it's all disk I/O)."""
    report = ScanReport()
    if not cleaners:
        return report
    with ThreadPoolExecutor(max_workers=min(8, len(cleaners))) as pool:
        futures = {pool.submit(c.scan): c for c in cleaners}
        for future in as_completed(futures):
            cleaner = futures[future]
            try:
                report.items.extend(future.result())
            except Exception as exc:  # one broken cleaner must not kill the scan
                report.errors[cleaner.name] = f"{type(exc).__name__}: {exc}"
            if on_done:
                on_done(cleaner)
    report.items.sort(key=lambda i: (i.category, -i.size))
    return report


def select_items(
    items: Sequence[CleanableItem], include_review: bool = False
) -> List[CleanableItem]:
    """Pick what `clean` may remove: SAFE always, REVIEW only on request."""
    allowed = {Safety.SAFE}
    if include_review:
        allowed.add(Safety.REVIEW)
    return [i for i in items if i.cleanable and i.safety in allowed]
