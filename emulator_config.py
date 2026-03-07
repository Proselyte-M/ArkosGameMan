from __future__ import annotations

import configparser
from dataclasses import dataclass, field
from pathlib import Path

from emulator_profiles import EMULATOR_PROFILES, EmulatorProfile, profile_for_system


@dataclass
class EmulatorProfileConfig:
    folders: list[str] = field(default_factory=list)
    emulator_path: str = ""
    launch_command: str = '{emulator} "{rom}"'
    install_script: str = ""
    use_bundled: bool = False
    bundled_emulator_path: str = ""
    key_profile: str = "default"
    display_profile: str = "pixel"

    def normalized_folders(self) -> set[str]:
        return {item.strip().lower() for item in self.folders if item.strip()}


class EmulatorConfigStore:
    def __init__(self, settings_file: Path):
        self.settings_file = settings_file

    @staticmethod
    def default_config(profile: EmulatorProfile) -> EmulatorProfileConfig:
        return EmulatorProfileConfig(folders=list(profile.systems))

    def load(self) -> dict[str, EmulatorProfileConfig]:
        parser = configparser.ConfigParser()
        if self.settings_file.exists():
            parser.read(self.settings_file, encoding="utf-8")
        state: dict[str, EmulatorProfileConfig] = {
            profile.profile_id: self.default_config(profile) for profile in EMULATOR_PROFILES
        }
        for profile in EMULATOR_PROFILES:
            section = f"emulator_profile:{profile.profile_id}"
            if section not in parser:
                continue
            cfg = state[profile.profile_id]
            folders_raw = parser.get(section, "folders", fallback="")
            folders = [item.strip() for item in folders_raw.replace("\n", ",").split(",") if item.strip()]
            cfg.folders = folders or list(profile.systems)
            cfg.emulator_path = parser.get(section, "emulator_path", fallback=cfg.emulator_path).strip()
            cfg.launch_command = parser.get(section, "launch_command", fallback=cfg.launch_command).strip() or cfg.launch_command
            cfg.install_script = parser.get(section, "install_script", fallback=cfg.install_script).strip()
            cfg.use_bundled = parser.getboolean(section, "use_bundled", fallback=False)
            cfg.bundled_emulator_path = parser.get(section, "bundled_emulator_path", fallback=cfg.bundled_emulator_path).strip()
            cfg.key_profile = parser.get(section, "key_profile", fallback=cfg.key_profile).strip() or "default"
            cfg.display_profile = parser.get(section, "display_profile", fallback=cfg.display_profile).strip() or "pixel"
        self._migrate_removed_fds_profile(parser, state)
        self._migrate_legacy_system_bindings(parser, state)
        return state

    @staticmethod
    def _migrate_removed_fds_profile(
        parser: configparser.ConfigParser,
        state: dict[str, EmulatorProfileConfig],
    ) -> None:
        section = "emulator_profile:fds"
        if section not in parser or "fc" not in state:
            return
        fds_cfg = EmulatorProfileConfig()
        fds_cfg.folders = [item.strip() for item in parser.get(section, "folders", fallback="").replace("\n", ",").split(",") if item.strip()]
        fds_cfg.emulator_path = parser.get(section, "emulator_path", fallback="").strip()
        fds_cfg.launch_command = parser.get(section, "launch_command", fallback='').strip()
        fds_cfg.install_script = parser.get(section, "install_script", fallback="").strip()
        fds_cfg.use_bundled = parser.getboolean(section, "use_bundled", fallback=False)
        fds_cfg.bundled_emulator_path = parser.get(section, "bundled_emulator_path", fallback="").strip()
        fds_cfg.key_profile = parser.get(section, "key_profile", fallback="").strip()
        fds_cfg.display_profile = parser.get(section, "display_profile", fallback="").strip()
        fc_cfg = state["fc"]
        for folder in [*fds_cfg.folders, "fds"]:
            if folder and folder.strip().lower() not in fc_cfg.normalized_folders():
                fc_cfg.folders.append(folder)
        if fds_cfg.emulator_path and not fc_cfg.emulator_path:
            fc_cfg.emulator_path = fds_cfg.emulator_path
        if fds_cfg.launch_command and fc_cfg.launch_command == '{emulator} "{rom}"':
            fc_cfg.launch_command = fds_cfg.launch_command
        if fds_cfg.install_script and not fc_cfg.install_script:
            fc_cfg.install_script = fds_cfg.install_script
        if fds_cfg.use_bundled:
            fc_cfg.use_bundled = True
        if fds_cfg.bundled_emulator_path and not fc_cfg.bundled_emulator_path:
            fc_cfg.bundled_emulator_path = fds_cfg.bundled_emulator_path
        if fds_cfg.key_profile and fc_cfg.key_profile == "default":
            fc_cfg.key_profile = fds_cfg.key_profile
        if fds_cfg.display_profile and fc_cfg.display_profile == "pixel":
            fc_cfg.display_profile = fds_cfg.display_profile

    @staticmethod
    def _migrate_legacy_system_bindings(
        parser: configparser.ConfigParser,
        state: dict[str, EmulatorProfileConfig],
    ) -> None:
        for section in parser.sections():
            if not section.startswith("emulator:"):
                continue
            system = section.split(":", 1)[1].strip().lower()
            if not system:
                continue
            profile = profile_for_system(system)
            if profile is None:
                continue
            cfg = state[profile.profile_id]
            path = parser.get(section, "path", fallback="").strip()
            cmd = parser.get(section, "command", fallback="").strip()
            if path and not cfg.emulator_path:
                cfg.emulator_path = path
            if cmd and cfg.launch_command == '{emulator} "{rom}"':
                cfg.launch_command = cmd
            if system not in cfg.normalized_folders():
                cfg.folders.append(system)

    def save(self, state: dict[str, EmulatorProfileConfig]) -> None:
        parser = configparser.ConfigParser()
        if self.settings_file.exists():
            parser.read(self.settings_file, encoding="utf-8")
        for section in list(parser.sections()):
            if section.startswith("emulator_profile:"):
                parser.remove_section(section)
        for profile in EMULATOR_PROFILES:
            cfg = state.get(profile.profile_id, self.default_config(profile))
            section = f"emulator_profile:{profile.profile_id}"
            parser[section] = {
                "folders": ",".join(cfg.folders),
                "emulator_path": cfg.emulator_path,
                "launch_command": cfg.launch_command,
                "install_script": cfg.install_script,
                "use_bundled": "true" if cfg.use_bundled else "false",
                "bundled_emulator_path": cfg.bundled_emulator_path,
                "key_profile": cfg.key_profile,
                "display_profile": cfg.display_profile,
            }
        self.settings_file.parent.mkdir(parents=True, exist_ok=True)
        with self.settings_file.open("w", encoding="utf-8") as handle:
            parser.write(handle)

    @staticmethod
    def resolve_profile(
        system: str,
        state: dict[str, EmulatorProfileConfig],
    ) -> tuple[EmulatorProfile, EmulatorProfileConfig] | None:
        norm_system = system.strip().lower()
        for profile in EMULATOR_PROFILES:
            cfg = state.get(profile.profile_id)
            if cfg is None:
                continue
            if norm_system in cfg.normalized_folders():
                return profile, cfg
        matched_profile = profile_for_system(norm_system)
        if matched_profile is None:
            return None
        cfg = state.get(matched_profile.profile_id)
        if cfg is None:
            return None
        return matched_profile, cfg
