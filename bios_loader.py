from __future__ import annotations

from pathlib import Path

ARCADE_PROFILES = {"arcade", "cps", "neogeo", "neocd", "mame"}

PROFILE_BIOS_MAP: dict[str, tuple[str, ...]] = {
    "arcade": ("neogeo.zip", "pgm.zip", "cps3.zip", "qsound.zip"),
    "cps": ("qsound.zip", "cps3.zip"),
    "neogeo": ("neogeo.zip",),
    "neocd": ("neogeo.zip",),
    "mame": ("neogeo.zip", "pgm.zip"),
}

SYSTEM_BIOS_MAP: dict[str, tuple[str, ...]] = {
    "cps1": ("qsound.zip",),
    "cps2": ("qsound.zip",),
    "cps3": ("cps3.zip",),
    "neogeo": ("neogeo.zip",),
    "mv": ("neogeo.zip",),
    "neocd": ("neogeo.zip",),
    "neogeocd": ("neogeo.zip",),
    "pgm": ("pgm.zip",),
    "arcade": ("neogeo.zip", "pgm.zip"),
}


def should_enable_auto_bios(profile_id: str) -> bool:
    return profile_id.strip().lower() in ARCADE_PROFILES


def detect_bios_dir_from_rom(rom_path: Path) -> Path | None:
    candidate = rom_path.parent / "bios"
    if candidate.is_dir():
        return candidate
    for parent in rom_path.parents:
        bios_dir = parent / "bios"
        if bios_dir.is_dir():
            return bios_dir
    return None


def scan_bios_files(bios_dir: Path) -> dict[str, Path]:
    if not bios_dir.is_dir():
        return {}
    collected: dict[str, Path] = {}
    for path in bios_dir.rglob("*.zip"):
        key = path.name.lower()
        if key not in collected:
            collected[key] = path
    return collected


def expected_bios_names(profile_id: str, system: str) -> tuple[str, ...]:
    names: list[str] = []
    profile_key = profile_id.strip().lower()
    system_key = system.strip().lower()
    for item in PROFILE_BIOS_MAP.get(profile_key, ()):
        if item not in names:
            names.append(item)
    for item in SYSTEM_BIOS_MAP.get(system_key, ()):
        if item not in names:
            names.append(item)
    return tuple(names)


def match_bios_files(profile_id: str, system: str, bios_dir: Path) -> tuple[list[Path], list[str]]:
    bios_index = scan_bios_files(bios_dir)
    expected = expected_bios_names(profile_id, system)
    matched: list[Path] = []
    missing: list[str] = []
    for name in expected:
        path = bios_index.get(name.lower())
        if path is None:
            missing.append(name)
        else:
            matched.append(path)
    return matched, missing
