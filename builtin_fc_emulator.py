from __future__ import annotations

import argparse
import ctypes
import os
import shutil
import struct
import sys
import tempfile
import zipfile
from collections import deque
from pathlib import Path
from typing import Any

from PySide6.QtCore import QIODevice, QRect, Qt, QTimer
from PySide6.QtGui import QImage, QKeyEvent, QPainter
from PySide6.QtMultimedia import QAudioFormat, QAudioSink
from PySide6.QtWidgets import QApplication, QWidget
from bios_loader import detect_bios_dir_from_rom, match_bios_files

RETRO_DEVICE_JOYPAD = 1
RETRO_DEVICE_ID_JOYPAD_B = 0
RETRO_DEVICE_ID_JOYPAD_Y = 1
RETRO_DEVICE_ID_JOYPAD_SELECT = 2
RETRO_DEVICE_ID_JOYPAD_START = 3
RETRO_DEVICE_ID_JOYPAD_UP = 4
RETRO_DEVICE_ID_JOYPAD_DOWN = 5
RETRO_DEVICE_ID_JOYPAD_LEFT = 6
RETRO_DEVICE_ID_JOYPAD_RIGHT = 7
RETRO_DEVICE_ID_JOYPAD_A = 8
RETRO_DEVICE_ID_JOYPAD_X = 9
RETRO_DEVICE_ID_JOYPAD_L = 10
RETRO_DEVICE_ID_JOYPAD_R = 11

JOYPAD_NAME_TO_ID = {
    "up": RETRO_DEVICE_ID_JOYPAD_UP,
    "down": RETRO_DEVICE_ID_JOYPAD_DOWN,
    "left": RETRO_DEVICE_ID_JOYPAD_LEFT,
    "right": RETRO_DEVICE_ID_JOYPAD_RIGHT,
    "a": RETRO_DEVICE_ID_JOYPAD_A,
    "b": RETRO_DEVICE_ID_JOYPAD_B,
    "x": RETRO_DEVICE_ID_JOYPAD_X,
    "y": RETRO_DEVICE_ID_JOYPAD_Y,
    "start": RETRO_DEVICE_ID_JOYPAD_START,
    "select": RETRO_DEVICE_ID_JOYPAD_SELECT,
    "l": RETRO_DEVICE_ID_JOYPAD_L,
    "r": RETRO_DEVICE_ID_JOYPAD_R,
}

KEY_PROFILE_MAP: dict[str, dict[str, str]] = {
    "default": {
        "up": "Up",
        "down": "Down",
        "left": "Left",
        "right": "Right",
        "a": "X",
        "b": "Z",
        "x": "S",
        "y": "A",
        "start": "Return",
        "select": "Shift",
        "l": "Q",
        "r": "W",
    },
    "arcade-stick": {
        "up": "Up",
        "down": "Down",
        "left": "Left",
        "right": "Right",
        "a": "J",
        "b": "K",
        "x": "U",
        "y": "I",
        "start": "Return",
        "select": "Space",
        "l": "H",
        "r": "L",
    },
    "xinput-pad": {
        "up": "W",
        "down": "S",
        "left": "A",
        "right": "D",
        "a": "J",
        "b": "K",
        "x": "U",
        "y": "I",
        "start": "Return",
        "select": "Backspace",
        "l": "Q",
        "r": "E",
    },
}


def _qt_key_from_name(name: str) -> int | None:
    value = name.strip()
    if not value:
        return None
    attr = value if value.startswith("Key_") else f"Key_{value}"
    key = getattr(Qt.Key, attr, None)
    return int(key) if key is not None else None


def build_input_mapping(key_profile: str, key_bindings: str) -> dict[int, int]:
    profile_map = dict(KEY_PROFILE_MAP.get(key_profile, KEY_PROFILE_MAP["default"]))
    for segment in key_bindings.split(","):
        chunk = segment.strip()
        if not chunk or "=" not in chunk:
            continue
        joy_name, key_name = chunk.split("=", 1)
        normalized = joy_name.strip().lower()
        if normalized in JOYPAD_NAME_TO_ID:
            profile_map[normalized] = key_name.strip()
    mapping: dict[int, int] = {}
    for joy_name, joy_id in JOYPAD_NAME_TO_ID.items():
        qt_key = _qt_key_from_name(profile_map.get(joy_name, ""))
        if qt_key is not None:
            mapping[joy_id] = qt_key
    return mapping

RETRO_PIXEL_FORMAT_0RGB1555 = 0
RETRO_PIXEL_FORMAT_XRGB8888 = 1
RETRO_PIXEL_FORMAT_RGB565 = 2
RETRO_ENVIRONMENT_GET_SYSTEM_DIRECTORY = 9
RETRO_ENVIRONMENT_SET_PIXEL_FORMAT = 10
RETRO_ENVIRONMENT_GET_SAVE_DIRECTORY = 31

ENV_CB = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_uint, ctypes.c_void_p)
VIDEO_CB = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_size_t)
AUDIO_CB = ctypes.CFUNCTYPE(None, ctypes.c_int16, ctypes.c_int16)
AUDIO_BATCH_CB = ctypes.CFUNCTYPE(ctypes.c_size_t, ctypes.POINTER(ctypes.c_int16), ctypes.c_size_t)
INPUT_POLL_CB = ctypes.CFUNCTYPE(None)
INPUT_STATE_CB = ctypes.CFUNCTYPE(ctypes.c_int16, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint)


class RetroGameInfo(ctypes.Structure):
    _fields_ = [
        ("path", ctypes.c_char_p),
        ("data", ctypes.c_void_p),
        ("size", ctypes.c_size_t),
        ("meta", ctypes.c_char_p),
    ]


class RetroGameGeometry(ctypes.Structure):
    _fields_ = [
        ("base_width", ctypes.c_uint),
        ("base_height", ctypes.c_uint),
        ("max_width", ctypes.c_uint),
        ("max_height", ctypes.c_uint),
        ("aspect_ratio", ctypes.c_float),
    ]


class RetroSystemTiming(ctypes.Structure):
    _fields_ = [
        ("fps", ctypes.c_double),
        ("sample_rate", ctypes.c_double),
    ]


class RetroSystemAvInfo(ctypes.Structure):
    _fields_ = [
        ("geometry", RetroGameGeometry),
        ("timing", RetroSystemTiming),
    ]


class RetroSystemInfo(ctypes.Structure):
    _fields_ = [
        ("library_name", ctypes.c_char_p),
        ("library_version", ctypes.c_char_p),
        ("valid_extensions", ctypes.c_char_p),
        ("need_fullpath", ctypes.c_bool),
        ("block_extract", ctypes.c_bool),
    ]


class AudioQueueDevice(QIODevice):
    def __init__(self):
        super().__init__()
        self._queue = deque()
        self._queue_size = 0

    def start(self) -> None:
        self.open(QIODevice.OpenModeFlag.ReadOnly)

    def push(self, data: bytes) -> None:
        if not data:
            return
        self._queue.append(data)
        self._queue_size += len(data)
        if self._queue_size > 4 * 1024 * 1024:
            while self._queue and self._queue_size > 2 * 1024 * 1024:
                removed = self._queue.popleft()
                self._queue_size -= len(removed)

    def readData(self, maxlen: int) -> bytes:
        if maxlen <= 0 or not self._queue:
            return b""
        out = bytearray()
        while self._queue and len(out) < maxlen:
            head = self._queue[0]
            need = maxlen - len(out)
            if len(head) <= need:
                out.extend(self._queue.popleft())
                self._queue_size -= len(head)
            else:
                out.extend(head[:need])
                self._queue[0] = head[need:]
                self._queue_size -= need
        return bytes(out)

    def writeData(self, _data: bytes | bytearray | memoryview, _max_size: int) -> int:
        return 0

    def bytesAvailable(self) -> int:
        return self._queue_size


class LibretroCore:
    def __init__(
        self,
        core_path: Path,
        input_mapping: dict[int, int],
        audio_latency_ms: int,
        system_dir: Path | None = None,
        save_dir: Path | None = None,
    ):
        self.dll = ctypes.CDLL(str(core_path))
        self.pixel_format = RETRO_PIXEL_FORMAT_XRGB8888
        self.keys: set[int] = set()
        self.latest_image = QImage()
        self.audio_device = AudioQueueDevice()
        self.audio_sink: QAudioSink | None = None
        self._content_buffer: ctypes.Array[ctypes.c_char] | None = None
        self._sample_cache = bytearray()
        self.input_mapping = input_mapping
        self.audio_latency_ms = max(20, min(300, int(audio_latency_ms)))
        self._env_cb = ENV_CB(self._on_environment)
        self._video_cb = VIDEO_CB(self._on_video)
        self._audio_cb = AUDIO_CB(self._on_audio_sample)
        self._audio_batch_cb = AUDIO_BATCH_CB(self._on_audio_batch)
        self._input_poll_cb = INPUT_POLL_CB(self._on_input_poll)
        self._input_state_cb = INPUT_STATE_CB(self._on_input_state)
        self.system_dir = system_dir
        self.save_dir = save_dir
        self._system_dir_ptr: ctypes.c_char_p | None = None
        self._save_dir_ptr: ctypes.c_char_p | None = None
        if self.system_dir is not None:
            self.system_dir.mkdir(parents=True, exist_ok=True)
            self._system_dir_ptr = ctypes.c_char_p(os.fsencode(str(self.system_dir)))
        if self.save_dir is not None:
            self.save_dir.mkdir(parents=True, exist_ok=True)
            self._save_dir_ptr = ctypes.c_char_p(os.fsencode(str(self.save_dir)))
        self._bind_api()

    def _bind_api(self) -> None:
        self.retro_init = self.dll.retro_init
        self.retro_deinit = self.dll.retro_deinit
        self.retro_load_game = self.dll.retro_load_game
        self.retro_unload_game = self.dll.retro_unload_game
        self.retro_run = self.dll.retro_run
        self.retro_set_environment = self.dll.retro_set_environment
        self.retro_set_video_refresh = self.dll.retro_set_video_refresh
        self.retro_set_audio_sample = self.dll.retro_set_audio_sample
        self.retro_set_audio_sample_batch = self.dll.retro_set_audio_sample_batch
        self.retro_set_input_poll = self.dll.retro_set_input_poll
        self.retro_set_input_state = self.dll.retro_set_input_state
        self.retro_get_system_av_info = self.dll.retro_get_system_av_info
        self.retro_get_system_info = self.dll.retro_get_system_info
        self.retro_load_game.argtypes = [ctypes.POINTER(RetroGameInfo)]
        self.retro_load_game.restype = ctypes.c_bool
        self.retro_set_environment.argtypes = [ENV_CB]
        self.retro_set_video_refresh.argtypes = [VIDEO_CB]
        self.retro_set_audio_sample.argtypes = [AUDIO_CB]
        self.retro_set_audio_sample_batch.argtypes = [AUDIO_BATCH_CB]
        self.retro_set_input_poll.argtypes = [INPUT_POLL_CB]
        self.retro_set_input_state.argtypes = [INPUT_STATE_CB]
        self.retro_get_system_av_info.argtypes = [ctypes.POINTER(RetroSystemAvInfo)]
        self.retro_get_system_info.argtypes = [ctypes.POINTER(RetroSystemInfo)]

    def setup(self) -> float:
        self.retro_set_environment(self._env_cb)
        self.retro_set_video_refresh(self._video_cb)
        self.retro_set_audio_sample(self._audio_cb)
        self.retro_set_audio_sample_batch(self._audio_batch_cb)
        self.retro_set_input_poll(self._input_poll_cb)
        self.retro_set_input_state(self._input_state_cb)
        self.retro_init()
        av = RetroSystemAvInfo()
        self.retro_get_system_av_info(ctypes.byref(av))
        fps = float(av.timing.fps) if av.timing.fps > 1 else 60.0
        sample_rate = int(av.timing.sample_rate) if av.timing.sample_rate > 1000 else 44100
        audio_format = QAudioFormat()
        audio_format.setSampleRate(sample_rate)
        audio_format.setChannelCount(2)
        audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        self.audio_sink = QAudioSink(audio_format)
        self.audio_sink.setBufferSize(int(sample_rate * 2 * 2 * self.audio_latency_ms / 1000))
        self.audio_sink.setVolume(0.8)
        self.audio_device.start()
        self.audio_sink.start(self.audio_device)
        return fps

    def load_game(self, rom_path: Path) -> None:
        system_info = RetroSystemInfo()
        self.retro_get_system_info(ctypes.byref(system_info))
        fs_path_bytes = os.fsencode(str(rom_path))
        if system_info.need_fullpath:
            info = RetroGameInfo(path=ctypes.c_char_p(fs_path_bytes), data=None, size=0, meta=None)
        else:
            raw = rom_path.read_bytes()
            self._content_buffer = ctypes.create_string_buffer(raw)
            info = RetroGameInfo(
                path=ctypes.c_char_p(fs_path_bytes),
                data=ctypes.cast(self._content_buffer, ctypes.c_void_p),
                size=len(raw),
                meta=None,
            )
        if not self.retro_load_game(ctypes.byref(info)):
            raise RuntimeError("core 加载 ROM 失败")

    def run_frame(self) -> None:
        self.retro_run()

    def shutdown(self) -> None:
        try:
            self.retro_unload_game()
        except Exception:
            pass
        try:
            self.retro_deinit()
        except Exception:
            pass
        self._content_buffer = None
        if self.audio_sink is not None:
            self.audio_sink.stop()

    def _on_environment(self, cmd: int, data: int) -> bool:
        if cmd == RETRO_ENVIRONMENT_GET_SYSTEM_DIRECTORY and data and self._system_dir_ptr is not None:
            target = ctypes.cast(data, ctypes.POINTER(ctypes.c_char_p))
            target[0] = self._system_dir_ptr
            return True
        if cmd == RETRO_ENVIRONMENT_GET_SAVE_DIRECTORY and data and self._save_dir_ptr is not None:
            target = ctypes.cast(data, ctypes.POINTER(ctypes.c_char_p))
            target[0] = self._save_dir_ptr
            return True
        if cmd == RETRO_ENVIRONMENT_SET_PIXEL_FORMAT and data:
            self.pixel_format = ctypes.cast(data, ctypes.POINTER(ctypes.c_int)).contents.value
            return True
        return False

    def _on_video(self, data: int, width: int, height: int, pitch: int) -> None:
        if not data or width == 0 or height == 0:
            return
        raw = ctypes.string_at(data, pitch * height)
        self.latest_image = self._convert_frame(raw, width, height, pitch)

    def _convert_frame(self, raw: bytes, width: int, height: int, pitch: int) -> QImage:
        if self.pixel_format == RETRO_PIXEL_FORMAT_XRGB8888:
            return QImage(raw, width, height, pitch, QImage.Format.Format_RGB32).copy()
        if self.pixel_format == RETRO_PIXEL_FORMAT_RGB565:
            return QImage(raw, width, height, pitch, QImage.Format.Format_RGB16).copy()
        format_rgb555 = getattr(QImage.Format, "Format_RGB555", None)
        if self.pixel_format == RETRO_PIXEL_FORMAT_0RGB1555 and format_rgb555 is not None:
            return QImage(raw, width, height, pitch, format_rgb555).copy()
        image = QImage(width, height, QImage.Format.Format_RGB32)
        for y in range(height):
            base = y * pitch
            for x in range(width):
                pos = base + x * 2
                value = raw[pos] | (raw[pos + 1] << 8)
                r = ((value >> 10) & 0x1F) * 255 // 31
                g = ((value >> 5) & 0x1F) * 255 // 31
                b = (value & 0x1F) * 255 // 31
                image.setPixel(x, y, (255 << 24) | (r << 16) | (g << 8) | b)
        return image

    def _on_audio_sample(self, left: int, right: int) -> None:
        self._sample_cache.extend(struct.pack("<hh", left, right))
        if len(self._sample_cache) >= 4096:
            self.audio_device.push(bytes(self._sample_cache))
            self._sample_cache.clear()

    def _on_audio_batch(self, data: Any, frames: int) -> int:
        if not data or frames <= 0:
            return frames
        if self._sample_cache:
            self.audio_device.push(bytes(self._sample_cache))
            self._sample_cache.clear()
        payload = ctypes.string_at(data, int(frames) * 4)
        self.audio_device.push(payload)
        return frames

    def _on_input_poll(self) -> None:
        return

    def _on_input_state(self, port: int, device: int, _index: int, id_: int) -> int:
        if port != 0 or device != RETRO_DEVICE_JOYPAD:
            return 0
        key = self.input_mapping.get(id_)
        return 1 if key in self.keys else 0


class LibretroWindow(QWidget):
    def __init__(self, core: LibretroCore, title: str, fps: float, video_scaling: str, video_filter: str, frame_sync: str):
        super().__init__()
        self.core = core
        self.video_scaling = video_scaling
        self.video_filter = video_filter
        self.setWindowTitle(title)
        self.resize(1024, 720)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer if frame_sync == "precise" else Qt.TimerType.CoarseTimer)
        self.timer.timeout.connect(self._tick)
        self.timer.start(max(1, int(1000 / fps)))

    def _tick(self) -> None:
        self.core.run_frame()
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        if self.core.latest_image.isNull():
            painter.fillRect(self.rect(), Qt.GlobalColor.black)
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self.video_filter == "smooth")
        target = self.rect()
        if self.video_scaling == "integer":
            image = self.core.latest_image
            if image.width() > 0 and image.height() > 0:
                scale = max(1, min(target.width() // image.width(), target.height() // image.height()))
                draw_w = image.width() * scale
                draw_h = image.height() * scale
                x = target.x() + (target.width() - draw_w) // 2
                y = target.y() + (target.height() - draw_h) // 2
                target = QRect(x, y, draw_w, draw_h)
        elif self.video_scaling == "fit":
            image = self.core.latest_image
            if image.width() > 0 and image.height() > 0:
                width_ratio = target.width() / image.width()
                height_ratio = target.height() / image.height()
                fit_scale = min(width_ratio, height_ratio)
                draw_w = max(1, int(image.width() * fit_scale))
                draw_h = max(1, int(image.height() * fit_scale))
                x = target.x() + (target.width() - draw_w) // 2
                y = target.y() + (target.height() - draw_h) // 2
                target = QRect(x, y, draw_w, draw_h)
        painter.drawImage(target, self.core.latest_image)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        self.core.keys.add(key)
        if key == Qt.Key.Key_Escape:
            self.close()

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        self.core.keys.discard(event.key())

    def closeEvent(self, event) -> None:
        self.timer.stop()
        self.core.shutdown()
        super().closeEvent(event)


def resolve_core(profile: str, base_dir: Path) -> Path:
    core_dir = base_dir / "core"
    mapping = {
        "fc": "quicknes_libretro.dll",
        "snes": "snes9x_libretro.dll",
        "megadrive": "picodrive_libretro.dll",
        "sega8": "picodrive_libretro.dll",
        "segacd32x": "picodrive_libretro.dll",
        "gb": "mgba_libretro.dll",
        "gba": "mgba_libretro.dll",
        "cps": "fbneo_libretro.dll",
    }
    dll = mapping.get(profile)
    if dll is None:
        raise ValueError(f"不支持的内置类型: {profile}")
    target = core_dir / dll
    if not target.exists():
        raise FileNotFoundError(f"缺少核心DLL: {target}")
    return target


def resolve_core_candidates(profile: str, base_dir: Path, core_path_arg: str) -> list[Path]:
    if core_path_arg.strip():
        explicit = Path(core_path_arg.strip())
        if explicit.exists():
            base = [explicit]
        else:
            base = []
    else:
        base = []
    default_core = resolve_core(profile, base_dir)
    if all(path != default_core for path in base):
        base.append(default_core)
    if profile in {"gb", "gba"}:
        for dll in ("mgba_libretro.dll", "vbam_libretro.dll"):
            candidate = base_dir / "core" / dll
            if candidate.exists() and all(path != candidate for path in base):
                base.append(candidate)
    return base


def _profile_zip_exts(profile: str) -> tuple[str, ...]:
    mapping = {
        "fc": (".nes", ".fds", ".unf", ".unif"),
        "snes": (".sfc", ".smc", ".fig", ".swc"),
        "megadrive": (".md", ".bin", ".gen", ".smd", ".32x", ".iso", ".cue"),
        "sega8": (".sms", ".gg", ".sg"),
        "segacd32x": (".cue", ".iso", ".bin", ".md", ".32x"),
        "gb": (".gb", ".gbc"),
        "gba": (".gba",),
        "cps": (".zip",),
    }
    return mapping.get(profile, ())


def prepare_content_path(profile: str, rom_path: Path) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
    profile_key = profile.lower()
    suffix = rom_path.suffix.lower()
    has_non_ascii = any(ord(ch) > 127 for ch in str(rom_path))
    if suffix != ".zip" and not has_non_ascii:
        return rom_path, None
    temp_dir = tempfile.TemporaryDirectory(prefix="arkos_libretro_")
    temp_root = Path(temp_dir.name)
    if suffix == ".zip":
        allowed_exts = _profile_zip_exts(profile_key)
        with zipfile.ZipFile(rom_path, "r") as zf:
            names = [name for name in zf.namelist() if not name.endswith("/")]
            candidates: list[str] = []
            for ext in allowed_exts:
                for name in names:
                    if name.lower().endswith(ext):
                        candidates.append(name)
            if not candidates and names:
                candidates = names
            if not candidates:
                temp_dir.cleanup()
                raise ValueError(f"zip 内没有可用 ROM 文件: {rom_path}")
            selected = candidates[0]
            selected_suffix = Path(selected).suffix.lower() or ".rom"
            target = temp_root / f"content{selected_suffix}"
            target.write_bytes(zf.read(selected))
            return target, temp_dir
    target = temp_root / f"content{(suffix or '.rom').lower()}"
    shutil.copy2(rom_path, target)
    return target, temp_dir


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("rom_path")
    parser.add_argument("--profile", default="fc")
    parser.add_argument("--system", default="")
    parser.add_argument("--base-dir", default=str(Path(__file__).resolve().parent))
    parser.add_argument("--bios-dir", default="")
    parser.add_argument("--key-profile", default="default")
    parser.add_argument("--key-bindings", default="")
    parser.add_argument("--core-path", default="")
    parser.add_argument("--video-scaling", default="fit")
    parser.add_argument("--video-filter", default="nearest")
    parser.add_argument("--audio-latency-ms", type=int, default=80)
    parser.add_argument("--frame-sync", default="precise")
    args = parser.parse_args()
    rom_path = Path(args.rom_path)
    if not rom_path.exists():
        print(f"ROM 文件不存在：{rom_path}")
        return 1
    profile = args.profile.lower()
    base_dir = Path(args.base_dir)
    system_name = args.system.strip().lower()
    explicit_bios_dir = args.bios_dir.strip()
    bios_dir = Path(explicit_bios_dir) if explicit_bios_dir else detect_bios_dir_from_rom(rom_path)
    if bios_dir is not None:
        matched_bios, missing_bios = match_bios_files(profile, system_name, bios_dir)
        if matched_bios:
            print(f"检测到BIOS目录: {bios_dir}")
            print(f"已匹配BIOS: {', '.join(path.name for path in matched_bios)}")
        elif missing_bios:
            print(f"检测到BIOS目录: {bios_dir}")
            print(f"未匹配到目标BIOS: {', '.join(missing_bios)}")
    try:
        core_candidates = resolve_core_candidates(profile, base_dir, args.core_path)
    except Exception as exc:
        print(f"核心DLL加载失败: {exc}")
        return 1
    if not core_candidates:
        print("核心DLL加载失败: 未找到可用核心")
        return 1
    app = QApplication(sys.argv)
    input_mapping = build_input_mapping(args.key_profile.strip(), args.key_bindings.strip())
    prepared_path = rom_path
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    try:
        prepared_path, temp_dir = prepare_content_path(profile, rom_path)
    except Exception as exc:
        print(f"启动核心失败: {exc}")
        return 1
    last_error: Exception | None = None
    host: LibretroCore | None = None
    fps = 60.0
    for core_path in core_candidates:
        try:
            host = LibretroCore(core_path, input_mapping, args.audio_latency_ms, system_dir=bios_dir, save_dir=rom_path.parent)
            fps = host.setup()
            host.load_game(prepared_path)
            print(f"使用核心启动成功: {core_path.name}")
            break
        except Exception as exc:
            last_error = exc
            if host is not None:
                host.shutdown()
            host = None
            print(f"核心启动失败({core_path.name}): {exc}")
    if host is None:
        if temp_dir is not None:
            temp_dir.cleanup()
        print(f"启动核心失败: {last_error}")
        return 1
    window = LibretroWindow(
        host,
        f"Libretro {args.profile.upper()} - {prepared_path.name}",
        fps,
        args.video_scaling.strip().lower(),
        args.video_filter.strip().lower(),
        args.frame_sync.strip().lower(),
    )
    window.show()
    code = app.exec()
    if temp_dir is not None:
        temp_dir.cleanup()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
