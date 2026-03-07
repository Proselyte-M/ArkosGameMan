import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from arkos_core import ArkosService, GameEntry


class ArkosServiceRollbackTests(unittest.TestCase):
    def _build_service(self) -> tuple[ArkosService, Path]:
        root = Path(tempfile.mkdtemp(prefix="arkos_service_test_"))
        service = ArkosService(root)
        service.current_system = "nes"
        (root / "nes").mkdir(parents=True, exist_ok=True)
        return service, root

    def test_save_metadata_rollback_on_save_failure(self) -> None:
        service, root = self._build_service()
        rom = root / "nes" / "mario.nes"
        rom.write_bytes(b"rom")
        game = GameEntry(path="./mario.nes", fields={"name": "Mario", "favorite": "false"})
        service.repo.save_games("nes", [game])
        selected = service.repo.load_games("nes")[0]
        with patch.object(service.repo, "save_games", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                service.save_metadata(selected, {"name": "Mario New"})
        self.assertEqual(selected.get("name"), "Mario")
        reloaded = service.repo.load_games("nes")
        self.assertEqual(reloaded[0].get("name"), "Mario")

    def test_delete_game_rollback_on_save_failure(self) -> None:
        service, root = self._build_service()
        rom = root / "nes" / "contra.nes"
        rom.write_bytes(b"rom")
        save_file = root / "saves" / "nes" / "contra.srm"
        save_file.parent.mkdir(parents=True, exist_ok=True)
        save_file.write_bytes(b"save")
        media_file = root / "nes" / "media" / "covers" / "contra.png"
        media_file.parent.mkdir(parents=True, exist_ok=True)
        media_file.write_bytes(b"img")
        game = GameEntry(path="./contra.nes", fields={"name": "Contra", "image": "./media/covers/contra.png"})
        service.repo.save_games("nes", [game])
        selected = service.repo.load_games("nes")[0]
        with patch.object(service.repo, "save_games", side_effect=OSError("save failed")):
            with self.assertRaises(OSError):
                service.delete_game(selected, full_delete=True)
        self.assertTrue(rom.exists())
        self.assertTrue(save_file.exists())
        self.assertTrue(media_file.exists())
        self.assertEqual(service.repo.load_games("nes")[0].path, "./contra.nes")

    def test_rename_game_rollback_on_save_failure(self) -> None:
        service, root = self._build_service()
        rom = root / "nes" / "zelda.nes"
        rom.write_bytes(b"rom")
        save_file = root / "saves" / "nes" / "zelda.srm"
        save_file.parent.mkdir(parents=True, exist_ok=True)
        save_file.write_bytes(b"save")
        media_file = root / "nes" / "media" / "covers" / "zelda.png"
        media_file.parent.mkdir(parents=True, exist_ok=True)
        media_file.write_bytes(b"img")
        game = GameEntry(path="./zelda.nes", fields={"name": "zelda", "image": "./media/covers/zelda.png"})
        service.repo.save_games("nes", [game])
        selected = service.repo.load_games("nes")[0]
        with patch.object(service.repo, "save_games", side_effect=OSError("save failed")):
            with self.assertRaises(OSError):
                service.rename_game(selected, "zelda_new")
        self.assertTrue((root / "nes" / "zelda.nes").exists())
        self.assertTrue((root / "saves" / "nes" / "zelda.srm").exists())
        self.assertTrue((root / "nes" / "media" / "covers" / "zelda.png").exists())
        self.assertFalse((root / "nes" / "zelda_new.nes").exists())
        self.assertEqual(selected.path, "./zelda.nes")

    def test_rel_to_abs_rejects_path_traversal(self) -> None:
        service, _root = self._build_service()
        with self.assertRaises(ValueError):
            service.repo.rel_to_abs("nes", "../../windows/system32/notepad.exe")


if __name__ == "__main__":
    unittest.main()
