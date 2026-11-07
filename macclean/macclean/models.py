from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional, Tuple


class Safety(str, Enum):
    """How risky it is to remove something.

    SAFE       regenerable data (build caches, package caches). Cleaned by default.
    REVIEW     probably fine, but you should look first. Needs --include-review.
    DANGEROUS  could lose real data. Reported only, never cleaned.
    """

    SAFE = "safe"
    REVIEW = "review"
    DANGEROUS = "dangerous"


@dataclass(frozen=True)
class CleanableItem:
    """One thing a cleaner found.

    Exactly one of `path` or `command` says how it would be cleaned.
    `report_only` items are shown to the user but can never be removed by macclean.
    """

    category: str  # name of the cleaner that produced it, e.g. "xcode"
    label: str  # human-readable name
    size: int  # bytes
    safety: Safety
    path: Optional[Path] = None
    command: Optional[Tuple[str, ...]] = None
    contents_only: bool = False  # delete what is inside `path`, keep the folder
    report_only: bool = False
    note: str = ""

    @property
    def id(self) -> str:
        """Stable short id, so callers can name an item without passing paths around."""
        identity = "|".join((self.category, self.label, str(self.path), str(self.command)))
        return hashlib.sha256(identity.encode()).hexdigest()[:12]

    @property
    def cleanable(self) -> bool:
        if self.report_only or self.safety is Safety.DANGEROUS:
            return False
        return self.path is not None or self.command is not None


@dataclass
class CleanResult:
    freed: int = 0
    cleaned: List[CleanableItem] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def merge(self, other: "CleanResult") -> None:
        self.freed += other.freed
        self.cleaned.extend(other.cleaned)
        self.errors.extend(other.errors)
