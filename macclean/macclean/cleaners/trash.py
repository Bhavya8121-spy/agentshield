from __future__ import annotations

from typing import List

from ..models import CleanableItem, Safety
from .base import Cleaner


class TrashCleaner(Cleaner):
    name = "trash"

    def scan(self) -> List[CleanableItem]:
        item = self.dir_item(
            self.home / ".Trash",
            "Trash",
            Safety.REVIEW,
            contents_only=True,
            note="Permanent: emptied files cannot be recovered",
        )
        return [item] if item else []
