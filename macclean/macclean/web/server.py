from __future__ import annotations

import hmac
import json
import secrets
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple
from urllib.parse import urlsplit

from .body import RequestBody
from .errors import ApiError
from .routes import GET_ROUTES, POST_ROUTES, Route
from .service import DashboardService

LOCAL_HOST = "127.0.0.1"
TOKEN_HEADER = "X-Macclean-Token"
TOKEN_PLACEHOLDER = "{{TOKEN}}"
MAX_BODY_BYTES = 1_000_000

HTTP_FORBIDDEN = 403
HTTP_TOO_LARGE = 413

WEB_DIR = Path(__file__).parent
STATIC_FILES: Dict[str, Tuple[str, str]] = {
    "/static/style.css": ("style.css", "text/css; charset=utf-8"),
    "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
}
SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; base-uri 'none'; "
        "form-action 'none'; frame-ancestors 'none'"
    ),
}


class DashboardServer(ThreadingHTTPServer):
    """Serves the dashboard on localhost only, guarded by a per-run token."""

    daemon_threads = True

    def __init__(self, port: int, service: DashboardService) -> None:
        super().__init__((LOCAL_HOST, port), DashboardHandler)
        self.service = service
        self.token = secrets.token_urlsafe(32)

    @property
    def port(self) -> int:
        return self.server_address[1]

    @property
    def url(self) -> str:
        return f"http://{LOCAL_HOST}:{self.port}/"

    def serves_host(self, host_header: str) -> bool:
        return host_header in (f"{LOCAL_HOST}:{self.port}", f"localhost:{self.port}")


class DashboardHandler(BaseHTTPRequestHandler):
    server: DashboardServer
    server_version = "macclean"
    sys_version = ""

    def do_GET(self) -> None:
        self._respond_safely(self._get)

    def do_POST(self) -> None:
        self._respond_safely(self._post)

    def log_message(self, format: str, *args: object) -> None:
        """Stay quiet: the dashboard is not a place for access logs."""

    # -- request handling ------------------------------------------------------

    def _respond_safely(self, handle: Callable[[], None]) -> None:
        try:
            self._refuse_foreign_requests()
            handle()
        except ApiError as exc:
            self._send_json({"error": exc.message}, exc.status)
        except Exception:
            traceback.print_exc(file=sys.stderr)
            self._send_json({"error": "Unexpected server error. See the Terminal."}, 500)

    def _get(self) -> None:
        path = urlsplit(self.path).path
        if path == "/":
            self._send_page()
        elif path in STATIC_FILES:
            self._send_static(*STATIC_FILES[path])
        else:
            self._run_route(GET_ROUTES, path, RequestBody({}))

    def _post(self) -> None:
        path = urlsplit(self.path).path
        self._run_route(POST_ROUTES, path, RequestBody.parse(self._read_body()))

    def _run_route(self, routes: Dict[str, Route], path: str, body: RequestBody) -> None:
        route: Optional[Route] = routes.get(path)
        if route is None:
            raise ApiError("Not found.", 404)
        self._require_token()
        self._send_json(route(self.server.service, body))

    # -- guards ----------------------------------------------------------------

    def _refuse_foreign_requests(self) -> None:
        """Block DNS-rebinding (odd Host) and cross-site posts (odd Origin)."""
        host = self.headers.get("Host", "")
        if not self.server.serves_host(host):
            raise ApiError("Unexpected Host header.", HTTP_FORBIDDEN)
        origin = self.headers.get("Origin")
        if origin is not None and origin != f"http://{host}":
            raise ApiError("Cross-site requests are not allowed.", HTTP_FORBIDDEN)

    def _require_token(self) -> None:
        sent = self.headers.get(TOKEN_HEADER, "").encode()
        if not hmac.compare_digest(sent, self.server.token.encode()):
            raise ApiError("Missing or wrong token. Reload the page.", HTTP_FORBIDDEN)

    def _read_body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ApiError("Bad Content-Length.")
        if length > MAX_BODY_BYTES:
            raise ApiError("Request body too large.", HTTP_TOO_LARGE)
        return self.rfile.read(length)

    # -- responses -------------------------------------------------------------

    def _send_page(self) -> None:
        page = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        page = page.replace(TOKEN_PLACEHOLDER, self.server.token)
        self._send(200, page.encode(), "text/html; charset=utf-8")

    def _send_static(self, filename: str, content_type: str) -> None:
        self._send(200, (WEB_DIR / "static" / filename).read_bytes(), content_type)

    def _send_json(self, payload: object, status: int = 200) -> None:
        self._send(status, json.dumps(payload).encode(), "application/json")

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)
