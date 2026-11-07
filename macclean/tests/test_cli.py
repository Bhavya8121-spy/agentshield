import importlib.util
import os
import unittest
from unittest import mock

from helpers import FakeHomeTestCase, write_bytes

HAS_RICH = importlib.util.find_spec("rich") is not None


@unittest.skipUnless(HAS_RICH, "rich is not installed")
class CliTests(FakeHomeTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.derived = self.home / "Library/Developer/Xcode/DerivedData"
        self.file = write_bytes(self.derived / "App/a.o")

    def run_cli(self, *argv):
        from macclean.cli import main
        return main(list(argv))

    def test_scan_succeeds(self):
        self.assertEqual(self.run_cli("scan", "-c", "xcode"), 0)

    def test_unknown_category_is_an_error(self):
        self.assertEqual(self.run_cli("scan", "-c", "bogus"), 2)

    def test_clean_is_dry_run_by_default(self):
        self.assertEqual(self.run_cli("clean", "-c", "xcode"), 0)
        self.assertTrue(self.file.exists())

    def test_clean_execute_yes_deletes(self):
        self.assertEqual(self.run_cli("clean", "-c", "xcode", "--execute", "--yes"), 0)
        self.assertFalse(self.file.exists())
        self.assertTrue(self.derived.is_dir())

    def test_declining_confirmation_keeps_files(self):
        with mock.patch("macclean.cli.Confirm.ask", return_value=False):
            self.assertEqual(self.run_cli("clean", "-c", "xcode", "--execute"), 1)
        self.assertTrue(self.file.exists())

    def test_review_items_need_opt_in(self):
        trash = write_bytes(self.home / ".Trash/x")
        self.run_cli("clean", "-c", "trash", "--execute", "--yes")
        self.assertTrue(trash.exists())
        self.run_cli("clean", "-c", "trash", "--include-review", "--execute", "--yes")
        self.assertFalse(trash.exists())

    def test_doctor_succeeds(self):
        self.assertEqual(self.run_cli("doctor"), 0)

    def test_web_stops_cleanly_on_ctrl_c_and_opens_the_browser(self):
        with mock.patch("macclean.cli.DashboardServer") as server_class, \
                mock.patch("macclean.cli.webbrowser.open") as open_browser:
            server = server_class.return_value
            server.serve_forever.side_effect = KeyboardInterrupt
            self.assertEqual(self.run_cli("web"), 130)
        open_browser.assert_called_once_with(server.url)
        server.server_close.assert_called_once()

    def test_web_no_browser_flag(self):
        with mock.patch("macclean.cli.DashboardServer") as server_class, \
                mock.patch("macclean.cli.webbrowser.open") as open_browser:
            server_class.return_value.serve_forever.side_effect = KeyboardInterrupt
            self.run_cli("web", "--no-browser")
        open_browser.assert_not_called()

    def test_web_reports_a_busy_port(self):
        with mock.patch("macclean.cli.DashboardServer", side_effect=OSError(48, "Address already in use")):
            self.assertEqual(self.run_cli("web"), 2)

    def test_largest(self):
        write_bytes(self.home / "movie.mov", 50_000)
        self.assertEqual(self.run_cli("largest", str(self.home), "--min-size", "0"), 0)


if __name__ == "__main__":
    unittest.main()
