from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


def normalize_version(value: str) -> str:
    text = (value or "").strip()
    if text.lower().startswith("v"):
        text = text[1:]
    return text


def _version_key(version: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", normalize_version(version))
    if not parts:
        return (0,)
    return tuple(int(p) for p in parts)


def is_newer_version(latest: str, current: str) -> bool:
    return _version_key(latest) > _version_key(current)


def fetch_latest_release(repo: str, timeout: float = 8.0) -> dict[str, str] | None:
    repo = repo.strip().strip("/")
    if not repo or "/" not in repo:
        return None
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    req = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "ArkosGameMan-Updater",
        },
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except URLError:
        return None
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    tag = str(payload.get("tag_name", "")).strip()
    page_url = str(payload.get("html_url", "")).strip()
    assets = payload.get("assets", [])
    exe_asset = None
    for asset in assets:
        name = str(asset.get("name", "")).lower()
        if name.endswith(".exe"):
            exe_asset = asset
            break
    if exe_asset is None:
        return {
            "tag": tag,
            "version": normalize_version(tag),
            "asset_name": "",
            "asset_url": "",
            "page_url": page_url,
        }
    return {
        "tag": tag,
        "version": normalize_version(tag),
        "asset_name": str(exe_asset.get("name", "")).strip(),
        "asset_url": str(exe_asset.get("browser_download_url", "")).strip(),
        "page_url": page_url,
    }


def download_file(
    url: str,
    target_path: Path,
    progress_cb,
    cancel_event,
    timeout: float = 20.0,
) -> Path:
    req = Request(url, headers={"User-Agent": "ArkosGameMan-Updater"})
    with urlopen(req, timeout=timeout) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        received = 0
        with target_path.open("wb") as handle:
            while True:
                if cancel_event.is_set():
                    raise RuntimeError("cancelled")
                chunk = resp.read(1024 * 128)
                if not chunk:
                    break
                handle.write(chunk)
                received += len(chunk)
                progress_cb(received, total)
    return target_path


def is_running_as_exe() -> bool:
    exe = Path(sys.executable)
    return bool(getattr(sys, "frozen", False)) and exe.suffix.lower() == ".exe"


def current_executable_path() -> Path:
    return Path(sys.executable).resolve()


def create_replace_script(current_exe: Path, downloaded_exe: Path, pid: int) -> Path:
    temp_dir = Path(tempfile.gettempdir()) / "arkosgameman_update"
    temp_dir.mkdir(parents=True, exist_ok=True)
    script = temp_dir / f"replace_{uuid.uuid4().hex}.bat"
    content = "\n".join(
        [
            "@echo off",
            "setlocal",
            f"set APP_PID={pid}",
            f'set SRC="{downloaded_exe}"',
            f'set DST="{current_exe}"',
            ":wait_loop",
            'tasklist /FI "PID eq %APP_PID%" | find "%APP_PID%" >nul',
            "if %ERRORLEVEL%==0 (",
            "  timeout /t 1 /nobreak >nul",
            "  goto wait_loop",
            ")",
            "timeout /t 1 /nobreak >nul",
            "move /Y %SRC% %DST% >nul",
            "start \"\" %DST%",
            "del \"%~f0\"",
        ]
    )
    script.write_text(content, encoding="utf-8")
    return script


def launch_replace_script(script_path: Path) -> None:
    creation_flags = 0
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        creation_flags = subprocess.CREATE_NO_WINDOW
    subprocess.Popen(["cmd", "/c", str(script_path)], creationflags=creation_flags)


def default_download_path(filename: str) -> Path:
    return Path(tempfile.gettempdir()) / "arkosgameman_update" / filename
