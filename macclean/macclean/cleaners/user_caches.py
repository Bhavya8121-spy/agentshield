from __future__ import annotations

import os
from typing import List

from ..models import CleanableItem, Safety
from .base import Cleaner
from ..utils import disk_usage

# Handled by dedicated cleaners.
_HANDLED = {"Homebrew", "pip"}


class UserCachesCleaner(Cleaner):
    """Large per-app caches in ~/Library/Caches. Conservative: REVIEW only."""

    name = "caches"
    min_size = 50_000_000  # ignore anything under ~50 MB

    def scan(self) -> List[CleanableItem]:
        root = self.home / "Library" / "Caches"
        items: List[CleanableItem] = []
        try:
            entries = list(os.scandir(root))
        except OSError:
            return items
        for entry in entries:
            if entry.name in _HANDLED or entry.name.startswith("com.apple."):
                continue
            if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                continue
            size = disk_usage(root / entry.name)
            if size < self.min_size:
                continue
            items.append(
                CleanableItem(
                    category=self.name,
                    label=f"App cache: {entry.name}",
                    size=size,
                    safety=Safety.REVIEW,
                    path=root / entry.name,
                    contents_only=True,
                    note="Quit the app first; it rebuilds this cache",
                )
            )
        return items
