import os
import time
import unittest

from macclean.cleaners import build_cleaners
from macclean.cleaners.docker import parse_size
from macclean.cleaners.node_modules import NodeModulesCleaner
from macclean.cleaners.user_caches import UserCachesCleaner
from macclean.cleaners.xcode import XcodeCleaner
from macclean.models import CleanableItem, Safety
from macclean.scanner import scan, select_items
from macclean.utils import check_deletable, delete_path, UnsafePathError, format_size

from helpers import FakeHomeTestCase, write_bytes


class XcodeTests(FakeHomeTestCase):
    def setUp(self):
        super().setUp()
        self.derived = self.home / "Library/Developer/Xcode/DerivedData"
        write_bytes(self.derived / "App-abc/Build/a.o")
        write_bytes(self.derived / "App-abc/Build/b.o")
        self.cleaner = XcodeCleaner(self.home)

    def test_scan_finds_derived_data_as_safe(self):
        items = self.cleaner.scan()
        self.assertEqual([i.label for i in items], ["Xcode DerivedData"])
        self.assertIs(items[0].safety, Safety.SAFE)
        self.assertGreaterEqual(items[0].size, 16384)

    def test_dry_run_deletes_nothing(self):
        items = self.cleaner.scan()
        result = self.cleaner.clean(items, dry_run=True)
        self.assertGreater(result.freed, 0)
        self.assertTrue((self.derived / "App-abc/Build/a.o").exists())

    def test_execute_removes_contents_but_keeps_folder(self):
        items = self.cleaner.scan()
        result = self.cleaner.clean(items, dry_run=False)
        self.assertEqual(result.errors, [])
        self.assertGreater(result.freed, 0)
        self.assertTrue(self.derived.is_dir())
        self.assertEqual(list(self.derived.iterdir()), [])

    def test_archives_are_report_only_and_never_deleted(self):
        archive = write_bytes(self.home / "Library/Developer/Xcode/Archives/2026/app.xcarchive/Info.plist")
        items = self.cleaner.scan()
        archives = [i for i in items if i.label == "Xcode Archives"][0]
        self.assertTrue(archives.report_only)
        self.assertFalse(archives.cleanable)
        result = self.cleaner.clean([archives], dry_run=False)
        self.assertEqual(result.freed, 0)
        self.assertTrue(archive.exists())
        self.assertEqual(select_items(items), [i for i in items if i.label == "Xcode DerivedData"])


class SafetyGuardTests(FakeHomeTestCase):
    def test_protected_locations_are_refused(self):
        for rel in ("Documents/thesis.docx", "Desktop/x", "Downloads/y", "Library/Application Support/App/db"):
            target = write_bytes(self.home / rel)
            freed, errors = delete_path(target, self.home)
            self.assertEqual(freed, 0, rel)
            self.assertTrue(errors, rel)
            self.assertTrue(target.exists(), rel)

    def test_home_and_container_dirs_are_refused(self):
        for p in (self.home, self.home / "Library", self.home / "Library/Caches"):
            with self.assertRaises(UnsafePathError):
                check_deletable(p, self.home)

    def test_outside_home_is_refused(self):
        victim = write_bytes(self.outside / "precious.txt")
        freed, errors = delete_path(victim, self.home)
        self.assertEqual(freed, 0)
        self.assertTrue(errors)
        self.assertTrue(victim.exists())

    def test_symlinks_are_not_followed(self):
        derived = self.home / "Library/Developer/Xcode/DerivedData"
        write_bytes(derived / "junk")
        precious = write_bytes(self.outside / "precious.txt")
        (derived / "link").symlink_to(self.outside, target_is_directory=True)
        cleaner = XcodeCleaner(self.home)
        cleaner.clean(cleaner.scan(), dry_run=False)
        self.assertTrue(precious.exists())
        self.assertFalse((derived / "link").exists() or (derived / "link").is_symlink())

    def test_dangerous_items_are_never_cleaned(self):
        target = write_bytes(self.home / ".npm/_cacache/x")
        item = CleanableItem(
            category="npm", label="x", size=1, safety=Safety.DANGEROUS, path=target.parent
        )
        result = XcodeCleaner(self.home).clean([item], dry_run=False)
        self.assertTrue(result.errors)
        self.assertTrue(target.exists())


class OtherCleanerTests(FakeHomeTestCase):
    def test_trash_is_review_and_needs_opt_in(self):
        write_bytes(self.home / ".Trash/old.zip")
        report = scan(build_cleaners(self.home, only=["trash"]))
        self.assertEqual(len(report.items), 1)
        self.assertIs(report.items[0].safety, Safety.REVIEW)
        self.assertEqual(select_items(report.items), [])
        self.assertEqual(len(select_items(report.items, include_review=True)), 1)

    def test_npm_and_pip_caches(self):
        write_bytes(self.home / ".npm/_cacache/content/a")
        write_bytes(self.home / "Library/Caches/pip/http/b")
        report = scan(build_cleaners(self.home, only=["npm", "pip"]))
        self.assertEqual(sorted(i.category for i in report.items), ["npm", "pip"])

    def test_user_caches_skip_apple_small_and_handled(self):
        caches = self.home / "Library/Caches"
        write_bytes(caches / "com.spotify.client/big", 20000)
        write_bytes(caches / "com.apple.Safari/big", 20000)
        write_bytes(caches / "Homebrew/big", 20000)
        write_bytes(caches / "tiny.app/small", 10)
        cleaner = UserCachesCleaner(self.home)
        cleaner.min_size = 10000
        labels = [i.label for i in cleaner.scan()]
        self.assertEqual(labels, ["App cache: com.spotify.client"])

    def test_node_modules_only_stale_and_report_only(self):
        old, fresh = self.home / "code/old", self.home / "code/fresh"
        for proj in (old, fresh):
            write_bytes(proj / "package.json", 10)
            write_bytes(proj / "node_modules/dep/index.js")
        stale = time.time() - 200 * 86400
        for p in (old / "package.json", old / "node_modules/dep/index.js",
                  old / "node_modules/dep", old / "node_modules"):
            os.utime(p, (stale, stale))
        items = NodeModulesCleaner(self.home).scan()
        self.assertEqual([i.label for i in items], ["~/code/old/node_modules"])
        self.assertTrue(items[0].report_only)

    def test_unknown_category_raises(self):
        with self.assertRaises(ValueError):
            build_cleaners(self.home, only=["nope"])

    def test_scan_survives_a_broken_cleaner(self):
        class Boom(XcodeCleaner):
            name = "boom"
            def scan(self):
                raise RuntimeError("kaput")
        report = scan([Boom(self.home), XcodeCleaner(self.home)])
        self.assertIn("boom", report.errors)


class ParsingTests(unittest.TestCase):
    def test_docker_sizes(self):
        self.assertEqual(parse_size("6.8GB (100%)"), 6_800_000_000)
        self.assertEqual(parse_size("1.2kB"), 1200)
        self.assertEqual(parse_size("0B"), 0)
        self.assertEqual(parse_size(""), 0)

    def test_format_size(self):
        self.assertEqual(format_size(512), "512 B")
        self.assertEqual(format_size(1_500_000), "1.50 MB")
        self.assertEqual(format_size(8_400_000_000), "8.40 GB")


if __name__ == "__main__":
    unittest.main()
