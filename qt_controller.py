from __future__ import annotations

import configparser
import os
import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QTimer, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QImage, QPixmap
from PySide6.QtWidgets import QApplication

from arkos_core import ArkosService, GameEntry
from emulator_runner import EmulatorRunner
from emulator_config import EmulatorConfigStore
from game_actions import (
    ControllerGameActionsMixin,
    build_table,
    collect_games_all_systems,
    game_to_row,
    should_refresh_after_save,
)
from i18n import tr
from qt_view import MainWindow
from update_service import UpdateService
from version import APP_VERSION

logger = logging.getLogger(__name__)


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
        self._header_sort_column: int | None = None
        self._header_sort_asc = True
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

    def _schedule_refresh(self, *_args) -> None:
        self._search_debounce.start()

    def show(self) -> None:
        self.view.show()

    def _choose_root(self) -> None:
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
            self.view.set_systems([self._t("system.all_games"), self._t("system.favorites"), *systems])
            self.selected_game = None
            self.filtered_games = []
            self.display_games = []
            self._mode = "all"
            self.view.set_games([], set())
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
        start = time.perf_counter()
        logger.info("切换系统: %s", system)
        self.view.set_busy(True, self._t("status.loading_games"))
        try:
            self.view.set_task_progress(self._t("status.loading_games"), 1, 3)
            if system == self._t("system.all_games"):
                self._mode = "all"
                self.service.current_system = ""
                self.service.games = collect_games_all_systems(
                    systems=self._systems,
                    load_games=self.service.repo.load_games,
                    favorites_only=False,
                )
            elif system == self._t("system.favorites"):
                self._mode = "favorites"
                self.service.current_system = ""
                self.service.games = collect_games_all_systems(
                    systems=self._systems,
                    load_games=self.service.repo.load_games,
                    favorites_only=True,
                )
            else:
                self._mode = "system"
                self.service.select_system(system)
            self.selected_game = None
            self._header_sort_column = None
            self._header_sort_asc = True
            self.view.clear_edit_form()
            self.view.set_task_progress(self._t("status.loading_games"), 2, 3)
            self._refresh_game_table()
            self.view.set_task_progress(f"{system} {self._t('status.ready')}", 3, 3)
            self.view.set_busy(False, f"{system} {self._t('status.ready')}")
            logger.info("系统加载完成: %s, 模式=%s, 耗时=%.3fs", system, self._mode, time.perf_counter() - start)
        except (OSError, ValueError, FileNotFoundError) as exc:
            self.view.set_busy(False, self._t("status.load_failed"))
            logger.exception("系统加载失败: %s", system)
            self.view.notify(self._t("notify.failed"), self._t("notify.load_system_failed", error=exc), error=True)

    def _refresh_game_table(self, *_args) -> None:
        start = time.perf_counter()
        if self._mode == "all":
            self.service.games = collect_games_all_systems(
                systems=self._systems,
                load_games=self.service.repo.load_games,
                favorites_only=False,
            )
        elif self._mode == "favorites":
            self.service.games = collect_games_all_systems(
                systems=self._systems,
                load_games=self.service.repo.load_games,
                favorites_only=True,
            )
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
            self.service.current_system = game_system
            self.service.save_metadata(game, data)
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
            self.service.current_system = game_system
            changed = self.service.save_metadata(self.selected_game, data)
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
        self._refresh_systems()
        self._refresh_game_table()

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
