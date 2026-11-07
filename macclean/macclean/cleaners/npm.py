from __future__ import annotations

from typing import List

from ..models import CleanableItem, Safety
from .base import Cleaner


class NpmCleaner(Cleaner):
    name = "npm"

    def scan(self) -> List[CleanableItem]:
        item = self.dir_item(
            self.home / ".npm" / "_cacache",
            "npm cache",
            Safety.SAFE,
            contents_only=True,
            note="Package tarballs; re-fetched on the next install",
        )
        return [item] if item else []
