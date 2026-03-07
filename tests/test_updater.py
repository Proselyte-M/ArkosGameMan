import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from updater import download_file, is_newer_version


class _DummyResponse:
    def __init__(self) -> None:
        self.headers = {"Content-Length": "4"}
        self._chunks = [b"data", b""]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, _size: int) -> bytes:
        return self._chunks.pop(0)


class UpdaterTests(unittest.TestCase):
    def test_is_newer_version(self) -> None:
        self.assertTrue(is_newer_version("v1.3.0", "1.2.9"))
        self.assertTrue(is_newer_version("2.0", "1.9.99"))
        self.assertTrue(is_newer_version("1.2.0", "1.2"))
        self.assertFalse(is_newer_version("1.2.0", "1.2.0"))

    def test_download_file_can_be_cancelled(self) -> None:
        with tempfile.TemporaryDirectory(prefix="arkos_update_test_") as tmp:
            cancel_event = threading.Event()
            cancel_event.set()
            target = Path(tmp) / "update.exe"
            progress_calls: list[tuple[int, int]] = []
            with patch("updater.urlopen", return_value=_DummyResponse()):
                with self.assertRaises(RuntimeError):
                    download_file(
                        "https://example.com/update.exe",
                        target,
                        lambda received, total: progress_calls.append((received, total)),
                        cancel_event,
                    )
            self.assertEqual(progress_calls, [])


if __name__ == "__main__":
    unittest.main()
