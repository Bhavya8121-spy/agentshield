from __future__ import annotations

import shutil
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator, List, NamedTuple, Optional, Sequence, Tuple

from ..cleaners import Cleaner, UnknownCategoryError, build_cleaners
from ..cleaning import clean_items
from ..health import HealthCheck, run_health_checks
from ..largest import find_largest
from ..models import CleanableItem, CleanResult
from ..scanner import ScanReport
from ..scanner import scan as run_scan
from .errors import ApiError

HTTP_FORBIDDEN = 403
HTTP_CONFLICT = 409


class DiskUsage(NamedTuple):
    total: int
    used: int
    free: int

    @property
    def is_known(self) -> bool:
        return self.total > 0


UNKNOWN_DISK = DiskUsage(0, 0, 0)


class DashboardService:
    """Everything the dashboard can do. It knows nothing about HTTP.

    Only items from the latest scan can be cleaned, and only by id, so the
    browser can never ask for an arbitrary path to be deleted.
    """

    def __init__(self, home: Optional[Path] = None) -> None:
        self.home = Path(home) if home else Path.home()
        self._items_by_id: Dict[str, CleanableItem] = {}
        self._busy = threading.Lock()

    def disk_usage(self) -> DiskUsage:
        try:
            return DiskUsage(*shutil.disk_usage(self.home))
        except OSError:
            return UNKNOWN_DISK

    def scan(self, deep: bool, categories: Sequence[str]) -> ScanReport:
        with self._exclusive():
            report = run_scan(self._build_cleaners(deep, categories))
            self._items_by_id = {item.id: item for item in report.items}
            return report

    def clean(self, ids: Sequence[str], *, dry_run: bool, confirmed: bool) -> CleanResult:
        if not dry_run and not confirmed:
            raise ApiError("Deleting needs explicit confirmation.")
        with self._exclusive():
            items = self._cleanable_items(ids)
            result = clean_items(items, self.home, dry_run=dry_run)
            if not dry_run:
                self._forget(items)
            return result

    def largest(
        self, path: str, limit: int, min_size: int
    ) -> Tuple[Path, List[Tuple[int, Path]]]:
        root = self._search_root(path)
        return root, find_largest(root, limit=limit, min_size=min_size)

    def health(self) -> List[HealthCheck]:
        return run_health_checks(self.home)

    # -- helpers ---------------------------------------------------------------

    @contextmanager
    def _exclusive(self) -> Iterator[None]:
        if not self._busy.acquire(blocking=False):
            raise ApiError("Another scan or clean is still running.", HTTP_CONFLICT)
        try:
            yield
        finally:
            self._busy.release()

    def _build_cleaners(self, deep: bool, categories: Sequence[str]) -> List[Cleaner]:
        try:
            return build_cleaners(self.home, deep=deep, only=categories)
        except UnknownCategoryError as exc:
            raise ApiError(str(exc)) from exc

    def _cleanable_items(self, ids: Sequence[str]) -> List[CleanableItem]:
        if not ids:
            raise ApiError("Select at least one item.")
        if any(wanted not in self._items_by_id for wanted in ids):
            raise ApiError("Those results are out of date. Scan again.", HTTP_CONFLICT)
        items = [self._items_by_id[wanted] for wanted in dict.fromkeys(ids)]
        refused = [item.label for item in items if not item.cleanable]
        if refused:
            raise ApiError("macclean can't clean: " + ", ".join(refused))
        return items

    def _forget(self, items: Sequence[CleanableItem]) -> None:
        for item in items:
            self._items_by_id.pop(item.id, None)

    def _search_root(self, text: str) -> Path:
        if text == "~" or text.startswith("~/"):
            text = str(self.home) + text[1:]
        root = Path(text).resolve()
        if not root.is_dir():
            raise ApiError(f"Not a folder: {text}")
        home = self.home.resolve()
        if root != home and home not in root.parents:
            raise ApiError("Only folders inside your home folder can be searched.", HTTP_FORBIDDEN)
        return root
