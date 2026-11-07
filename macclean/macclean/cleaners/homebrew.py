from __future__ import annotations

from pathlib import Path
from typing import List

from ..models import CleanableItem, Safety
from ..utils import run_output, which
from .base import Cleaner


class HomebrewCleaner(Cleaner):
    name = "homebrew"

    def _cache_dir(self) -> Path:
        if which("brew"):
            out = run_output(["brew", "--cache"], timeout=10)
            if out and out.strip():
                return Path(out.strip())
        return self.home / "Library" / "Caches" / "Homebrew"

    def scan(self) -> List[CleanableItem]:
        item = self.dir_item(
            self._cache_dir(),
            "Homebrew cache",
            Safety.SAFE,
            contents_only=True,
            note="Downloaded bottles and sources; re-downloaded when needed",
        )
        return [item] if item else []
