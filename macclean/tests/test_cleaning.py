import unittest

from helpers import FakeHomeTestCase, write_bytes
from macclean.cleaners import build_cleaners
from macclean.cleaning import clean_items
from macclean.scanner import scan


class CleanItemsTests(FakeHomeTestCase):
    def setUp(self):
        super().setUp()
        self.derived_file = write_bytes(self.home / "Library/Developer/Xcode/DerivedData/App/a.o")
        self.trash_file = write_bytes(self.home / ".Trash/old.zip")
        self.items = scan(build_cleaners(self.home, only=["xcode", "trash"])).items

    def test_dry_run_reports_total_but_deletes_nothing(self):
        result = clean_items(self.items, self.home, dry_run=True)
        self.assertEqual(result.freed, sum(item.size for item in self.items))
        self.assertTrue(self.derived_file.exists() and self.trash_file.exists())

    def test_combines_results_from_several_categories(self):
        result = clean_items(self.items, self.home, dry_run=False)
        self.assertEqual(result.errors, [])
        self.assertEqual({item.category for item in result.cleaned}, {"xcode", "trash"})
        self.assertFalse(self.derived_file.exists() or self.trash_file.exists())


if __name__ == "__main__":
    unittest.main()
