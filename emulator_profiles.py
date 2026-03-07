from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EmulatorProfile:
    profile_id: str
    title: str
    category: str
    systems: tuple[str, ...]
    recommended_cores: tuple[str, ...]


EMULATOR_PROFILES: tuple[EmulatorProfile, ...] = (
    EmulatorProfile("fc", "FC / NES / Famicom", "8位机 / 怀旧", ("nes", "famicom", "fds"), ("fceumm", "nestopia")),
    EmulatorProfile("snes", "SNES / SFC", "8位机 / 怀旧", ("snes", "sfc"), ("snes9x", "bsnes")),
    EmulatorProfile("gb", "GB / GBC", "8位机 / 怀旧", ("gb", "gbc"), ("gambatte",)),
    EmulatorProfile("gba", "GBA", "8位机 / 怀旧", ("gba",), ("mgba", "vba-next")),
    EmulatorProfile(
        "sega8",
        "GameGear / MasterSystem",
        "8位机 / 怀旧",
        ("gamegear", "mastersystem"),
        ("genesis_plus_gx",),
    ),
    EmulatorProfile(
        "megadrive",
        "MegaDrive / Genesis",
        "8位机 / 怀旧",
        ("megadrive", "genesis"),
        ("genesis_plus_gx",),
    ),
    EmulatorProfile("atari2600", "Atari 2600", "8位机 / 怀旧", ("atari2600",), ("stella",)),
    EmulatorProfile("atari52xx", "Atari 5200 / 7800", "8位机 / 怀旧", ("atari5200", "atari7800"), ("mame2003",)),
    EmulatorProfile("vice", "C64 / C128", "8位机 / 怀旧", ("c64", "c128"), ("vice",)),
    EmulatorProfile("msx", "MSX / MSX2", "8位机 / 怀旧", ("msx", "msx2"), ("bluemsx",)),
    EmulatorProfile("coleco", "Coleco", "8位机 / 怀旧", ("coleco",), ("bluemsx",)),
    EmulatorProfile(
        "pce",
        "PCE / TurboGrafx",
        "8位机 / 怀旧",
        ("pcengine", "turbografx"),
        ("beetle_pce_fast",),
    ),
    EmulatorProfile("arcade", "Arcade", "街机", ("arcade",), ("fbneo", "mame2003", "mame")),
    EmulatorProfile("cps", "CPS1 / CPS2 / CPS3", "街机", ("cps1", "cps2", "cps3"), ("fbneo",)),
    EmulatorProfile("neogeo", "NeoGeo / MV", "街机", ("neogeo", "mv"), ("fbneo",)),
    EmulatorProfile("neocd", "NeoCD", "街机", ("neocd", "neogeocd"), ("fbneo",)),
    EmulatorProfile("mame", "MAME Family", "街机", ("mame", "mame2003", "hbmame"), ("mame2003", "mame")),
    EmulatorProfile("daphne", "Daphne", "街机", ("daphne",), ("daphne",)),
    EmulatorProfile("psx", "PSX", "32位主机", ("psx",), ("beetle_psx", "pcsx_rearmed")),
    EmulatorProfile("saturn", "Saturn", "32位主机", ("saturn",), ("yabause", "kronos")),
    EmulatorProfile("n64", "N64", "32位主机", ("n64",), ("mupen64plus_next",)),
    EmulatorProfile("dreamcast", "Dreamcast", "32位主机", ("dreamcast",), ("flycast",)),
    EmulatorProfile("naomi", "Naomi / Atomiswave", "32位主机", ("naomi", "atomiswave"), ("flycast",)),
    EmulatorProfile("psp", "PSP", "32位主机", ("psp",), ("ppsspp",)),
    EmulatorProfile("lynx", "Atari Lynx", "掌机", ("atarilynx",), ("beetle_lynx",)),
    EmulatorProfile("ngpc", "NGP / NGPC", "掌机", ("ngp", "ngpc"), ("beetle_neopop",)),
    EmulatorProfile(
        "wswan",
        "WonderSwan / Color",
        "掌机",
        ("wonderswan", "wonderswancolor"),
        ("beetle_wswan",),
    ),
    EmulatorProfile("nds", "NDS", "掌机", ("nds",), ("melonds", "desmume")),
    EmulatorProfile("3do", "3DO", "特殊主机", ("3do",), ("opera",)),
    EmulatorProfile("pcfx", "PC-FX", "特殊主机", ("pc-fx",), ("beetle_pcfx",)),
    EmulatorProfile("segacd32x", "SegaCD / Sega32X", "特殊主机", ("segacd", "sega32x"), ("genesis_plus_gx",)),
    EmulatorProfile("virtualboy", "Virtual Boy", "特殊主机", ("virtualboy",), ("beetle_vb",)),
    EmulatorProfile("pokemonmini", "Pokemon Mini", "特殊主机", ("pokemonmini",), ("pokemini",)),
)

PROFILES_BY_ID = {profile.profile_id: profile for profile in EMULATOR_PROFILES}


def normalize_system_name(name: str) -> str:
    return name.strip().lower().replace(" ", "").replace("_", "").replace("-", "")


def profile_for_system(system_name: str) -> EmulatorProfile | None:
    target = normalize_system_name(system_name)
    for profile in EMULATOR_PROFILES:
        for system in profile.systems:
            if normalize_system_name(system) == target:
                return profile
    return None
