import unittest
from unittest import mock

from helpers import FakeHomeTestCase, write_bytes
from macclean.web.errors import ApiError
from macclean.web.service import DashboardService


class ServiceTestCase(FakeHomeTestCase):
    def setUp(self):
        super().setUp()
        self.service = DashboardService(self.home)
        self.derived = self.home / "Library/Developer/Xcode/DerivedData"
        self.file = write_bytes(self.derived / "App/a.o")

    def scan_xcode(self):
        return self.service.scan(deep=False, categories=["xcode"])

    def derived_data_id(self):
        return self.scan_xcode().items[0].id


class ScanTests(ServiceTestCase):
    def test_scan_finds_items_with_stable_ids(self):
        first, second = self.scan_xcode().items[0], self.scan_xcode().items[0]
        self.assertEqual(first.id, second.id)

    def test_unknown_category_is_a_400(self):
        with self.assertRaises(ApiError) as caught:
            self.service.scan(deep=False, categories=["bogus"])
        self.assertEqual(caught.exception.status, 400)

    def test_second_operation_while_busy_is_a_409(self):
        def scan_again(_cleaners):
            self.service.scan(deep=False, categories=[])

        with mock.patch("macclean.web.service.run_scan", side_effect=scan_again):
            with self.assertRaises(ApiError) as caught:
                self.scan_xcode()
        self.assertEqual(caught.exception.status, 409)


class CleanTests(ServiceTestCase):
    def test_dry_run_deletes_nothing(self):
        result = self.service.clean([self.derived_data_id()], dry_run=True, confirmed=False)
        self.assertGreater(result.freed, 0)
        self.assertTrue(self.file.exists())

    def test_deleting_without_confirmation_is_refused(self):
        item_id = self.derived_data_id()
        with self.assertRaises(ApiError):
            self.service.clean([item_id], dry_run=False, confirmed=False)
        self.assertTrue(self.file.exists())

    def test_confirmed_delete_empties_folder_but_keeps_it(self):
        result = self.service.clean([self.derived_data_id()], dry_run=False, confirmed=True)
        self.assertEqual(result.errors, [])
        self.assertFalse(self.file.exists())
        self.assertTrue(self.derived.is_dir())

    def test_same_result_cannot_be_cleaned_twice(self):
        item_id = self.derived_data_id()
        self.service.clean([item_id], dry_run=False, confirmed=True)
        with self.assertRaises(ApiError) as caught:
            self.service.clean([item_id], dry_run=False, confirmed=True)
        self.assertEqual(caught.exception.status, 409)

    def test_ids_from_no_scan_are_rejected(self):
        with self.assertRaises(ApiError) as caught:
            self.service.clean(["deadbeef0000"], dry_run=True, confirmed=False)
        self.assertEqual(caught.exception.status, 409)

    def test_empty_selection_is_rejected(self):
        self.scan_xcode()
        with self.assertRaises(ApiError):
            self.service.clean([], dry_run=True, confirmed=False)

    def test_report_only_items_are_refused(self):
        archive = write_bytes(self.home / "Library/Developer/Xcode/Archives/a.xcarchive/Info.plist")
        report = self.scan_xcode()
        archives = next(item for item in report.items if item.label == "Xcode Archives")
        with self.assertRaises(ApiError):
            self.service.clean([archives.id], dry_run=False, confirmed=True)
        self.assertTrue(archive.exists())


class LargestTests(ServiceTestCase):
    def test_finds_big_files_inside_home(self):
        write_bytes(self.home / "movie.mov", 50_000)
        root, rows = self.service.largest("~", limit=5, min_size=10_000)
        self.assertEqual(root, self.home)
        self.assertEqual([path.name for _, path in rows], ["movie.mov"])

    def test_folders_outside_home_are_forbidden(self):
        with self.assertRaises(ApiError) as caught:
            self.service.largest(str(self.outside), limit=5, min_size=0)
        self.assertEqual(caught.exception.status, 403)

    def test_dot_dot_cannot_escape_home(self):
        with self.assertRaises(ApiError) as caught:
            self.service.largest("~/../outside", limit=5, min_size=0)
        self.assertEqual(caught.exception.status, 403)

    def test_not_a_folder_is_a_400(self):
        with self.assertRaises(ApiError) as caught:
            self.service.largest("~/nope", limit=5, min_size=0)
        self.assertEqual(caught.exception.status, 400)


class DiskTests(ServiceTestCase):
    def test_disk_usage_of_real_folder_is_known(self):
        self.assertTrue(self.service.disk_usage().is_known)


if __name__ == "__main__":
    unittest.main()
