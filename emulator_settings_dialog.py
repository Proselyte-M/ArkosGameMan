from __future__ import annotations

import copy
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidgetItem,
    QListWidget,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from emulator_config import EmulatorProfileConfig
from emulator_profiles import EMULATOR_PROFILES


class FolderPickerDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None,
        t: Callable[..., str],
        current_profile_id: str,
        current_folders: list[str],
        all_folders: list[str],
        folder_owners: dict[str, str],
        profile_title_map: dict[str, str],
    ) -> None:
        super().__init__(parent)
        self._t = t
        self._current_profile_id = current_profile_id
        self._folder_owners = folder_owners
        self._profile_title_map = profile_title_map
        self.setWindowTitle(self._t("dialog.folder_picker_title"))
        self.resize(520, 620)
        root = QVBoxLayout(self)
        tip = QLabel(self._t("dialog.folder_picker_tip"))
        tip.setWordWrap(True)
        root.addWidget(tip)
        self.folder_list = QListWidget()
        root.addWidget(self.folder_list, 1)
        current_set = {item.strip().lower() for item in current_folders if item.strip()}
        for folder in sorted({item.strip() for item in all_folders if item.strip()}, key=str.lower):
            owner = folder_owners.get(folder.lower())
            item = QListWidgetItem(folder)
            if folder.lower() in current_set:
                item.setCheckState(Qt.CheckState.Checked)
            else:
                item.setCheckState(Qt.CheckState.Unchecked)
            if owner is not None and owner != current_profile_id:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                title = profile_title_map.get(owner, owner)
                item.setText(f"{folder} ({self._t('label.assigned_to', profile=title)})")
            self.folder_list.addItem(item)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def selected_folders(self) -> list[str]:
        folders: list[str] = []
        for idx in range(self.folder_list.count()):
            item = self.folder_list.item(idx)
            if item.flags() & Qt.ItemFlag.ItemIsEnabled and item.checkState() == Qt.CheckState.Checked:
                raw = item.text().split(" (", 1)[0].strip()
                if raw:
                    folders.append(raw)
        return folders


class KeyBindingDialog(QDialog):
    _layout_rows = [
        ("up", "button.up"),
        ("down", "button.down"),
        ("left", "button.left"),
        ("right", "button.right"),
        ("a", "button.a"),
        ("b", "button.b"),
        ("x", "button.x"),
        ("y", "button.y"),
        ("start", "button.start"),
        ("select", "button.select"),
        ("l", "button.l"),
        ("r", "button.r"),
    ]

    def __init__(self, parent: QWidget | None, t: Callable[..., str], value: str) -> None:
        super().__init__(parent)
        self._t = t
        self._edits: dict[str, QLineEdit] = {}
        self.setWindowTitle(self._t("dialog.key_binding_title"))
        self.resize(640, 360)
        root = QVBoxLayout(self)
        tip = QLabel(self._t("dialog.key_binding_tip"))
        tip.setWordWrap(True)
        root.addWidget(tip)
        pad = QWidget()
        grid = QGridLayout(pad)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        parsed = self._parse(value)
        for idx, (name, label_key) in enumerate(self._layout_rows):
            row = idx % 6
            col_base = 0 if idx < 6 else 2
            label = QLabel(self._t(label_key))
            edit = QLineEdit()
            edit.setPlaceholderText("Key_X / X / Return / Space")
            edit.setText(parsed.get(name, ""))
            self._edits[name] = edit
            grid.addWidget(label, row, col_base)
            grid.addWidget(edit, row, col_base + 1)
        root.addWidget(pad, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @staticmethod
    def _parse(value: str) -> dict[str, str]:
        result: dict[str, str] = {}
        for segment in value.split(","):
            chunk = segment.strip()
            if not chunk or "=" not in chunk:
                continue
            left, right = chunk.split("=", 1)
            key = left.strip().lower()
            val = right.strip()
            if key and val:
                result[key] = val
        return result

    def to_binding_text(self) -> str:
        parts: list[str] = []
        for name, _ in self._layout_rows:
            value = self._edits[name].text().strip()
            if value:
                parts.append(f"{name}={value}")
        return ",".join(parts)


class OtherSettingsDialog(QDialog):
    def __init__(self, parent: QWidget | None, t: Callable[..., str], cfg: EmulatorProfileConfig) -> None:
        super().__init__(parent)
        self._t = t
        self.setWindowTitle(self._t("dialog.other_settings_title"))
        self.resize(520, 300)
        root = QVBoxLayout(self)
        tip = QLabel(self._t("dialog.other_settings_tip"))
        tip.setWordWrap(True)
        root.addWidget(tip)
        grid = QGridLayout()
        root.addLayout(grid, 1)
        row = 0

        grid.addWidget(QLabel(self._t("settings.field.key_profile")), row, 0)
        self.key_profile_combo = QComboBox()
        for value in ["default", "arcade-stick", "xinput-pad"]:
            self.key_profile_combo.addItem(value, value)
        self._set_combo_data(self.key_profile_combo, cfg.key_profile or "default")
        grid.addWidget(self.key_profile_combo, row, 1)
        row += 1

        grid.addWidget(QLabel(self._t("settings.field.display_profile")), row, 0)
        self.display_profile_combo = QComboBox()
        for value in ["pixel", "crt", "smooth-hd"]:
            self.display_profile_combo.addItem(value, value)
        self._set_combo_data(self.display_profile_combo, cfg.display_profile or "pixel")
        grid.addWidget(self.display_profile_combo, row, 1)
        row += 1

        grid.addWidget(QLabel(self._t("settings.field.video_scaling")), row, 0)
        self.video_scaling_combo = QComboBox()
        self.video_scaling_combo.addItem(self._t("option.video_scaling.fit"), "fit")
        self.video_scaling_combo.addItem(self._t("option.video_scaling.integer"), "integer")
        self.video_scaling_combo.addItem(self._t("option.video_scaling.stretch"), "stretch")
        self._set_combo_data(self.video_scaling_combo, cfg.video_scaling or "fit")
        grid.addWidget(self.video_scaling_combo, row, 1)
        row += 1

        grid.addWidget(QLabel(self._t("settings.field.video_filter")), row, 0)
        self.video_filter_combo = QComboBox()
        self.video_filter_combo.addItem(self._t("option.video_filter.nearest"), "nearest")
        self.video_filter_combo.addItem(self._t("option.video_filter.smooth"), "smooth")
        self._set_combo_data(self.video_filter_combo, cfg.video_filter or "nearest")
        grid.addWidget(self.video_filter_combo, row, 1)
        row += 1

        grid.addWidget(QLabel(self._t("settings.field.audio_latency_ms")), row, 0)
        self.audio_latency_spin = QSpinBox()
        self.audio_latency_spin.setRange(20, 300)
        self.audio_latency_spin.setSingleStep(5)
        self.audio_latency_spin.setValue(max(20, min(300, cfg.audio_latency_ms)))
        grid.addWidget(self.audio_latency_spin, row, 1)
        row += 1

        grid.addWidget(QLabel(self._t("settings.field.frame_sync")), row, 0)
        self.frame_sync_combo = QComboBox()
        self.frame_sync_combo.addItem(self._t("option.frame_sync.precise"), "precise")
        self.frame_sync_combo.addItem(self._t("option.frame_sync.coarse"), "coarse")
        self._set_combo_data(self.frame_sync_combo, cfg.frame_sync or "precise")
        grid.addWidget(self.frame_sync_combo, row, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: str) -> None:
        idx = combo.findData(value)
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    def apply_to(self, cfg: EmulatorProfileConfig) -> None:
        cfg.key_profile = str(self.key_profile_combo.currentData() or "default")
        cfg.display_profile = str(self.display_profile_combo.currentData() or "pixel")
        cfg.video_scaling = str(self.video_scaling_combo.currentData() or "fit")
        cfg.video_filter = str(self.video_filter_combo.currentData() or "nearest")
        cfg.audio_latency_ms = int(self.audio_latency_spin.value())
        cfg.frame_sync = str(self.frame_sync_combo.currentData() or "precise")


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
        self._profile_by_id = {profile.profile_id: profile for profile in EMULATOR_PROFILES}
        self._profile_titles = {profile.profile_id: profile.title for profile in EMULATOR_PROFILES}
        self._row_profile_ids = [profile.profile_id for profile in EMULATOR_PROFILES]
        self._widgets: dict[str, dict[str, QWidget]] = {}
        self._key_bindings: dict[str, str] = {}
        self._folder_owners = self._build_folder_owners()
        self._all_folder_candidates = self._collect_folder_candidates()
        self._core_options = self._discover_core_options()
        self.setWindowTitle(self._t("dialog.emulator_manager_title"))
        self.resize(1500, 760)
        self._build_ui()
        self._load_rows()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        tip = QLabel(self._t("dialog.emulator_manager_tip"))
        tip.setWordWrap(True)
        root.addWidget(tip)
        self.table = QTableWidget(len(self._row_profile_ids), 8)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setHorizontalHeaderLabels(
            [
                self._t("settings.col.profile"),
                self._t("settings.col.folders"),
                self._t("settings.col.core_dll"),
                self._t("settings.col.use_external"),
                self._t("settings.col.path"),
                self._t("settings.col.command"),
                self._t("settings.col.key_menu"),
                self._t("settings.col.other"),
            ]
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self.table, 1)
        root.addWidget(QLabel(self._t("settings.fc.sample_only")))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept_with_save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _discover_core_options(self) -> list[str]:
        core_dir = Path(__file__).resolve().parent / "core"
        dlls = sorted({path.name for path in core_dir.glob("*_libretro.dll")}, key=str.lower)
        default_map = {
            "fc": "quicknes_libretro.dll",
            "snes": "snes9x_libretro.dll",
            "megadrive": "picodrive_libretro.dll",
            "sega8": "picodrive_libretro.dll",
            "segacd32x": "picodrive_libretro.dll",
            "gb": "mgba_libretro.dll",
            "gba": "mgba_libretro.dll",
            "cps": "fbneo_libretro.dll",
        }
        for item in default_map.values():
            if item not in dlls:
                dlls.append(item)
        return dlls

    def _collect_folder_candidates(self) -> list[str]:
        values: dict[str, str] = {}
        for profile in EMULATOR_PROFILES:
            for folder in profile.systems:
                key = folder.strip().lower()
                if key and key not in values:
                    values[key] = folder.strip()
        for cfg in self._state.values():
            for folder in cfg.folders:
                key = folder.strip().lower()
                if key and key not in values:
                    values[key] = folder.strip()
        return [values[key] for key in sorted(values.keys())]

    def _build_folder_owners(self) -> dict[str, str]:
        owners: dict[str, str] = {}
        for profile in EMULATOR_PROFILES:
            cfg = self._state.get(profile.profile_id, EmulatorProfileConfig(folders=list(profile.systems)))
            for folder in cfg.folders:
                key = folder.strip().lower()
                if key and key not in owners:
                    owners[key] = profile.profile_id
        return owners

    def _default_core_for_profile(self, profile_id: str) -> str:
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
        return mapping.get(profile_id, "")

    def _load_rows(self) -> None:
        for row, profile_id in enumerate(self._row_profile_ids):
            profile = self._profile_by_id[profile_id]
            cfg = self._state.get(profile_id, EmulatorProfileConfig(folders=list(profile.systems)))
            self._state[profile_id] = cfg
            title_item = QTableWidgetItem(f"[{profile.category}] {profile.title}")
            self.table.setItem(row, 0, title_item)

            folder_button = QPushButton()
            folder_button.clicked.connect(lambda _=False, pid=profile_id: self._open_folder_picker(pid))
            self.table.setCellWidget(row, 1, folder_button)

            core_combo = QComboBox()
            core_combo.addItems(self._core_options)
            preferred_core = cfg.bundled_core_dll.strip() or self._default_core_for_profile(profile_id)
            self._set_combo_value(core_combo, preferred_core)
            self.table.setCellWidget(row, 2, core_combo)

            external_check = QComboBox()
            external_check.addItems([self._t("option.internal"), self._t("option.external")])
            external_check.setCurrentIndex(1 if cfg.use_external else 0)
            external_check.currentIndexChanged.connect(lambda _idx, pid=profile_id: self._sync_external_enabled(pid))
            self.table.setCellWidget(row, 3, external_check)

            path_edit = QLineEdit(cfg.emulator_path)
            browse_btn = QPushButton(self._t("button.browse"))
            browse_btn.clicked.connect(lambda _=False, pid=profile_id: self._choose_emulator_path(pid))
            path_wrap = QWidget()
            path_layout = QHBoxLayout(path_wrap)
            path_layout.setContentsMargins(0, 0, 0, 0)
            path_layout.addWidget(path_edit, 1)
            path_layout.addWidget(browse_btn)
            self.table.setCellWidget(row, 4, path_wrap)

            command_edit = QLineEdit(cfg.launch_command or '{emulator} "{rom}"')
            self.table.setCellWidget(row, 5, command_edit)

            key_btn = QPushButton(self._t("button.key_bindings"))
            key_btn.clicked.connect(lambda _=False, pid=profile_id: self._open_key_dialog(pid))
            self.table.setCellWidget(row, 6, key_btn)

            other_btn = QPushButton(self._t("button.other_settings"))
            other_btn.clicked.connect(lambda _=False, pid=profile_id: self._open_other_settings_dialog(pid))
            self.table.setCellWidget(row, 7, other_btn)

            self._widgets[profile_id] = {
                "folder_button": folder_button,
                "core_combo": core_combo,
                "external_combo": external_check,
                "path_edit": path_edit,
                "browse_btn": browse_btn,
                "command_edit": command_edit,
                "key_btn": key_btn,
                "other_btn": other_btn,
            }
            self._key_bindings[profile_id] = cfg.key_bindings
            self._sync_external_enabled(profile_id)
            self._refresh_folder_button(profile_id)
            self._refresh_other_button(profile_id)

    @staticmethod
    def _set_combo_value(combo: QComboBox, value: str) -> None:
        idx = combo.findText(value)
        if idx < 0:
            combo.addItem(value)
            idx = combo.findText(value)
        combo.setCurrentIndex(max(idx, 0))

    def _refresh_folder_button(self, profile_id: str) -> None:
        cfg = self._state.get(profile_id)
        widgets = self._widgets.get(profile_id)
        if cfg is None or widgets is None:
            return
        folder_button = widgets["folder_button"]
        if isinstance(folder_button, QPushButton):
            folder_button.setText(self._t("button.pick_folders", count=len(cfg.folders)))

    def _refresh_other_button(self, profile_id: str) -> None:
        cfg = self._state.get(profile_id)
        widgets = self._widgets.get(profile_id)
        if cfg is None or widgets is None:
            return
        other_btn = widgets.get("other_btn")
        if not isinstance(other_btn, QPushButton):
            return
        other_btn.setText(
            self._t(
                "button.other_settings_summary",
                filter=cfg.video_filter,
                latency=cfg.audio_latency_ms,
                sync=cfg.frame_sync,
            )
        )

    def _sync_external_enabled(self, profile_id: str) -> None:
        widgets = self._widgets.get(profile_id)
        if widgets is None:
            return
        mode_widget = widgets["external_combo"]
        path_edit = widgets["path_edit"]
        browse_btn = widgets["browse_btn"]
        command_edit = widgets["command_edit"]
        if not isinstance(mode_widget, QComboBox):
            return
        is_external = mode_widget.currentIndex() == 1
        path_edit.setEnabled(is_external)
        browse_btn.setEnabled(is_external)
        command_edit.setEnabled(is_external)

    def _open_folder_picker(self, profile_id: str) -> None:
        cfg = self._state.get(profile_id)
        if cfg is None:
            return
        dialog = FolderPickerDialog(
            self,
            self._t,
            profile_id,
            cfg.folders,
            self._all_folder_candidates,
            self._folder_owners,
            self._profile_titles,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selected = dialog.selected_folders()
        for key, owner in list(self._folder_owners.items()):
            if owner == profile_id:
                self._folder_owners.pop(key, None)
        for folder in selected:
            self._folder_owners[folder.lower()] = profile_id
        cfg.folders = selected
        self._refresh_folder_button(profile_id)

    def _open_key_dialog(self, profile_id: str) -> None:
        current = self._key_bindings.get(profile_id, "")
        dialog = KeyBindingDialog(self, self._t, current)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._key_bindings[profile_id] = dialog.to_binding_text()

    def _open_other_settings_dialog(self, profile_id: str) -> None:
        cfg = self._state.get(profile_id)
        if cfg is None:
            return
        dialog = OtherSettingsDialog(self, self._t, cfg)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        dialog.apply_to(cfg)
        self._state[profile_id] = cfg
        self._refresh_other_button(profile_id)

    def _choose_emulator_path(self, profile_id: str) -> None:
        file_name = QFileDialog.getOpenFileName(self, self._t("dialog.select_emulator_exe"), filter="Executable (*.exe);;All Files (*)")[0]
        if not file_name:
            return
        widgets = self._widgets.get(profile_id)
        if widgets is None:
            return
        path_edit = widgets["path_edit"]
        if isinstance(path_edit, QLineEdit):
            path_edit.setText(file_name)

    def _save_state(self) -> None:
        for profile_id in self._row_profile_ids:
            widgets = self._widgets.get(profile_id)
            if widgets is None:
                continue
            cfg = self._state.get(profile_id, EmulatorProfileConfig())
            external_combo = widgets["external_combo"]
            path_edit = widgets["path_edit"]
            command_edit = widgets["command_edit"]
            core_combo = widgets["core_combo"]
            cfg.use_external = isinstance(external_combo, QComboBox) and external_combo.currentIndex() == 1
            cfg.emulator_path = path_edit.text().strip() if isinstance(path_edit, QLineEdit) else ""
            cfg.launch_command = command_edit.text().strip() if isinstance(command_edit, QLineEdit) else ""
            if not cfg.launch_command:
                cfg.launch_command = '{emulator} "{rom}"'
            cfg.bundled_core_dll = core_combo.currentText().strip() if isinstance(core_combo, QComboBox) else ""
            cfg.bundled_emulator_path = ""
            if not cfg.key_profile:
                cfg.key_profile = "default"
            if not cfg.display_profile:
                cfg.display_profile = "pixel"
            cfg.video_scaling = cfg.video_scaling or "fit"
            cfg.video_filter = cfg.video_filter or "nearest"
            cfg.audio_latency_ms = max(20, min(300, int(cfg.audio_latency_ms or 80)))
            cfg.frame_sync = cfg.frame_sync or "precise"
            cfg.key_bindings = self._key_bindings.get(profile_id, "")
            self._state[profile_id] = cfg

    def _accept_with_save(self) -> None:
        self._save_state()
        self.accept()

    def get_state(self) -> dict[str, EmulatorProfileConfig]:
        self._save_state()
        return copy.deepcopy(self._state)
