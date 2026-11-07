from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar, List, Optional, Sequence

from ..models import CleanableItem, CleanResult, Safety
from ..utils import delete_path, disk_usage, run_command


class Cleaner(ABC):
    """A cleaner knows how to find one kind of reclaimable space.

    To add a new one: subclass this, set `name`, implement `scan()`, and
    register it in `cleaners/__init__.py`. The default `clean()` handles both
    path-based and command-based items, and always goes through the deletion
    guard in `utils.check_deletable`.
    """

    name: ClassVar[str] = ""

    def __init__(self, home: Optional[Path] = None) -> None:
        self.home = Path(home) if home else Path.home()

    @abstractmethod
    def scan(self) -> List[CleanableItem]:
        """Find things this cleaner could remove. Must not modify anything."""

    def clean(
        self, items: Sequence[CleanableItem], dry_run: bool = True
    ) -> CleanResult:
        result = CleanResult()
        for item in items:
            if item.safety is Safety.DANGEROUS:
                result.errors.append(f"refusing dangerous item: {item.label}")
                continue
            if not item.cleanable:
                continue
            if dry_run:
                result.freed += item.size
                result.cleaned.append(item)
                continue

            if item.path is not None:
                freed, errors = delete_path(
                    item.path, self.home, contents_only=item.contents_only
                )
                result.freed += freed
                result.errors.extend(errors)
            elif item.command is not None:
                error = run_command(item.command)
                if error:
                    result.errors.append(error)
                else:
                    result.freed += item.size
            result.cleaned.append(item)
        return result

    # -- helper for subclasses ------------------------------------------------

    def dir_item(
        self,
        path: Path,
        label: str,
        safety: Safety,
        *,
        contents_only: bool = False,
        report_only: bool = False,
        note: str = "",
    ) -> Optional[CleanableItem]:
        """Build an item for a directory, or None if it is missing or empty."""
        if not path.exists():
            return None
        size = disk_usage(path)
        if size <= 0:
            return None
        return CleanableItem(
            category=self.name,
            label=label,
            size=size,
            safety=safety,
            path=path,
            contents_only=contents_only,
            report_only=report_only,
            note=note,
        )
