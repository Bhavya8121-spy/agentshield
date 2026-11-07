from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

_UNITS = ("B", "kB", "MB", "GB", "TB")


def format_size(num_bytes: int) -> str:
    """Format like Finder does (decimal units)."""
    size = float(num_bytes)
    for unit in _UNITS:
        if size < 1000 or unit == _UNITS[-1]:
            return f"{int(size)} B" if unit == "B" else f"{size:.2f} {unit}"
        size /= 1000
    return f"{num_bytes} B"  # unreachable


def _file_size(st: os.stat_result) -> int:
    blocks = getattr(st, "st_blocks", None)
    return blocks * 512 if blocks is not None else st.st_size


def disk_usage(path: Path) -> int:
    """Bytes of disk used by a file or directory tree. Never follows symlinks."""
    try:
        st = os.lstat(path)
    except OSError:
        return 0
    if not stat.S_ISDIR(st.st_mode):
        return _file_size(st)

    total = 0
    stack = [str(path)]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        entry_stat = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if stat.S_ISDIR(entry_stat.st_mode):
                        stack.append(entry.path)
                    else:
                        total += _file_size(entry_stat)
        except OSError:
            continue
    return total


# ---------------------------------------------------------------------------
# Deletion guard
# ---------------------------------------------------------------------------


class UnsafePathError(Exception):
    """Raised when something tries to delete a path we never want to touch."""


# Never delete these (or anything inside them), no matter what a cleaner says.
_PROTECTED_PREFIXES: Tuple[Tuple[str, ...], ...] = (
    ("Documents",),
    ("Desktop",),
    ("Downloads",),
    ("Pictures",),
    ("Movies",),
    ("Music",),
    ("Public",),
    ("Applications",),
    (".ssh",),
    (".gnupg",),
    ("Library", "Application Support"),
    ("Library", "Preferences"),
    ("Library", "Keychains"),
    ("Library", "Containers"),
    ("Library", "Group Containers"),
    ("Library", "Mobile Documents"),  # iCloud Drive
    ("Library", "Mail"),
    ("Library", "Messages"),
    ("Library", "Photos"),
)

# Container folders that may never be removed themselves.
_BLOCKED_EXACT = {
    ("Library",),
    ("Library", "Caches"),
    ("Library", "Developer"),
}


def check_deletable(path: Path, home: Path) -> Path:
    """Return the path to delete, or raise UnsafePathError.

    The final path component is deliberately *not* resolved, so a symlink is
    removed as a link instead of being followed to wherever it points.
    """
    home_resolved = Path(home).resolve()
    path = Path(path)
    target = path.parent.resolve() / path.name
    try:
        parts = target.relative_to(home_resolved).parts
    except ValueError:
        raise UnsafePathError(f"refusing {path}: outside the home directory")
    if not parts:
        raise UnsafePathError("refusing to delete the home directory itself")
    if parts in _BLOCKED_EXACT:
        raise UnsafePathError(f"refusing {path}: too broad")
    for prefix in _PROTECTED_PREFIXES:
        if parts[: len(prefix)] == prefix:
            raise UnsafePathError(f"refusing {path}: protected location")
    return target


def delete_path(
    path: Path, home: Path, contents_only: bool = False
) -> Tuple[int, List[str]]:
    """Delete `path` (or everything inside it). Returns (bytes_freed, errors)."""
    try:
        target = check_deletable(path, home)
    except UnsafePathError as exc:
        return 0, [str(exc)]

    if contents_only:
        if target.is_symlink() or not target.is_dir():
            return 0, []
        try:
            children = list(target.iterdir())
        except OSError as exc:
            return 0, [f"{target}: {exc.strerror or exc}"]
    else:
        children = [target]

    freed = 0
    errors: List[str] = []
    for child in children:
        before = disk_usage(child)
        try:
            if child.is_symlink() or not child.is_dir():
                child.unlink()
            else:
                shutil.rmtree(child)
        except FileNotFoundError:
            continue
        except OSError as exc:
            errors.append(f"{child}: {exc.strerror or exc}")
            after = disk_usage(child) if os.path.lexists(child) else 0
            freed += max(before - after, 0)
            continue
        freed += before
    return freed, errors


# ---------------------------------------------------------------------------
# Subprocess helpers
# ---------------------------------------------------------------------------


def run_output(cmd: Sequence[str], timeout: int = 20) -> Optional[str]:
    """Run a command, return stdout, or None if it is missing/fails/times out."""
    try:
        proc = subprocess.run(
            list(cmd), capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 else None


def run_command(cmd: Sequence[str], timeout: int = 900) -> Optional[str]:
    """Run a cleanup command. Returns an error message, or None on success."""
    try:
        proc = subprocess.run(
            list(cmd), capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"{' '.join(cmd)}: {exc}"
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        return f"{' '.join(cmd)}: {detail[-1] if detail else 'failed'}"
    return None


def which(name: str) -> Optional[str]:
    return shutil.which(name)
