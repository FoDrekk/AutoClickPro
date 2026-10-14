"""Main application window and user controls."""

from __future__ import annotations

import os
import time
from collections import deque

from PySide6.QtCore import Qt, QSettings, Slot
from PySide6.QtGui import QColor, QIcon, QPalette, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)
from pynput.mouse import Controller

from autoclick_pro import __version__
from autoclick_pro.click_engine import ClickEngine
from autoclick_pro.global_hotkeys import KEY_NAMES, GlobalHotkeys

_ACCENT = "#2f81f7"
_ACCENT_END = "#7c5cff"

_STATUS = {
    "idle": ("rgba(139,147,163,0.12)", "#a8b0bd"),
    "run": ("rgba(63,185,80,0.12)", "#57ab5f"),
    "pause": ("rgba(210,153,34,0.12)", "#c79a3a"),
    "stop": ("rgba(248,81,73,0.12)", "#e05a52"),
    "done": ("rgba(88,140,255,0.12)", "#7aa5f0"),
    "error": ("rgba(248,81,73,0.12)", "#e05a52"),
}

_DARK_QSS = """
QGroupBox {
    background: #1e2129;
    border: 1px solid #2c313c;
    border-radius: 4px;
    margin-top: 12px;
    padding: 12px 12px 10px 12px;
    font-size: 13px;
    font-weight: 600;
    color: #c8cdd6;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 4px;
}
QSpinBox, QDoubleSpinBox, QComboBox {
    background: #15171d;
    border: 1px solid #333947;
    border-radius: 4px;
    padding: 5px 8px;
    color: #dce1ea;
    selection-background-color: #2563c9;
    min-height: 22px;
}
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border: 1px solid #2563c9;
}
QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {
    color: #6a7180;
}
QComboBox QAbstractItemView {
    background: #15171d;
    color: #dce1ea;
    selection-background-color: #2563c9;
    border: 1px solid #333947;
}
QCheckBox {
    color: #dce1ea;
    spacing: 8px;
    font-size: 13px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #4a5162;
    background: #15171d;
}
QCheckBox::indicator:checked {
    background: #2563c9;
    border: 1px solid #2563c9;
}
QCheckBox::indicator:disabled {
    background: #1a1d24;
    border: 1px solid #262b36;
}
QSlider::groove:horizontal {
    height: 4px;
    background: #333947;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: #2563c9;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    width: 14px;
    height: 14px;
    background: #dce1ea;
    border-radius: 7px;
    margin: -5px 0;
}
QSlider::handle:horizontal:hover {
    background: #ffffff;
}
QPushButton#primary {
    background: #2563c9;
    color: white;
    font-size: 14px;
    font-weight: 600;
    border: 1px solid #2563c9;
    border-radius: 4px;
    padding: 10px 14px;
}
QPushButton#primary:hover {
    background: #1d4fa3;
}
QPushButton#primary:disabled {
    background: #2c313c;
    color: #6a7180;
    border-color: #2c313c;
}
QPushButton#danger {
    background: #b02a25;
    color: white;
    font-size: 13px;
    font-weight: 600;
    border: 1px solid #b02a25;
    border-radius: 4px;
    padding: 10px 14px;
}
QPushButton#danger:hover {
    background: #8f221e;
}
QPushButton#ghost {
    background: #15171d;
    color: #dce1ea;
    border: 1px solid #333947;
    border-radius: 4px;
    padding: 7px 12px;
}
QPushButton#ghost:hover {
    border: 1px solid #4a5162;
    color: #ffffff;
}
QPushButton#primary:focus, QPushButton#danger:focus, QPushButton#ghost:focus {
    border: 1px solid #dce1ea;
}
QMenu {
    background: #1e2129;
    color: #dce1ea;
    border: 1px solid #2c313c;
}
QMenu::item {
    padding: 5px 12px;
}
QMenu::item:selected {
    background: #2563c9;
}
QProgressBar {
    background: #15171d;
    border: 1px solid #333947;
    border-radius: 2px;
    max-height: 10px;
    text-visible: false;
}
QProgressBar::chunk {
    background: #2563c9;
    border-radius: 2px;
}
QScrollArea {
    background: transparent;
}
QScrollBar:vertical {
    background: transparent;
    width: 12px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #333947;
    min-height: 40px;
}
QScrollBar::handle:vertical:hover {
    background: #4a5162;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
"""

_LIGHT_SWAP = {
    "#1e2129": "#ffffff",
    "#2c313c": "#d5dae2",
    "#15171d": "#f5f6f9",
    "#333947": "#c2c9d4",
    "#4a5162": "#9aa3b0",
    "#1a1d24": "#e9ebf0",
    "#262b36": "#d5dae2",
    "#dce1ea": "#1a1a1a",
    "#c8cdd6": "#3c4350",
    "#6a7180": "#9aa0a6",
}

_LIGHT_QSS = _DARK_QSS
for _dark_hex, _light_hex in _LIGHT_SWAP.items():
    _LIGHT_QSS = _LIGHT_QSS.replace(_dark_hex, _light_hex)

_DEFAULT_STYLE = None
_DEFAULT_PALETTE = None


def _palette(ink: str, faint: str, window: str, base: str, alt: str, button: str) -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(window))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(ink))
    palette.setColor(QPalette.ColorRole.Base, QColor(base))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(alt))
    palette.setColor(QPalette.ColorRole.Text, QColor(ink))
    palette.setColor(QPalette.ColorRole.Button, QColor(button))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(ink))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#2f81f7"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Link, QColor("#58a6ff"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(button))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(ink))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(faint))
    disabled = QPalette.ColorGroup.Disabled
    palette.setColor(disabled, QPalette.ColorRole.WindowText, QColor(faint))
    palette.setColor(disabled, QPalette.ColorRole.Text, QColor(faint))
    palette.setColor(disabled, QPalette.ColorRole.ButtonText, QColor(faint))
    return palette


def set_app_theme(app: QApplication, mode: str) -> str:
    global _DEFAULT_STYLE, _DEFAULT_PALETTE
    if _DEFAULT_STYLE is None:
        _DEFAULT_STYLE = app.style().objectName()
        _DEFAULT_PALETTE = QPalette(app.palette())
    if mode == "light":
        app.setStyle("Fusion")
        app.setPalette(
            _palette("#1a1a1a", "#9aa0a6", "#f0f0f0", "#ffffff", "#f5f5f5", "#f0f0f0")
        )
        return _LIGHT_QSS
    if mode == "system":
        app.setStyle(_DEFAULT_STYLE)
        app.setPalette(_DEFAULT_PALETTE)
        return ""
    app.setStyle("Fusion")
    app.setPalette(
        _palette("#e8ebf0", "#5b6270", "#121418", "#1a1d23", "#20242c", "#23262e")
    )
    return _DARK_QSS


def _is_admin() -> bool:
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("AutoClick Pro")
        self.setWindowIcon(QIcon(self._icon_path()))
        self.setMinimumSize(600, 420)
        self.resize(620, 720)
        self._settings = QSettings("AutoClick Pro", "AutoClick Pro")
        self._target_clicks: int | None = None
        self._quit_requested = False
        self._status_kind = "idle"
        self._click_times: deque[float] = deque()
        self._session_total = 0
        self._last_count = 0

        self.engine = ClickEngine(self)
        self.hotkeys = GlobalHotkeys(self.engine.emergency_stop, self)
        self._fixed_position: tuple[int, int] | None = None

        self._build_ui()
        self._load_settings()
        self.interval_spin.valueChanged.connect(self.engine.set_interval_ms)
        self.interval_spin.valueChanged.connect(self._on_interval_spin)
        self.interval_slider.valueChanged.connect(self._on_interval_slider)
        self.button_combo.currentIndexChanged.connect(self._sync_button)
        self.double_check.toggled.connect(self.engine.set_double_click)
        self.failsafe_check.toggled.connect(self.engine.set_failsafe)
        self.toggle_combo.currentIndexChanged.connect(self._sync_hotkeys)
        self.stop_combo.currentIndexChanged.connect(self._sync_hotkeys)
        queued = Qt.ConnectionType.QueuedConnection
        self.engine.click_count_changed.connect(self._update_click_count, queued)
        self.engine.error_occurred.connect(self._on_engine_error, queued)
        self.engine.limit_reached.connect(self._on_limit_reached, queued)
        self.hotkeys.toggle_requested.connect(self._toggle_clicking, queued)
        self.hotkeys.emergency_stop_requested.connect(self._on_global_emergency_stop, queued)
        self.hotkeys.error_occurred.connect(self._on_hotkey_error, queued)
        self.top_check.toggled.connect(self._apply_always_on_top)
        self.theme_combo.currentIndexChanged.connect(self._apply_theme)
        self._setup_tray()
        self.hotkeys.start()

    def _make_card(self, title: str) -> tuple[QGroupBox, QFormLayout]:
        group = QGroupBox(title)
        form = QFormLayout(group)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return group, form

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(14)
        self.logo_label = QLabel()
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        logo_path = os.path.join(base, "assets", "icon.png")
        if not os.path.isfile(logo_path):
            logo_path = os.path.join(base, "assets", "icon.ico")
        if os.path.isfile(logo_path):
            pix = QPixmap(logo_path).scaled(
                46, 46, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.logo_label.setPixmap(pix)
        self.logo_label.setFixedSize(46, 46)
        header.addWidget(self.logo_label)
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        self._heading = QLabel("AutoClick Pro")
        self._heading.setStyleSheet("font-size: 22px; font-weight: 700;")
        self._subtitle = QLabel("Automatic clicks for Windows")
        self._subtitle.setStyleSheet("font-size: 13px;")
        title_box.addWidget(self._heading)
        title_box.addWidget(self._subtitle)
        header.addLayout(title_box, 1)
        self.version_pill = QLabel(f"v{__version__}")
        self.version_pill.setStyleSheet(
            "font-size: 12px; font-weight: 700; border-radius: 10px; padding: 5px 12px;"
        )
        header.addWidget(self.version_pill, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        self.hero = QGroupBox()
        self.hero.setStyleSheet("QGroupBox { border: 0; margin-top: 0; padding: 18px; }")
        hero_layout = QVBoxLayout(self.hero)
        hero_layout.setContentsMargins(18, 18, 18, 18)
        hero_layout.setSpacing(10)
        self.status_label = QLabel("Status: Stopped")
        self.status_label.setWordWrap(True)
        self._set_status("Status: Stopped", "idle")
        hero_layout.addWidget(self.status_label)
        hero_row = QHBoxLayout()
        hero_row.setSpacing(18)
        counter_box = QVBoxLayout()
        counter_box.setSpacing(0)
        self.count_label = QLabel("0")
        self.count_label.setStyleSheet("font-size: 30px; font-weight: 700;")
        counter_box.addWidget(self.count_label)
        self.stats_label = QLabel("0/min · session 0")
        self.stats_label.setStyleSheet("font-size: 12px; font-weight: 600;")
        counter_box.addWidget(self.stats_label)
        hero_row.addLayout(counter_box, 1)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        hero_row.addWidget(self.progress_bar, 1)
        hero_layout.addLayout(hero_row)
        layout.addWidget(self.hero)

        controls = QHBoxLayout()
        controls.setSpacing(12)
        self.toggle_button = QPushButton("Start")
        self.toggle_button.setObjectName("primary")
        self.toggle_button.setMinimumHeight(48)
        self.toggle_button.clicked.connect(self._toggle_clicking)
        self.stop_button = QPushButton("Emergency Stop")
        self.stop_button.setObjectName("danger")
        self.stop_button.setMinimumHeight(48)
        self.stop_button.clicked.connect(self._emergency_stop)
        controls.addWidget(self.toggle_button, 1)
        controls.addWidget(self.stop_button, 1)
        layout.addLayout(controls)

        interval_group, interval_form = self._make_card("Interval")
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(10, 3_600_000)
        self.interval_spin.setValue(100)
        self.interval_spin.setSuffix(" ms")
        self.interval_spin.setMinimumWidth(110)
        self.interval_spin.setToolTip("Delay between clicks. Minimum 10 milliseconds.")
        self.interval_slider = QSlider(Qt.Orientation.Horizontal)
        self.interval_slider.setRange(10, 2000)
        self.interval_slider.setValue(100)
        self.interval_slider.setToolTip("Drag to tune the interval. Range 10–2000 ms.")
        spin_row = QHBoxLayout()
        spin_row.setSpacing(12)
        spin_row.addWidget(self.interval_spin, 0)
        spin_row.addWidget(self.interval_slider, 1)
        interval_form.addRow("Click every:", spin_row)
        layout.addWidget(interval_group)

        click_group, click_form = self._make_card("Click")
        self.button_combo = QComboBox()
        self.button_combo.addItem("Left button", "left")
        self.button_combo.addItem("Right button", "right")
        self.button_combo.addItem("Middle button", "middle")
        self.double_check = QCheckBox("Double-click (2 presses per cycle)")
        click_form.addRow("Button:", self.button_combo)
        click_form.addRow("", self.double_check)
        layout.addWidget(click_group)

        position_group, position_form = self._make_card("Click position")
        self.position_combo = QComboBox()
        self.position_combo.addItem("At cursor position", "cursor")
        self.position_combo.addItem("At fixed coordinates", "fixed")
        self.position_combo.currentIndexChanged.connect(self._sync_position)
        self.position_label = QLabel("Not set")
        self.position_label.setStyleSheet("color: #58a6ff; font-size: 13px; font-weight: 600;")
        self.position_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.capture_button = QPushButton("Capture position")
        self.capture_button.setObjectName("ghost")
        self.capture_button.clicked.connect(self._capture_position)
        position_form.addRow("Mode:", self.position_combo)
        position_form.addRow("Coordinates:", self.position_label)
        position_form.addRow("", self.capture_button)
        layout.addWidget(position_group)

        limits_group, limits_form = self._make_card("Limits and safety")
        self.max_clicks_spin = QSpinBox()
        self.max_clicks_spin.setRange(0, 1_000_000)
        self.max_clicks_spin.setSpecialValueText("Unlimited")
        self.max_clicks_spin.setSuffix(" clicks")
        self.max_clicks_spin.setToolTip("Stop automatically after this many clicks. 0 means no limit.")
        self.max_seconds_spin = QDoubleSpinBox()
        self.max_seconds_spin.setRange(0, 86400)
        self.max_seconds_spin.setDecimals(1)
        self.max_seconds_spin.setSpecialValueText("Unlimited")
        self.max_seconds_spin.setSuffix(" s")
        self.max_seconds_spin.setToolTip("Stop automatically after this many seconds. 0 means no limit.")
        self.failsafe_check = QCheckBox("Stop at top-left corner")
        self.failsafe_check.setToolTip("Slam the cursor into the top-left corner to halt clicking.")
        limits_form.addRow("Max clicks:", self.max_clicks_spin)
        limits_form.addRow("Max duration:", self.max_seconds_spin)
        limits_form.addRow("", self.failsafe_check)
        layout.addWidget(limits_group)

        window_group, window_form = self._make_card("Window and feedback")
        self.sound_check = QCheckBox("Sound on start/stop")
        self.sound_check.setChecked(True)
        self.top_check = QCheckBox("Always on top")
        self.tray_check = QCheckBox("Minimize to tray on close")
        self.tray_check.setToolTip("Closing the window minimizes to tray instead of quitting.")
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Dark", "dark")
        self.theme_combo.addItem("Light", "light")
        self.theme_combo.addItem("System", "system")
        window_form.addRow("", self.sound_check)
        window_form.addRow("", self.top_check)
        window_form.addRow("", self.tray_check)
        window_form.addRow("Theme:", self.theme_combo)
        layout.addWidget(window_group)

        hotkeys_group, hotkeys_form = self._make_card("Hotkeys")
        self.toggle_combo = QComboBox()
        self.stop_combo = QComboBox()
        for name in KEY_NAMES:
            self.toggle_combo.addItem(name.upper(), name)
            self.stop_combo.addItem(name.upper(), name)
        self.toggle_combo.setCurrentIndex(self.toggle_combo.findData("f6"))
        self.stop_combo.setCurrentIndex(self.stop_combo.findData("f12"))
        hotkeys_form.addRow("Start/pause:", self.toggle_combo)
        hotkeys_form.addRow("Emergency stop:", self.stop_combo)
        layout.addWidget(hotkeys_group)

        profiles_group, profiles_form = self._make_card("Profiles")
        self.profile_combo = QComboBox()
        self.profile_combo.currentIndexChanged.connect(self._load_profile)
        profile_buttons = QHBoxLayout()
        profile_buttons.setSpacing(8)
        self.profile_save_button = QPushButton("Save")
        self.profile_save_button.setObjectName("ghost")
        self.profile_save_button.clicked.connect(self._save_profile)
        self.profile_delete_button = QPushButton("Delete")
        self.profile_delete_button.setObjectName("ghost")
        self.profile_delete_button.clicked.connect(self._delete_profile)
        profile_buttons.addWidget(self.profile_save_button, 1)
        profile_buttons.addWidget(self.profile_delete_button, 1)
        profiles_form.addRow("Preset:", self.profile_combo)
        profiles_form.addRow("", profile_buttons)
        layout.addWidget(profiles_group)

        self.hotkey_note = QLabel("Global hotkeys: F6 start/pause · F12 emergency stop")
        self.hotkey_note.setWordWrap(True)
        self.hotkey_note.setStyleSheet("color: #8b93a3; font-size: 12px;")
        footer = QHBoxLayout()
        footer.addWidget(self.hotkey_note, 1)
        self.about_button = QPushButton("About")
        self.about_button.setObjectName("ghost")
        self.about_button.setMaximumWidth(110)
        self.about_button.clicked.connect(self._show_about)
        footer.addWidget(self.about_button)
        layout.addLayout(footer)
        layout.addStretch(1)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(root)
        self.setCentralWidget(scroll)

    def _set_status(self, text: str, kind: str) -> None:
        self._status_kind = kind
        bg, fg = _STATUS.get(kind, _STATUS["idle"])
        self.status_label.setText(text)
        self.status_label.setStyleSheet(
            f"background: {bg}; color: {fg}; font-size: 13px; "
            "font-weight: 700; border-radius: 10px; padding: 8px 12px;"
        )

    def _settings_dict(self, prefix: str = "") -> dict:
        s = self._settings
        p = f"{prefix}/" if prefix else ""
        return {
            "interval": int(s.value(p + "interval", 100)),
            "mode": str(s.value(p + "mode", "cursor")),
            "fixedX": s.value(p + "fixedX", None),
            "fixedY": s.value(p + "fixedY", None),
            "button": str(s.value(p + "button", "left")),
            "double": str(s.value(p + "double", "false")).lower() == "true",
            "maxClicks": int(s.value(p + "maxClicks", 0)),
            "maxSeconds": float(s.value(p + "maxSeconds", 0)),
            "failsafe": str(s.value(p + "failsafe", "false")).lower() == "true",
            "sound": str(s.value(p + "sound", "true")).lower() == "true",
            "alwaysOnTop": str(s.value(p + "alwaysOnTop", "false")).lower() == "true",
            "minimizeToTray": str(s.value(p + "minimizeToTray", "false")).lower() == "true",
            "theme": str(s.value(p + "theme", "dark")),
            "toggleKey": str(s.value(p + "toggleKey", "f6")),
            "stopKey": str(s.value(p + "stopKey", "f12")),
        }

    def _collect_settings(self) -> dict:
        d = {
            "interval": self.interval_spin.value(),
            "mode": self.position_combo.currentData(),
            "button": self.button_combo.currentData(),
            "double": self.double_check.isChecked(),
            "maxClicks": self.max_clicks_spin.value(),
            "maxSeconds": self.max_seconds_spin.value(),
            "failsafe": self.failsafe_check.isChecked(),
            "sound": self.sound_check.isChecked(),
            "alwaysOnTop": self.top_check.isChecked(),
            "minimizeToTray": self.tray_check.isChecked(),
            "theme": self.theme_combo.currentData(),
            "toggleKey": self.toggle_combo.currentData(),
            "stopKey": self.stop_combo.currentData(),
        }
        if self._fixed_position is not None:
            d["fixedX"] = self._fixed_position[0]
            d["fixedY"] = self._fixed_position[1]
        return d

    def _apply_dict(self, d: dict) -> None:
        self.interval_spin.setValue(int(d.get("interval", 100)))
        mode = str(d.get("mode", "cursor"))
        self.position_combo.setCurrentIndex(1 if mode == "fixed" else 0)
        fx, fy = d.get("fixedX"), d.get("fixedY")
        if fx is not None and fy is not None:
            try:
                self._fixed_position = (int(fx), int(fy))  # type: ignore[arg-type]
                x, y = self._fixed_position
                self.position_label.setText(f"X: {x}   Y: {y}")
            except (TypeError, ValueError):
                self._fixed_position = None
        button = str(d.get("button", "left"))
        idx = self.button_combo.findData(button)
        self.button_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.double_check.setChecked(bool(d.get("double", False)))
        self.max_clicks_spin.setValue(int(d.get("maxClicks", 0)))
        self.max_seconds_spin.setValue(float(d.get("maxSeconds", 0)))
        self.failsafe_check.setChecked(bool(d.get("failsafe", False)))
        self.sound_check.setChecked(bool(d.get("sound", True)))
        self.top_check.setChecked(bool(d.get("alwaysOnTop", False)))
        self.tray_check.setChecked(bool(d.get("minimizeToTray", False)))
        self.theme_combo.blockSignals(True)
        theme = str(d.get("theme", "dark"))
        ti = self.theme_combo.findData(theme)
        self.theme_combo.setCurrentIndex(ti if ti >= 0 else 0)
        self.theme_combo.blockSignals(False)
        self._apply_theme()
        self.toggle_combo.blockSignals(True)
        self.stop_combo.blockSignals(True)
        toggle = str(d.get("toggleKey", "f6"))
        stop = str(d.get("stopKey", "f12"))
        ti = self.toggle_combo.findData(toggle)
        si = self.stop_combo.findData(stop)
        self.toggle_combo.setCurrentIndex(ti if ti >= 0 else self.toggle_combo.findData("f6"))
        self.stop_combo.setCurrentIndex(si if si >= 0 else self.stop_combo.findData("f12"))
        self.toggle_combo.blockSignals(False)
        self.stop_combo.blockSignals(False)
        self._apply_always_on_top()
        self._sync_position()
        self._sync_button()
        self._sync_hotkeys()
        self.engine.set_double_click(self.double_check.isChecked())
        self.engine.set_failsafe(self.failsafe_check.isChecked())

    def _load_settings(self) -> None:
        self._apply_dict(self._settings_dict())
        self._refresh_profiles()

    def _save_settings(self) -> None:
        s = self._settings
        for key, value in self._collect_settings().items():
            s.setValue(key, value)
        if self._fixed_position is None:
            s.remove("fixedX")
            s.remove("fixedY")
        s.sync()

    def _refresh_profiles(self, select: str | None = None) -> None:
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self._settings.beginGroup("profiles")
        names = sorted(self._settings.childGroups())
        self._settings.endGroup()
        for name in names:
            self.profile_combo.addItem(name, name)
        if not names:
            self.profile_combo.addItem("(No profiles saved)", None)
        self.profile_combo.setEnabled(bool(names))
        if select is not None:
            idx = self.profile_combo.findData(select)
            if idx >= 0:
                self.profile_combo.setCurrentIndex(idx)
        self.profile_combo.blockSignals(False)

    @Slot()
    def _save_profile(self) -> None:
        name, ok = QInputDialog.getText(self, "Save profile", "Profile name:")
        name = name.strip()
        if not ok or not name:
            return
        if self.profile_combo.findData(name) >= 0:
            answer = QMessageBox.question(
                self,
                "Overwrite profile",
                f"Profile '{name}' exists. Overwrite?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        for key, value in self._collect_settings().items():
            self._settings.setValue(f"profiles/{name}/{key}", value)
        if self._fixed_position is None:
            self._settings.remove(f"profiles/{name}/fixedX")
            self._settings.remove(f"profiles/{name}/fixedY")
        self._settings.sync()
        self._refresh_profiles(select=name)

    @Slot(int)
    def _load_profile(self, index: int) -> None:
        if index < 0:
            return
        name = self.profile_combo.itemData(index)
        if not name:
            return
        self._apply_dict(self._settings_dict(f"profiles/{name}"))

    @Slot()
    def _delete_profile(self) -> None:
        name = self.profile_combo.currentData()
        if not name:
            return
        answer = QMessageBox.question(
            self,
            "Delete profile",
            f"Delete profile '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._settings.remove(f"profiles/{name}")
        self._settings.sync()
        self._refresh_profiles()

    def _on_interval_spin(self, value: int) -> None:
        self.interval_slider.blockSignals(True)
        self.interval_slider.setValue(max(10, min(2000, int(value))))
        self.interval_slider.blockSignals(False)

    def _on_interval_slider(self, value: int) -> None:
        self.interval_spin.setValue(int(value))

    def _capture_position(self) -> None:
        try:
            x, y = Controller().position
            self._fixed_position = (int(x), int(y))
            self.position_label.setText(f"X: {int(x)}   Y: {int(y)}")
            self._sync_position()
            if self.failsafe_check.isChecked() and int(x) <= 3 and int(y) <= 3:
                QMessageBox.warning(
                    self,
                    "Failsafe conflict",
                    "Captured corner with failsafe on stops instantly. "
                    "Pick another spot or turn failsafe off.",
                )
        except Exception as exc:
            QMessageBox.warning(self, "Could not read position", str(exc))

    def _sync_position(self, *_args) -> None:
        mode = self.position_combo.currentData()
        if mode == "fixed" and self._fixed_position is not None:
            x, y = self._fixed_position
            self.engine.set_position("fixed", x, y)
        elif mode == "fixed":
            self.engine.set_position("fixed")
        else:
            self.engine.set_position("cursor")

    def _sync_button(self, *_args) -> None:
        self.engine.set_button(self.button_combo.currentData())

    def _sync_hotkeys(self, *_args) -> None:
        toggle = self.toggle_combo.currentData()
        stop = self.stop_combo.currentData()
        if toggle == stop:
            QMessageBox.warning(
                self,
                "Hotkey conflict",
                "Start/pause and emergency stop need different keys.",
            )
            fallback = "f12" if toggle != "f12" else "f6"
            self.stop_combo.blockSignals(True)
            self.stop_combo.setCurrentIndex(self.stop_combo.findData(fallback))
            self.stop_combo.blockSignals(False)
            stop = self.stop_combo.currentData()
        try:
            self.hotkeys.set_keys(toggle, stop)
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid hotkeys", str(exc))
            return
        self._refresh_hotkey_note()
        self._refresh_tray_labels()

    def _refresh_hotkey_note(self) -> None:
        toggle = str(self.toggle_combo.currentData()).upper()
        stop = str(self.stop_combo.currentData()).upper()
        self.hotkey_note.setText(f"Global hotkeys: {toggle} start/pause · {stop} emergency stop")

    def _refresh_tray_labels(self) -> None:
        toggle_action = getattr(self, "_tray_toggle_action", None)
        stop_action = getattr(self, "_tray_stop_action", None)
        if toggle_action is None or stop_action is None:
            return
        toggle = str(self.toggle_combo.currentData()).upper()
        stop = str(self.stop_combo.currentData()).upper()
        toggle_action.setText(f"Start/Pause ({toggle})")
        stop_action.setText(f"Emergency Stop ({stop})")

    def _icon_path(self) -> str:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base, "assets", "icon.ico")

    def _setup_tray(self) -> None:
        self._tray = QSystemTrayIcon(self)
        if os.path.isfile(self._icon_path()):
            self._tray.setIcon(QIcon(self._icon_path()))
        self._tray.setToolTip("AutoClick Pro")
        menu = QMenu(self)
        self._tray_show_action = menu.addAction("Hide", self._tray_toggle_show)
        self._tray_toggle_action = menu.addAction("Start/Pause", self._tray_toggle_click)
        self._tray_stop_action = menu.addAction("Emergency Stop", self._emergency_stop)
        menu.addSeparator()
        menu.addAction("Quit", self._tray_quit)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._refresh_hotkey_note()
        self._refresh_tray_labels()
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._tray.show()

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._tray_toggle_show()

    def _tray_toggle_show(self) -> None:
        if self.isVisible():
            self.hide()
            self._tray_show_action.setText("Show")
        else:
            self.show()
            self.raise_()
            self.activateWindow()
            self._tray_show_action.setText("Hide")

    def _tray_toggle_click(self) -> None:
        self._toggle_clicking()
        if not self.isVisible() and QSystemTrayIcon.isSystemTrayAvailable():
            self._tray.showMessage(
                "AutoClick Pro",
                "Clicking" if self.engine.is_active() else "Paused",
                QSystemTrayIcon.MessageIcon.Information,
                1500,
            )

    def _tray_quit(self) -> None:
        self._quit_requested = True
        self.close()

    def _apply_theme(self, *_args) -> None:
        mode = str(self.theme_combo.currentData())
        app = QApplication.instance()
        if app is not None:
            self.setStyleSheet(set_app_theme(app, mode))
        ink = "#f2f4f8" if mode == "dark" else "#14161b" if mode == "light" else ""
        blue = "#dce1ea" if mode == "dark" else "#0b3d91" if mode == "light" else ""
        muted = "#8b93a3" if mode == "dark" else "#5b6270" if mode == "light" else ""
        coord = "#6ea8fe" if mode == "dark" else "#0b3d91" if mode == "light" else ""
        hero_bg = (
            "background: #1e2129; border: 1px solid #2c313c;"
            if mode == "dark"
            else "background: #ffffff; border: 1px solid #d5dae2;"
        )
        self._heading.setStyleSheet(
            f"font-size: 22px; font-weight: 700;{f' color: {ink};' if ink else ''}"
        )
        self.count_label.setStyleSheet(
            f"font-size: 30px; font-weight: 700;{f' color: {ink};' if ink else ''}"
        )
        self._subtitle.setStyleSheet(
            f"font-size: 13px;{f' color: {muted};' if muted else ''}"
        )
        self.stats_label.setStyleSheet(
            f"font-size: 12px; font-weight: 600;{f' color: {muted};' if muted else ''}"
        )
        self.hotkey_note.setStyleSheet(
            f"font-size: 12px;{f' color: {muted};' if muted else ''}"
        )
        self.position_label.setStyleSheet(
            "font-size: 13px; font-weight: 600;"
            f"{f' color: {coord};' if coord else ''}"
        )
        self.version_pill.setStyleSheet(
            "font-size: 12px; font-weight: 700; border-radius: 10px; padding: 5px 12px;"
            f"{f' background: rgba(47,129,247,0.16); color: {blue};' if blue else ''}"
        )
        self.hero.setStyleSheet(
            f"QGroupBox {{ border: 0; margin-top: 0; {hero_bg}}}"
        )

    def _apply_always_on_top(self, *_args) -> None:
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.top_check.isChecked())
        if self.isVisible():
            self.show()

    def _beep(self) -> None:
        if self.sound_check.isChecked():
            QApplication.beep()

    @Slot()
    def _toggle_clicking(self) -> None:
        if self.engine.is_active():
            self.engine.pause_clicking()
            self._set_running_ui(False)
            self._set_status("Status: Paused", "pause")
            self._beep()
            return

        interval_ms = self.interval_spin.value()
        if not self.engine.set_interval_ms(interval_ms):
            QMessageBox.warning(self, "Invalid interval", "Minimum interval is 10 ms.")
            return

        mode = self.position_combo.currentData()
        if mode == "fixed":
            if self._fixed_position is None:
                QMessageBox.information(
                    self,
                    "Coordinates required",
                    "Press 'Capture position' before using fixed coordinates.",
                )
                return
            self.engine.set_position("fixed", *self._fixed_position)
        else:
            self.engine.set_position("cursor")

        self.engine.set_button(self.button_combo.currentData())
        self.engine.set_double_click(self.double_check.isChecked())
        self.engine.set_failsafe(self.failsafe_check.isChecked())
        max_clicks = self.max_clicks_spin.value() or None
        max_seconds = self.max_seconds_spin.value() or None
        try:
            self.engine.set_limits(max_clicks, max_seconds)
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid limits", str(exc))
            return
        self._target_clicks = max_clicks
        self.engine.reset_count()
        self.engine.start_clicking()
        self._set_running_ui(True)
        self._set_status("Status: Clicking", "run")
        self._beep()

    @Slot()
    def _emergency_stop(self) -> None:
        self.engine.emergency_stop()
        self._show_emergency_stopped()

    @Slot()
    def _on_global_emergency_stop(self) -> None:
        # The listener has already stopped the engine directly. This queued
        # receiver only updates widgets on the main UI thread.
        self._show_emergency_stopped()

    def _show_emergency_stopped(self) -> None:
        self._set_running_ui(False)
        self._set_status("Status: Emergency stop — clicking halted", "stop")
        self._beep()

    def _set_running_ui(self, running: bool) -> None:
        self.toggle_button.setText("Pause" if running else "Start")
        self.position_combo.setEnabled(not running)
        self.capture_button.setEnabled(not running)
        self.max_clicks_spin.setEnabled(not running)
        self.max_seconds_spin.setEnabled(not running)

    @Slot(int)
    def _update_click_count(self, count: int) -> None:
        if self._target_clicks:
            self.count_label.setText(f"{count} / {self._target_clicks}")
        else:
            self.count_label.setText(f"{count}")
        now = time.monotonic()
        if count > self._last_count:
            self._session_total += count - self._last_count
            self._click_times.extend([now] * (count - self._last_count))
        self._last_count = count
        cutoff = now - 60
        while self._click_times and self._click_times[0] < cutoff:
            self._click_times.popleft()
        self.stats_label.setText(f"{len(self._click_times)}/min · session {self._session_total}")
        if self._target_clicks:
            self.progress_bar.setVisible(True)
            self.progress_bar.setMaximum(int(self._target_clicks))
            self.progress_bar.setValue(min(count, int(self._target_clicks)))
        else:
            self.progress_bar.setVisible(False)

    @Slot(str)
    def _on_engine_error(self, message: str) -> None:
        self._set_running_ui(False)
        display = message
        if message.startswith("Click failed") and not _is_admin():
            display += " Run AutoClick Pro and the target app at the same privilege level (both normal or both as admin)."
        self._set_status(f"Status: {display}", "error")
        self._beep()
        QMessageBox.critical(self, "Auto-click error", display)

    @Slot(str)
    def _on_limit_reached(self, message: str) -> None:
        self._set_running_ui(False)
        self._set_status(f"Status: {message}", "done")
        self._beep()

    @Slot(str)
    def _on_hotkey_error(self, message: str) -> None:
        self._set_status("Status: Global hotkeys unavailable", "error")
        QMessageBox.warning(self, "Global hotkeys", message)

    @Slot()
    def _show_about(self) -> None:
        version = __version__
        admin = "yes" if _is_admin() else "no"
        log_path = os.path.join(os.path.expanduser("~"), ".autoclick_pro.log")
        QMessageBox.about(
            self,
            "About AutoClick Pro",
            f"AutoClick Pro {version}\n\n"
            "Automatic mouse clicks for Windows.\n"
            f"Running as admin: {admin}\n"
            f"Log file: {log_path}\n\n"
            "Tip: run this app and the target app at the same "
            "privilege level or clicks may be blocked.",
        )

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt event API name.
        if (
            not self._quit_requested
            and self.tray_check.isChecked()
            and self._tray.isVisible()
        ):
            event.ignore()
            self.hide()
            self._tray_show_action.setText("Show")
            self._tray.showMessage(
                "AutoClick Pro",
                "Minimized to tray. Right-click the tray icon to quit.",
                QSystemTrayIcon.MessageIcon.Information,
                2000,
            )
            return
        self._save_settings()
        self._tray.hide()
        self.hotkeys.stop()
        self.engine.shutdown()
        event.accept()
