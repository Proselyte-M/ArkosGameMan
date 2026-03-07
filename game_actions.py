from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import shutil
import time
from typing import TYPE_CHECKING, Callable, Protocol

from arkos_core import GameEntry

if TYPE_CHECKING:
    from arkos_core import ArkosService
    from qt_view import MainWindow

logger = logging.getLogger(__name__)


@dataclass
class GameTableResult:
    filtered_games: list[GameEntry]
    display_games: list[GameEntry | None]
    rows: list[tuple[str, str, str, str, str, str]]
    group_rows: set[int]
    query: str


def collect_games_all_systems(
    systems: list[str],
    load_games: Callable[[str], list[GameEntry]],
    favorites_only: bool,
) -> list[GameEntry]:
    all_games: list[GameEntry] = []
    for system in systems:
        for game in load_games(system):
            if favorites_only and game.get("favorite", "false").lower() != "true":
                continue
            game.fields["__system__"] = system
            all_games.append(game)
    return all_games


def display_name(game: GameEntry, mode: str) -> str:
    name = game.get("name", game.rom_name)
    if mode in {"all", "favorites"}:
        return f"[{game.get('__system__', '')}] {name}"
    return name


def display_path(game: GameEntry, mode: str) -> str:
    if mode in {"all", "favorites"}:
        return f"{game.get('__system__', '')}:{game.path}"
    return game.path


def favorite_text(game: GameEntry) -> str:
    return "♥" if game.get("favorite", "false").lower() == "true" else "♡"


def game_to_row(game: GameEntry, mode: str) -> tuple[str, str, str, str, str, str]:
    return (
        favorite_text(game),
        display_name(game, mode),
        display_path(game, mode),
        game.get("playcount", "0"),
        game.get("rating", ""),
        game.get("lastplayed", ""),
    )


def safe_int(value: str) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def safe_float(value: str) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def sort_games(
    data: list[GameEntry],
    mode: str,
    header_sort_column: int | None,
    header_sort_asc: bool,
) -> list[GameEntry]:
    sorted_games = data[:]
    if header_sort_column is None:
        sorted_games.sort(key=lambda g: display_name(g, mode).lower())
        return sorted_games
    key_fn = column_sort_key(header_sort_column, mode)
    if key_fn is None:
        return sorted_games
    return sorted(sorted_games, key=key_fn, reverse=not header_sort_asc)


def column_sort_key(column: int, mode: str):
    if column == 0:
        return lambda g: g.get("favorite", "false").lower() == "true"
    if column == 1:
        return lambda g: display_name(g, mode).lower()
    if column == 2:
        return lambda g: display_path(g, mode).lower()
    if column == 3:
        return lambda g: safe_int(g.get("playcount", "0"))
    if column == 4:
        return lambda g: safe_float(g.get("rating", "0"))
    if column == 5:
        return lambda g: g.get("lastplayed", "")
    return None


def build_table(
    mode: str,
    source_games: list[GameEntry],
    query_text: str,
    header_sort_column: int | None,
    header_sort_asc: bool,
    group_system_header: Callable[[str], str],
) -> GameTableResult:
    query = query_text.strip().lower()
    data = source_games[:]
    if query:
        data = [
            g
            for g in data
            if query in g.get("name", "").lower()
            or query in g.path.lower()
            or query in g.get("__system__", "").lower()
        ]
    filtered_games = sort_games(data, mode, header_sort_column, header_sort_asc)
    rows: list[tuple[str, str, str, str, str, str]] = []
    display_games: list[GameEntry | None] = []
    group_rows: set[int] = set()
    if mode == "favorites":
        grouped: dict[str, list[GameEntry]] = {}
        for game in filtered_games:
            grouped.setdefault(game.get("__system__", ""), []).append(game)
        for system in sorted(grouped.keys(), key=str.lower):
            row_idx = len(rows)
            rows.append(("", group_system_header(system), "", "", "", ""))
            display_games.append(None)
            group_rows.add(row_idx)
            for game in grouped[system]:
                rows.append(game_to_row(game, mode))
                display_games.append(game)
    else:
        for game in filtered_games:
            rows.append(game_to_row(game, mode))
            display_games.append(game)
    return GameTableResult(
        filtered_games=filtered_games,
        display_games=display_games,
        rows=rows,
        group_rows=group_rows,
        query=query,
    )


def should_refresh_after_save(
    mode: str,
    query: str,
    before_row: tuple[str, str, str, str, str, str],
    after_row: tuple[str, str, str, str, str, str],
    header_sort_column: int | None,
) -> bool:
    if mode in {"all", "favorites"}:
        return True
    if query:
        return True
    if header_sort_column is None:
        return before_row[1] != after_row[1]
    return before_row[header_sort_column] != after_row[header_sort_column]


class _ControllerContext(Protocol):
    service: ArkosService
    view: MainWindow
    selected_game: GameEntry | None

    def _t(self, key: str, **kwargs) -> str: ...
    def _game_system(self, game: GameEntry) -> str: ...
    def _refresh_game_table(self, *_args) -> None: ...
    def _select_game_by_path(self, rel_path: str) -> None: ...
    def _refresh_preview(self, game: GameEntry) -> None: ...


class ControllerGameActionsMixin:
    selected_game: GameEntry | None

    def _add_rom(self: _ControllerContext) -> None:
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
        except (OSError, ValueError) as exc:
            self.view.set_busy(False, self._t("status.add_rom_failed"))
            logger.exception("添加ROM失败: system=%s, source=%s", self.service.current_system, file_name)
            self.view.notify(self._t("notify.failed"), self._t("notify.add_rom_failed", error=exc), error=True)

    def _delete_game(self: _ControllerContext) -> None:
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
        except (OSError, ValueError) as exc:
            self.view.set_busy(False, self._t("status.delete_failed"))
            self.view.notify(self._t("notify.failed"), self._t("notify.delete_failed_rollback", error=exc), error=True)

    def _rename_game(self: _ControllerContext) -> None:
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
        except (OSError, ValueError) as exc:
            self.view.set_busy(False, self._t("status.rename_failed"))
            self.view.notify(self._t("notify.failed"), self._t("notify.rename_failed_rollback", error=exc), error=True)

    def _backup_saves(self: _ControllerContext) -> None:
        self.view.set_busy(True, self._t("status.backing_up_saves"))
        try:
            zip_file = self.service.backup_saves()
            self.view.set_busy(False, self._t("status.backup_done"))
            self.view.notify(self._t("notify.success"), self._t("notify.backup_success", path=zip_file))
        except OSError as exc:
            self.view.set_busy(False, self._t("status.backup_failed"))
            self.view.notify(self._t("notify.failed"), self._t("notify.backup_failed", error=exc), error=True)

    def _import_media(self: _ControllerContext, media_key: str) -> None:
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
        except (OSError, ValueError) as exc:
            self.view.set_busy(False, self._t("status.media_import_failed"))
            logger.exception("导入媒体失败: system=%s, type=%s, source=%s", game_system, media_key, file_name)
            self.view.notify(self._t("notify.failed"), self._t("notify.media_import_failed", error=exc), error=True)
