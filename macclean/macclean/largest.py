from __future__ import annotations

import heapq
import os
from pathlib import Path
from typing import List, Tuple

from .utils import disk_usage

_SKIP_TOP_LEVEL = {"Library", ".Trash"}


def find_largest(
    root: Path, limit: int = 20, min_size: int = 100_000_000
) -> List[Tuple[int, Path]]:
    """Largest files under `root`. Report only; nothing here deletes."""
    root = Path(root)
    heap: List[Tuple[int, int, Path]] = []
    counter = 0
    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        if Path(dirpath) == root:
            dirnames[:] = [d for d in dirnames if d not in _SKIP_TOP_LEVEL]
        for name in filenames:
            file_path = Path(dirpath) / name
            if file_path.is_symlink():
                continue
            size = disk_usage(file_path)
            if size < min_size:
                continue
            counter += 1
            entry = (size, counter, file_path)
            if len(heap) < limit:
                heapq.heappush(heap, entry)
            else:
                heapq.heappushpop(heap, entry)
    return [(size, path) for size, _, path in sorted(heap, reverse=True)]
