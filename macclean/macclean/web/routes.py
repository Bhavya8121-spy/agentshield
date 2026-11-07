"""Map each API path to a function that turns a request into a JSON payload."""
from __future__ import annotations

from typing import Any, Callable, Dict

from ..cleaners import all_names
from .body import RequestBody
from .payloads import (
    clean_payload,
    health_payload,
    largest_payload,
    scan_payload,
    status_payload,
)
from .service import DashboardService

Route = Callable[[DashboardService, RequestBody], Dict[str, Any]]

MEGABYTE = 1_000_000
MAX_LARGEST_FILES = 200


def status(service: DashboardService, body: RequestBody) -> Dict[str, Any]:
    return status_payload(service.disk_usage(), all_names())


def doctor(service: DashboardService, body: RequestBody) -> Dict[str, Any]:
    return health_payload(service.health())


def scan(service: DashboardService, body: RequestBody) -> Dict[str, Any]:
    report = service.scan(
        deep=body.boolean("deep", default=False),
        categories=body.text_list("categories"),
    )
    return scan_payload(report, service.home)


def clean(service: DashboardService, body: RequestBody) -> Dict[str, Any]:
    result = service.clean(
        body.text_list("ids"),
        dry_run=body.boolean("dry_run", default=True),
        confirmed=body.boolean("confirm", default=False),
    )
    return clean_payload(result)


def largest(service: DashboardService, body: RequestBody) -> Dict[str, Any]:
    min_megabytes = body.number("min_mb", default=100, minimum=0, maximum=10**7)
    root, rows = service.largest(
        path=body.text("path", default="~").strip() or "~",
        limit=int(body.number("number", default=20, minimum=1, maximum=MAX_LARGEST_FILES)),
        min_size=int(min_megabytes * MEGABYTE),
    )
    return largest_payload(root, rows)


GET_ROUTES: Dict[str, Route] = {
    "/api/status": status,
    "/api/doctor": doctor,
}

POST_ROUTES: Dict[str, Route] = {
    "/api/scan": scan,
    "/api/clean": clean,
    "/api/largest": largest,
}
