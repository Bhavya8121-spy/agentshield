import http.client
import json
import threading
import unittest

from helpers import FakeHomeTestCase, write_bytes
from macclean.web.server import DashboardServer
from macclean.web.service import DashboardService


class ServerTestCase(FakeHomeTestCase):
    def setUp(self):
        super().setUp()
        self.server = DashboardServer(0, DashboardService(self.home))
        threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        ).start()
        self.addCleanup(self._stop_server)
        self.derived = self.home / "Library/Developer/Xcode/DerivedData"
        self.file = write_bytes(self.derived / "App/a.o")

    def _stop_server(self):
        self.server.shutdown()
        self.server.server_close()

    def request(self, method, path, body=None, token=True, headers=None):
        sent = dict(headers or {})
        sent.setdefault("Host", f"127.0.0.1:{self.server.port}")
        if token:
            sent["X-Macclean-Token"] = self.server.token
        data = json.dumps(body) if body is not None else None
        connection = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=10)
        connection.request(method, path, body=data, headers=sent)
        response = connection.getresponse()
        raw = response.read()
        connection.close()
        return response, raw

    def call(self, method, path, body=None, **kwargs):
        response, raw = self.request(method, path, body, **kwargs)
        return response.status, json.loads(raw)

    def scan_xcode(self):
        status, data = self.call("POST", "/api/scan", {"categories": ["xcode"]})
        self.assertEqual(status, 200)
        return data


class PageTests(ServerTestCase):
    def test_index_has_the_token_filled_in(self):
        response, raw = self.request("GET", "/", token=False)
        self.assertEqual(response.status, 200)
        self.assertIn(self.server.token, raw.decode())
        self.assertNotIn("{{TOKEN}}", raw.decode())

    def test_pages_carry_a_strict_content_security_policy(self):
        response, _ = self.request("GET", "/", token=False)
        policy = response.getheader("Content-Security-Policy")
        self.assertIn("default-src 'self'", policy)
        self.assertIn("frame-ancestors 'none'", policy)

    def test_static_files_are_served_with_the_right_type(self):
        css, _ = self.request("GET", "/static/style.css", token=False)
        js, _ = self.request("GET", "/static/app.js", token=False)
        self.assertTrue(css.getheader("Content-Type").startswith("text/css"))
        self.assertTrue(js.getheader("Content-Type").startswith("text/javascript"))

    def test_only_listed_static_files_are_served(self):
        for path in ("/static/../server.py", "/static/index.html", "/static/"):
            response, _ = self.request("GET", path)
            self.assertEqual(response.status, 404, path)

    def test_unknown_path_is_404(self):
        self.assertEqual(self.call("GET", "/api/nope")[0], 404)


class GuardTests(ServerTestCase):
    def test_api_needs_the_token(self):
        self.assertEqual(self.call("GET", "/api/status", token=False)[0], 403)

    def test_wrong_token_is_refused(self):
        status, _ = self.call("GET", "/api/status", token=False, headers={"X-Macclean-Token": "nope"})
        self.assertEqual(status, 403)

    def test_foreign_host_header_is_refused(self):
        status, _ = self.call("GET", "/api/status", headers={"Host": "evil.example"})
        self.assertEqual(status, 403)

    def test_foreign_origin_is_refused(self):
        status, _ = self.call("POST", "/api/scan", {}, headers={"Origin": "http://evil.example"})
        self.assertEqual(status, 403)

    def test_invalid_json_is_a_400(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=10)
        connection.request(
            "POST", "/api/scan", body="{nope",
            headers={"Host": f"127.0.0.1:{self.server.port}", "X-Macclean-Token": self.server.token},
        )
        self.assertEqual(connection.getresponse().status, 400)

    def test_oversized_body_is_refused_before_it_is_read(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=10)
        connection.putrequest("POST", "/api/scan", skip_host=True)
        connection.putheader("Host", f"127.0.0.1:{self.server.port}")
        connection.putheader("X-Macclean-Token", self.server.token)
        connection.putheader("Content-Length", "5000000")
        connection.endheaders()
        self.assertEqual(connection.getresponse().status, 413)


class ApiTests(ServerTestCase):
    def test_status_describes_the_machine(self):
        status, data = self.call("GET", "/api/status")
        self.assertEqual(status, 200)
        self.assertIn("xcode", data["categories"])
        self.assertEqual(data["disk"].keys(), {"free_human", "used_human", "total_human", "percent"})

    def test_doctor_lists_checks(self):
        status, data = self.call("GET", "/api/doctor")
        self.assertEqual(status, 200)
        self.assertIn("Trash access", [check["name"] for check in data["checks"]])

    def test_scan_returns_what_the_dashboard_renders(self):
        data = self.scan_xcode()
        item = data["items"][0]
        for key in ("id", "label", "size", "size_human", "safety", "cleanable", "report_only", "note", "target"):
            self.assertIn(key, item)
        self.assertEqual(item["target"], "~/Library/Developer/Xcode/DerivedData/* (contents)")
        self.assertEqual(data["totals_human"].keys(), {"safe", "review", "report_only"})

    def test_clean_defaults_to_a_dry_run(self):
        item_id = self.scan_xcode()["items"][0]["id"]
        status, data = self.call("POST", "/api/clean", {"ids": [item_id]})
        self.assertEqual(status, 200)
        self.assertGreater(data["freed"], 0)
        self.assertTrue(self.file.exists())

    def test_delete_needs_confirm_true(self):
        item_id = self.scan_xcode()["items"][0]["id"]
        status, _ = self.call("POST", "/api/clean", {"ids": [item_id], "dry_run": False})
        self.assertEqual(status, 400)
        self.assertTrue(self.file.exists())

    def test_confirmed_delete_removes_files(self):
        item_id = self.scan_xcode()["items"][0]["id"]
        status, data = self.call(
            "POST", "/api/clean", {"ids": [item_id], "dry_run": False, "confirm": True}
        )
        self.assertEqual(status, 200)
        self.assertEqual(data["errors"], [])
        self.assertFalse(self.file.exists())

    def test_a_path_is_not_an_id(self):
        self.scan_xcode()
        status, _ = self.call(
            "POST", "/api/clean", {"ids": [str(self.derived)], "dry_run": False, "confirm": True}
        )
        self.assertEqual(status, 409)
        self.assertTrue(self.file.exists())

    def test_bad_field_types_are_a_400(self):
        status, data = self.call("POST", "/api/scan", {"deep": "yes"})
        self.assertEqual(status, 400)
        self.assertIn("deep", data["error"])

    def test_largest_reports_files_in_home(self):
        write_bytes(self.home / "movie.mov", 50_000)
        status, data = self.call("POST", "/api/largest", {"path": "~", "number": 5, "min_mb": 0})
        self.assertEqual(status, 200)
        self.assertEqual([f["path"] for f in data["files"]], [str(self.home / "movie.mov")])

    def test_largest_outside_home_is_403(self):
        status, _ = self.call("POST", "/api/largest", {"path": str(self.outside)})
        self.assertEqual(status, 403)


if __name__ == "__main__":
    unittest.main()
