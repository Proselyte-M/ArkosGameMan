from __future__ import annotations

import configparser
import logging
import shutil
import subprocess
import time
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QImage, QPixmap
from PySide6.QtWidgets import QApplication

from arkos_core import ArkosService, GameEntry
from i18n import tr
from qt_view import MainWindow

logger = logging.getLogger(__name__)


class ArkosController:
    def __init__(self) -> None:
        self.view = MainWindow()
        self._settings_file = Path(__file__).resolve().parent / "arkosgameman.ini"
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
        self._theme_anim = QPropertyAnimation(self.view, b"windowOpacity", self.view)
        self._theme_anim.setDuration(180)
        self._theme_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.view.set_root_path(str(initial_root))
        self.view.set_language(self.current_language)
        self._wire_signals()
        self._apply_theme(self.current_theme, animate=False)
        self._refresh_systems()

    def _load_last_root(self) -> Path:
        parser = configparser.ConfigParser()
        if self._settings_file.exists():
            parser.read(self._settings_file, encoding="utf-8")
            saved = parser.get("app", "rom_root", fallback="/roms").strip()
            if saved:
                return Path(saved)
        return Path("/roms")

    def _save_last_root(self, root_path: Path) -> None:
        parser = configparser.ConfigParser()
        parser["app"] = {"rom_root": str(root_path)}
        with self._settings_file.open("w", encoding="utf-8") as handle:
            parser.write(handle)

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
        self.view.request_search_or_sort.connect(lambda _text: self._refresh_game_table())
        self.view.request_game_selected.connect(self._on_game_selected)
        self.view.request_header_sort.connect(self._on_header_sort)
        self.view.request_context_action.connect(self._on_context_action)
        self.view.request_preview_image_double_click.connect(self.view.show_preview_image_dialog)
        self.view.request_toggle_favorite.connect(self._toggle_favorite_by_row)
        self.view.request_import_media.connect(self._import_media)
        self.view.request_language_changed.connect(self._on_language_changed)

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
            self.service.set_root(root_path)
            self._save_last_root(root_path)
            systems = self.service.list_systems()
            self._systems = systems[:]
            self.view.set_systems([self._t("system.all_games"), self._t("system.favorites"), *systems])
            self.selected_game = None
            self.filtered_games = []
            self.display_games = []
            self._mode = "all"
            self.view.set_games([], set())
            self.view.clear_edit_form()
            self.view.set_busy(False, self._t("status.systems_refreshed"))
            logger.info("系统刷新完成: root=%s, 系统数=%d, 耗时=%.3fs", root_path, len(systems), time.perf_counter() - start)
        except Exception as exc:
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
            if system == self._t("system.all_games"):
                self._mode = "all"
                self.service.current_system = ""
                self.service.games = self._collect_games_all_systems(favorites_only=False)
            elif system == self._t("system.favorites"):
                self._mode = "favorites"
                self.service.current_system = ""
                self.service.games = self._collect_games_all_systems(favorites_only=True)
            else:
                self._mode = "system"
                self.service.select_system(system)
            self.selected_game = None
            self._header_sort_column = None
            self._header_sort_asc = True
            self.view.clear_edit_form()
            self._refresh_game_table()
            self.view.set_busy(False, f"{system} {self._t('status.ready')}")
            logger.info("系统加载完成: %s, 模式=%s, 耗时=%.3fs", system, self._mode, time.perf_counter() - start)
        except Exception as exc:
            self.view.set_busy(False, self._t("status.load_failed"))
            logger.exception("系统加载失败: %s", system)
            self.view.notify(self._t("notify.failed"), self._t("notify.load_system_failed", error=exc), error=True)

    def _collect_games_all_systems(self, favorites_only: bool) -> list[GameEntry]:
        all_games: list[GameEntry] = []
        for system in self._systems:
            for game in self.service.repo.load_games(system):
                if favorites_only and game.get("favorite", "false").lower() != "true":
                    continue
                game.fields["__system__"] = system
                all_games.append(game)
        return all_games

    @staticmethod
    def _display_name(game: GameEntry, mode: str) -> str:
        name = game.get("name", game.rom_name)
        if mode in {"all", "favorites"}:
            return f"[{game.get('__system__', '')}] {name}"
        return name

    @staticmethod
    def _display_path(game: GameEntry, mode: str) -> str:
        if mode in {"all", "favorites"}:
            return f"{game.get('__system__', '')}:{game.path}"
        return game.path

    def _refresh_game_table(self, *_args) -> None:
        start = time.perf_counter()
        if self._mode == "all":
            self.service.games = self._collect_games_all_systems(favorites_only=False)
        elif self._mode == "favorites":
            self.service.games = self._collect_games_all_systems(favorites_only=True)
        source_games = self.service.games[:]
        query = self.view.search_edit.text().strip().lower()
        if query:
            source_games = [
                g
                for g in source_games
                if query in g.get("name", "").lower()
                or query in g.path.lower()
                or query in g.get("__system__", "").lower()
            ]
        self.filtered_games = self._sort_games(source_games)
        rows: list[tuple[str, str, str, str, str, str]] = []
        self.display_games = []
        group_rows: set[int] = set()
        if self._mode == "favorites":
            grouped: dict[str, list[GameEntry]] = {}
            for game in self.filtered_games:
                grouped.setdefault(game.get("__system__", ""), []).append(game)
            for system in sorted(grouped.keys(), key=str.lower):
                row_idx = len(rows)
                rows.append(("", self._t("group.system_header", system=system), "", "", "", ""))
                self.display_games.append(None)
                group_rows.add(row_idx)
                for game in grouped[system]:
                    rows.append(self._game_to_row(game))
                    self.display_games.append(game)
        else:
            for game in self.filtered_games:
                rows.append(self._game_to_row(game))
                self.display_games.append(game)
        self.view.set_games(rows, group_rows)
        logger.info(
            "刷新游戏表: 模式=%s, 查询='%s', 数据=%d, 展示=%d, 分组头=%d, 耗时=%.3fs",
            self._mode,
            query,
            len(self.service.games),
            len(rows),
            len(group_rows),
            time.perf_counter() - start,
        )

    def _sort_games(self, data: list[GameEntry]) -> list[GameEntry]:
        sorted_games = data[:]
        if self._header_sort_column is None:
            sorted_games.sort(key=lambda g: self._display_name(g, self._mode).lower())
            return sorted_games
        key_fn = self._column_sort_key(self._header_sort_column)
        if key_fn is None:
            return sorted_games
        sorted_games = sorted(sorted_games, key=key_fn, reverse=not self._header_sort_asc)
        self.view.set_header_sort_indicator(self._header_sort_column, self._header_sort_asc)
        return sorted_games

    @staticmethod
    def _favorite_text(game: GameEntry) -> str:
        return "♥" if game.get("favorite", "false").lower() == "true" else "♡"

    def _game_to_row(self, game: GameEntry) -> tuple[str, str, str, str, str, str]:
        return (
            self._favorite_text(game),
            self._display_name(game, self._mode),
            self._display_path(game, self._mode),
            game.get("playcount", "0"),
            game.get("rating", ""),
            game.get("lastplayed", ""),
        )

    def _column_sort_key(self, column: int):
        if column == 0:
            return lambda g: g.get("favorite", "false").lower() == "true"
        if column == 1:
            return lambda g: self._display_name(g, self._mode).lower()
        if column == 2:
            return lambda g: self._display_path(g, self._mode).lower()
        if column == 3:
            return lambda g: self._safe_int(g.get("playcount", "0"))
        if column == 4:
            return lambda g: self._safe_float(g.get("rating", "0"))
        if column == 5:
            return lambda g: g.get("lastplayed", "")
        return None

    @staticmethod
    def _safe_int(value: str) -> int:
        try:
            return int(value or 0)
        except Exception:
            return 0

    @staticmethod
    def _safe_float(value: str) -> float:
        try:
            return float(value or 0)
        except Exception:
            return 0.0

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

    def _reveal_file(self, target_file: Path) -> None:
        if not target_file.exists():
            self.view.notify(self._t("notify.failed"), self._t("notify.file_not_found", path=target_file), error=True)
            return
        self._open_in_explorer_select(target_file)

    @staticmethod
    def _open_in_explorer_select(target_file: Path) -> None:
        try:
            subprocess.Popen(["explorer", f"/select,{str(target_file)}"])
        except Exception:
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

    def _should_refresh_after_save(
        self,
        query: str,
        before_row: tuple[str, str, str, str, str, str],
        after_row: tuple[str, str, str, str, str, str],
    ) -> bool:
        if self._mode in {"all", "favorites"}:
            return True
        if query:
            return True
        if self._header_sort_column is None:
            return before_row[1] != after_row[1]
        return before_row[self._header_sort_column] != after_row[self._header_sort_column]

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
        except Exception as exc:
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
            before_row = self._game_to_row(self.selected_game)
            query = self.view.search_edit.text().strip().lower()
            self.service.current_system = game_system
            changed = self.service.save_metadata(self.selected_game, data)
            if changed:
                after_row = self._game_to_row(self.selected_game)
                need_refresh = self._should_refresh_after_save(query, before_row, after_row)
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
        except Exception as exc:
            self.view.set_busy(False, self._t("status.metadata_save_failed"))
            logger.exception("保存元数据失败: system=%s, game=%s", game_system, self.selected_game.path)
            self.view.notify(self._t("notify.validation_failed"), str(exc), error=True)

    def _add_rom(self) -> None:
        if not self.service.current_system:
            self.view.notify(self._t("notify.tip"), self._t("notify.select_system_first"), error=True)
            return
        file_name = self.view.choose_file(self._t("dialog.select_rom_file"))
        if not file_name:
            return
        self.view.set_busy(True, self._t("status.adding_rom"))
        try:
            start = time.perf_counter()
            source = Path(file_name)
            self.service.add_rom(source)
            if self.view.search_edit.text():
                self.view.search_edit.clear()
            self._refresh_game_table()
            self._select_game_by_path(self.service.repo.normalize_rel_path(source.name))
            self.view.set_busy(False, self._t("status.add_rom_done"))
            self.view.notify(self._t("notify.success"), self._t("notify.rom_added"))
            logger.info(
                "添加ROM完成: system=%s, source=%s, 耗时=%.3fs",
                self.service.current_system,
                source,
                time.perf_counter() - start,
            )
        except Exception as exc:
            self.view.set_busy(False, self._t("status.add_rom_failed"))
            logger.exception("添加ROM失败: system=%s, source=%s", self.service.current_system, file_name)
            self.view.notify(self._t("notify.failed"), self._t("notify.add_rom_failed", error=exc), error=True)

    def _delete_game(self) -> None:
        if self.selected_game is None:
            self.view.notify(self._t("notify.tip"), self._t("notify.select_game_first"), error=True)
            return
        game_system = self._game_system(self.selected_game) or self.service.current_system
        if not game_system:
            self.view.notify(self._t("notify.tip"), self._t("notify.select_game_first"), error=True)
            return
        display_name = self.selected_game.get("name", self.selected_game.rom_name)
        if not self.view.ask_yes_no(self._t("dialog.delete_confirm_title"), self._t("dialog.delete_confirm", name=display_name)):
            return
        full_delete = self.view.ask_yes_no(self._t("dialog.delete_mode_title"), self._t("dialog.delete_mode"))
        self.view.set_busy(True, self._t("status.deleting"))
        try:
            self.service.current_system = game_system
            self.service.delete_game(self.selected_game, full_delete)
            self.selected_game = None
            self._refresh_game_table()
            self.view.clear_edit_form()
            self.view.set_busy(False, self._t("status.delete_done"))
            self.view.notify(self._t("notify.success"), self._t("notify.delete_success"))
        except Exception as exc:
            self.view.set_busy(False, self._t("status.delete_failed"))
            self.view.notify(self._t("notify.failed"), self._t("notify.delete_failed_rollback", error=exc), error=True)

    def _rename_game(self) -> None:
        if self.selected_game is None:
            self.view.notify(self._t("notify.tip"), self._t("notify.select_game_first"), error=True)
            return
        game_system = self._game_system(self.selected_game) or self.service.current_system
        if not game_system:
            self.view.notify(self._t("notify.tip"), self._t("notify.select_game_first"), error=True)
            return
        old_stem = Path(self.selected_game.path).stem
        new_stem = self.view.ask_text(self._t("dialog.rename_title"), self._t("dialog.rename_label"), old_stem).strip()
        if not new_stem:
            return
        self.view.set_busy(True, self._t("status.renaming"))
        try:
            self.service.current_system = game_system
            self.service.rename_game(self.selected_game, new_stem)
            self._refresh_game_table()
            self.view.set_busy(False, self._t("status.rename_done"))
            self.view.notify(self._t("notify.success"), self._t("notify.rename_success"))
        except Exception as exc:
            self.view.set_busy(False, self._t("status.rename_failed"))
            self.view.notify(self._t("notify.failed"), self._t("notify.rename_failed_rollback", error=exc), error=True)

    def _backup_saves(self) -> None:
        self.view.set_busy(True, self._t("status.backing_up_saves"))
        try:
            zip_file = self.service.backup_saves()
            self.view.set_busy(False, self._t("status.backup_done"))
            self.view.notify(self._t("notify.success"), self._t("notify.backup_success", path=zip_file))
        except Exception as exc:
            self.view.set_busy(False, self._t("status.backup_failed"))
            self.view.notify(self._t("notify.failed"), self._t("notify.backup_failed", error=exc), error=True)

    def _import_media(self, media_key: str) -> None:
        if self.selected_game is None:
            self.view.notify(self._t("notify.tip"), self._t("notify.select_game_first"), error=True)
            return
        game_system = self._game_system(self.selected_game) or self.service.current_system
        if not game_system:
            self.view.notify(self._t("notify.tip"), self._t("notify.select_game_first"), error=True)
            return
        filters = {
            "image": "Image Files (*.png *.jpg *.jpeg *.bmp *.webp)",
            "thumbnail": "Image Files (*.png *.jpg *.jpeg *.bmp *.webp)",
            "video": "Video Files (*.mp4 *.mkv *.avi *.mov *.webm)",
        }
        titles = {
            "image": self._t("dialog.select_image"),
            "thumbnail": self._t("dialog.select_image"),
            "video": self._t("dialog.select_video"),
        }
        folder_map = {"image": "covers", "thumbnail": "thumbnails", "video": "videos"}
        if media_key not in folder_map:
            return
        file_name = self.view.choose_file(titles[media_key], filters[media_key])
        if not file_name:
            return
        self.view.set_busy(True, self._t("status.media_importing"))
        try:
            start = time.perf_counter()
            source = Path(file_name)
            folder = folder_map[media_key]
            ext = source.suffix.lower()
            if not ext:
                raise ValueError("文件扩展名无效")
            rom_stem = Path(self.selected_game.path).stem
            target_dir = self.service.repo.system_dir(game_system) / "media" / folder
            target_dir.mkdir(parents=True, exist_ok=True)
            target_name = f"{rom_stem}{ext}"
            target = target_dir / target_name
            shutil.copy2(source, target)
            rel = f"./media/{folder}/{target_name}".replace("\\", "/")
            data = {k: self.selected_game.get(k, "") for k in self.view.field_widgets}
            data[media_key] = rel
            self.service.current_system = game_system
            self.service.save_metadata(self.selected_game, data)
            self._refresh_game_table()
            values = {k: self.selected_game.get(k, "") for k in self.view.field_widgets}
            self.view.set_edit_form(values)
            self._refresh_preview(self.selected_game)
            self.view.set_busy(False, self._t("status.media_import_done"))
            self.view.notify(self._t("notify.success"), self._t("notify.media_import_success", label=self._t(f"label.{media_key}")))
            logger.info(
                "导入媒体完成: system=%s, game=%s, type=%s, source=%s, 耗时=%.3fs",
                game_system,
                self.selected_game.path,
                media_key,
                source,
                time.perf_counter() - start,
            )
        except Exception as exc:
            self.view.set_busy(False, self._t("status.media_import_failed"))
            logger.exception("导入媒体失败: system=%s, type=%s, source=%s", game_system, media_key, file_name)
            self.view.notify(self._t("notify.failed"), self._t("notify.media_import_failed", error=exc), error=True)

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
    w = image.width()
    h = image.height()
    for y in range(h):
        for x in range(w):
            c = image.pixelColor(x, y)
            if c.red() <= 20 and c.green() <= 20 and c.blue() <= 20:
                image.setPixelColor(x, y, QColor(c.red(), c.green(), c.blue(), 0))
    return QIcon(QPixmap.fromImage(image))
