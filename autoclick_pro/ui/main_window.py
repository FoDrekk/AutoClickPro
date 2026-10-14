"""Main application window and user controls."""

from __future__ import annotations

import logging
import time
from collections import deque
from pathlib import Path
from typing import Any

from pynput.mouse import Controller
from PySide6.QtCore import QSignalBlocker, Qt, QTimer, Slot
from PySide6.QtGui import QCloseEvent, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from autoclick_pro import __version__
from autoclick_pro.click_engine import ClickEngine, in_failsafe_corner
from autoclick_pro.global_hotkeys import KEY_NAMES, GlobalHotkeys
from autoclick_pro.paths import asset_path, log_path
from autoclick_pro.settings_store import PROFILE_KEYS, SettingsStore, validate_profile_name
from autoclick_pro.ui.theme import label_styles, set_app_theme, status_style
from autoclick_pro.ui.tray import TrayIcon

_logger = logging.getLogger("autoclick_pro")

_SAVE_DELAY_MS = 400


def _is_admin() -> bool:
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


class MainWindow(QMainWindow):
    def __init__(self, store: SettingsStore, *, start_hotkeys: bool = True) -> None:
        super().__init__()
        self.setWindowTitle(f"AutoClick Pro {__version__}")
        self.setWindowIcon(QIcon(str(asset_path("icon.ico"))))
        self.setMinimumSize(600, 420)
        self.resize(620, 720)
        self._store = store
        self._target_clicks: int | None = None
        self._quit_requested = False
        self._state = "idle"  # idle | running | paused
        self._click_times: deque[float] = deque()
        self._session_total = 0
        self._last_count = 0
        self._fixed_position: tuple[int, int] | None = None

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(_SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self._save_settings)

        self.engine = ClickEngine(self)
        self.hotkeys = GlobalHotkeys(self.engine.emergency_stop, self)

        self._build_ui()
        self._tray = TrayIcon(self.windowIcon(), self)
        self._apply_settings(store.settings)
        self._refresh_profiles()

        self.interval_spin.valueChanged.connect(self.engine.set_interval_ms)
        self.interval_spin.valueChanged.connect(self._on_interval_spin)
        self.interval_slider.valueChanged.connect(self._on_interval_slider)
        self.button_combo.currentIndexChanged.connect(self._sync_button)
        self.double_check.toggled.connect(self.engine.set_double_click)
        self.failsafe_check.toggled.connect(self.engine.set_failsafe)
        self.position_combo.currentIndexChanged.connect(self._sync_position)
        self.toggle_combo.currentIndexChanged.connect(self._sync_hotkeys)
        self.stop_combo.currentIndexChanged.connect(self._sync_hotkeys)
        self.top_check.toggled.connect(self._apply_always_on_top)
        self.theme_combo.currentIndexChanged.connect(self._apply_theme)
        self.profile_combo.currentIndexChanged.connect(self._load_profile)
        for signal in (
            self.interval_spin.valueChanged,
            self.position_combo.currentIndexChanged,
            self.button_combo.currentIndexChanged,
            self.double_check.toggled,
            self.max_clicks_spin.valueChanged,
            self.max_seconds_spin.valueChanged,
            self.failsafe_check.toggled,
            self.sound_check.toggled,
            self.top_check.toggled,
            self.tray_check.toggled,
            self.theme_combo.currentIndexChanged,
            self.toggle_combo.currentIndexChanged,
            self.stop_combo.currentIndexChanged,
        ):
            signal.connect(self._schedule_save)

        queued = Qt.ConnectionType.QueuedConnection
        self.engine.click_count_changed.connect(self._update_click_count, queued)
        self.engine.error_occurred.connect(self._on_engine_error, queued)
        self.engine.limit_reached.connect(self._on_limit_reached, queued)
        self.engine.failsafe_triggered.connect(self._on_failsafe, queued)
        self.hotkeys.toggle_requested.connect(self._toggle_clicking, queued)
        self.hotkeys.emergency_stop_requested.connect(self._on_global_emergency_stop, queued)
        self.hotkeys.error_occurred.connect(self._on_hotkey_error, queued)
        self._tray.show_toggle_requested.connect(self._tray_toggle_show)
        self._tray.toggle_click_requested.connect(self._tray_toggle_click)
        self._tray.emergency_stop_requested.connect(self._emergency_stop)
        self._tray.quit_requested.connect(self._tray_quit)

        if store.load_warning:
            self._set_status(f"Status: {store.load_warning}", "error")
        if start_hotkeys:
            self.hotkeys.start()

    # ----------------------------------------------------------------- layout

    def _make_card(self, title: str) -> tuple[QGroupBox, QFormLayout]:
        group = QGroupBox(title)
        form = QFormLayout(group)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return group, form

    def _ghost_button(self, text: str, slot) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("ghost")
        button.clicked.connect(slot)
        return button

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(14)
        self.logo_label = QLabel()
        logo_path = asset_path("icon.png")
        if not logo_path.is_file():
            logo_path = asset_path("icon.ico")
        if logo_path.is_file():
            pix = QPixmap(str(logo_path)).scaled(
                46, 46, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.logo_label.setPixmap(pix)
        self.logo_label.setFixedSize(46, 46)
        header.addWidget(self.logo_label)
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        self._heading = QLabel("AutoClick Pro")
        self._subtitle = QLabel("Automatic clicks for Windows")
        title_box.addWidget(self._heading)
        title_box.addWidget(self._subtitle)
        header.addLayout(title_box, 1)
        self.version_pill = QLabel(f"v{__version__}")
        header.addWidget(self.version_pill, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        self.hero = QGroupBox()
        hero_layout = QVBoxLayout(self.hero)
        hero_layout.setContentsMargins(18, 18, 18, 18)
        hero_layout.setSpacing(10)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self._set_status("Status: Stopped", "idle")
        hero_layout.addWidget(self.status_label)
        hero_row = QHBoxLayout()
        hero_row.setSpacing(18)
        counter_box = QVBoxLayout()
        counter_box.setSpacing(0)
        self.count_label = QLabel("0")
        counter_box.addWidget(self.count_label)
        self.stats_label = QLabel("0/min · session 0")
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
        self.position_label = QLabel("Not set")
        self.position_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.capture_button = self._ghost_button("Capture position", self._capture_position)
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
        self.max_seconds_spin.setToolTip(
            "Stop automatically after this many seconds of clicking. Paused time "
            "does not count. 0 means no limit."
        )
        self.failsafe_check = QCheckBox("Stop at top-left corner")
        self.failsafe_check.setToolTip(
            "Slam the cursor into the top-left corner of the primary monitor to halt clicking."
        )
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
        self.profile_combo.setToolTip("Profiles store click settings: interval, button, position, limits.")
        profile_buttons = QHBoxLayout()
        profile_buttons.setSpacing(8)
        self.profile_save_button = self._ghost_button("Save", self._save_profile)
        self.profile_delete_button = self._ghost_button("Delete", self._delete_profile)
        self.profile_import_button = self._ghost_button("Import…", self._import_profiles)
        self.profile_export_button = self._ghost_button("Export…", self._export_profiles)
        for button in (
            self.profile_save_button,
            self.profile_delete_button,
            self.profile_import_button,
            self.profile_export_button,
        ):
            profile_buttons.addWidget(button, 1)
        profiles_form.addRow("Preset:", self.profile_combo)
        profiles_form.addRow("", profile_buttons)
        layout.addWidget(profiles_group)

        self.hotkey_note = QLabel()
        self.hotkey_note.setWordWrap(True)
        footer = QHBoxLayout()
        footer.addWidget(self.hotkey_note, 1)
        self.about_button = self._ghost_button("About", self._show_about)
        self.about_button.setMaximumWidth(110)
        footer.addWidget(self.about_button)
        layout.addLayout(footer)
        layout.addStretch(1)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(root)
        self.setCentralWidget(scroll)

    def _set_status(self, text: str, kind: str) -> None:
        self.status_label.setText(text)
        self.status_label.setStyleSheet(status_style(kind))

    def _alert(self, title: str, text: str, level: str = "warning") -> None:
        """Show a dialog when the user is looking at the window, else a tray note.

        Hotkeys fire while another app has focus; a modal box would open
        behind that app and look like the hotkey did nothing.
        """
        if self.isVisible() and self.isActiveWindow():
            show = {
                "info": QMessageBox.information,
                "critical": QMessageBox.critical,
            }.get(level, QMessageBox.warning)
            show(self, title, text)
        else:
            self._tray.notify(text, level, 4000)

    # --------------------------------------------------------------- settings

    def _collect_settings(self) -> dict[str, Any]:
        fixed = self._fixed_position
        return {
            "interval": self.interval_spin.value(),
            "mode": self.position_combo.currentData(),
            "fixedX": fixed[0] if fixed else None,
            "fixedY": fixed[1] if fixed else None,
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

    def _apply_click_settings(self, d: dict[str, Any]) -> None:
        self.interval_spin.setValue(int(d["interval"]))
        self.position_combo.setCurrentIndex(1 if d["mode"] == "fixed" else 0)
        if d["fixedX"] is not None and d["fixedY"] is not None:
            self._fixed_position = (int(d["fixedX"]), int(d["fixedY"]))
            self.position_label.setText(f"X: {self._fixed_position[0]}   Y: {self._fixed_position[1]}")
        idx = self.button_combo.findData(d["button"])
        self.button_combo.setCurrentIndex(max(idx, 0))
        self.double_check.setChecked(bool(d["double"]))
        self.max_clicks_spin.setValue(int(d["maxClicks"]))
        self.max_seconds_spin.setValue(float(d["maxSeconds"]))
        self.failsafe_check.setChecked(bool(d["failsafe"]))
        self._sync_position()
        self._sync_button()
        self.engine.set_double_click(self.double_check.isChecked())
        self.engine.set_failsafe(self.failsafe_check.isChecked())

    def _apply_settings(self, d: dict[str, Any]) -> None:
        self._apply_click_settings(d)
        self.sound_check.setChecked(bool(d["sound"]))
        self.top_check.setChecked(bool(d["alwaysOnTop"]))
        self.tray_check.setChecked(bool(d["minimizeToTray"]))
        with QSignalBlocker(self.theme_combo):
            self.theme_combo.setCurrentIndex(max(self.theme_combo.findData(d["theme"]), 0))
        self._apply_theme()
        with QSignalBlocker(self.toggle_combo), QSignalBlocker(self.stop_combo):
            self.toggle_combo.setCurrentIndex(self.toggle_combo.findData(d["toggleKey"]))
            self.stop_combo.setCurrentIndex(self.stop_combo.findData(d["stopKey"]))
        self._apply_always_on_top()
        self._sync_hotkeys()

    @Slot()
    def _schedule_save(self, *_args) -> None:
        self._save_timer.start()

    @Slot()
    def _save_settings(self) -> bool:
        self._save_timer.stop()
        self._store.update_settings(self._collect_settings())
        try:
            self._store.save()
        except OSError as exc:
            _logger.exception("Could not save settings")
            self._set_status(f"Status: Could not save settings: {exc}", "error")
            return False
        return True

    # --------------------------------------------------------------- profiles

    def _refresh_profiles(self, select: str | None = None) -> None:
        names = self._store.profile_names()
        with QSignalBlocker(self.profile_combo):
            self.profile_combo.clear()
            for name in names:
                self.profile_combo.addItem(name, name)
            if not names:
                self.profile_combo.addItem("(No profiles saved)", None)
            if select is not None:
                idx = self.profile_combo.findData(select)
                if idx >= 0:
                    self.profile_combo.setCurrentIndex(idx)
        self._update_profile_controls()

    def _update_profile_controls(self) -> None:
        has_profiles = bool(self._store.profiles)
        # Loading a profile mid-run would rewrite live engine settings.
        self.profile_combo.setEnabled(has_profiles and self._state == "idle")
        self.profile_delete_button.setEnabled(has_profiles)
        self.profile_export_button.setEnabled(has_profiles)

    @Slot()
    def _save_profile(self) -> None:
        name, ok = QInputDialog.getText(self, "Save profile", "Profile name:")
        if not ok:
            return
        try:
            name = validate_profile_name(name)
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid profile name", str(exc))
            return
        if name in self._store.profiles:
            answer = QMessageBox.question(
                self,
                "Overwrite profile",
                f"Profile '{name}' exists. Overwrite?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        settings = self._collect_settings()
        self._store.set_profile(name, {key: settings[key] for key in PROFILE_KEYS})
        self._save_settings()
        self._refresh_profiles(select=name)

    @Slot(int)
    def _load_profile(self, index: int) -> None:
        name = self.profile_combo.itemData(index) if index >= 0 else None
        profile = self._store.profiles.get(name) if name else None
        if profile is None or self._state != "idle":
            return
        self._apply_click_settings(profile)
        self._set_status(f"Status: Loaded profile '{name}'", "idle")

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
        self._store.delete_profile(name)
        self._save_settings()
        self._refresh_profiles()

    @Slot()
    def _export_profiles(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export profiles", "autoclick-profiles.json", "JSON files (*.json)"
        )
        if not path:
            return
        try:
            count = self._store.export_profiles(Path(path))
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))
            return
        self._set_status(f"Status: Exported {count} profile(s)", "done")

    @Slot()
    def _import_profiles(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import profiles", "", "JSON files (*.json);;All files (*)"
        )
        if not path:
            return
        try:
            added, replaced = self._store.import_profiles(Path(path))
        except ValueError as exc:
            QMessageBox.warning(self, "Import failed", str(exc))
            return
        self._save_settings()
        self._refresh_profiles()
        self._set_status(f"Status: Imported {added} new, replaced {replaced} profile(s)", "done")

    # ------------------------------------------------------------ live sync

    def _on_interval_spin(self, value: int) -> None:
        with QSignalBlocker(self.interval_slider):
            self.interval_slider.setValue(max(10, min(2000, int(value))))

    def _on_interval_slider(self, value: int) -> None:
        self.interval_spin.setValue(int(value))

    def _capture_position(self) -> None:
        try:
            x, y = (int(v) for v in Controller().position)
        except Exception as exc:
            QMessageBox.warning(self, "Could not read position", str(exc))
            return
        self._fixed_position = (x, y)
        self.position_label.setText(f"X: {x}   Y: {y}")
        self._sync_position()
        self._schedule_save()
        if self.failsafe_check.isChecked() and in_failsafe_corner(x, y):
            QMessageBox.warning(
                self,
                "Failsafe conflict",
                "Captured corner with failsafe on stops instantly. "
                "Pick another spot or turn failsafe off.",
            )

    def _sync_position(self, *_args) -> None:
        mode = self.position_combo.currentData()
        if mode == "fixed" and self._fixed_position is not None:
            self.engine.set_position("fixed", *self._fixed_position)
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
            with QSignalBlocker(self.stop_combo):
                self.stop_combo.setCurrentIndex(
                    self.stop_combo.findData("f12" if toggle != "f12" else "f6")
                )
            stop = self.stop_combo.currentData()
        try:
            self.hotkeys.set_keys(toggle, stop)
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid hotkeys", str(exc))
            return
        self.hotkey_note.setText(
            f"Global hotkeys: {toggle.upper()} start/pause · {stop.upper()} emergency stop"
        )
        self._tray.set_hotkey_labels(toggle, stop)

    # ----------------------------------------------------------- tray/window

    def _tray_toggle_show(self) -> None:
        if self.isVisible():
            self.hide()
            self._tray.set_window_shown(False)
        else:
            self.show()
            self.raise_()
            self.activateWindow()
            self._tray.set_window_shown(True)

    def _tray_toggle_click(self) -> None:
        self._toggle_clicking()
        if not self.isVisible():
            self._tray.notify("Clicking" if self.engine.is_active() else "Paused", msecs=1500)

    def _tray_quit(self) -> None:
        self._quit_requested = True
        self.close()

    def _apply_theme(self, *_args) -> None:
        mode = str(self.theme_combo.currentData())
        app = QApplication.instance()
        if isinstance(app, QApplication):
            self.setStyleSheet(set_app_theme(app, mode))
        styles = label_styles(mode)
        self._heading.setStyleSheet(styles["heading"])
        self.count_label.setStyleSheet(styles["count"])
        self._subtitle.setStyleSheet(styles["subtitle"])
        self.stats_label.setStyleSheet(styles["stats"])
        self.hotkey_note.setStyleSheet(styles["note"])
        self.position_label.setStyleSheet(styles["position"])
        self.version_pill.setStyleSheet(styles["version"])
        self.hero.setStyleSheet(styles["hero"])

    def _apply_always_on_top(self, *_args) -> None:
        # setWindowFlag() re-parents and hides a visible window; restore it.
        was_visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.top_check.isChecked())
        if was_visible:
            self.show()

    def _beep(self) -> None:
        if self.sound_check.isChecked():
            QApplication.beep()

    # ------------------------------------------------------------- clicking

    def _push_engine_settings(self) -> bool:
        if not self.engine.set_interval_ms(self.interval_spin.value()):
            self._alert("Invalid interval", "Minimum interval is 10 ms.")
            return False
        if self.position_combo.currentData() == "fixed" and self._fixed_position is None:
            self._set_status("Status: Capture a position before using fixed coordinates", "error")
            self._alert(
                "Coordinates required",
                "Press 'Capture position' before using fixed coordinates.",
                "info",
            )
            return False
        self._sync_position()
        self._sync_button()
        self.engine.set_double_click(self.double_check.isChecked())
        self.engine.set_failsafe(self.failsafe_check.isChecked())
        return True

    @Slot()
    def _toggle_clicking(self) -> None:
        if self.engine.is_active():
            self.engine.pause_clicking()
            self._set_state("paused")
            self._set_status("Status: Paused", "pause")
            self._beep()
            return

        if not self._push_engine_settings():
            return
        if not self.engine.resume_clicking():
            max_clicks = self.max_clicks_spin.value() or None
            max_seconds = self.max_seconds_spin.value() or None
            try:
                self.engine.set_limits(max_clicks, max_seconds)
            except ValueError as exc:
                self._alert("Invalid limits", str(exc))
                return
            self._target_clicks = max_clicks
            self.engine.start_clicking()
        self._set_state("running")
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
        self._set_state("idle")
        self._set_status("Status: Emergency stop — clicking halted", "stop")
        self._beep()

    def _set_state(self, state: str) -> None:
        self._state = state
        running = state == "running"
        idle = state == "idle"
        self.toggle_button.setText({"running": "Pause", "paused": "Resume"}.get(state, "Start"))
        self.position_combo.setEnabled(not running)
        self.capture_button.setEnabled(not running)
        # Limits belong to a run; editing them while paused would be ignored.
        self.max_clicks_spin.setEnabled(idle)
        self.max_seconds_spin.setEnabled(idle)
        self._update_profile_controls()

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
        self._set_state("idle")
        display = message
        if message.startswith("Click failed") and not _is_admin():
            display += (
                " Run AutoClick Pro and the target app at the same privilege level"
                " (both normal or both as admin)."
            )
        self._set_status(f"Status: {display}", "error")
        self._beep()
        self._alert("Auto-click error", display, "critical")

    @Slot(str)
    def _on_failsafe(self, message: str) -> None:
        self._set_state("idle")
        self._set_status(f"Status: {message}", "stop")
        self._beep()

    @Slot(str)
    def _on_limit_reached(self, message: str) -> None:
        self._set_state("idle")
        self._set_status(f"Status: {message}", "done")
        self._beep()

    @Slot(str)
    def _on_hotkey_error(self, message: str) -> None:
        self._set_status("Status: Global hotkeys unavailable", "error")
        QMessageBox.warning(self, "Global hotkeys", message)

    @Slot()
    def _show_about(self) -> None:
        admin = "yes" if _is_admin() else "no"
        QMessageBox.about(
            self,
            "About AutoClick Pro",
            f"AutoClick Pro {__version__}\n\n"
            "Automatic mouse clicks for Windows.\n"
            f"Running as admin: {admin}\n"
            f"Settings: {self._store.path}\n"
            f"Log file: {log_path()}\n\n"
            "Tip: run this app and the target app at the same "
            "privilege level or clicks may be blocked.",
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        if (
            not self._quit_requested
            and self.tray_check.isChecked()
            and self._tray.is_visible()
        ):
            event.ignore()
            self.hide()
            self._tray.set_window_shown(False)
            self._tray.notify("Minimized to tray. Right-click the tray icon to quit.")
            self._save_settings()
            return
        self._save_settings()
        self._tray.hide()
        self.hotkeys.stop()
        self.engine.shutdown()
        event.accept()

