from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Type

from .base import Cleaner
from .docker import DockerCleaner
from .homebrew import HomebrewCleaner
from .node_modules import NodeModulesCleaner
from .npm import NpmCleaner
from .pip import PipCleaner
from .trash import TrashCleaner
from .user_caches import UserCachesCleaner
from .xcode import XcodeCleaner

class UnknownCategoryError(ValueError):
    """A category name that no cleaner is registered under."""


# Cleaners that run on every scan.
REGISTRY: Dict[str, Type[Cleaner]] = {
    cls.name: cls
    for cls in (
        XcodeCleaner,
        HomebrewCleaner,
        NpmCleaner,
        PipCleaner,
        DockerCleaner,
        UserCachesCleaner,
        TrashCleaner,
    )
}

# Slow cleaners that only run with --deep (or when asked for by name).
DEEP_REGISTRY: Dict[str, Type[Cleaner]] = {NodeModulesCleaner.name: NodeModulesCleaner}


def all_names() -> List[str]:
    return sorted(list(REGISTRY) + list(DEEP_REGISTRY))


def build_cleaners(
    home: Optional[Path] = None,
    deep: bool = False,
    only: Optional[Sequence[str]] = None,
) -> List[Cleaner]:
    """Instantiate cleaners. Raises UnknownCategoryError on an unknown category name."""
    if only:
        known = {**REGISTRY, **DEEP_REGISTRY}
        unknown = [name for name in only if name not in known]
        if unknown:
            raise UnknownCategoryError(
                f"unknown category: {', '.join(unknown)} (choose from {', '.join(all_names())})"
            )
        return [known[name](home) for name in dict.fromkeys(only)]
    classes = list(REGISTRY.values()) + (list(DEEP_REGISTRY.values()) if deep else [])
    return [cls(home) for cls in classes]


__all__ = [
    "Cleaner",
    "REGISTRY",
    "DEEP_REGISTRY",
    "UnknownCategoryError",
    "all_names",
    "build_cleaners",
]
