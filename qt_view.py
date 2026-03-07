from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEasingCurve, Property, QPropertyAnimation, QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QDialog,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenuBar,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QHeaderView,
    QScrollArea,
    QMenu,
    QStackedLayout,
)

from i18n import LANGUAGE_CHOICES, tr

try:
    import qtawesome
except Exception:
    qtawesome = None


EDIT_KEYS = [
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


class FadeLabel(QLabel):
    double_clicked = Signal()
    resized = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._opacity = 1.0
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._anim = QPropertyAnimation(self, b"opacity")
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

    def get_opacity(self) -> float:
        return self._opacity

    def set_opacity(self, value: float) -> None:
        self._opacity = value
        self._effect.setOpacity(value)

    opacity = Property(float, get_opacity, set_opacity)

    def fade_in(self) -> None:
        self._anim.stop()
        self._anim.setStartValue(0.25)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def mouseDoubleClickEvent(self, event) -> None:
        self.double_clicked.emit()
        super().mouseDoubleClickEvent(event)

    def resizeEvent(self, event) -> None:
        self.resized.emit()
        super().resizeEvent(event)


class IosSwitch(QCheckBox):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._offset = 1.0 if self.isChecked() else 0.0
        self._glow = 0.25
        self._anim = QPropertyAnimation(self, b"offset")
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._glow_anim = QPropertyAnimation(self, b"glow")
        self._glow_anim.setDuration(180)
        self._glow_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.toggled.connect(self._animate_to_state)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setText("")

    def sizeHint(self) -> QSize:
        return QSize(50, 30)

    def minimumSizeHint(self) -> QSize:
        return QSize(50, 30)

    def get_offset(self) -> float:
        return self._offset

    def set_offset(self, value: float) -> None:
        self._offset = value
        self.update()

    offset = Property(float, get_offset, set_offset)

    def get_glow(self) -> float:
        return self._glow

    def set_glow(self, value: float) -> None:
        self._glow = value
        self.update()

    glow = Property(float, get_glow, set_glow)

    def _animate_to_state(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()
        self._glow_anim.stop()
        self._glow_anim.setStartValue(self._glow)
        self._glow_anim.setEndValue(1.0 if checked else 0.2)
        self._glow_anim.start()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.pos()):
            self.setChecked(not self.isChecked())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        _ = event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(2, 2, -2, -2)
        radius = rect.height() / 2
        is_dark = self.palette().window().color().lightness() < 128
        if self.isChecked():
            bg = QColor("#28c9bf") if is_dark else QColor("#4f7fdb")
        else:
            bg = QColor("#4a5874") if is_dark else QColor("#cfd8e7")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, radius, radius)
        knob_diameter = rect.height() - 4
        min_x = rect.x() + 2
        max_x = rect.right() - knob_diameter - 2
        knob_x = min_x + (max_x - min_x) * self._offset
        knob_rect = QRectF(knob_x, rect.y() + 2, knob_diameter, knob_diameter)
        shadow_alpha = 50 + int(50 * self._glow)
        shadow = QColor("#0f1728" if is_dark else "#8894aa")
        shadow.setAlpha(min(140, shadow_alpha))
        shadow_rect = QRectF(knob_rect.x(), knob_rect.y() + 1.5, knob_rect.width(), knob_rect.height())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(shadow)
        painter.drawEllipse(shadow_rect)
        painter.setPen(QPen(QColor(255, 255, 255, 80), 1))
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(knob_rect)


class MainWindow(QMainWindow):
    request_choose_root = Signal()
    request_refresh_systems = Signal()
    request_backup_saves = Signal()
    request_add_rom = Signal()
    request_delete_game = Signal()
    request_rename_game = Signal()
    request_save_metadata = Signal()
    request_toggle_theme = Signal()
    request_system_changed = Signal(str)
    request_search_or_sort = Signal(str)
    request_game_selected = Signal(int)
    request_header_sort = Signal(int)
    request_context_action = Signal(str, int)
    request_preview_image_double_click = Signal()
    request_toggle_favorite = Signal(int)
    request_import_media = Signal(str)
    request_language_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._lang = "zh"
        self.setWindowTitle(self._t("app.title"))
        self.resize(1560, 960)
        self.setMinimumSize(1180, 700)
        self._preview_original = QPixmap()
        self._has_image_media = False
        self._has_video_media = False
        self._show_image_preview = True
        self._preview_panel_visible = True
        self._root_path = "/roms"
        self._build_ui()

    def _icon(self, name: str, fallback: QIcon | None = None) -> QIcon:
        if qtawesome is not None:
            try:
                return qtawesome.icon(name, color="#7aa2f7")
            except Exception:
                pass
        if fallback is not None:
            return fallback
        return QIcon()

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(14, 14, 14, 14)
        root_layout.setSpacing(10)

        menu_bar = QMenuBar()
        self.setMenuBar(menu_bar)
        self.view_menu = menu_bar.addMenu(self._t("menu.view"))
        self.action_toggle_theme = QAction(self._icon("fa5s.adjust"), self._t("action.toggle_theme"), self)
        self.view_menu.addAction(self.action_toggle_theme)
        self.action_toggle_theme.triggered.connect(self.request_toggle_theme.emit)

        top = QFrame()
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(12, 10, 12, 10)
        top_layout.setSpacing(8)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(self._t("search.placeholder"))
        self.search_edit.setToolTip(self._t("search.tooltip"))
        self.btn_choose_root = QPushButton(self._icon("fa5s.folder-open"), self._t("button.choose_root"))
        self.btn_refresh = QPushButton(self._icon("fa5s.sync-alt"), self._t("button.refresh_systems"))
        self.btn_backup = QPushButton(self._icon("fa5s.save"), self._t("button.backup_saves"))
        self.btn_theme = QToolButton()
        self.btn_theme.setIcon(self._icon("fa5s.moon"))
        self.btn_theme.setToolTip(self._t("button.theme.tooltip"))
        self.language_combo = QComboBox()
        for code, name in LANGUAGE_CHOICES:
            self.language_combo.addItem(name, code)
        self.btn_theme.clicked.connect(self.request_toggle_theme.emit)
        top_layout.addWidget(self.search_edit, 2)
        top_layout.addWidget(self.btn_choose_root)
        top_layout.addWidget(self.btn_refresh)
        top_layout.addWidget(self.btn_backup)
        top_layout.addWidget(self.language_combo)
        top_layout.addWidget(self.btn_theme)
        root_layout.addWidget(top)

        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        root_layout.addWidget(main_splitter, 1)

        left_panel = QFrame()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(6)
        self.left_title = QLabel(self._t("title.system_list"))
        self.left_title.setObjectName("sectionTitle")
        left_layout.addWidget(self.left_title)
        self.system_list = QListWidget()
        self.system_list.setToolTip(self._t("tooltip.system_list"))
        left_layout.addWidget(self.system_list, 1)
        main_splitter.addWidget(left_panel)

        center_panel = QFrame()
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(8, 8, 8, 8)
        center_layout.setSpacing(6)
        control_row = QHBoxLayout()
        self.preview_switch_label = QLabel(self._t("label.preview_switch"))
        self.toggle_show_preview_image = IosSwitch()
        self.toggle_show_preview_image.setChecked(True)
        self.btn_add = QPushButton(self._icon("fa5s.plus"), self._t("button.add_rom"))
        self.btn_delete = QPushButton(self._icon("fa5s.trash"), self._t("button.delete_game"))
        self.btn_rename = QPushButton(self._icon("fa5s.i-cursor"), self._t("button.rename_rom"))
        control_row.addWidget(self.preview_switch_label)
        control_row.addWidget(self.toggle_show_preview_image)
        control_row.addStretch(1)
        control_row.addWidget(self.btn_add)
        control_row.addWidget(self.btn_delete)
        control_row.addWidget(self.btn_rename)
        center_layout.addLayout(control_row)
        self.games_table = QTableWidget(0, 6)
        self.games_table.setHorizontalHeaderLabels(
            [
                self._t("table.col.favorite"),
                self._t("table.col.name"),
                self._t("table.col.path"),
                self._t("table.col.playcount"),
                self._t("table.col.rating"),
                self._t("table.col.lastplayed"),
            ]
        )
        self.games_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.games_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.games_table.setAlternatingRowColors(True)
        self.games_table.verticalHeader().setVisible(False)
        header = self.games_table.horizontalHeader()
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.games_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        center_layout.addWidget(self.games_table, 1)
        main_splitter.addWidget(center_panel)

        right_panel = QFrame()
        self.right_splitter = QSplitter(Qt.Orientation.Vertical)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.addWidget(self.right_splitter, 1)

        form_box = QFrame()
        form_layout = QVBoxLayout(form_box)
        form_layout.setContentsMargins(8, 8, 8, 8)
        form_layout.setSpacing(8)
        self.form_title = QLabel(self._t("title.metadata_edit"))
        self.form_title.setObjectName("sectionTitle")
        form_layout.addWidget(self.form_title)
        form_scroll = QScrollArea()
        form_scroll.setWidgetResizable(True)
        form_scroll.setFrameShape(QFrame.Shape.NoFrame)
        form_widget = QWidget()
        form_grid = QFormLayout(form_widget)
        form_grid.setContentsMargins(0, 0, 0, 0)
        form_grid.setHorizontalSpacing(10)
        form_grid.setVerticalSpacing(10)
        form_grid.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form_grid.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form_grid.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.field_widgets: dict[str, QWidget] = {}
        self.field_label_widgets: dict[str, QWidget] = {}
        for key in EDIT_KEYS:
            if key == "desc":
                editor = QPlainTextEdit()
                editor.setMinimumHeight(120)
                editor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            else:
                editor = QLineEdit()
                editor.setMinimumHeight(36)
            label_key = f"label.{key}"
            tooltip_key = f"tooltip.{key}"
            editor.setToolTip(self._t(tooltip_key) if tooltip_key in {"tooltip.image", "tooltip.video", "tooltip.thumbnail"} else self._t(label_key))
            self.field_widgets[key] = editor
            if key in {"image", "video", "thumbnail"}:
                label_btn = QToolButton()
                label_btn.setText(self._t(label_key))
                label_btn.setToolTip(self._t(tooltip_key))
                label_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                label_btn.clicked.connect(lambda _=False, k=key: self.request_import_media.emit(k))
                self.field_label_widgets[key] = label_btn
                form_grid.addRow(label_btn, editor)
            else:
                label_widget = QLabel(self._t(label_key))
                self.field_label_widgets[key] = label_widget
                form_grid.addRow(label_widget, editor)
        form_scroll.setWidget(form_widget)
        form_layout.addWidget(form_scroll, 1)
        self.btn_save = QPushButton(self._icon("fa5s.check"), self._t("button.save_metadata"))
        form_layout.addWidget(self.btn_save, 0, Qt.AlignmentFlag.AlignRight)
        self.right_splitter.addWidget(form_box)

        self.preview_box = QFrame()
        preview_layout = QVBoxLayout(self.preview_box)
        preview_layout.setContentsMargins(8, 8, 8, 8)
        preview_layout.setSpacing(8)
        self.preview_title = QLabel(self._t("title.preview"))
        self.preview_title.setObjectName("sectionTitle")
        preview_layout.addWidget(self.preview_title)
        self.image_preview = FadeLabel()
        self.image_preview.setObjectName("previewLabel")
        self.image_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_preview.setText(self._t("preview.none"))
        self.image_preview.setWordWrap(True)
        self.image_preview.setMinimumHeight(200)
        self.image_preview.setScaledContents(False)
        self.image_preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        preview_layout.addWidget(self.image_preview, 1)
        self.video_layer = QWidget()
        video_stack = QStackedLayout(self.video_layer)
        video_stack.setContentsMargins(0, 0, 0, 0)
        video_stack.setStackingMode(QStackedLayout.StackingMode.StackAll)
        self.video_widget = QVideoWidget()
        self.video_widget.setMinimumHeight(180)
        self.video_player = QMediaPlayer(self)
        self.video_audio = QAudioOutput(self)
        self.video_audio.setVolume(0.9)
        self.video_audio.setMuted(True)
        self.video_player.setAudioOutput(self.video_audio)
        self.video_player.setVideoOutput(self.video_widget)
        self.video_overlay = QWidget()
        overlay_layout = QHBoxLayout(self.video_overlay)
        overlay_layout.setContentsMargins(0, 8, 8, 0)
        overlay_layout.addStretch(1)
        self.btn_toggle_mute = QToolButton(self.video_overlay)
        self.btn_toggle_mute.setObjectName("videoMuteButton")
        self.btn_toggle_mute.setToolTip(self._t("tooltip.video_mute"))
        self.btn_toggle_mute.setIcon(self._icon("fa5s.volume-mute"))
        overlay_layout.addWidget(self.btn_toggle_mute, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        video_stack.addWidget(self.video_widget)
        video_stack.addWidget(self.video_overlay)
        preview_layout.addWidget(self.video_layer, 1)
        self.right_splitter.addWidget(self.preview_box)
        main_splitter.addWidget(right_panel)

        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 3)
        main_splitter.setStretchFactor(2, 3)
        self.right_splitter.setStretchFactor(0, 3)
        self.right_splitter.setStretchFactor(1, 2)
        main_splitter.setSizes([260, 680, 700])
        self.right_splitter.setSizes([540, 360])

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.path_info_label = QLabel()
        self.status.addWidget(self.path_info_label, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(False)
        self.progress.setMaximumWidth(220)
        self.status.addPermanentWidget(self.progress)
        self.status.showMessage(self._t("status.ready"))

        self.btn_choose_root.clicked.connect(self.request_choose_root.emit)
        self.btn_refresh.clicked.connect(self.request_refresh_systems.emit)
        self.btn_backup.clicked.connect(self.request_backup_saves.emit)
        self.btn_add.clicked.connect(self.request_add_rom.emit)
        self.btn_delete.clicked.connect(self.request_delete_game.emit)
        self.btn_rename.clicked.connect(self.request_rename_game.emit)
        self.btn_save.clicked.connect(self.request_save_metadata.emit)
        self.system_list.currentTextChanged.connect(self.request_system_changed.emit)
        self.search_edit.textChanged.connect(self.request_search_or_sort.emit)
        self.toggle_show_preview_image.toggled.connect(self._on_toggle_show_preview_image)
        self.games_table.itemSelectionChanged.connect(self._emit_selected_game_row)
        self.games_table.cellClicked.connect(self._on_table_cell_clicked)
        self.games_table.horizontalHeader().sectionClicked.connect(self.request_header_sort.emit)
        self.games_table.customContextMenuRequested.connect(self._open_games_context_menu)
        self.image_preview.double_clicked.connect(self.request_preview_image_double_click.emit)
        self.image_preview.resized.connect(self._update_preview_image_display)
        self.btn_toggle_mute.clicked.connect(self._toggle_video_mute)
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        self.video_layer.setVisible(False)
        self.btn_toggle_mute.setVisible(False)
        self.image_preview.setVisible(False)
        self.set_root_path(self._root_path)
        self._update_preview_panel_visibility()

    def _emit_selected_game_row(self) -> None:
        row = self.games_table.currentRow()
        if row >= 0:
            self.request_game_selected.emit(row)

    def _on_table_cell_clicked(self, row: int, column: int) -> None:
        if column == 0:
            self.request_toggle_favorite.emit(row)

    def _on_language_changed(self, index: int) -> None:
        code = self.language_combo.itemData(index)
        if isinstance(code, str):
            self.request_language_changed.emit(code)

    def _open_games_context_menu(self, pos) -> None:
        item = self.games_table.itemAt(pos)
        if item is None:
            return
        row = item.row()
        menu = QMenu(self)
        open_rom_dir = menu.addAction(self._t("context.open_rom_dir"))
        open_image_dir = menu.addAction(self._t("context.open_image_dir"))
        open_video_dir = menu.addAction(self._t("context.open_video_dir"))
        menu.addSeparator()
        delete_action = menu.addAction(self._t("context.delete"))
        favorite_action = menu.addAction(self._t("context.favorite"))
        feature_action = menu.addAction(self._t("context.feature"))
        chosen = menu.exec(self.games_table.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == open_rom_dir:
            self.request_context_action.emit("open_rom_dir", row)
        elif chosen == open_image_dir:
            self.request_context_action.emit("open_image_dir", row)
        elif chosen == open_video_dir:
            self.request_context_action.emit("open_video_dir", row)
        elif chosen == delete_action:
            self.request_context_action.emit("delete", row)
        elif chosen == favorite_action:
            self.request_context_action.emit("favorite", row)
        elif chosen == feature_action:
            self.request_context_action.emit("feature", row)

    def choose_directory(self) -> str:
        return QFileDialog.getExistingDirectory(self, self._t("dialog.select_root"))

    def choose_file(self, title: str, filter_text: str = "") -> str:
        return QFileDialog.getOpenFileName(self, title, filter=filter_text)[0]

    def set_root_path(self, path: str) -> None:
        self._root_path = path
        self.path_info_label.setText(self._t("status.rom_path", path=path))

    def set_language(self, lang: str) -> None:
        self._lang = lang
        idx = self.language_combo.findData(lang)
        if idx >= 0 and idx != self.language_combo.currentIndex():
            self.language_combo.setCurrentIndex(idx)
        self._apply_language()

    def _apply_language(self) -> None:
        self.setWindowTitle(self._t("app.title"))
        self.view_menu.setTitle(self._t("menu.view"))
        self.action_toggle_theme.setText(self._t("action.toggle_theme"))
        self.search_edit.setPlaceholderText(self._t("search.placeholder"))
        self.search_edit.setToolTip(self._t("search.tooltip"))
        self.btn_choose_root.setText(self._t("button.choose_root"))
        self.btn_refresh.setText(self._t("button.refresh_systems"))
        self.btn_backup.setText(self._t("button.backup_saves"))
        self.btn_add.setText(self._t("button.add_rom"))
        self.btn_delete.setText(self._t("button.delete_game"))
        self.btn_rename.setText(self._t("button.rename_rom"))
        self.btn_save.setText(self._t("button.save_metadata"))
        self.btn_theme.setToolTip(self._t("button.theme.tooltip"))
        self.left_title.setText(self._t("title.system_list"))
        self.system_list.setToolTip(self._t("tooltip.system_list"))
        self.form_title.setText(self._t("title.metadata_edit"))
        self.preview_title.setText(self._t("title.preview"))
        self.preview_switch_label.setText(self._t("label.preview_switch"))
        self.btn_toggle_mute.setToolTip(self._t("tooltip.video_mute"))
        self.games_table.setHorizontalHeaderLabels(
            [
                self._t("table.col.favorite"),
                self._t("table.col.name"),
                self._t("table.col.path"),
                self._t("table.col.playcount"),
                self._t("table.col.rating"),
                self._t("table.col.lastplayed"),
            ]
        )
        for key, label_widget in self.field_label_widgets.items():
            text = self._t(f"label.{key}")
            label_widget.setText(text)
            if key in {"image", "video", "thumbnail"}:
                label_widget.setToolTip(self._t(f"tooltip.{key}"))
        self.set_root_path(self._root_path)
        if self._preview_original.isNull():
            self.image_preview.setText(self._t("preview.none"))

    def _t(self, key: str, **kwargs) -> str:
        return tr(self._lang, key, **kwargs)

    def get_root_path(self) -> str:
        return self._root_path

    def set_systems(self, systems: list[str]) -> None:
        self.system_list.clear()
        self.system_list.addItems(systems)

    def set_games(self, rows: list[tuple[str, str, str, str, str, str]], group_rows: set[int] | None = None) -> None:
        groups = group_rows or set()
        self.games_table.blockSignals(True)
        self.games_table.setUpdatesEnabled(False)
        self.games_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                item = QTableWidgetItem(value)
                if c == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if r in groups:
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                    item.setBackground(QColor(60, 78, 106, 95))
                    if c in {0, 2, 3, 4, 5}:
                        item.setText("")
                self.games_table.setItem(r, c, item)
        self.games_table.clearSelection()
        self.games_table.setCurrentCell(-1, -1)
        self.games_table.setUpdatesEnabled(True)
        self.games_table.blockSignals(False)

    def set_header_sort_indicator(self, column: int, ascending: bool) -> None:
        order = Qt.SortOrder.AscendingOrder if ascending else Qt.SortOrder.DescendingOrder
        self.games_table.horizontalHeader().setSortIndicator(column, order)

    def clear_edit_form(self) -> None:
        for key, widget in self.field_widgets.items():
            if key == "desc":
                widget.setPlainText("")
            else:
                widget.setText("")
        self.clear_preview()

    def set_edit_form(self, data: dict[str, str]) -> None:
        for key, widget in self.field_widgets.items():
            value = data.get(key, "")
            if key == "desc":
                widget.setPlainText(value)
            else:
                widget.setText(value)

    def get_edit_form(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for key, widget in self.field_widgets.items():
            if key == "desc":
                result[key] = widget.toPlainText()
            else:
                result[key] = widget.text()
        return result

    def set_busy(self, busy: bool, text: str) -> None:
        self.progress.setVisible(busy)
        if busy:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
        self.status.showMessage(text)

    def notify(self, title: str, message: str, error: bool = False) -> None:
        if error:
            QMessageBox.critical(self, title, message)
        else:
            QMessageBox.information(self, title, message)

    def ask_yes_no(self, title: str, message: str) -> bool:
        return QMessageBox.question(self, title, message) == QMessageBox.StandardButton.Yes

    def ask_text(self, title: str, label: str, value: str) -> str:
        from PySide6.QtWidgets import QInputDialog

        text, ok = QInputDialog.getText(self, title, label, text=value)
        if not ok:
            return ""
        return text

    def set_preview_image(self, pixmap: QPixmap | None, fallback_text: str) -> None:
        if pixmap is None:
            self._preview_original = QPixmap()
            self._has_image_media = False
            self.image_preview.setText(fallback_text)
            self.image_preview.setPixmap(QPixmap())
            self.image_preview.setVisible(False)
            self._update_preview_panel_visibility()
            return
        self._preview_original = QPixmap(pixmap)
        self._has_image_media = True
        self.image_preview.setVisible(self._show_image_preview)
        self._update_preview_image_display()
        self.image_preview.fade_in()
        self._update_preview_panel_visibility()

    def _update_preview_image_display(self) -> None:
        if self._preview_original.isNull():
            return
        view_size = self.image_preview.contentsRect().size()
        if view_size.width() <= 0 or view_size.height() <= 0:
            return
        scaled = self._preview_original.scaled(
            view_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_preview.setText("")
        self.image_preview.setPixmap(scaled)

    def clear_preview(self) -> None:
        self._preview_original = QPixmap()
        self._has_image_media = False
        self._has_video_media = False
        self.image_preview.setText(self._t("preview.none"))
        self.image_preview.setPixmap(QPixmap())
        self.video_player.stop()
        self.video_player.setSource(QUrl())
        self.video_layer.setVisible(False)
        self.btn_toggle_mute.setVisible(False)
        self.image_preview.setVisible(False)
        self._update_preview_panel_visibility()

    def set_preview_video(self, file_path: Path | None) -> None:
        if file_path is None:
            self._has_video_media = False
            self.video_player.stop()
            self.video_player.setSource(QUrl())
            self.video_layer.setVisible(False)
            self.btn_toggle_mute.setVisible(False)
            self._update_preview_panel_visibility()
            return
        self._has_video_media = True
        self.video_player.stop()
        self.video_player.setSource(QUrl.fromLocalFile(str(file_path)))
        self.video_audio.setMuted(True)
        self._sync_video_mute_icon()
        self.video_player.play()
        self.video_layer.setVisible(True)
        self.btn_toggle_mute.setVisible(True)
        self.video_widget.setToolTip(str(file_path))
        self._update_preview_panel_visibility()

    def show_preview_image_dialog(self) -> None:
        if self._preview_original.isNull():
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(self._t("dialog.preview_image"))
        dialog.resize(1200, 800)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(10, 10, 10, 10)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QLabel()
        content.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content.setPixmap(self._preview_original)
        scroll.setWidget(content)
        layout.addWidget(scroll)
        dialog.exec()

    def _on_toggle_show_preview_image(self, checked: bool) -> None:
        self._show_image_preview = checked
        if self._has_image_media:
            self.image_preview.setVisible(checked)
        else:
            self.image_preview.setVisible(False)
        self._update_preview_image_display()
        self._update_preview_panel_visibility()

    def _toggle_video_mute(self) -> None:
        self.video_audio.setMuted(not self.video_audio.isMuted())
        self._sync_video_mute_icon()

    def _sync_video_mute_icon(self) -> None:
        if self.video_audio.isMuted():
            self.btn_toggle_mute.setIcon(self._icon("fa5s.volume-mute"))
        else:
            self.btn_toggle_mute.setIcon(self._icon("fa5s.volume-up"))

    def _update_preview_panel_visibility(self) -> None:
        show_image = self._has_image_media and self._show_image_preview
        show_video = self._has_video_media
        should_show_panel = show_image or show_video
        self.preview_box.setVisible(should_show_panel)
        self.image_preview.setVisible(show_image)
        self.video_layer.setVisible(show_video)
        self.btn_toggle_mute.setVisible(show_video)
        if should_show_panel and not self._preview_panel_visible:
            self.right_splitter.setSizes([540, 360])
        if not should_show_panel:
            self.right_splitter.setSizes([1000, 0])
        self._preview_panel_visible = should_show_panel

    def apply_stylesheet(self, qss: str) -> None:
        QApplication.instance().setStyleSheet(qss)
