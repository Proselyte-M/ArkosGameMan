from __future__ import annotations

import configparser
import os
import logging
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QObject, QPropertyAnimation, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QImage, QPixmap
from PySide6.QtWidgets import QApplication

from arkos_core import ArkosService, GameEntry
from emulator_runner import EmulatorRunner
from emulator_config import EmulatorConfigStore
from game_actions import (
    ControllerGameActionsMixin,
    build_table,
    game_to_row,
    should_refresh_after_save,
)
from i18n import tr
from qt_view import MainWindow
from update_service import UpdateService
from version import APP_VERSION

logger = logging.getLogger(__name__)


class _SavePendingBridge(QObject):
    save_succeeded = Signal(int, list)
    save_failed = Signal(int, str)


class ArkosController(ControllerGameActionsMixin):
    def __init__(self) -> None:
        self.view = MainWindow()
        self._settings_file = self._resolve_settings_file()
        initial_root = self._load_last_root()
        self.service = ArkosService(initial_root)
        self.filtered_games: list[GameEntry] = []
        self.display_games: list[GameEntry | None] = []
        self.selected_game: GameEntry | None = None
        self._systems: list[str] = []
        self._mode = "system"
        self._is_normalizing_names = False
        self._header_sort_column: int | None = None
        self._header_sort_asc = True
        self._memory_games_by_system: dict[str, list[GameEntry]] = {}
        self._dirty_systems: set[str] = set()
        self._pending_changes: dict[str, dict[str, str]] = {}
        self._save_lock = threading.Lock()
        self._is_saving_pending = False
        self._save_timeout_ms = 15000
        self._save_request_seq = 0
        self._active_save_request_seq = 0
        self._save_timeout_timer = QTimer(self.view)
        self._save_timeout_timer.setSingleShot(True)
        self._save_timeout_timer.timeout.connect(self._on_save_pending_timeout)
        self._save_pending_bridge = _SavePendingBridge()
        self._save_pending_bridge.save_succeeded.connect(self._on_save_pending_succeeded)
        self._save_pending_bridge.save_failed.connect(self._on_save_pending_failed)
        self._last_system_label = ""
        self.current_theme = "dark"
        self.current_language = "zh"
        self._emulator_store = EmulatorConfigStore(self._settings_file)
        self._update_repo = self._load_update_repo()
        self._update_check_enabled = self._load_update_enabled()
        self._emulator_configs = self._emulator_store.load()
        self._search_debounce = QTimer(self.view)
        self._search_debounce.setSingleShot(True)
        self._search_debounce.setInterval(180)
        self._search_debounce.timeout.connect(self._refresh_game_table)
        self._theme_anim = QPropertyAnimation(self.view, b"windowOpacity", self.view)
        self._theme_anim.setDuration(180)
        self._theme_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._update_service = UpdateService(
            parent_view=self.view,
            app_version=APP_VERSION,
            tr=self._t,
            notify=lambda title, message, error: self.view.notify(title, message, error=error),
            ask_yes_no=self.view.ask_yes_no,
        )
        self._update_service.configure(self._update_repo, self._update_check_enabled)
        self._emulator_runner = EmulatorRunner(
            notify=lambda title, message, error: self.view.notify(title, message, error=error),
            tr=self._t,
            resolve_game_system=self._game_system,
            rel_to_abs=self.service.repo.rel_to_abs,
            current_system_getter=lambda: self.service.current_system,
            store=self._emulator_store,
            get_configs=lambda: self._emulator_configs,
        )
        self.view.set_root_path(str(initial_root))
        self.view.set_language(self.current_language)
        self.view.set_close_guard(self._handle_close_guard)
        self._wire_signals()
        self._apply_theme(self.current_theme, animate=False)
        self._refresh_systems()
        if self._update_service.should_check_on_start():
            QTimer.singleShot(2000, self._start_update_check)

    def _load_last_root(self) -> Path:
        parser = configparser.ConfigParser()
        if self._settings_file.exists():
            parser.read(self._settings_file, encoding="utf-8")
            saved = parser.get("app", "rom_root", fallback="/roms").strip()
            if saved:
                return Path(saved)
        return Path("/roms")

    def _resolve_settings_file(self) -> Path:
        project_settings = Path(__file__).resolve().parent / "arkosgameman.ini"
        if not getattr(sys, "frozen", False):
            return project_settings
        appdata = os.environ.get("APPDATA", "").strip()
        if appdata:
            settings_dir = Path(appdata) / "ArkosGameMan"
        else:
            settings_dir = Path.home() / "AppData" / "Roaming" / "ArkosGameMan"
        settings_file = settings_dir / "arkosgameman.ini"
        if settings_file.exists():
            return settings_file
        legacy_candidates = [
            Path(sys.executable).resolve().parent / "arkosgameman.ini",
            Path.cwd() / "arkosgameman.ini",
        ]
        for legacy in legacy_candidates:
            if not legacy.exists():
                continue
            try:
                settings_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(legacy, settings_file)
                return settings_file
            except OSError:
                return legacy
        return settings_file

    def _save_last_root(self, root_path: Path) -> None:
        parser = configparser.ConfigParser()
        if self._settings_file.exists():
            parser.read(self._settings_file, encoding="utf-8")
        if "app" not in parser:
            parser["app"] = {}
        parser["app"]["rom_root"] = str(root_path)
        self._settings_file.parent.mkdir(parents=True, exist_ok=True)
        with self._settings_file.open("w", encoding="utf-8") as handle:
            parser.write(handle)

    def _load_update_repo(self) -> str:
        parser = configparser.ConfigParser()
        if self._settings_file.exists():
            parser.read(self._settings_file, encoding="utf-8")
        configured = parser.get("update", "repository", fallback="").strip()
        if configured:
            return configured
        return self._detect_repo_from_git()

    def _load_update_enabled(self) -> bool:
        parser = configparser.ConfigParser()
        if self._settings_file.exists():
            parser.read(self._settings_file, encoding="utf-8")
        return parser.getboolean("update", "check_on_start", fallback=True)

    def _detect_repo_from_git(self) -> str:
        git_cfg = Path(__file__).resolve().parent / ".git" / "config"
        if not git_cfg.exists():
            return ""
        parser = configparser.ConfigParser()
        try:
            parser.read(git_cfg, encoding="utf-8")
            origin = parser.get('remote "origin"', "url", fallback="").strip()
        except (configparser.Error, OSError):
            return ""
        if not origin:
            return ""
        if origin.startswith("git@github.com:"):
            repo = origin.removeprefix("git@github.com:")
        elif "github.com/" in origin:
            repo = origin.split("github.com/", 1)[1]
        else:
            return ""
        repo = repo.strip().rstrip("/")
        if repo.lower().endswith(".git"):
            repo = repo[:-4]
        if "/" not in repo:
            return ""
        return repo

    def _start_update_check(self) -> None:
        self._update_service.start_check()

    def _wire_signals(self) -> None:
        self.view.request_choose_root.connect(self._choose_root)
        self.view.request_refresh_systems.connect(self._refresh_systems)
        self.view.request_backup_saves.connect(self._backup_saves)
        self.view.request_normalize_names.connect(self._normalize_game_names)
        self.view.request_add_rom.connect(self._add_rom)
        self.view.request_delete_game.connect(self._delete_game)
        self.view.request_rename_game.connect(self._rename_game)
        self.view.request_save_metadata.connect(self._save_metadata)
        self.view.request_toggle_theme.connect(self._toggle_theme)
        self.view.request_system_changed.connect(self._on_system_changed)
        self.view.request_search_or_sort.connect(self._schedule_refresh)
        self.view.request_game_selected.connect(self._on_game_selected)
        self.view.request_header_sort.connect(self._on_header_sort)
        self.view.request_context_action.connect(self._on_context_action)
        self.view.request_preview_image_double_click.connect(self.view.show_preview_image_dialog)
        self.view.request_toggle_favorite.connect(self._toggle_favorite_by_row)
        self.view.request_import_media.connect(self._import_media)
        self.view.request_language_changed.connect(self._on_language_changed)
        self.view.request_open_emulator_settings.connect(self._open_emulator_settings)
        self.view.request_run_game_by_row.connect(self._run_game_by_row)
        self.view.request_save_pending.connect(self._save_pending_changes_clicked)
        self.view.request_reset_pending.connect(self._reset_pending_changes)

    @staticmethod
    def _clone_game(entry: GameEntry, system: str) -> GameEntry:
        fields = dict(entry.fields)
        fields["__system__"] = system
        return GameEntry(path=entry.path, fields=fields)

    @staticmethod
    def _norm_rel_path(path: str) -> str:
        clean = path.strip().replace("\\", "/")
        if clean.startswith("./"):
            clean = clean[2:]
        return clean

    def _load_system_cache(self, system: str) -> list[GameEntry]:
        cached = self._memory_games_by_system.get(system)
        if cached is not None:
            return cached
        loaded = [self._clone_game(game, system) for game in self.service.repo.load_games(system)]
        self._memory_games_by_system[system] = loaded
        return loaded

    def _reload_all_system_caches(self) -> None:
        self._memory_games_by_system = {
            system: [self._clone_game(game, system) for game in self.service.repo.load_games(system)]
            for system in self._systems
        }

    def _pending_change_key(self, system: str, rel_path: str) -> str:
        return f"{system}|{self._norm_rel_path(rel_path)}"

    def _pending_count(self) -> int:
        return len(self._pending_changes)

    def _refresh_pending_action_state(self) -> None:
        enabled = self._pending_count() > 0 and not self._is_saving_pending and not self._is_normalizing_names
        self.view.set_pending_actions_enabled(enabled)

    def _bind_mode_games_from_cache(self) -> None:
        if self._mode == "all":
            merged: list[GameEntry] = []
            for system in self._systems:
                merged.extend(self._load_system_cache(system))
            self.service.games = merged
            self.service.current_system = ""
            return
        if self._mode == "favorites":
            merged = []
            for system in self._systems:
                for game in self._load_system_cache(system):
                    if game.get("favorite", "false").lower() == "true":
                        merged.append(game)
            self.service.games = merged
            self.service.current_system = ""
            return
        if self.service.current_system:
            self.service.games = self._load_system_cache(self.service.current_system)

    def _find_cache_game(self, game_system: str, rel_path: str) -> GameEntry | None:
        target = self._norm_rel_path(rel_path)
        for game in self._load_system_cache(game_system):
            if self._norm_rel_path(game.path) == target:
                return game
        return None

    def _stage_metadata_update(self, game: GameEntry, game_system: str, data: dict[str, str]) -> bool:
        self.service.validate_metadata(data)
        target = self._find_cache_game(game_system, game.path)
        if target is None:
            raise FileNotFoundError(f"未找到目标游戏: {game.path}")
        changed = False
        updated = dict(data)
        for key, value in updated.items():
            clean = value.strip()
            if key in {"image", "video", "thumbnail"} and clean:
                clean = clean.replace("\\", "/")
            if target.get(key, "") != clean:
                target.set(key, clean)
                changed = True
            updated[key] = clean
        if not changed:
            return False
        game.fields = dict(target.fields)
        key = self._pending_change_key(game_system, target.path)
        self._pending_changes[key] = {"system": game_system, "path": target.path}
        self._dirty_systems.add(game_system)
        self._refresh_pending_action_state()
        return True

    def _save_pending_snapshot(self) -> dict[str, list[GameEntry]]:
        return {system: [self._clone_game(item, system) for item in self._load_system_cache(system)] for system in self._dirty_systems}

    def _apply_save_success(self, saved_systems: list[str]) -> None:
        self._pending_changes.clear()
        self._dirty_systems.clear()
        self._is_saving_pending = False
        self._save_timeout_timer.stop()
        self.view.set_save_pending_state(False)
        self._refresh_pending_action_state()
        self._refresh_game_table()
        self.view.notify(self._t("notify.success"), self._t("notify.pending_saved", systems=len(saved_systems)))

    def _apply_save_failed(self, error: str) -> None:
        self._is_saving_pending = False
        self._save_timeout_timer.stop()
        self.view.set_save_pending_state(False)
        self._refresh_pending_action_state()
        self.view.notify(self._t("notify.failed"), self._t("notify.pending_save_failed", error=error), error=True)

    def _on_save_pending_succeeded(self, request_seq: int, saved_systems: list[str]) -> None:
        if request_seq != self._active_save_request_seq:
            return
        self._apply_save_success(saved_systems)

    def _on_save_pending_failed(self, request_seq: int, error: str) -> None:
        if request_seq != self._active_save_request_seq:
            return
        self._apply_save_failed(error)

    def _on_save_pending_timeout(self) -> None:
        if not self._is_saving_pending:
            return
        self._active_save_request_seq += 1
        self._apply_save_failed(self._t("notify.pending_save_timeout"))

    def _save_pending_worker(self, request_seq: int, snapshot: dict[str, list[GameEntry]]) -> None:
        try:
            saved_systems = self._write_snapshot_with_rollback(snapshot)
            self._save_pending_bridge.save_succeeded.emit(request_seq, saved_systems)
        except (OSError, ValueError, FileNotFoundError) as exc:
            error_text = str(exc)
            self._save_pending_bridge.save_failed.emit(request_seq, error_text)
        except Exception as exc:  # noqa: BLE001
            self._save_pending_bridge.save_failed.emit(request_seq, str(exc))
        finally:
            self._save_lock.release()

    def _write_snapshot_with_rollback(self, snapshot: dict[str, list[GameEntry]]) -> list[str]:
        backups: dict[str, bytes | None] = {}
        saved_systems: list[str] = []
        for system in snapshot:
            gpath = self.service.repo.gamelist_path(system)
            backups[system] = gpath.read_bytes() if gpath.exists() else None
        try:
            for system, games in snapshot.items():
                ordered = sorted(games, key=lambda g: g.get("name", g.rom_name).lower())
                self.service.repo.save_games(system, ordered)
                saved_systems.append(system)
            return saved_systems
        except (OSError, ValueError, FileNotFoundError):
            for system in saved_systems:
                gpath = self.service.repo.gamelist_path(system)
                before = backups.get(system)
                if before is None:
                    gpath.unlink(missing_ok=True)
                    self.service.repo.invalidate_system_cache(system)
                    continue
                rollback_tmp = gpath.with_suffix(".xml.rollback.tmp")
                rollback_tmp.parent.mkdir(parents=True, exist_ok=True)
                rollback_tmp.write_bytes(before)
                rollback_tmp.replace(gpath)
                self.service.repo.invalidate_system_cache(system)
            raise

    def _save_pending_to_disk(self, async_mode: bool) -> bool:
        if self._pending_count() == 0:
            self.view.notify(self._t("notify.tip"), self._t("notify.no_pending_changes"))
            return True
        if not self._save_lock.acquire(blocking=False):
            self.view.notify(self._t("notify.tip"), self._t("notify.pending_save_in_progress"))
            return False
        snapshot = self._save_pending_snapshot()
        self._is_saving_pending = True
        self.view.set_save_pending_state(True)
        self._refresh_pending_action_state()
        if async_mode:
            self._save_request_seq += 1
            request_seq = self._save_request_seq
            self._active_save_request_seq = request_seq
            self._save_timeout_timer.start(self._save_timeout_ms)
            worker = threading.Thread(target=self._save_pending_worker, args=(request_seq, snapshot), daemon=True)
            worker.start()
            return True
        try:
            saved_systems = self._write_snapshot_with_rollback(snapshot)
            self._apply_save_success(saved_systems)
            return True
        except (OSError, ValueError, FileNotFoundError) as exc:
            self._apply_save_failed(str(exc))
            return False
        finally:
            self._save_lock.release()

    def _save_pending_changes_clicked(self) -> None:
        pending = self._pending_count()
        if pending == 0:
            self.view.notify(self._t("notify.tip"), self._t("notify.no_pending_changes"))
            return
        if not self.view.ask_yes_no(
            self._t("dialog.save_pending_confirm_title"),
            self._t("dialog.save_pending_confirm", count=pending),
        ):
            return
        self._save_pending_to_disk(async_mode=True)

    def _discard_pending_changes(self) -> None:
        self._pending_changes.clear()
        self._dirty_systems.clear()
        self._reload_all_system_caches()
        self._bind_mode_games_from_cache()
        self._refresh_game_table()
        self._refresh_pending_action_state()
        self.view.notify(self._t("notify.success"), self._t("notify.pending_reset_done"))

    def _reset_pending_changes(self) -> None:
        pending = self._pending_count()
        if pending == 0:
            self.view.notify(self._t("notify.tip"), self._t("notify.no_pending_changes"))
            return
        if not self.view.ask_yes_no(
            self._t("dialog.reset_pending_confirm_title"),
            self._t("dialog.reset_pending_confirm", count=pending),
        ):
            return
        self._discard_pending_changes()

    def _handle_unsaved_before_navigation(self) -> bool:
        pending = self._pending_count()
        if pending == 0:
            return True
        action = self.view.ask_save_discard_cancel(
            self._t("dialog.unsaved_title"),
            self._t("dialog.unsaved_message", count=pending),
        )
        if action == "cancel":
            return False
        if action == "discard":
            self._discard_pending_changes()
            return True
        return self._save_pending_to_disk(async_mode=False)

    def _handle_close_guard(self) -> bool:
        return self._handle_unsaved_before_navigation()

    def _schedule_refresh(self, *_args) -> None:
        self._search_debounce.start()

    def show(self) -> None:
        self.view.show()

    def _choose_root(self) -> None:
        if not self._handle_unsaved_before_navigation():
            return
        selected = self.view.choose_directory()
        if not selected:
            return
        logger.info("选择ROM根目录: %s", selected)
        self.view.set_root_path(selected)
        self.service.set_root(Path(selected))
        self._save_last_root(Path(selected))
        self._refresh_systems()

    def _refresh_systems(self) -> None:
        start = time.perf_counter()
        self.view.set_busy(True, self._t("status.refreshing_systems"))
        try:
            root_path = Path(self.view.get_root_path().strip())
            self.view.set_task_progress(self._t("status.refreshing_systems"), 1, 3)
            self.service.set_root(root_path)
            self._save_last_root(root_path)
            self.view.set_task_progress(self._t("status.refreshing_systems"), 2, 3)
            systems = self.service.list_systems()
            self._systems = systems[:]
            self._reload_all_system_caches()
            self.view.set_systems([self._t("system.all_games"), self._t("system.favorites"), *systems])
            self.selected_game = None
            self.filtered_games = []
            self.display_games = []
            self._mode = "all"
            self.service.current_system = ""
            self._bind_mode_games_from_cache()
            self._pending_changes.clear()
            self._dirty_systems.clear()
            self._refresh_game_table()
            self._refresh_pending_action_state()
            self._last_system_label = self._t("system.all_games")
            self.view.clear_edit_form()
            self.view.set_task_progress(self._t("status.systems_refreshed"), 3, 3)
            self.view.set_busy(False, self._t("status.systems_refreshed"))
            logger.info("系统刷新完成: root=%s, 系统数=%d, 耗时=%.3fs", root_path, len(systems), time.perf_counter() - start)
        except (OSError, ValueError, configparser.Error) as exc:
            self.view.set_busy(False, self._t("status.refresh_failed"))
            logger.exception("系统刷新失败: root=%s", self.view.get_root_path().strip())
            self.view.notify(self._t("notify.failed"), self._t("notify.refresh_system_failed", error=exc), error=True)

    def _on_system_changed(self, system: str) -> None:
        if not system:
            return
        if system != self._last_system_label and not self._handle_unsaved_before_navigation():
            self.view.system_list.blockSignals(True)
            idx = self.view.system_list.findItems(self._last_system_label, Qt.MatchFlag.MatchExactly)
            if idx:
                self.view.system_list.setCurrentItem(idx[0])
            self.view.system_list.blockSignals(False)
            return
        start = time.perf_counter()
        logger.info("切换系统: %s", system)
        self.view.set_busy(True, self._t("status.loading_games"))
        try:
            self.view.set_task_progress(self._t("status.loading_games"), 1, 3)
            if system == self._t("system.all_games"):
                self._mode = "all"
                self.service.current_system = ""
            elif system == self._t("system.favorites"):
                self._mode = "favorites"
                self.service.current_system = ""
            else:
                self._mode = "system"
                self.service.current_system = system
            self._bind_mode_games_from_cache()
            self.selected_game = None
            self._header_sort_column = None
            self._header_sort_asc = True
            self.view.clear_edit_form()
            self.view.set_task_progress(self._t("status.loading_games"), 2, 3)
            self._refresh_game_table()
            self._last_system_label = system
            self.view.set_task_progress(f"{system} {self._t('status.ready')}", 3, 3)
            self.view.set_busy(False, f"{system} {self._t('status.ready')}")
            logger.info("系统加载完成: %s, 模式=%s, 耗时=%.3fs", system, self._mode, time.perf_counter() - start)
        except (OSError, ValueError, FileNotFoundError) as exc:
            self.view.set_busy(False, self._t("status.load_failed"))
            logger.exception("系统加载失败: %s", system)
            self.view.notify(self._t("notify.failed"), self._t("notify.load_system_failed", error=exc), error=True)

    def _refresh_game_table(self, *_args) -> None:
        start = time.perf_counter()
        self._bind_mode_games_from_cache()
        table = build_table(
            mode=self._mode,
            source_games=self.service.games,
            query_text=self.view.search_edit.text(),
            header_sort_column=self._header_sort_column,
            header_sort_asc=self._header_sort_asc,
            group_system_header=lambda system: self._t("group.system_header", system=system),
        )
        self.filtered_games = table.filtered_games
        self.display_games = table.display_games
        self.view.set_games(table.rows, table.group_rows)
        if self._header_sort_column is not None:
            self.view.set_header_sort_indicator(self._header_sort_column, self._header_sort_asc)
        logger.info(
            "刷新游戏表: 模式=%s, 查询='%s', 数据=%d, 展示=%d, 分组头=%d, 耗时=%.3fs",
            self._mode,
            table.query,
            len(self.service.games),
            len(table.rows),
            len(table.group_rows),
            time.perf_counter() - start,
        )

    def _on_header_sort(self, column: int) -> None:
        if self._header_sort_column == column:
            self._header_sort_asc = not self._header_sort_asc
        else:
            self._header_sort_column = column
            self._header_sort_asc = True
        self._refresh_game_table()

    def _on_context_action(self, action: str, row: int) -> None:
        selected = self._row_game(row)
        if selected is None:
            return
        self.selected_game = selected
        self.view.games_table.selectRow(row)
        if action == "delete":
            self._delete_game()
            return
        if action == "favorite":
            self._add_favorite()
            return
        if action == "open_rom_dir":
            game_system = self._game_system(self.selected_game) or self.service.current_system
            rom_abs = self.service.repo.rel_to_abs(game_system, self.selected_game.path)
            self._reveal_file(rom_abs)
            return
        if action == "open_image_dir":
            image_rel = self.selected_game.get("image", "") or self.selected_game.get("thumbnail", "")
            if not image_rel:
                self.view.notify(self._t("notify.tip"), self._t("notify.no_bg_configured"), error=True)
                return
            game_system = self._game_system(self.selected_game) or self.service.current_system
            image_abs = self.service.repo.rel_to_abs(game_system, image_rel)
            self._reveal_file(image_abs)
            return
        if action == "open_video_dir":
            video_rel = self.selected_game.get("video", "")
            if not video_rel:
                self.view.notify(self._t("notify.tip"), self._t("notify.no_video_configured"), error=True)
                return
            game_system = self._game_system(self.selected_game) or self.service.current_system
            video_abs = self.service.repo.rel_to_abs(game_system, video_rel)
            self._reveal_file(video_abs)
            return
        if action == "feature":
            self.view.notify(self._t("notify.tip"), self._t("notify.feature_reserved"))
            return
        if action == "run_emulator":
            self._run_game_with_emulator(selected)

    def _run_game_by_row(self, row: int) -> None:
        game = self._row_game(row)
        if game is None:
            return
        self.selected_game = game
        self.view.games_table.selectRow(row)
        self._run_game_with_emulator(game)

    def _open_emulator_settings(self) -> None:
        edited = self.view.show_emulator_settings_dialog(self._emulator_configs)
        if edited is None:
            return
        self._emulator_configs = edited
        self._emulator_store.save(edited)
        self.view.notify(self._t("notify.success"), self._t("notify.emulator_settings_saved"))

    def _run_game_with_emulator(self, game: GameEntry) -> None:
        self._emulator_runner.run_game(game)

    def _reveal_file(self, target_file: Path) -> None:
        if not target_file.exists():
            self.view.notify(self._t("notify.failed"), self._t("notify.file_not_found", path=target_file), error=True)
            return
        self._open_in_explorer_select(target_file)

    @staticmethod
    def _open_in_explorer_select(target_file: Path) -> None:
        try:
            subprocess.Popen(["explorer", f"/select,{str(target_file)}"])
        except OSError:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target_file)))

    def _row_game(self, row: int) -> GameEntry | None:
        if row < 0 or row >= len(self.display_games):
            return None
        game = self.display_games[row]
        if game is None:
            return None
        return game

    def _select_game_by_path(self, rel_path: str) -> None:
        for idx, game in enumerate(self.display_games):
            if game is None:
                continue
            if game.path == rel_path:
                self.view.games_table.setCurrentCell(idx, 1)
                self.view.games_table.selectRow(idx)
                self._on_game_selected(idx)
                return

    def _display_row_index(self, game: GameEntry) -> int:
        for idx, displayed in enumerate(self.display_games):
            if displayed is game:
                return idx
        return -1

    def _toggle_favorite_by_row(self, row: int) -> None:
        game = self._row_game(row)
        if game is None:
            return
        game_system = self._game_system(game) or self.service.current_system
        if not game_system:
            return
        data = {k: game.get(k, "") for k in self.view.field_widgets}
        current = data.get("favorite", "false").lower() == "true"
        data["favorite"] = "false" if current else "true"
        try:
            self._stage_metadata_update(game, game_system, data)
            if self.selected_game is game:
                self.selected_game.set("favorite", data["favorite"])
            self._refresh_game_table()
        except (OSError, ValueError, FileNotFoundError) as exc:
            self.view.notify(self._t("notify.failed"), self._t("notify.favorite_failed", error=exc), error=True)

    def _add_favorite(self) -> None:
        if self.selected_game is None:
            return
        row = next((i for i, g in enumerate(self.display_games) if g is self.selected_game), -1)
        if row >= 0:
            self._toggle_favorite_by_row(row)

    def _on_game_selected(self, row: int) -> None:
        game = self._row_game(row)
        if game is None:
            return
        self.selected_game = game
        values = {k: self.selected_game.get(k, "") for k in self.view.field_widgets}
        self.view.set_edit_form(values)
        self._refresh_preview(self.selected_game)

    @staticmethod
    def _game_system(game: GameEntry) -> str:
        return game.get("__system__", "")

    def _refresh_preview(self, game: GameEntry) -> None:
        game_system = self._game_system(game) or self.service.current_system
        image_rel = game.get("image", "") or game.get("thumbnail", "")
        image_abs: Path | None = None
        if image_rel:
            image_abs = self.service.repo.rel_to_abs(game_system, image_rel)
            if not image_abs.exists():
                image_abs = None
        if image_abs is None:
            self.view.set_preview_image(None, self._t("preview.none"))
        else:
            pix = QPixmap(str(image_abs))
            if pix.isNull():
                self.view.set_preview_image(None, self._t("preview.unreadable"))
            else:
                self.view.set_preview_image(pix, "")
        video_rel = game.get("video", "")
        if not video_rel:
            self.view.set_preview_video(None)
            return
        video_abs = self.service.repo.rel_to_abs(game_system, video_rel)
        if not video_abs.exists():
            self.view.set_preview_video(None)
            return
        self.view.set_preview_video(video_abs)

    def _save_metadata(self) -> None:
        if self.selected_game is None:
            self.view.notify(self._t("notify.tip"), self._t("notify.select_system_game_first"), error=True)
            return
        game_system = self._game_system(self.selected_game) or self.service.current_system
        if not game_system:
            self.view.notify(self._t("notify.tip"), self._t("notify.select_system_game_first"), error=True)
            return
        data = self.view.get_edit_form()
        try:
            start = time.perf_counter()
            self.view.set_busy(True, self._t("status.saving_metadata"))
            before_row = game_to_row(self.selected_game, self._mode)
            query = self.view.search_edit.text().strip().lower()
            changed = self._stage_metadata_update(self.selected_game, game_system, data)
            if changed:
                after_row = game_to_row(self.selected_game, self._mode)
                need_refresh = should_refresh_after_save(
                    mode=self._mode,
                    query=query,
                    before_row=before_row,
                    after_row=after_row,
                    header_sort_column=self._header_sort_column,
                )
                if need_refresh:
                    self._refresh_game_table()
                    self._select_game_by_path(self.selected_game.path)
                else:
                    row = self._display_row_index(self.selected_game)
                    if row >= 0:
                        self.view.update_game_row(row, after_row)
                        self.view.games_table.setCurrentCell(row, 1)
                        self.view.games_table.selectRow(row)
                    self._refresh_preview(self.selected_game)
            self.view.set_busy(False, self._t("status.metadata_saved"))
            self._refresh_pending_action_state()
            self.view.notify(self._t("notify.success"), self._t("notify.metadata_saved"))
            logger.info(
                "保存元数据完成: system=%s, game=%s, changed=%s, 耗时=%.3fs",
                game_system,
                self.selected_game.path,
                changed,
                time.perf_counter() - start,
            )
        except (OSError, ValueError, FileNotFoundError) as exc:
            self.view.set_busy(False, self._t("status.metadata_save_failed"))
            logger.exception("保存元数据失败: system=%s, game=%s", game_system, self.selected_game.path)
            self.view.notify(self._t("notify.validation_failed"), str(exc), error=True)

    def _on_language_changed(self, lang: str) -> None:
        self.current_language = lang
        self.view.set_language(lang)
        selected_system = self.service.current_system
        self.view.set_systems([self._t("system.all_games"), self._t("system.favorites"), *self._systems])
        if self._mode == "all":
            self._last_system_label = self._t("system.all_games")
        elif self._mode == "favorites":
            self._last_system_label = self._t("system.favorites")
        else:
            self._last_system_label = selected_system
        items = self.view.system_list.findItems(self._last_system_label, Qt.MatchFlag.MatchExactly)
        if items:
            self.view.system_list.blockSignals(True)
            self.view.system_list.setCurrentItem(items[0])
            self.view.system_list.blockSignals(False)
        self._refresh_game_table()
        self._refresh_pending_action_state()

    def _toggle_theme(self) -> None:
        self.current_theme = "light" if self.current_theme == "dark" else "dark"
        self._apply_theme(self.current_theme, animate=True)

    def _apply_theme(self, theme: str, animate: bool) -> None:
        qss_path = Path(__file__).parent / "styles" / f"{theme}.qss"
        if not qss_path.exists():
            return
        qss = qss_path.read_text(encoding="utf-8")
        self._theme_anim.stop()
        if animate:
            self.view.setWindowOpacity(0.92)
            self._theme_anim.setStartValue(0.92)
            self._theme_anim.setEndValue(1.0)
        self.view.apply_stylesheet(qss)
        if animate:
            self._theme_anim.start()
        else:
            self.view.setWindowOpacity(1.0)
        if theme == "dark":
            self.view.btn_theme.setText(self._t("button.theme.dark"))
        else:
            self.view.btn_theme.setText(self._t("button.theme.light"))

    def _t(self, key: str, **kwargs) -> str:
        return tr(self.current_language, key, **kwargs)


def run_app() -> int:
    app = QApplication.instance()
    if app is None:
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
        app = QApplication([])
    assert isinstance(app, QApplication)
    icon = _load_app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)
    controller = ArkosController()
    if not icon.isNull():
        controller.view.setWindowIcon(icon)
    controller.show()
    return app.exec()

def _load_app_icon() -> QIcon:
    base_dir = Path(__file__).resolve().parent
    logo_path = base_dir / "logo.png"
    if not logo_path.exists():
        return QIcon()
    image = QImage(str(logo_path))
    if image.isNull():
        return QIcon(str(logo_path))
    if image.format() != QImage.Format.Format_ARGB32:
        image = image.convertToFormat(QImage.Format.Format_ARGB32)
    w, h = image.width(), image.height()
    for y in range(h):
        for x in range(w):
            c = image.pixelColor(x, y)
            if c.red() <= 20 and c.green() <= 20 and c.blue() <= 20:
                image.setPixelColor(x, y, QColor(c.red(), c.green(), c.blue(), 0))
    return QIcon(QPixmap.fromImage(image))
