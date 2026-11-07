from __future__ import annotations

from pathlib import Path

from .models import CleanableItem


def display_path(path: Path, home: Path) -> str:
    try:
        return "~/" + str(Path(path).relative_to(home))
    except ValueError:
        return str(path)


def describe_target(item: CleanableItem, home: Path) -> str:
    """What cleaning this item would do, in words a user can read."""
    if item.command is not None:
        return "run: " + " ".join(item.command)
    if item.path is None:
        return ""
    shown = display_path(item.path, home)
    return shown + "/* (contents)" if item.contents_only else shown
