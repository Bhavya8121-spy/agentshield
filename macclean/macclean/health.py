from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .utils import which

OK = "ok"
WARN = "warn"
MISSING = "missing"
DENIED = "denied"
NOT_APPLICABLE = "n/a"

_TOOLS = (
    ("brew", "Homebrew cache cleanup"),
    ("docker", "Docker cleanup"),
    ("xcrun", "Xcode command line tools"),
    ("npm", "npm cache cleanup"),
)
_FULL_DISK_ACCESS_HINT = (
    "Grant your terminal Full Disk Access in System Settings > Privacy & Security"
)


@dataclass(frozen=True)
class HealthCheck:
    name: str
    status: str
    note: str = ""


def is_macos() -> bool:
    return platform.system() == "Darwin"


def run_health_checks(home: Optional[Path] = None) -> List[HealthCheck]:
    home = Path(home) if home else Path.home()
    tool_checks = [_check_tool(name, purpose) for name, purpose in _TOOLS]
    return [_check_platform(), *tool_checks, _check_trash_access(home)]


def _check_platform() -> HealthCheck:
    if is_macos():
        return HealthCheck("macOS", OK, platform.platform())
    return HealthCheck("macOS", WARN, "macclean targets macOS")


def _check_tool(name: str, purpose: str) -> HealthCheck:
    return HealthCheck(name, OK if which(name) else MISSING, purpose)


def _check_trash_access(home: Path) -> HealthCheck:
    try:
        os.listdir(home / ".Trash")
    except PermissionError:
        return HealthCheck("Trash access", DENIED, _FULL_DISK_ACCESS_HINT)
    except OSError:
        return HealthCheck("Trash access", NOT_APPLICABLE, "no Trash folder")
    return HealthCheck("Trash access", OK)
