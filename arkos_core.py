from __future__ import annotations

import shutil
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
import logging
from pathlib import Path
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)


EXCLUDED_SYSTEM_DIRS = {
    "saves",
    "backups",
    "bios",
    "config",
    "bezels",
    "emulators",
    "launchimages",
    "savestates",
    "themes",
}
MEDIA_SUBDIRS = ("covers", "screenshots", "videos", "thumbnails")
NON_ROM_EXTENSIONS = {
    ".xml",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".mp4",
    ".avi",
    ".mkv",
    ".txt",
    ".nfo",
    ".db",
}
EDITABLE_FIELDS = [
    "name",
    "desc",
    "image",
    "video",
    "thumbnail",
    "releasedate",
    "developer",
    "publisher",
    "genre",
    "players",
    "rating",
    "favorite",
    "lastplayed",
    "playcount",
]


@dataclass
class GameEntry:
    path: str
    fields: dict[str, str] = field(default_factory=dict)

    def get(self, key: str, default: str = "") -> str:
        if key == "path":
            return self.path
        return self.fields.get(key, default)

    def set(self, key: str, value: str) -> None:
        if key == "path":
            self.path = value
            return
        self.fields[key] = value

    @property
    def rom_name(self) -> str:
        return Path(self.path).name


class ArkosRepository:
    def __init__(self, roms_root: Path):
        self.roms_root = roms_root

    def set_root(self, roms_root: Path) -> None:
        self.roms_root = roms_root

    def list_systems(self) -> list[str]:
        if not self.roms_root.exists():
            return []
        systems = []
        for item in self.roms_root.iterdir():
            if item.is_dir() and item.name.lower() not in EXCLUDED_SYSTEM_DIRS and not item.name.startswith("."):
                systems.append(item.name)
        return sorted(systems, key=str.lower)

    def system_dir(self, system: str) -> Path:
        return self.roms_root / system

    def gamelist_path(self, system: str) -> Path:
        return self.system_dir(system) / "gamelist.xml"

    def saves_dir(self, system: str) -> Path:
        return self.roms_root / "saves" / system

    def normalize_rel_path(self, file_name: str) -> str:
        return f"./{file_name}".replace("\\", "/")

    def rel_to_abs(self, system: str, rel_path: str) -> Path:
        clean = rel_path.strip()
        if clean.startswith("./"):
            clean = clean[2:]
        return (self.system_dir(system) / clean).resolve()

    def list_rom_files(self, system: str) -> list[Path]:
        target = self.system_dir(system)
        if not target.exists():
            return []
        files = []
        for item in target.iterdir():
            if not item.is_file():
                continue
            if item.name.lower() == "gamelist.xml":
                continue
            if item.name.lower() == "gamelist.xml.old":
                continue
            if item.suffix.lower() in NON_ROM_EXTENSIONS:
                continue
            files.append(item)
        return sorted(files, key=lambda p: p.name.lower())

    def load_games(self, system: str) -> list[GameEntry]:
        games: list[GameEntry] = []
        gpath = self.gamelist_path(system)
        if gpath.exists():
            tree = ET.parse(gpath)
            root = tree.getroot()
            for node in root.findall("game"):
                path_text = (node.findtext("path") or "").strip()
                if not path_text:
                    continue
                file_name = Path(path_text).name.lower()
                if file_name in {"gamelist.xml", "gamelist.xml.old"}:
                    continue
                fields: dict[str, str] = {}
                for child in list(node):
                    if child.tag == "path":
                        continue
                    fields[child.tag] = (child.text or "").strip()
                if "name" not in fields or not fields["name"]:
                    fields["name"] = Path(path_text).stem
                games.append(GameEntry(path=path_text.replace("\\", "/"), fields=fields))
        existing_paths = {g.path for g in games}
        for rom in self.list_rom_files(system):
            rel = self.normalize_rel_path(rom.name)
            if rel not in existing_paths:
                games.append(GameEntry(path=rel, fields={"name": rom.stem, "favorite": "false", "playcount": "0"}))
        return sorted(games, key=lambda g: g.get("name", g.rom_name).lower())

    def save_games(self, system: str, games: list[GameEntry]) -> None:
        start = time.perf_counter()
        sys_dir = self.system_dir(system)
        sys_dir.mkdir(parents=True, exist_ok=True)
        gamelist_file = self.gamelist_path(system)
        old_backup_file = sys_dir / "gamelist.xml.old"
        root = ET.Element("gameList")
        ordered = sorted(games, key=lambda g: g.get("name", g.rom_name).lower())
        for idx, game in enumerate(ordered, start=1):
            gnode = ET.SubElement(root, "game", {"id": str(idx)})
            p = ET.SubElement(gnode, "path")
            p.text = game.path.replace("\\", "/")
            for key in EDITABLE_FIELDS:
                value = game.get(key, "").strip()
                if not value:
                    continue
                n = ET.SubElement(gnode, key)
                n.text = value
        ET.indent(root, space="  ")
        temp_file = self.gamelist_path(system).with_suffix(".xml.tmp")
        tree = ET.ElementTree(root)
        tree.write(temp_file, encoding="utf-8", xml_declaration=True)
        if gamelist_file.exists():
            shutil.copy2(gamelist_file, old_backup_file)
        temp_file.replace(gamelist_file)
        logger.info("写入gamelist完成: system=%s, games=%d, 耗时=%.3fs", system, len(ordered), time.perf_counter() - start)


class ArkosService:
    def __init__(self, roms_root: Path):
        self.repo = ArkosRepository(roms_root)
        self.current_system = ""
        self.games: list[GameEntry] = []

    def set_root(self, root: Path) -> None:
        self.repo.set_root(root)
        self.current_system = ""
        self.games = []

    def list_systems(self) -> list[str]:
        return self.repo.list_systems()

    def select_system(self, system: str) -> list[GameEntry]:
        self.current_system = system
        self.games = self.repo.load_games(system)
        return self.games

    def get_filtered_sorted_games(self, query: str, sort_text: str) -> list[GameEntry]:
        data = self.games[:]
        norm_query = query.strip().lower()
        if norm_query:
            data = [g for g in data if norm_query in g.get("name", "").lower() or norm_query in g.path.lower()]
        reverse = "降序" in sort_text
        if sort_text.startswith("名称"):
            key_fn = lambda g: g.get("name", g.rom_name).lower()
        elif sort_text.startswith("发布日期"):
            key_fn = lambda g: g.get("releasedate", "")
        elif sort_text.startswith("最后游玩"):
            key_fn = lambda g: g.get("lastplayed", "")
        elif sort_text.startswith("游玩次数"):
            key_fn = lambda g: int(g.get("playcount", "0") or 0)
        elif sort_text.startswith("评分"):
            key_fn = lambda g: float(g.get("rating", "0") or 0)
        else:
            key_fn = lambda g: g.get("name", g.rom_name).lower()
        data.sort(key=key_fn, reverse=reverse)
        return data

    def validate_metadata(self, metadata: dict[str, str]) -> None:
        favorite = metadata.get("favorite", "").strip().lower()
        if favorite and favorite not in {"true", "false"}:
            raise ValueError("favorite 仅支持 true 或 false。")
        rating = metadata.get("rating", "").strip()
        if rating:
            try:
                r = float(rating)
            except ValueError as exc:
                raise ValueError("rating 必须是数字。") from exc
            if r < 0 or r > 1:
                raise ValueError("rating 必须在 0 到 1 之间。")
        rd = metadata.get("releasedate", "").strip()
        lp = metadata.get("lastplayed", "").strip()
        if rd and not self.valid_arkos_datetime(rd):
            raise ValueError("releasedate 格式应为 YYYYMMDDTHHMMSS。")
        if lp and not self.valid_arkos_datetime(lp):
            raise ValueError("lastplayed 格式应为 YYYYMMDDTHHMMSS。")

    @staticmethod
    def _norm_rel_path(path: str) -> str:
        clean = path.strip().replace("\\", "/")
        if clean.startswith("./"):
            clean = clean[2:]
        return clean

    def _load_current_system_games(self) -> list[GameEntry]:
        if not self.current_system:
            raise ValueError("请先选择系统目录。")
        games = self.repo.load_games(self.current_system)
        self.games = games
        return games

    def _find_game_by_path(self, games: list[GameEntry], rel_path: str) -> GameEntry | None:
        target = self._norm_rel_path(rel_path)
        for item in games:
            if self._norm_rel_path(item.path) == target:
                return item
        return None

    def save_metadata(self, game: GameEntry, metadata: dict[str, str]) -> bool:
        start = time.perf_counter()
        self.validate_metadata(metadata)
        games = self._load_current_system_games()
        target_game = self._find_game_by_path(games, game.path)
        if target_game is None:
            raise FileNotFoundError(f"未找到目标游戏: {game.path}")
        changed = False
        for key, value in metadata.items():
            clean_value = value.strip()
            if key in {"image", "video", "thumbnail"} and clean_value:
                clean_value = clean_value.replace("\\", "/")
            if target_game.get(key, "") != clean_value:
                target_game.set(key, clean_value)
                game.set(key, clean_value)
                changed = True
        if not changed:
            logger.info("元数据未变化，跳过保存: system=%s, game=%s", self.current_system, game.path)
            return False
        self.repo.save_games(self.current_system, games)
        self.games = games
        logger.info("元数据保存完成: system=%s, game=%s, 耗时=%.3fs", self.current_system, game.path, time.perf_counter() - start)
        return True

    def add_rom(self, src_file: Path) -> None:
        if not self.current_system:
            raise ValueError("请先选择系统目录。")
        self._load_current_system_games()
        dst_dir = self.repo.system_dir(self.current_system)
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / src_file.name
        if dst.exists():
            raise FileExistsError(f"目标已存在: {dst.name}")
        try:
            shutil.copy2(src_file, dst)
            entry = GameEntry(path=self.repo.normalize_rel_path(dst.name), fields={"name": dst.stem, "favorite": "false", "playcount": "0"})
            self.games.append(entry)
            self.persist_games()
            logger.info("ROM已添加: system=%s, rom=%s", self.current_system, entry.path)
        except Exception:
            if dst.exists():
                dst.unlink(missing_ok=True)
            raise

    def delete_game(self, game: GameEntry, full_delete: bool) -> None:
        games = self._load_current_system_games()
        target_game = self._find_game_by_path(games, game.path)
        if target_game is None:
            raise FileNotFoundError(f"未找到目标游戏: {game.path}")
        moved: list[tuple[Path, Path]] = []
        tmpdir = Path(tempfile.mkdtemp(prefix="arkos_delete_"))
        try:
            rom_abs = self.repo.rel_to_abs(self.current_system, target_game.path)
            if rom_abs.exists():
                temp_target = tmpdir / rom_abs.name
                shutil.move(str(rom_abs), str(temp_target))
                moved.append((rom_abs, temp_target))
            if full_delete:
                stem = Path(target_game.path).stem
                saves = self.repo.saves_dir(self.current_system)
                if saves.exists():
                    for sf in saves.iterdir():
                        if sf.is_file() and (sf.stem == stem or sf.name.startswith(f"{stem}.")):
                            t = tmpdir / f"saves_{sf.name}"
                            shutil.move(str(sf), str(t))
                            moved.append((sf, t))
                media_root = self.repo.system_dir(self.current_system) / "media"
                for folder in MEDIA_SUBDIRS:
                    p = media_root / folder
                    if not p.exists():
                        continue
                    for mf in p.iterdir():
                        if mf.is_file() and mf.stem == stem:
                            t = tmpdir / f"media_{folder}_{mf.name}"
                            shutil.move(str(mf), str(t))
                            moved.append((mf, t))
            target_path = self._norm_rel_path(target_game.path)
            games = [g for g in games if self._norm_rel_path(g.path) != target_path]
            self.repo.save_games(self.current_system, games)
            self.games = games
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            for original, temp_loc in reversed(moved):
                try:
                    original.parent.mkdir(parents=True, exist_ok=True)
                    if temp_loc.exists():
                        shutil.move(str(temp_loc), str(original))
                except Exception:
                    pass
            shutil.rmtree(tmpdir, ignore_errors=True)
            raise

    def rename_game(self, game: GameEntry, new_stem: str) -> None:
        games = self._load_current_system_games()
        target_game = self._find_game_by_path(games, game.path)
        if target_game is None:
            raise FileNotFoundError(f"未找到目标游戏: {game.path}")
        old_rel = target_game.path
        old_stem = Path(old_rel).stem
        old_ext = Path(old_rel).suffix
        new_name = f"{new_stem}{old_ext}"
        new_rel = self.repo.normalize_rel_path(new_name)
        old_abs = self.repo.rel_to_abs(self.current_system, old_rel)
        new_abs = self.repo.rel_to_abs(self.current_system, new_rel)
        if new_abs.exists():
            raise FileExistsError("目标 ROM 文件已存在。")
        renames: list[tuple[Path, Path]] = []
        try:
            old_abs.rename(new_abs)
            renames.append((old_abs, new_abs))
            saves_dir = self.repo.saves_dir(self.current_system)
            if saves_dir.exists():
                for sf in saves_dir.iterdir():
                    if sf.is_file() and (sf.stem == old_stem or sf.name.startswith(f"{old_stem}.")):
                        suffix = sf.name[len(old_stem) :]
                        target = saves_dir / f"{new_stem}{suffix}"
                        if target.exists():
                            raise FileExistsError(f"存档目标已存在: {target.name}")
                        sf.rename(target)
                        renames.append((sf, target))
            media_root = self.repo.system_dir(self.current_system) / "media"
            if media_root.exists():
                for folder in MEDIA_SUBDIRS:
                    d = media_root / folder
                    if not d.exists():
                        continue
                    for mf in d.iterdir():
                        if mf.is_file() and mf.stem == old_stem:
                            target = d / f"{new_stem}{mf.suffix}"
                            if target.exists():
                                raise FileExistsError(f"媒体目标已存在: {target.name}")
                            mf.rename(target)
                            renames.append((mf, target))
            target_game.path = new_rel
            game.path = new_rel
            if target_game.get("name", "") == old_stem:
                target_game.set("name", new_stem)
                game.set("name", new_stem)
            for media_key in ("image", "video", "thumbnail"):
                value = target_game.get(media_key, "").strip()
                if not value:
                    continue
                p = Path(value)
                if p.stem == old_stem:
                    new_value = value.replace(f"/{old_stem}.", f"/{new_stem}.")
                    target_game.set(media_key, new_value)
                    game.set(media_key, new_value)
            self.repo.save_games(self.current_system, games)
            self.games = games
        except Exception:
            for src, dst in reversed(renames):
                try:
                    if dst.exists():
                        dst.rename(src)
                except Exception:
                    pass
            target_game.path = old_rel
            game.path = old_rel
            raise

    def backup_saves(self) -> Path:
        saves_root = self.repo.roms_root / "saves"
        if not saves_root.exists():
            raise FileNotFoundError("未找到 saves 目录。")
        backup_dir = self.repo.roms_root / "backups" / "saves"
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_file = backup_dir / f"saves_{ts}.zip"
        try:
            with zipfile.ZipFile(zip_file, "w", zipfile.ZIP_DEFLATED) as zf:
                for path in saves_root.rglob("*"):
                    if path.is_file():
                        zf.write(path, arcname=str(path.relative_to(self.repo.roms_root)).replace("\\", "/"))
            return zip_file
        except Exception:
            zip_file.unlink(missing_ok=True)
            raise

    def persist_games(self, reload_after_save: bool = True) -> None:
        self.repo.save_games(self.current_system, self.games)
        if reload_after_save:
            self.games = self.repo.load_games(self.current_system)

    @staticmethod
    def valid_arkos_datetime(value: str) -> bool:
        if len(value) != 15 or value[8] != "T":
            return False
        try:
            datetime.strptime(value, "%Y%m%dT%H%M%S")
            return True
        except ValueError:
            return False
