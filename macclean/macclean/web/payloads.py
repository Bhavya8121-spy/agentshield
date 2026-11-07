"""Turn domain objects into the JSON the dashboard's JavaScript expects."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from .. import __version__
from ..health import HealthCheck, is_macos
from ..models import CleanableItem, CleanResult
from ..presentation import describe_target
from ..scanner import ScanReport
from ..utils import format_size
from .service import DiskUsage

Payload = Dict[str, Any]


def item_payload(item: CleanableItem, home: Path) -> Payload:
    return {
        "id": item.id,
        "category": item.category,
        "label": item.label,
        "size": item.size,
        "size_human": format_size(item.size),
        "safety": item.safety.value,
        "cleanable": item.cleanable,
        "report_only": item.report_only,
        "note": item.note,
        "target": describe_target(item, home),
    }


def scan_payload(report: ScanReport, home: Path) -> Payload:
    return {
        "items": [item_payload(item, home) for item in report.items],
        "totals_human": {
            "safe": format_size(report.safe_total),
            "review": format_size(report.review_total),
            "report_only": format_size(report.report_only_total),
        },
        "errors": report.errors,
    }


def clean_payload(result: CleanResult) -> Payload:
    return {
        "freed": result.freed,
        "freed_human": format_size(result.freed),
        "cleaned": [{"id": item.id, "label": item.label} for item in result.cleaned],
        "errors": result.errors,
    }


def largest_payload(root: Path, rows: Sequence[Tuple[int, Path]]) -> Payload:
    return {
        "root": str(root),
        "files": [
            {"size": size, "size_human": format_size(size), "path": str(path)}
            for size, path in rows
        ],
    }


def health_payload(checks: Sequence[HealthCheck]) -> Payload:
    return {
        "checks": [
            {"name": check.name, "status": check.status, "note": check.note}
            for check in checks
        ]
    }


def status_payload(disk: DiskUsage, categories: List[str]) -> Payload:
    return {
        "version": __version__,
        "is_mac": is_macos(),
        "categories": categories,
        "disk": _disk_payload(disk) if disk.is_known else None,
    }


def _disk_payload(disk: DiskUsage) -> Payload:
    return {
        "free_human": format_size(disk.free),
        "used_human": format_size(disk.used),
        "total_human": format_size(disk.total),
        "percent": round(disk.used / disk.total * 100),
    }
