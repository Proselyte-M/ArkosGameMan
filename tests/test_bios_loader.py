import tempfile
import unittest
from pathlib import Path

from bios_loader import detect_bios_dir_from_rom, match_bios_files, should_enable_auto_bios


class BiosLoaderTests(unittest.TestCase):
    def test_detect_bios_dir_from_rom(self) -> None:
        with tempfile.TemporaryDirectory(prefix="arkos_bios_test_") as tmp:
            root = Path(tmp)
            bios = root / "bios"
            bios.mkdir(parents=True, exist_ok=True)
            rom = root / "cps2" / "ssf2.zip"
            rom.parent.mkdir(parents=True, exist_ok=True)
            rom.write_bytes(b"rom")
            self.assertEqual(detect_bios_dir_from_rom(rom), bios)

    def test_match_bios_files_for_cps2(self) -> None:
        with tempfile.TemporaryDirectory(prefix="arkos_bios_test_") as tmp:
            bios = Path(tmp) / "bios"
            bios.mkdir(parents=True, exist_ok=True)
            (bios / "qsound.zip").write_bytes(b"bios")
            matched, missing = match_bios_files("cps", "cps2", bios)
            self.assertEqual([path.name for path in matched], ["qsound.zip"])
            self.assertIn("cps3.zip", missing)

    def test_should_enable_auto_bios(self) -> None:
        self.assertTrue(should_enable_auto_bios("cps"))
        self.assertTrue(should_enable_auto_bios("neogeo"))
        self.assertFalse(should_enable_auto_bios("fc"))


if __name__ == "__main__":
    unittest.main()
