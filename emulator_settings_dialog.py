from __future__ import annotations

import copy
import subprocess
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from emulator_config import EmulatorProfileConfig
from emulator_profiles import EMULATOR_PROFILES, EmulatorProfile


class EmulatorSettingsDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None,
        t: Callable[..., str],
        state: dict[str, EmulatorProfileConfig],
    ) -> None:
        super().__init__(parent)
        self._t = t
        self._state = copy.deepcopy(state)
        self._current_profile_id = ""
        self.setWindowTitle(self._t("dialog.emulator_manager_title"))
        self.resize(1080, 720)
        self._build_ui()
        self._load_profile_list()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        tip = QLabel(self._t("dialog.emulator_manager_tip"))
        tip.setWordWrap(True)
        root.addWidget(tip)
        content = QHBoxLayout()
        self.profile_list = QListWidget()
        self.profile_list.currentRowChanged.connect(self._on_profile_changed)
        content.addWidget(self.profile_list, 2)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.profile_title = QLabel("")
        self.profile_title.setObjectName("sectionTitle")
        right_layout.addWidget(self.profile_title)
        self.profile_desc = QLabel("")
        self.profile_desc.setWordWrap(True)
        right_layout.addWidget(self.profile_desc)
        form = QFormLayout()
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        self.folders_edit = QPlainTextEdit()
        self.folders_edit.setPlaceholderText(self._t("settings.folders.placeholder"))
        self.folders_edit.setFixedHeight(120)
        form.addRow(self._t("settings.field.folders"), self.folders_edit)
        self.emulator_path_edit = QLineEdit()
        browse_emulator = QPushButton(self._t("button.browse"))
        browse_emulator.clicked.connect(self._choose_emulator_path)
        emulator_path_row = QHBoxLayout()
        emulator_path_row.addWidget(self.emulator_path_edit, 1)
        emulator_path_row.addWidget(browse_emulator)
        emulator_path_wrap = QWidget()
        emulator_path_wrap.setLayout(emulator_path_row)
        form.addRow(self._t("settings.field.emulator_path"), emulator_path_wrap)
        self.launch_command_edit = QLineEdit()
        form.addRow(self._t("settings.field.launch_command"), self.launch_command_edit)
        self.install_script_edit = QLineEdit()
        browse_script = QPushButton(self._t("button.browse"))
        browse_script.clicked.connect(self._choose_install_script)
        self.install_button = QPushButton(self._t("button.install_emulator"))
        self.install_button.clicked.connect(self._run_install_script)
        install_row = QHBoxLayout()
        install_row.addWidget(self.install_script_edit, 1)
        install_row.addWidget(browse_script)
        install_row.addWidget(self.install_button)
        install_wrap = QWidget()
        install_wrap.setLayout(install_row)
        form.addRow(self._t("settings.field.install_script"), install_wrap)
        self.use_bundled_check = QCheckBox(self._t("settings.field.use_bundled"))
        form.addRow("", self.use_bundled_check)
        self.fc_only_hint = QLabel(self._t("settings.fc.sample_only"))
        self.fc_only_hint.setWordWrap(True)
        form.addRow("", self.fc_only_hint)
        self.key_profile_combo = QComboBox()
        self.key_profile_combo.addItems(
            [
                "default",
                "arcade-stick",
                "xinput-pad",
            ]
        )
        form.addRow(self._t("settings.field.key_profile"), self.key_profile_combo)
        self.display_profile_combo = QComboBox()
        self.display_profile_combo.addItems(
            [
                "pixel",
                "crt",
                "smooth-hd",
            ]
        )
        form.addRow(self._t("settings.field.display_profile"), self.display_profile_combo)
        right_layout.addLayout(form, 1)
        content.addWidget(right, 5)
        root.addLayout(content, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept_with_save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _load_profile_list(self) -> None:
        for profile in EMULATOR_PROFILES:
            self.profile_list.addItem(f"[{profile.category}] {profile.title}")
        if self.profile_list.count() > 0:
            self.profile_list.setCurrentRow(0)

    def _current_profile(self) -> EmulatorProfile | None:
        idx = self.profile_list.currentRow()
        if idx < 0 or idx >= len(EMULATOR_PROFILES):
            return None
        return EMULATOR_PROFILES[idx]

    def _on_profile_changed(self, _row: int) -> None:
        self._save_current_editor_state()
        profile = self._current_profile()
        if profile is None:
            return
        self._current_profile_id = profile.profile_id
        cfg = self._state.get(profile.profile_id, EmulatorProfileConfig(folders=list(profile.systems)))
        self.profile_title.setText(profile.title)
        self.profile_desc.setText(
            self._t(
                "settings.profile_desc",
                category=profile.category,
                systems=", ".join(profile.systems),
                cores=", ".join(profile.recommended_cores),
            )
        )
        self.folders_edit.setPlainText("\n".join(cfg.folders))
        self.emulator_path_edit.setText(cfg.emulator_path)
        self.launch_command_edit.setText(cfg.launch_command)
        self.install_script_edit.setText(cfg.install_script)
        self.use_bundled_check.setChecked(cfg.use_bundled)
        self._set_combo_value(self.key_profile_combo, cfg.key_profile)
        self._set_combo_value(self.display_profile_combo, cfg.display_profile)
        is_fc = profile.profile_id == "fc"
        self.key_profile_combo.setVisible(is_fc)
        self.display_profile_combo.setVisible(is_fc)
        self.fc_only_hint.setVisible(not is_fc)

    @staticmethod
    def _set_combo_value(combo: QComboBox, value: str) -> None:
        idx = combo.findText(value)
        if idx < 0:
            combo.addItem(value)
            idx = combo.findText(value)
        combo.setCurrentIndex(max(idx, 0))

    def _save_current_editor_state(self) -> None:
        if not self._current_profile_id:
            return
        folders = [item.strip() for item in self.folders_edit.toPlainText().splitlines() if item.strip()]
        cfg = self._state.get(self._current_profile_id, EmulatorProfileConfig())
        cfg.folders = folders
        cfg.emulator_path = self.emulator_path_edit.text().strip()
        cfg.launch_command = self.launch_command_edit.text().strip() or '{emulator} "{rom}"'
        cfg.install_script = self.install_script_edit.text().strip()
        cfg.use_bundled = self.use_bundled_check.isChecked()
        cfg.bundled_emulator_path = ""
        cfg.key_profile = self.key_profile_combo.currentText().strip() or "default"
        cfg.display_profile = self.display_profile_combo.currentText().strip() or "pixel"
        self._state[self._current_profile_id] = cfg

    def _accept_with_save(self) -> None:
        self._save_current_editor_state()
        self.accept()

    def _choose_emulator_path(self) -> None:
        file_name = QFileDialog.getOpenFileName(self, self._t("dialog.select_emulator_exe"), filter="Executable (*.exe);;All Files (*)")[0]
        if file_name:
            self.emulator_path_edit.setText(file_name)

    def _choose_install_script(self) -> None:
        file_name = QFileDialog.getOpenFileName(self, self._t("dialog.select_install_script"), filter="PowerShell Script (*.ps1);;All Files (*)")[0]
        if file_name:
            self.install_script_edit.setText(file_name)

    def _run_install_script(self) -> None:
        self._save_current_editor_state()
        profile = self._current_profile()
        if profile is None:
            return
        cfg = self._state.get(profile.profile_id)
        if cfg is None:
            return
        script = cfg.install_script.strip()
        if not script:
            QMessageBox.critical(self, self._t("notify.failed"), self._t("notify.install_script_missing"))
            return
        script_path = Path(script)
        if not script_path.exists():
            QMessageBox.critical(self, self._t("notify.failed"), self._t("notify.file_not_found", path=script_path))
            return
        target = cfg.emulator_path.strip()
        target_dir = str(Path(target).parent) if target else str(Path.cwd())
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script_path),
                    "-ProfileId",
                    profile.profile_id,
                    "-TargetDir",
                    target_dir,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                msg = (result.stderr or result.stdout or "").strip() or f"exit={result.returncode}"
                QMessageBox.critical(self, self._t("notify.failed"), self._t("notify.install_failed", error=msg))
                return
            QMessageBox.information(self, self._t("notify.success"), self._t("notify.install_success"))
        except Exception as exc:
            QMessageBox.critical(self, self._t("notify.failed"), self._t("notify.install_failed", error=exc))

    def get_state(self) -> dict[str, EmulatorProfileConfig]:
        self._save_current_editor_state()
        return copy.deepcopy(self._state)
