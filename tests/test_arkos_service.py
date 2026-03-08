import tempfile
import threading
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from arkos_core import ArkosService, GameEntry
from game_actions import ControllerGameActionsMixin, build_standardized_name, is_standardized_name, sanitize_core_name
from qt_controller import ArkosController


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
        self.assertEqual(selected.get("name"), "zelda")
        self.assertEqual(selected.path, "./zelda.nes")

    def test_rel_to_abs_rejects_path_traversal(self) -> None:
        service, _root = self._build_service()
        with self.assertRaises(ValueError):
            service.repo.rel_to_abs("nes", "../../windows/system32/notepad.exe")

    def test_rename_game_only_updates_metadata_name(self) -> None:
        service, root = self._build_service()
        rom_a = root / "nes" / "contra.nes"
        rom_a.write_bytes(b"a")
        game = GameEntry(path="./contra.nes", fields={"name": "Contra"})
        service.repo.save_games("nes", [game])
        loaded = service.repo.load_games("nes")[0]
        service.rename_game(loaded, "C Contra [CONTRA]")
        reloaded = service.repo.load_games("nes")[0]
        self.assertTrue((root / "nes" / "contra.nes").exists())
        self.assertFalse((root / "nes" / "C Contra [CONTRA].nes").exists())
        self.assertEqual(reloaded.path, "./contra.nes")
        self.assertEqual(reloaded.get("name"), "C Contra [CONTRA]")


class NameNormalizationTests(unittest.TestCase):
    def test_is_standardized_name(self) -> None:
        self.assertTrue(is_standardized_name("S 超级马里奥 [CJMLA]"))
        self.assertFalse(is_standardized_name("超级马里奥"))

    def test_sanitize_core_name(self) -> None:
        self.assertEqual(sanitize_core_name("A- [Hack] 超级马里奥（中文）"), "超级马里奥")
        self.assertEqual(sanitize_core_name("B__ Contra (USA) !!!"), "Contra")
        self.assertEqual(sanitize_core_name("007"), "007")

    def test_build_standardized_name(self) -> None:
        self.assertEqual(build_standardized_name("A- [Hack] 超级马里奥（中文）"), "C 超级马里奥 [CJMLA]")
        self.assertEqual(build_standardized_name("B__ Contra (USA) !!!"), "C Contra [CONTRA]")
        self.assertEqual(build_standardized_name("007"), "A 007 [007]")


class RepositoryAtomicityTests(unittest.TestCase):
    def test_save_games_keeps_xml_parseable_under_parallel_writes(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="arkos_repo_atomic_"))
        service = ArkosService(root)
        service.current_system = "nes"
        (root / "nes").mkdir(parents=True, exist_ok=True)
        repo = service.repo
        errors: list[Exception] = []

        def worker(seed: int) -> None:
            games = [
                GameEntry(path=f"./game_{seed}_{idx}.nes", fields={"name": f"Game {seed}-{idx}", "favorite": "false"})
                for idx in range(100)
            ]
            try:
                repo.save_games("nes", games)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(idx,)) for idx in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        gpath = root / "nes" / "gamelist.xml"
        self.assertTrue(gpath.exists())
        tree = ET.parse(gpath)
        root_node = tree.getroot()
        self.assertEqual(root_node.tag, "gameList")
        games = root_node.findall("game")
        self.assertGreater(len(games), 0)


class _DummyProgress:
    def __init__(self) -> None:
        self.closed = False
        self.steps: list[int] = []

    def update(self, _text: str, value: int) -> None:
        self.steps.append(value)

    def close(self) -> None:
        self.closed = True


class _DummyView:
    def __init__(self, answers: list[bool]) -> None:
        self._answers = answers[:]
        self.field_widgets = {"name": object(), "desc": object()}
        self.ask_messages: list[tuple[str, str]] = []
        self.notifications: list[tuple[str, str, bool]] = []
        self.highlight_notifications: list[tuple[str, str, list[str]]] = []
        self.progresses: list[_DummyProgress] = []
        self.next_text = ""

    def ask_yes_no(self, title: str, message: str) -> bool:
        self.ask_messages.append((title, message))
        return self._answers.pop(0) if self._answers else False

    def open_batch_progress(self, _title: str, _total: int) -> _DummyProgress:
        progress = _DummyProgress()
        self.progresses.append(progress)
        return progress

    def notify(self, title: str, message: str, error: bool = False) -> None:
        self.notifications.append((title, message, error))

    def notify_highlight_list(self, title: str, summary: str, items: list[str]) -> None:
        self.highlight_notifications.append((title, summary, items))

    def ask_text(self, _title: str, _label: str, _default: str = "") -> str:
        return self.next_text

    def set_busy(self, _busy: bool, _message: str) -> None:
        return


class _DummyService:
    def __init__(self, games: list[GameEntry]) -> None:
        self.games = games
        self.current_system = "nes"
        self.events: list[str] = []

    def save_metadata(self, game: GameEntry, data: dict[str, str]) -> None:
        self.events.append(f"metadata:{data.get('name', '')}")
        game.fields.update(data)


class _DummyController(ControllerGameActionsMixin):
    def __init__(self, games: list[GameEntry], answers: list[bool]) -> None:
        self.service = _DummyService(games)
        self.view = _DummyView(answers)
        self.selected_game: GameEntry | None = games[0] if games else None
        self._is_normalizing_names = False
        self.refreshed = 0
        self.pending_updates: list[str] = []
        self.pending_enabled_history: list[bool] = []

    def _t(self, key: str, **kwargs) -> str:
        if kwargs:
            args = ", ".join(f"{k}={v}" for k, v in kwargs.items())
            return f"{key}({args})"
        return key

    def _game_system(self, _game: GameEntry) -> str:
        return "nes"

    def _refresh_game_table(self, *_args) -> None:
        self.refreshed += 1

    def _select_game_by_path(self, _rel_path: str) -> None:
        return

    def _refresh_preview(self, _game: GameEntry) -> None:
        return

    def _stage_metadata_update(self, game: GameEntry, _game_system: str, data: dict[str, str]) -> bool:
        self.pending_updates.append(f"metadata:{data.get('name', '')}")
        game.fields.update(data)
        self._refresh_pending_action_state()
        return True

    def _refresh_pending_action_state(self) -> None:
        enabled = bool(self.pending_updates) and not self._is_normalizing_names
        self.pending_enabled_history.append(enabled)


class NormalizeFlowTests(unittest.TestCase):
    def test_apply_metadata_with_single_confirm(self) -> None:
        games = [
            GameEntry(path="./contra.nes", fields={"name": "Contra"}),
            GameEntry(path="./mario.nes", fields={"name": "Mario"}),
        ]
        controller = _DummyController(games, [True])
        casted = controller
        casted_any: Any = casted
        casted_any._normalize_game_names()
        self.assertEqual(controller.refreshed, 1)
        self.assertEqual(len(controller.view.ask_messages), 1)
        self.assertEqual(
            controller.pending_updates,
            ["metadata:C Contra [CONTRA]", "metadata:M Mario [MARIO]"],
        )

    def test_cancel_when_user_declines_confirm(self) -> None:
        games = [
            GameEntry(path="./contra.nes", fields={"name": "Contra"}),
            GameEntry(path="./mario.nes", fields={"name": "Mario"}),
        ]
        controller = _DummyController(games, [False])
        casted = controller
        casted_any: Any = casted
        casted_any._normalize_game_names()
        self.assertEqual(controller.refreshed, 0)
        self.assertEqual(len(controller.view.ask_messages), 1)
        self.assertEqual(controller.pending_updates, [])

    def test_failed_item_still_advances_progress(self) -> None:
        games = [
            GameEntry(path="./ok.nes", fields={"name": "Mario"}),
            GameEntry(path="./bad.nes", fields={"name": "Contra"}),
        ]
        controller = _DummyController(games, [True])

        def stage(game: GameEntry, _system: str, data: dict[str, str]) -> bool:
            if game.path == "./bad.nes":
                raise ValueError("boom")
            game.fields.update(data)
            controller.pending_updates.append(f"metadata:{data.get('name', '')}")
            return True

        casted_any: Any = controller
        casted_any._stage_metadata_update = stage
        casted_any._normalize_game_names()
        self.assertEqual(len(controller.view.progresses), 1)
        progress = controller.view.progresses[0]
        self.assertEqual(progress.steps, [1, 2])
        self.assertTrue(progress.closed)
        self.assertFalse(controller.pending_enabled_history[0])
        self.assertTrue(controller.pending_enabled_history[-1])

    def test_metadata_edit_refreshes_pending_state(self) -> None:
        games = [GameEntry(path="./contra.nes", fields={"name": "Contra"})]
        controller = _DummyController(games, [])
        game = games[0]
        controller._stage_metadata_update(game, "nes", {"name": "Contra Plus", "desc": ""})
        self.assertTrue(controller.pending_enabled_history[-1])

    def test_rename_game_keeps_pending_state_enabled(self) -> None:
        games = [GameEntry(path="./contra.nes", fields={"name": "Contra"})]
        controller = _DummyController(games, [])
        controller.view.next_text = "Contra Remake"
        casted_any: Any = controller
        casted_any._rename_game()
        self.assertEqual(games[0].get("name"), "Contra Remake")
        self.assertTrue(controller.pending_enabled_history[-1])


class _DummyEmitter:
    def __init__(self) -> None:
        self.payloads: list[tuple[Any, ...]] = []

    def emit(self, *payload: Any) -> None:
        self.payloads.append(payload)


class _DummyBridge:
    def __init__(self) -> None:
        self.save_succeeded = _DummyEmitter()
        self.save_failed = _DummyEmitter()


class _DummyPendingView:
    def __init__(self) -> None:
        self.save_state: list[bool] = []
        self.notifies: list[tuple[str, str, bool]] = []

    def set_save_pending_state(self, saving: bool) -> None:
        self.save_state.append(saving)

    def notify(self, title: str, message: str, error: bool = False) -> None:
        self.notifies.append((title, message, error))

    def set_pending_actions_enabled(self, _enabled: bool) -> None:
        return


class SavePendingFlowTests(unittest.TestCase):
    def test_save_worker_success_emits_result_and_releases_lock(self) -> None:
        class Ctx:
            def __init__(self) -> None:
                self._save_pending_bridge = _DummyBridge()
                self._save_lock = threading.Lock()

            def _write_snapshot_with_rollback(self, _snapshot: dict[str, list[GameEntry]]) -> list[str]:
                return ["nes"]

        ctx = Ctx()
        ctx._save_lock.acquire()
        ArkosController._save_pending_worker(cast(Any, ctx), 1, {"nes": []})
        self.assertFalse(ctx._save_lock.locked())
        self.assertEqual(ctx._save_pending_bridge.save_succeeded.payloads, [(1, ["nes"])])
        self.assertEqual(ctx._save_pending_bridge.save_failed.payloads, [])

    def test_save_worker_failure_emits_error_and_releases_lock(self) -> None:
        class Ctx:
            def __init__(self) -> None:
                self._save_pending_bridge = _DummyBridge()
                self._save_lock = threading.Lock()

            def _write_snapshot_with_rollback(self, _snapshot: dict[str, list[GameEntry]]) -> list[str]:
                raise OSError("disk failed")

        ctx = Ctx()
        ctx._save_lock.acquire()
        ArkosController._save_pending_worker(cast(Any, ctx), 2, {"nes": []})
        self.assertFalse(ctx._save_lock.locked())
        self.assertEqual(ctx._save_pending_bridge.save_succeeded.payloads, [])
        self.assertEqual(ctx._save_pending_bridge.save_failed.payloads, [(2, "disk failed")])

    def test_apply_save_failed_resets_saving_state(self) -> None:
        class Ctx:
            def __init__(self) -> None:
                self._is_saving_pending = True
                self._pending_changes = {"a": {"system": "nes", "path": "./a.nes"}}
                self._dirty_systems = {"nes"}
                self.view = _DummyPendingView()
                self._save_timeout_timer = _Timer()

            def _t(self, key: str, **_kwargs: Any) -> str:
                return key

            def _refresh_pending_action_state(self) -> None:
                return

        ctx = Ctx()
        ArkosController._apply_save_failed(cast(Any, ctx), "boom")
        self.assertFalse(ctx._is_saving_pending)
        self.assertEqual(ctx.view.save_state[-1], False)
        self.assertTrue(ctx._save_timeout_timer.stopped)

    def test_save_to_disk_when_locked_notifies_in_progress(self) -> None:
        class Ctx:
            def __init__(self) -> None:
                self._save_lock = threading.Lock()
                self._save_lock.acquire()
                self._pending_changes = {"a": {"system": "nes", "path": "./a.nes"}}
                self._dirty_systems = {"nes"}
                self._is_saving_pending = True
                self.view = _DummyPendingView()

            def _pending_count(self) -> int:
                return 1

            def _t(self, key: str, **_kwargs: Any) -> str:
                return key

        ctx = Ctx()
        saved = ArkosController._save_pending_to_disk(cast(Any, ctx), async_mode=True)
        self.assertFalse(saved)
        self.assertTrue(ctx.view.notifies)
        self.assertEqual(ctx.view.notifies[-1][1], "notify.pending_save_in_progress")
        ctx._save_lock.release()

    def test_timeout_resets_saving_state_and_notifies(self) -> None:
        class Ctx:
            def __init__(self) -> None:
                self._is_saving_pending = True
                self._active_save_request_seq = 5
                self.view = _DummyPendingView()
                self._save_timeout_timer = _Timer()
                self.failed: list[str] = []

            def _t(self, key: str, **_kwargs: Any) -> str:
                return key

            def _apply_save_failed(self, error: str) -> None:
                self.failed.append(error)
                self._is_saving_pending = False

        ctx = Ctx()
        ArkosController._on_save_pending_timeout(cast(Any, ctx))
        self.assertEqual(ctx.failed, ["notify.pending_save_timeout"])
        self.assertEqual(ctx._active_save_request_seq, 6)


class _Timer:
    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


if __name__ == "__main__":
    unittest.main()
