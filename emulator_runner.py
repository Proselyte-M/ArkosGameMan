from __future__ import annotations

import logging
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Callable, Sequence

from arkos_core import GameEntry
from emulator_config import EmulatorConfigStore, EmulatorProfileConfig

logger = logging.getLogger(__name__)


class EmulatorRunner:
    def __init__(
        self,
        notify: Callable[[str, str, bool], None],
        tr: Callable[..., str],
        resolve_game_system: Callable[[GameEntry], str],
        rel_to_abs: Callable[[str, str], Path],
        current_system_getter: Callable[[], str],
        store: EmulatorConfigStore,
        get_configs: Callable[[], dict[str, EmulatorProfileConfig]],
    ) -> None:
        self._notify = notify
        self._t = tr
        self._resolve_game_system = resolve_game_system
        self._rel_to_abs = rel_to_abs
        self._current_system_getter = current_system_getter
        self._store = store
        self._get_configs = get_configs

    def run_game(self, game: GameEntry) -> None:
        system = self._resolve_game_system(game) or self._current_system_getter()
        if not system:
            self._notify(self._t("notify.tip"), self._t("notify.select_system_game_first"), True)
            return
        resolved = self._store.resolve_profile(system, self._get_configs())
        if resolved is None:
            self._notify(self._t("notify.tip"), self._t("notify.emulator_config_missing", system=system), True)
            return
        profile, conf = resolved
        rom_abs = self._rel_to_abs(system, game.path)
        if not rom_abs.exists():
            self._notify(self._t("notify.failed"), self._t("notify.file_not_found", path=rom_abs), True)
            return
        bundled_profiles = {"fc", "snes", "megadrive", "sega8", "segacd32x", "gb", "gba"}
        if not conf.use_external and profile.profile_id in bundled_profiles:
            self._run_builtin_libretro(
                profile.profile_id,
                rom_abs,
                conf.key_profile,
                conf.key_bindings,
                conf.bundled_core_dll,
                conf.video_scaling,
                conf.video_filter,
                conf.audio_latency_ms,
                conf.frame_sync,
            )
            return
        if not conf.use_external and profile.profile_id not in bundled_profiles:
            self._notify(
                self._t("notify.tip"),
                self._t("notify.bundled_profile_not_ready", profile=profile.title),
                True,
            )
            return
        emulator_path = conf.emulator_path.strip()
        launch_command = conf.launch_command.strip() or '{emulator} "{rom}"'
        if not emulator_path:
            self._notify(
                self._t("notify.tip"),
                self._t("notify.emulator_path_missing", profile=profile.title, system=system),
                True,
            )
            return
        self._run_external(profile.profile_id, system, rom_abs, emulator_path, launch_command, profile.recommended_cores)

    def _run_external(
        self,
        profile_id: str,
        system: str,
        rom_abs: Path,
        emulator_path: str,
        launch_command: str,
        recommended_cores: Sequence[str],
    ) -> None:
        try:
            cmd_text = launch_command.format(
                emulator=emulator_path,
                rom=str(rom_abs),
                system=system,
                profile=profile_id,
                core=recommended_cores[0] if recommended_cores else "",
            )
            cmd_args = shlex.split(cmd_text, posix=False)
            emulator_dir = Path(emulator_path).parent if Path(emulator_path).parent.exists() else None
            subprocess.Popen(cmd_args, cwd=emulator_dir, shell=False)
            logger.info("通过模拟器启动游戏: profile=%s, system=%s, rom=%s", profile_id, system, rom_abs)
        except (ValueError, OSError) as exc:
            logger.exception("模拟器启动失败: system=%s, rom=%s", system, rom_abs)
            self._notify(
                self._t("notify.failed"),
                self._t("notify.emulator_launch_failed", error=exc),
                True,
            )

    def _run_builtin_libretro(
        self,
        profile_id: str,
        rom_abs: Path,
        key_profile: str,
        key_bindings: str,
        core_override_dll: str,
        video_scaling: str,
        video_filter: str,
        audio_latency_ms: int,
        frame_sync: str,
    ) -> None:
        script_candidates = [
            Path(__file__).resolve().parent / "builtin_fc_emulator.py",
            Path(sys.executable).resolve().parent / "builtin_fc_emulator.py",
        ]
        script_path = next((path for path in script_candidates if path.exists()), None)
        if script_path is None:
            self._notify(self._t("notify.failed"), self._t("notify.builtin_fc_missing"), True)
            return
        core_path = self._resolve_bundled_core(profile_id, script_path.parent, core_override_dll)
        if core_path is None:
            self._notify(
                self._t("notify.failed"),
                self._t("notify.builtin_core_missing", profile=profile_id.upper()),
                True,
            )
            return
        launcher = self._resolve_python_launcher()
        if launcher is None:
            self._notify(self._t("notify.failed"), self._t("notify.python_runtime_missing"), True)
            return
        try:
            prefix = [launcher] if isinstance(launcher, str) else launcher
            cmd = [
                *prefix,
                str(script_path),
                str(rom_abs),
                "--profile",
                profile_id,
                "--key-profile",
                key_profile,
                "--key-bindings",
                key_bindings,
                "--core-path",
                str(core_path),
                "--video-scaling",
                video_scaling,
                "--video-filter",
                video_filter,
                "--audio-latency-ms",
                str(max(20, min(300, int(audio_latency_ms)))),
                "--frame-sync",
                frame_sync,
            ]
            subprocess.Popen(cmd, cwd=script_path.parent)
            logger.info(
                "启动内置Libretro模拟器: profile=%s, rom=%s, script=%s, core=%s",
                profile_id,
                rom_abs,
                script_path,
                core_path,
            )
        except (ValueError, OSError) as exc:
            logger.exception("启动内置Libretro模拟器失败: profile=%s, rom=%s", profile_id, rom_abs)
            self._notify(
                self._t("notify.failed"),
                self._t("notify.emulator_launch_failed", error=exc),
                True,
            )

    @staticmethod
    def _resolve_bundled_core(profile_id: str, base_dir: Path, core_override_dll: str = "") -> Path | None:
        core_map = {
            "fc": "quicknes_libretro.dll",
            "snes": "snes9x_libretro.dll",
            "megadrive": "picodrive_libretro.dll",
            "sega8": "picodrive_libretro.dll",
            "segacd32x": "picodrive_libretro.dll",
            "gb": "mgba_libretro.dll",
            "gba": "mgba_libretro.dll",
        }
        override = core_override_dll.strip()
        if profile_id in {"gb", "gba"} and override.lower() == "vbam_libretro.dll":
            stable_core = base_dir / "core" / "mgba_libretro.dll"
            if stable_core.exists():
                return stable_core
        if override:
            override_path = base_dir / "core" / override
            if override_path.exists():
                return override_path
        dll = core_map.get(profile_id)
        if dll is None:
            return None
        core_path = base_dir / "core" / dll
        return core_path if core_path.exists() else None

    @staticmethod
    def _resolve_python_launcher() -> str | list[str] | None:
        if not getattr(sys, "frozen", False):
            return sys.executable
        candidates: list[str | list[str]] = [
            ["py", "-3"],
            "python",
            "python3",
            "pythonw",
        ]
        for candidate in candidates:
            try:
                probe = [*candidate, "--version"] if isinstance(candidate, list) else [candidate, "--version"]
                result = subprocess.run(probe, capture_output=True, text=True, shell=False, check=False)
                if result.returncode == 0:
                    return candidate
            except OSError:
                continue
        return None
