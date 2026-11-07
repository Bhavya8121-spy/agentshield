import unittest
from unittest import mock

from helpers import FakeHomeTestCase
from macclean.health import DENIED, MISSING, NOT_APPLICABLE, OK, run_health_checks


def check_named(checks, name):
    return next(check for check in checks if check.name == name)


class HealthTests(FakeHomeTestCase):
    def test_reports_every_tool_and_trash_access(self):
        names = [check.name for check in run_health_checks(self.home)]
        self.assertEqual(names, ["macOS", "brew", "docker", "xcrun", "npm", "Trash access"])

    def test_missing_tool_is_reported_missing(self):
        with mock.patch("macclean.health.which", return_value=None):
            checks = run_health_checks(self.home)
        self.assertEqual(check_named(checks, "brew").status, MISSING)

    def test_trash_access_when_folder_exists(self):
        (self.home / ".Trash").mkdir()
        self.assertEqual(check_named(run_health_checks(self.home), "Trash access").status, OK)

    def test_trash_access_when_no_folder(self):
        status = check_named(run_health_checks(self.home), "Trash access").status
        self.assertEqual(status, NOT_APPLICABLE)

    def test_trash_access_denied_points_to_full_disk_access(self):
        with mock.patch("macclean.health.os.listdir", side_effect=PermissionError):
            check = check_named(run_health_checks(self.home), "Trash access")
        self.assertEqual(check.status, DENIED)
        self.assertIn("Full Disk Access", check.note)


if __name__ == "__main__":
    unittest.main()
