from __future__ import annotations

from typing import List

from ..models import CleanableItem, Safety
from .base import Cleaner


class PipCleaner(Cleaner):
    name = "pip"

    def scan(self) -> List[CleanableItem]:
        item = self.dir_item(
            self.home / "Library" / "Caches" / "pip",
            "pip cache",
            Safety.SAFE,
            contents_only=True,
            note="Wheels and HTTP cache; re-fetched on the next install",
        )
        return [item] if item else []
