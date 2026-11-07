import tempfile
import unittest
from pathlib import Path


def write_bytes(path: Path, size: int = 8192) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


class FakeHomeTestCase(unittest.TestCase):
    """Each test gets a throwaway home directory plus a sibling 'outside' dir."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name).resolve()
        self.home = base / "home"
        self.outside = base / "outside"
        self.home.mkdir()
        self.outside.mkdir()
