from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QProgressDialog, QWidget

from updater import (
    create_replace_script,
    current_executable_path,
    default_download_path,
    download_file,
    fetch_latest_release,
    is_newer_version,
    is_running_as_exe,
    launch_replace_script,
)

logger = logging.getLogger(__name__)


class UpdateBridge(QObject):
    check_finished = Signal(object)
    download_progress = Signal(int, int)
    download_finished = Signal(bool, str, str, str)


class UpdateService:
    def __init__(
        self,
        parent_view: QWidget,
        app_version: str,
        tr: Callable[..., str],
        notify: Callable[[str, str, bool], None],
        ask_yes_no: Callable[[str, str], bool],
    ) -> None:
        self._view = parent_view
        self._app_version = app_version
        self._t = tr
        self._notify = notify
        self._ask_yes_no = ask_yes_no
        self._repo = ""
        self._check_enabled = False
        self._check_started = False
        self._download_cancel = threading.Event()
        self._dialog: QProgressDialog | None = None
        self._latest: dict[str, str] | None = None
        self._bridge = UpdateBridge(parent_view)
        self._bridge.check_finished.connect(self._on_check_finished)
        self._bridge.download_progress.connect(self._on_download_progress)
        self._bridge.download_finished.connect(self._on_download_finished)

    def configure(self, repository: str, check_enabled: bool) -> None:
        self._repo = repository
        self._check_enabled = check_enabled

    def should_check_on_start(self) -> bool:
        return self._check_enabled

    def start_check(self) -> None:
        if self._check_started:
            return
        if not self._repo:
            logger.info("跳过更新检查: 未配置GitHub仓库")
            return
        self._check_started = True
        threading.Thread(target=self._check_worker, daemon=True).start()

    def _check_worker(self) -> None:
        latest = fetch_latest_release(self._repo)
        if not latest:
            self._bridge.check_finished.emit(None)
            return
        latest_version = latest.get("version", "")
        if not latest_version or not is_newer_version(latest_version, self._app_version):
            self._bridge.check_finished.emit(None)
            return
        self._bridge.check_finished.emit(latest)

    def _on_check_finished(self, latest: dict[str, str] | None) -> None:
        if not latest:
            return
        self._latest = latest
        ask = self._ask_yes_no(
            self._t("update.available_title"),
            self._t(
                "update.available_message",
                current=self._app_version,
                latest=latest.get("version", ""),
            ),
        )
        if ask:
            self._start_download(latest)

    def _start_download(self, latest: dict[str, str]) -> None:
        asset_url = latest.get("asset_url", "")
        asset_name = latest.get("asset_name", "")
        if not asset_url or not asset_name:
            self._notify(self._t("notify.failed"), self._t("notify.update_no_exe"), True)
            page_url = latest.get("page_url", "")
            if page_url:
                QDesktopServices.openUrl(QUrl(page_url))
            return
        self._download_cancel.clear()
        self._dialog = QProgressDialog(
            self._t("update.downloading_text"),
            self._t("update.downloading_cancel"),
            0,
            100,
            self._view,
        )
        self._dialog.setWindowTitle(self._t("update.downloading_title"))
        self._dialog.setMinimumWidth(480)
        self._dialog.setValue(0)
        self._dialog.setAutoClose(False)
        self._dialog.setAutoReset(False)
        self._dialog.canceled.connect(self._download_cancel.set)
        self._dialog.show()
        threading.Thread(
            target=self._download_worker,
            args=(asset_url, asset_name, latest.get("version", ""), latest.get("page_url", "")),
            daemon=True,
        ).start()

    def _download_worker(self, asset_url: str, asset_name: str, version: str, page_url: str) -> None:
        try:
            target = default_download_path(asset_name)
            path = download_file(asset_url, target, self._bridge.download_progress.emit, self._download_cancel)
            self._bridge.download_finished.emit(True, str(path), version, page_url)
        except RuntimeError as exc:
            self._bridge.download_finished.emit(False, str(exc), version, page_url)
        except OSError as exc:
            self._bridge.download_finished.emit(False, str(exc), version, page_url)

    def _on_download_progress(self, received: int, total: int) -> None:
        if self._dialog is None:
            return
        if total <= 0:
            self._dialog.setRange(0, 0)
            return
        self._dialog.setRange(0, 100)
        progress = int(received * 100 / total)
        self._dialog.setValue(max(0, min(progress, 100)))

    def _on_download_finished(self, ok: bool, payload: str, version: str, page_url: str) -> None:
        if self._dialog is not None:
            self._dialog.close()
            self._dialog = None
        if not ok:
            if payload != "cancelled":
                self._notify(
                    self._t("notify.failed"),
                    self._t("notify.update_download_failed", error=payload),
                    True,
                )
            return
        if not is_running_as_exe():
            self._notify(self._t("notify.tip"), self._t("notify.update_manual", version=version), False)
            if page_url:
                QDesktopServices.openUrl(QUrl(page_url))
            return
        try:
            current_exe = current_executable_path()
            script = create_replace_script(current_exe, Path(payload), os.getpid())
            launch_replace_script(script)
            self._notify(self._t("notify.success"), self._t("notify.update_installing"), False)
            QApplication.quit()
        except OSError as exc:
            self._notify(
                self._t("notify.failed"),
                self._t("notify.update_download_failed", error=exc),
                True,
            )
