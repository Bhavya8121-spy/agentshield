from __future__ import annotations

import json
import re
from typing import List

from ..models import CleanableItem, Safety
from ..utils import run_output, which
from .base import Cleaner

_SIZE_RE = re.compile(r"([\d.]+)\s*([kKMGT]?B)")
_MULTIPLIERS = {"B": 1, "KB": 10**3, "MB": 10**6, "GB": 10**9, "TB": 10**12}


def parse_size(text: str) -> int:
    """Parse Docker's size strings, e.g. '6.8GB (100%)' -> 6800000000."""
    match = _SIZE_RE.search(text or "")
    if not match:
        return 0
    return int(float(match.group(1)) * _MULTIPLIERS[match.group(2).upper()])


class DockerCleaner(Cleaner):
    name = "docker"

    def scan(self) -> List[CleanableItem]:
        if not which("docker"):
            return []
        out = run_output(["docker", "system", "df", "--format", "{{json .}}"])
        if not out:  # Docker not running, or command failed
            return []

        items: List[CleanableItem] = []
        for line in out.splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            size = parse_size(row.get("Reclaimable", ""))
            if size <= 0:
                continue
            kind = row.get("Type")
            if kind == "Build Cache":
                items.append(
                    CleanableItem(
                        category=self.name,
                        label="Docker build cache",
                        size=size,
                        safety=Safety.REVIEW,
                        command=("docker", "builder", "prune", "-f"),
                        note="Slows the next build; nothing is lost",
                    )
                )
            elif kind == "Images":
                items.append(
                    CleanableItem(
                        category=self.name,
                        label="Docker unused images",
                        size=size,
                        safety=Safety.REVIEW,
                        report_only=True,
                        note="Review with: docker image prune -a",
                    )
                )
            elif kind == "Local Volumes":
                items.append(
                    CleanableItem(
                        category=self.name,
                        label="Docker volumes",
                        size=size,
                        safety=Safety.DANGEROUS,
                        report_only=True,
                        note="Volumes hold real data (databases). Never auto-cleaned",
                    )
                )
        return items
