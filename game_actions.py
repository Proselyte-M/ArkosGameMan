from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import re
import shutil
import time
from typing import TYPE_CHECKING, Callable, Protocol

from arkos_core import GameEntry

if TYPE_CHECKING:
    from arkos_core import ArkosService
    from qt_view import MainWindow

logger = logging.getLogger(__name__)
STANDARD_NAME_PATTERN = re.compile(r"^[A-Za-z]\s.+\[.+\]$")
LEADING_PREFIX_PATTERN = re.compile(r"^[A-Za-z](?:\s*[-_.]\s*|\s+)")
BRACKET_CONTENT_PATTERN = re.compile(r"\[[^\]]*]|\([^)]*\)|（[^）]*）|【[^】]*】")
DISALLOWED_SYMBOL_PATTERN = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff\s]+")
MULTI_SPACE_PATTERN = re.compile(r"\s+")
PINYIN_RANGE = [
    (-20319, "A"),
    (-20284, "B"),
    (-19776, "C"),
    (-19219, "D"),
    (-18711, "E"),
    (-18527, "F"),
    (-18240, "G"),
    (-17923, "H"),
    (-17418, "J"),
    (-16475, "K"),
    (-16213, "L"),
    (-15641, "M"),
    (-15166, "N"),
    (-14923, "O"),
    (-14915, "P"),
    (-14631, "Q"),
    (-14150, "R"),
    (-14091, "S"),
    (-13319, "T"),
    (-12839, "W"),
    (-12557, "X"),
    (-11848, "Y"),
    (-11056, "Z"),
]


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


def is_standardized_name(name: str) -> bool:
    return bool(STANDARD_NAME_PATTERN.fullmatch(name.strip()))


def sanitize_core_name(name: str) -> str:
    text = MULTI_SPACE_PATTERN.sub(" ", name.strip())
    while True:
        updated = LEADING_PREFIX_PATTERN.sub("", text).strip()
        if updated == text:
            break
        text = updated
    text = BRACKET_CONTENT_PATTERN.sub(" ", text)
    text = re.sub(r"[\[\]()（）【】]", " ", text)
    text = MULTI_SPACE_PATTERN.sub(" ", text).strip()
    reduced = DISALLOWED_SYMBOL_PATTERN.sub("", text)
    reduced = MULTI_SPACE_PATTERN.sub(" ", reduced).strip()
    if any(("a" <= ch.lower() <= "z") or _is_hanzi(ch) for ch in reduced):
        return reduced
    return text or name.strip()


def build_standardized_name(name: str) -> str:
    core = sanitize_core_name(name)
    lead = leading_letter(core)
    short = abbreviation_letters(core)
    return f"{lead} {core} [{short}]"


def leading_letter(core_name: str) -> str:
    for ch in core_name:
        if _is_hanzi(ch):
            initial = _hanzi_initial(ch)
            if initial:
                return initial
            continue
        if ch.isascii() and ch.isalpha():
            return ch.upper()
    return "A"


def abbreviation_letters(core_name: str) -> str:
    out: list[str] = []
    for ch in core_name:
        if ch.isspace():
            continue
        if ch.isascii() and ch.isalpha():
            out.append(ch.upper())
            continue
        if ch.isdigit():
            out.append(ch)
            continue
        if _is_hanzi(ch):
            initial = _hanzi_initial(ch)
            if initial:
                out.append(initial)
    return "".join(out) or "A"


def _is_hanzi(ch: str) -> bool:
    return "\u4e00" <= ch <= "\u9fff"


def _hanzi_initial(ch: str) -> str:
    try:
        gbk = ch.encode("gbk")
    except UnicodeEncodeError:
        return ""
    if len(gbk) < 2:
        return ""
    code = gbk[0] * 256 + gbk[1] - 65536
    for idx, (start, letter) in enumerate(PINYIN_RANGE):
        if idx == len(PINYIN_RANGE) - 1:
            if start <= code <= -10247:
                return letter
            return ""
        next_start = PINYIN_RANGE[idx + 1][0]
        if start <= code < next_start:
            return letter
    return ""


class _ControllerContext(Protocol):
    service: ArkosService
    view: MainWindow
    selected_game: GameEntry | None
    _is_normalizing_names: bool

    def _t(self, key: str, **kwargs) -> str: ...
    def _game_system(self, game: GameEntry) -> str: ...
    def _refresh_game_table(self, *_args) -> None: ...
    def _select_game_by_path(self, rel_path: str) -> None: ...
    def _refresh_preview(self, game: GameEntry) -> None: ...
    def _stage_metadata_update(self, game: GameEntry, game_system: str, data: dict[str, str]) -> bool: ...
    def _refresh_pending_action_state(self) -> None: ...


class ControllerGameActionsMixin:
    selected_game: GameEntry | None

    def _normalize_game_names(self: _ControllerContext) -> None:
        if self._is_normalizing_names:
            self.view.notify(self._t("notify.tip"), self._t("notify.normalize_busy"), error=True)
            return
        source_games = [game for game in self.service.games]
        if not source_games:
            self.view.notify(self._t("notify.tip"), self._t("notify.select_system_game_first"), error=True)
            return
        pending: list[tuple[GameEntry, str, str, str]] = []
        skipped = 0
        for game in source_games:
            original_name = game.get("name", Path(game.path).stem).strip()
            if is_standardized_name(original_name):
                skipped += 1
                continue
            game_system = self._game_system(game) or self.service.current_system
            if not game_system:
                continue
            standardized_name = build_standardized_name(original_name)
            pending.append((game, game_system, original_name, standardized_name))
        if not pending:
            self.view.notify(self._t("notify.success"), self._t("notify.normalize_all_compliant"))
            return
        if not self.view.ask_yes_no(
            self._t("dialog.normalize_confirm_title"),
            self._t("dialog.normalize_confirm", count=len(pending)),
        ):
            return
        self._is_normalizing_names = True
        self._refresh_pending_action_state()
        previous_system = self.service.current_system
        progress = self.view.open_batch_progress(self._t("button.normalize_names"), len(pending))
        done = 0
        failed: list[str] = []
        try:
            for idx, (game, game_system, original_name, standardized_name) in enumerate(pending, start=1):
                progress.update(self._t("status.normalizing_item", current=idx, total=len(pending)), idx)
                try:
                    data = {k: game.get(k, "") for k in self.view.field_widgets}
                    data["name"] = standardized_name
                    if self._stage_metadata_update(game, game_system, data):
                        done += 1
                except (OSError, ValueError, FileNotFoundError) as exc:
                    failed.append(f"{game.path}: {original_name} -> {standardized_name}: {exc}")
            self.service.current_system = previous_system
            self._refresh_game_table()
            summary = self._t("notify.normalize_summary", done=done, skipped=skipped, failed=len(failed))
            if failed:
                self.view.notify_highlight_list(self._t("notify.failed"), summary, failed)
            else:
                self.view.notify(self._t("notify.success"), summary)
        finally:
            progress.close()
            self._is_normalizing_names = False
            self._refresh_pending_action_state()

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
            data = {k: self.selected_game.get(k, "") for k in self.view.field_widgets}
            data["name"] = new_stem
            self._stage_metadata_update(self.selected_game, game_system, data)
            self._refresh_game_table()
            self._refresh_pending_action_state()
            self.view.set_busy(False, self._t("status.rename_done"))
            self.view.notify(self._t("notify.success"), self._t("notify.rename_success"))
        except (OSError, ValueError, FileNotFoundError) as exc:
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
            self._stage_metadata_update(self.selected_game, game_system, data)
            self._refresh_game_table()
            self._refresh_pending_action_state()
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
