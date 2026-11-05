"""Main application window and user controls."""

from __future__ import annotations

import logging
import os
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSignalBlocker, Qt, QTimer, QUrl, Slot
from PySide6.QtGui import QCloseEvent, QDesktopServices, QIcon, QPixmap
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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from autoclick_pro import __version__, diagnostics, updater, winapi
from autoclick_pro.click_engine import (
    MIN_INTERVAL_MS,
    ClickEngine,
    current_failsafe_corners,
    in_failsafe_corner,
)
from autoclick_pro.global_hotkeys import DEFAULT_STOP, DEFAULT_TOGGLE, GlobalHotkeys, parse_hotkey
from autoclick_pro.paths import asset_path, log_path
from autoclick_pro.recorder import InputRecorder, events_to_steps
from autoclick_pro.settings_store import PROFILE_KEYS, SettingsStore, validate_profile_name
from autoclick_pro.steps import Trigger, format_color, sanitize_sequence, sanitize_trigger
from autoclick_pro.ui.hotkey_edit import HotkeyEdit
from autoclick_pro.ui.hud import StatusHud
from autoclick_pro.ui.picker import Pick, pick_point
from autoclick_pro.ui.sequence_editor import SequenceEditor
from autoclick_pro.ui.theme import label_styles, set_app_theme, status_style
from autoclick_pro.ui.tray import TrayIcon
from autoclick_pro.ui.update_check import Checker, UpdateChecker

_logger = logging.getLogger("autoclick_pro")

_SAVE_DELAY_MS = 400
_CLICKER_TAB, _SEQUENCE_TAB, _SETTINGS_TAB = range(3)


def _is_admin() -> bool:
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


class MainWindow(QMainWindow):
    def __init__(
        self,
        store: SettingsStore,
        *,
        start_hotkeys: bool = True,
        recorder: InputRecorder | None = None,
        update_checker: Checker | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle(f"AutoClick Pro {__version__}")
        self.setWindowIcon(QIcon(str(asset_path("icon.ico"))))
        self.setMinimumSize(640, 560)
        self.resize(680, 820)
        self._store = store
        self._target_clicks: int | None = None
        self._quit_requested = False
        self._shut_down = False
        self._state = "idle"  # idle | countdown | running | paused | recording
        self._run_mode = "simple"
        self._click_times: deque[float] = deque()
        self._session_total = 0
        self._last_count = 0
        self._last_progress: tuple[int, int] | None = None
        self._fixed_position: tuple[int, int] | None = None
        # Window picked for background clicks; window handles do not survive a restart.
        self._background_target: tuple[int, str] | None = None
        self._trigger = Trigger()
        # Last valid hotkeys; the pickers can hold an incomplete combo mid-edit.
        self._hotkey_specs = (DEFAULT_TOGGLE, DEFAULT_STOP)
        self._countdown_left = 0
        self._countdown_action: Callable[[], None] | None = None
        self._countdown_what = ""
        self._recorder = recorder or InputRecorder()
        self._last_update_check = 0
        self._update_url: str | None = None
        # An injected checker (tests) counts as a configured source.
        self._update_source_ready = update_checker is not None or updater.is_valid_repo(updater.UPDATE_REPO)
        self._update_checker = UpdateChecker(
            update_checker or (lambda: updater.check_for_update(updater.UPDATE_REPO)), self
        )
        self._update_checker.finished.connect(self._on_update_result)
        self._update_checker.failed.connect(self._on_update_failed)
        self._manual_update_check = False

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(_SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self._save_settings)
        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._countdown_tick)
        self._record_timer = QTimer(self)
        self._record_timer.setInterval(250)
        self._record_timer.timeout.connect(self._on_record_tick)

        self.engine = ClickEngine(self)
        self.hotkeys = GlobalHotkeys(self.engine.emergency_stop, self)
        self.hud = StatusHud()

        self._build_ui()
        self._tray = TrayIcon(self.windowIcon(), self)
        self._apply_settings(store.settings)
        self._refresh_profiles()

        self.interval_spin.valueChanged.connect(self.engine.set_interval_ms)
        self.interval_spin.valueChanged.connect(self._on_interval_spin)
        self.interval_spin.valueChanged.connect(self._update_rate_label)
        self.jitter_pct_spin.valueChanged.connect(self._sync_jitter)
        self.jitter_px_spin.valueChanged.connect(self._sync_jitter)
        self.interval_slider.valueChanged.connect(self._on_interval_slider)
        self.button_combo.currentIndexChanged.connect(self._sync_button)
        self.double_check.toggled.connect(self.engine.set_double_click)
        self.failsafe_check.toggled.connect(self.engine.set_failsafe)
        self.position_combo.currentIndexChanged.connect(self._sync_position)
        self.background_check.toggled.connect(self._on_background_toggled)
        self.trigger_combo.currentIndexChanged.connect(self._sync_trigger)
        self.trigger_tolerance_spin.valueChanged.connect(self._sync_trigger)
        self.toggle_edit.changed.connect(self._sync_hotkeys)
        self.stop_edit.changed.connect(self._sync_hotkeys)
        self.top_check.toggled.connect(self._apply_always_on_top)
        self.theme_combo.currentIndexChanged.connect(self._apply_theme)
        self.overlay_check.toggled.connect(self._refresh_hud)
        self.profile_combo.currentIndexChanged.connect(self._load_profile)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.update_button.clicked.connect(self._check_updates_now)
        self.update_open_button.clicked.connect(self._open_update_page)
        self.sequence_editor.record_requested.connect(self._toggle_recording)
        for signal in (
            self.interval_spin.valueChanged,
            self.jitter_pct_spin.valueChanged,
            self.jitter_px_spin.valueChanged,
            self.position_combo.currentIndexChanged,
            self.button_combo.currentIndexChanged,
            self.double_check.toggled,
            self.background_check.toggled,
            self.trigger_combo.currentIndexChanged,
            self.trigger_tolerance_spin.valueChanged,
            self.max_clicks_spin.valueChanged,
            self.max_seconds_spin.valueChanged,
            self.failsafe_check.toggled,
            self.sound_check.toggled,
            self.top_check.toggled,
            self.tray_check.toggled,
            self.overlay_check.toggled,
            self.updates_check.toggled,
            self.countdown_spin.valueChanged,
            self.theme_combo.currentIndexChanged,
            self.toggle_edit.changed,
            self.stop_edit.changed,
            self.sequence_editor.changed,
            self.tabs.currentChanged,
        ):
            signal.connect(self._schedule_save)

        queued = Qt.ConnectionType.QueuedConnection
        self.engine.click_count_changed.connect(self._update_click_count, queued)
        self.engine.progress_changed.connect(self._on_progress, queued)
        self.engine.error_occurred.connect(self._on_engine_error, queued)
        self.engine.limit_reached.connect(self._on_limit_reached, queued)
        self.engine.failsafe_triggered.connect(self._on_failsafe, queued)
        self.engine.condition_stopped.connect(self._on_condition_stopped, queued)
        self.hotkeys.toggle_requested.connect(self._on_hotkey_toggle, queued)
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
            QTimer.singleShot(4000, self._auto_check_updates)

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

    def _scroll_page(self, *widgets: QWidget) -> QScrollArea:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(2, 10, 8, 4)
        layout.setSpacing(12)
        for widget in widgets:
            layout.addWidget(widget)
        layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(page)
        return scroll

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 22, 24, 16)
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
        side_box = QVBoxLayout()
        self.mode_label = QLabel()
        side_box.addWidget(self.mode_label, 0, Qt.AlignmentFlag.AlignRight)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(False)
        side_box.addWidget(self.progress_bar)
        hero_row.addLayout(side_box, 1)
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

        self.tabs = QTabWidget()
        self.tabs.addTab(self._scroll_page(*self._build_clicker_cards()), "Clicker")
        self.sequence_editor = SequenceEditor(self._pick)
        sequence_note = QLabel(
            "Start runs the sequence while this tab is open. Max clicks, max duration and the "
            "failsafe from the Clicker tab apply too."
        )
        sequence_note.setWordWrap(True)
        self.sequence_note = sequence_note
        self.tabs.addTab(self._scroll_page(self.sequence_editor, sequence_note), "Sequence")
        self.tabs.addTab(self._scroll_page(*self._build_settings_cards()), "Settings")
        layout.addWidget(self.tabs, 1)

        self.hotkey_note = QLabel()
        self.hotkey_note.setWordWrap(True)
        footer = QHBoxLayout()
        footer.addWidget(self.hotkey_note, 1)
        self.about_button = self._ghost_button("About", self._show_about)
        self.about_button.setMaximumWidth(110)
        footer.addWidget(self.about_button)
        layout.addLayout(footer)
        self.setCentralWidget(root)

    def _build_clicker_cards(self) -> list[QWidget]:
        interval_group, interval_form = self._make_card("Interval")
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(MIN_INTERVAL_MS, 3_600_000)
        self.interval_spin.setValue(100)
        self.interval_spin.setSuffix(" ms")
        self.interval_spin.setMinimumWidth(110)
        self.interval_spin.setToolTip("Delay between clicks. 1 ms means up to 1000 clicks per second.")
        self.interval_slider = QSlider(Qt.Orientation.Horizontal)
        self.interval_slider.setRange(MIN_INTERVAL_MS, 2000)
        self.interval_slider.setValue(100)
        self.interval_slider.setToolTip("Drag to tune the interval. Range 1–2000 ms.")
        spin_row = QHBoxLayout()
        spin_row.setSpacing(12)
        spin_row.addWidget(self.interval_spin, 0)
        spin_row.addWidget(self.interval_slider, 1)
        interval_form.addRow("Click every:", spin_row)
        self.rate_label = QLabel()
        interval_form.addRow("Rate:", self.rate_label)
        self.jitter_pct_spin = QSpinBox()
        self.jitter_pct_spin.setRange(0, 50)
        self.jitter_pct_spin.setPrefix("± ")
        self.jitter_pct_spin.setSuffix(" %")
        self.jitter_pct_spin.setSpecialValueText("Off")
        self.jitter_pct_spin.setToolTip("Vary each delay randomly by up to this percentage.")
        self.jitter_px_spin = QSpinBox()
        self.jitter_px_spin.setRange(0, 50)
        self.jitter_px_spin.setPrefix("± ")
        self.jitter_px_spin.setSuffix(" px")
        self.jitter_px_spin.setSpecialValueText("Off")
        self.jitter_px_spin.setToolTip(
            "Click at a random point within this radius of the fixed coordinates. "
            "Ignored when clicking at the cursor."
        )
        interval_form.addRow("Random delay:", self.jitter_pct_spin)
        interval_form.addRow("Random position:", self.jitter_px_spin)

        click_group, click_form = self._make_card("Click")
        self.button_combo = QComboBox()
        self.button_combo.addItem("Left button", "left")
        self.button_combo.addItem("Right button", "right")
        self.button_combo.addItem("Middle button", "middle")
        self.double_check = QCheckBox("Double-click (2 presses per cycle)")
        click_form.addRow("Button:", self.button_combo)
        click_form.addRow("", self.double_check)

        position_group, position_form = self._make_card("Click position")
        self.position_combo = QComboBox()
        self.position_combo.addItem("At cursor position", "cursor")
        self.position_combo.addItem("At fixed coordinates", "fixed")
        self.position_label = QLabel("Not set")
        self.position_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.capture_button = self._ghost_button("Pick position…", self._capture_position)
        self.capture_button.setToolTip("Point at the target on screen and click. Esc cancels.")
        self.background_check = QCheckBox("Click the window in the background")
        self.background_check.setToolTip(
            "Send clicks to the picked window as messages, without moving your cursor. "
            "Many games and some apps ignore these clicks."
        )
        self.target_label = QLabel()
        self.target_label.setWordWrap(True)
        position_form.addRow("Mode:", self.position_combo)
        position_form.addRow("Coordinates:", self.position_label)
        position_form.addRow("", self.capture_button)
        position_form.addRow("", self.background_check)
        position_form.addRow("", self.target_label)

        trigger_group, trigger_form = self._make_card("Color trigger")
        self.trigger_combo = QComboBox()
        self.trigger_combo.addItem("Off", "off")
        self.trigger_combo.addItem("Click only while the color matches", "wait")
        self.trigger_combo.addItem("Stop when the color changes", "stop")
        self.trigger_label = QLabel("No pixel picked")
        self.trigger_pick_button = self._ghost_button("Pick pixel…", self._pick_trigger)
        self.trigger_tolerance_spin = QSpinBox()
        self.trigger_tolerance_spin.setRange(0, 255)
        self.trigger_tolerance_spin.setValue(16)
        self.trigger_tolerance_spin.setToolTip("How far each of red, green and blue may differ (0–255).")
        trigger_form.addRow("When:", self.trigger_combo)
        trigger_form.addRow("Pixel:", self.trigger_label)
        trigger_form.addRow("", self.trigger_pick_button)
        trigger_form.addRow("Tolerance:", self.trigger_tolerance_spin)

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
            "Slam the cursor into the top-left corner of the desktop to halt clicking."
        )
        limits_form.addRow("Max clicks:", self.max_clicks_spin)
        limits_form.addRow("Max duration:", self.max_seconds_spin)
        limits_form.addRow("", self.failsafe_check)
        return [interval_group, click_group, position_group, trigger_group, limits_group]

    def _build_settings_cards(self) -> list[QWidget]:
        window_group, window_form = self._make_card("Window and feedback")
        self.sound_check = QCheckBox("Sound on start/stop")
        self.sound_check.setChecked(True)
        self.top_check = QCheckBox("Always on top")
        self.tray_check = QCheckBox("Minimize to tray on close")
        self.tray_check.setToolTip("Closing the window minimizes to tray instead of quitting.")
        self.overlay_check = QCheckBox("Show floating status overlay")
        self.overlay_check.setToolTip("A small always-on-top box shows state and clicks while running.")
        self.countdown_spin = QSpinBox()
        self.countdown_spin.setRange(0, 10)
        self.countdown_spin.setSuffix(" s")
        self.countdown_spin.setSpecialValueText("Off")
        self.countdown_spin.setToolTip("Wait this long before clicking or recording starts.")
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Dark", "dark")
        self.theme_combo.addItem("Light", "light")
        self.theme_combo.addItem("System", "system")
        window_form.addRow("", self.sound_check)
        window_form.addRow("", self.top_check)
        window_form.addRow("", self.tray_check)
        window_form.addRow("", self.overlay_check)
        window_form.addRow("Countdown:", self.countdown_spin)
        window_form.addRow("Theme:", self.theme_combo)

        hotkeys_group, hotkeys_form = self._make_card("Hotkeys")
        self.toggle_edit = HotkeyEdit()
        self.toggle_edit.set_hotkey(DEFAULT_TOGGLE)
        self.stop_edit = HotkeyEdit()
        self.stop_edit.set_hotkey(DEFAULT_STOP)
        self.hotkey_hint = QLabel()
        self.hotkey_hint.setWordWrap(True)
        self.hotkey_hint.setVisible(False)
        hotkeys_form.addRow("Start/pause:", self.toggle_edit)
        hotkeys_form.addRow("Emergency stop:", self.stop_edit)
        hotkeys_form.addRow("", self.hotkey_hint)

        profiles_group, profiles_form = self._make_card("Profiles")
        self.profile_combo = QComboBox()
        self.profile_combo.setToolTip(
            "Profiles store click settings: interval, button, position, trigger, limits and the sequence."
        )
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
        updates_group, updates_form = self._make_card("Updates")
        self.updates_check = QCheckBox("Check for updates once a week")
        self.updates_check.setToolTip(
            "Asks GitHub for the latest release number. Nothing is downloaded or installed, "
            "and no personal data is sent."
        )
        self.update_button = self._ghost_button("Check now", lambda: None)
        self.update_label = QLabel()
        self.update_label.setWordWrap(True)
        self.update_open_button = self._ghost_button("Open release page", lambda: None)
        self.update_open_button.setVisible(False)
        updates_form.addRow("", self.updates_check)
        updates_form.addRow("Status:", self.update_label)
        updates_form.addRow("", self.update_button)
        updates_form.addRow("", self.update_open_button)
        if not self._update_source_ready:
            self.update_label.setText("This build has no update source configured.")
            self.update_button.setEnabled(False)
            self.updates_check.setEnabled(False)
        else:
            self.update_label.setText(f"Installed version: {__version__}")
        return [window_group, hotkeys_group, updates_group, profiles_group]

    def _set_status(self, text: str, kind: str) -> None:
        self.status_label.setText(text)
        self.status_label.setStyleSheet(status_style(kind))
        if hasattr(self, "overlay_check"):
            self._refresh_hud()

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
            "jitterPct": self.jitter_pct_spin.value(),
            "jitterPx": self.jitter_px_spin.value(),
            "background": self.background_check.isChecked(),
            "trigger": self._trigger.to_json(),
            "sequence": self.sequence_editor.sequence().to_json(),
            "sound": self.sound_check.isChecked(),
            "alwaysOnTop": self.top_check.isChecked(),
            "minimizeToTray": self.tray_check.isChecked(),
            "overlay": self.overlay_check.isChecked(),
            "countdown": self.countdown_spin.value(),
            "recordMoves": self.sequence_editor.record_moves_check.isChecked(),
            "checkUpdates": self.updates_check.isChecked(),
            "lastUpdateCheck": self._last_update_check,
            "runMode": self._run_mode,
            "theme": self.theme_combo.currentData(),
            "toggleKey": self._hotkey_specs[0],
            "stopKey": self._hotkey_specs[1],
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
        self.jitter_pct_spin.setValue(int(d["jitterPct"]))
        self.jitter_px_spin.setValue(int(d["jitterPx"]))
        with QSignalBlocker(self.background_check):
            self.background_check.setChecked(bool(d["background"]))
        self._apply_trigger(sanitize_trigger(d["trigger"]))
        self.sequence_editor.set_sequence(sanitize_sequence(d["sequence"]))
        self._sync_jitter()
        self._update_rate_label()
        self._sync_position()
        self._sync_button()
        self._update_target_label()
        self.engine.set_double_click(self.double_check.isChecked())
        self.engine.set_failsafe(self.failsafe_check.isChecked())

    def _apply_settings(self, d: dict[str, Any]) -> None:
        self._apply_click_settings(d)
        self.sound_check.setChecked(bool(d["sound"]))
        self.top_check.setChecked(bool(d["alwaysOnTop"]))
        self.tray_check.setChecked(bool(d["minimizeToTray"]))
        self.overlay_check.setChecked(bool(d["overlay"]))
        self.updates_check.setChecked(bool(d["checkUpdates"]) and self._update_source_ready)
        self._last_update_check = int(d["lastUpdateCheck"])
        self.countdown_spin.setValue(int(d["countdown"]))
        self.sequence_editor.record_moves_check.setChecked(bool(d["recordMoves"]))
        with QSignalBlocker(self.theme_combo):
            self.theme_combo.setCurrentIndex(max(self.theme_combo.findData(d["theme"]), 0))
        self._apply_theme()
        self.toggle_edit.set_hotkey(d["toggleKey"])
        self.stop_edit.set_hotkey(d["stopKey"])
        self._apply_always_on_top()
        self._sync_hotkeys()
        with QSignalBlocker(self.tabs):
            self.tabs.setCurrentIndex(_SEQUENCE_TAB if d["runMode"] == "sequence" else _CLICKER_TAB)
        self._set_run_mode(d["runMode"])

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
            self.interval_slider.setValue(max(MIN_INTERVAL_MS, min(2000, int(value))))

    def _on_interval_slider(self, value: int) -> None:
        self.interval_spin.setValue(int(value))

    def _update_rate_label(self, *_args) -> None:
        per_second = 1000 / self.interval_spin.value()
        if per_second >= 1:
            self.rate_label.setText(f"{per_second:,.1f} clicks/s")
        else:
            self.rate_label.setText(f"{per_second * 60:,.1f} clicks/min")

    def _sync_jitter(self, *_args) -> None:
        self.engine.set_jitter(self.jitter_pct_spin.value(), self.jitter_px_spin.value())

    def _pick(self) -> Pick | None:
        """Full-screen picker with this window and the overlay out of the way."""
        try:
            return pick_point(hide=[self, self.hud])
        except OSError as exc:
            QMessageBox.warning(self, "Could not pick a point", str(exc))
            return None

    def _capture_position(self) -> None:
        pick = self._pick()
        if pick is None:
            return
        x, y = pick.x, pick.y
        self._fixed_position = (x, y)
        self._background_target = (pick.hwnd, pick.title) if pick.hwnd else None
        self.position_label.setText(f"X: {x}   Y: {y}")
        self.position_combo.setCurrentIndex(self.position_combo.findData("fixed"))
        self._sync_position()
        self._update_target_label()
        self._schedule_save()
        if self.failsafe_check.isChecked() and in_failsafe_corner(
            x, y, current_failsafe_corners()
        ):
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

    def _on_background_toggled(self, checked: bool) -> None:
        if checked:
            self.position_combo.setCurrentIndex(self.position_combo.findData("fixed"))
        self._update_target_label()

    def _update_target_label(self) -> None:
        if not self.background_check.isChecked():
            self.target_label.setVisible(False)
            return
        self.target_label.setVisible(True)
        target = self._background_target
        if target and winapi.is_window(target[0]):
            self.target_label.setText(f"Target window: {target[1] or 'untitled window'}")
        else:
            self.target_label.setText("Pick the position to choose the target window.")

    def _sync_button(self, *_args) -> None:
        self.engine.set_button(self.button_combo.currentData())

    def _apply_trigger(self, trigger: Trigger) -> None:
        self._trigger = trigger
        with QSignalBlocker(self.trigger_combo), QSignalBlocker(self.trigger_tolerance_spin):
            self.trigger_combo.setCurrentIndex(max(self.trigger_combo.findData(trigger.mode), 0))
            self.trigger_tolerance_spin.setValue(trigger.tolerance)
        if trigger.x is None:
            self.trigger_label.setText("No pixel picked")
        else:
            self.trigger_label.setText(
                f"X: {trigger.x}   Y: {trigger.y}   "
                f"<span style='color:{trigger.color}'>■</span> {trigger.color}"
            )
        self.engine.set_trigger(trigger)

    def _sync_trigger(self, *_args) -> None:
        t = self._trigger
        self._apply_trigger(
            Trigger(
                str(self.trigger_combo.currentData()), t.x, t.y, t.color, self.trigger_tolerance_spin.value()
            )
        )

    def _pick_trigger(self) -> None:
        pick = self._pick()
        if pick is None:
            return
        mode = self._trigger.mode if self._trigger.mode != "off" else "wait"
        self._apply_trigger(
            Trigger(mode, pick.x, pick.y, format_color(pick.color), self.trigger_tolerance_spin.value())
        )
        self._schedule_save()

    def _sync_hotkeys(self, *_args) -> None:
        toggle_text = self.toggle_edit.hotkey()
        stop_text = self.stop_edit.hotkey()
        try:
            self.hotkeys.set_keys(toggle_text, stop_text)
        except ValueError as exc:
            # Keep the previous hotkeys active until the pickers hold a valid pair.
            self._show_hotkey_problem(str(exc))
            return
        self.hotkey_hint.setVisible(False)
        toggle, stop = parse_hotkey(toggle_text), parse_hotkey(stop_text)
        self._hotkey_specs = (str(toggle), str(stop))
        self.hotkey_note.setText(f"Global hotkeys: {toggle.label} start/pause · {stop.label} emergency stop")
        self._tray.set_hotkey_labels(toggle.label, stop.label)

    def _show_hotkey_problem(self, message: str) -> None:
        self.hotkey_hint.setText(message)
        self.hotkey_hint.setStyleSheet(status_style("error"))
        self.hotkey_hint.setVisible(True)

    def _on_tab_changed(self, index: int) -> None:
        if index in (_CLICKER_TAB, _SEQUENCE_TAB) and self._state == "idle":
            self._set_run_mode("sequence" if index == _SEQUENCE_TAB else "simple")

    def _set_run_mode(self, mode: str) -> None:
        self._run_mode = mode
        self.mode_label.setText("Mode: Sequence" if mode == "sequence" else "Mode: Clicker")

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
        self.mode_label.setStyleSheet(styles["stats"])
        self.hotkey_note.setStyleSheet(styles["note"])
        self.sequence_note.setStyleSheet(styles["note"])
        self.target_label.setStyleSheet(styles["note"])
        self.position_label.setStyleSheet(styles["position"])
        self.trigger_label.setStyleSheet(styles["position"])
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

    # ---------------------------------------------------------------- overlay

    def _refresh_hud(self, *_args) -> None:
        if self._state == "countdown":
            self.hud.show()
            return
        if not self.overlay_check.isChecked() or self._state == "idle":
            self.hud.hide()
            return
        titles = {"running": "Clicking", "paused": "Paused", "recording": "Recording"}
        kinds = {"running": "run", "paused": "pause", "recording": "record"}
        if self._state == "recording":
            stop_key = parse_hotkey(self._hotkey_specs[0]).label
            detail = f"{self._recorder.event_count} events · stop with {stop_key}"
        elif self._run_mode == "sequence" and self._last_progress is not None:
            step, loops = self._last_progress
            total = len(self.sequence_editor.model.steps())
            detail = f"Step {step + 1}/{total} · loop {loops + 1} · {self._last_count} clicks"
        else:
            detail = f"{self._last_count} clicks · {len(self._click_times)}/min"
        self.hud.set_status(titles.get(self._state, ""), detail, kinds.get(self._state, "idle"))
        self.hud.show()

    # -------------------------------------------------------------- countdown

    def _start_countdown(self, action: Callable[[], None], what: str) -> None:
        seconds = self.countdown_spin.value()
        if seconds <= 0:
            action()
            return
        self._countdown_left = seconds
        self._countdown_action = action
        self._countdown_what = what
        self._set_state("countdown")
        self.hud.set_countdown(seconds)
        self._set_status(f"Status: {what} in {seconds}…", "pause")
        self._countdown_timer.start()

    def _countdown_tick(self) -> None:
        self._countdown_left -= 1
        if self._countdown_left > 0:
            self.hud.set_countdown(self._countdown_left)
            self._set_status(f"Status: {self._countdown_what} in {self._countdown_left}…", "pause")
            return
        action = self._countdown_action
        self._end_countdown()
        if action is not None:
            action()

    def _end_countdown(self) -> None:
        self._countdown_timer.stop()
        self._countdown_action = None
        self.hud.set_countdown(None)
        if self._state == "countdown":
            self._set_state("idle")

    # ------------------------------------------------------------- clicking

    def _push_engine_settings(self) -> bool:
        if not self.engine.set_interval_ms(self.interval_spin.value()):
            self._alert("Invalid interval", f"Minimum interval is {MIN_INTERVAL_MS} ms.")
            return False
        if self._run_mode == "simple":
            if self.position_combo.currentData() == "fixed" and self._fixed_position is None:
                self._set_status("Status: Pick a position before using fixed coordinates", "error")
                self._alert(
                    "Coordinates required",
                    "Press 'Pick position…' before using fixed coordinates.",
                    "info",
                )
                return False
            if self.background_check.isChecked():
                target = self._background_target
                if not target or not winapi.is_window(target[0]):
                    self._set_status("Status: Pick the position again to choose the target window", "error")
                    self._alert(
                        "Target window required",
                        "Background clicks need a window. Press 'Pick position…' and click inside it.",
                        "info",
                    )
                    return False
                self.engine.set_background_target(target[0])
            else:
                self.engine.set_background_target(None)
            if self._trigger.mode != "off" and self._trigger.x is None:
                self._set_status("Status: Pick the trigger pixel first", "error")
                return False
        else:
            sequence = self.sequence_editor.sequence()
            if not sequence.steps:
                self._set_status("Status: Add or record steps before playing the sequence", "error")
                return False
            self.engine.set_sequence(sequence)
        self.engine.set_mode(self._run_mode)
        self._sync_position()
        self._sync_button()
        self.engine.set_trigger(self._trigger)
        self.engine.set_double_click(self.double_check.isChecked())
        self.engine.set_failsafe(self.failsafe_check.isChecked())
        self._sync_jitter()
        return True

    @Slot()
    def _on_hotkey_toggle(self) -> None:
        if self._state == "recording":
            self._stop_recording(via_hotkey=True)
        else:
            self._toggle_clicking()

    @Slot()
    def _toggle_clicking(self) -> None:
        if self._state == "countdown":
            self._end_countdown()
            self._set_status("Status: Start cancelled", "idle")
            return
        if self._state == "recording":
            self._stop_recording(via_hotkey=False)
            return
        if self.engine.is_active():
            self.engine.pause_clicking()
            self._set_state("paused")
            self._set_status("Status: Paused", "pause")
            self._beep()
            return
        if self.engine.is_paused():
            if not self._push_engine_settings():
                return
            self.engine.resume_clicking()
            self._set_state("running")
            self._set_status(self._running_text(), "run")
            self._beep()
            return

        if not self._push_engine_settings():
            return
        max_clicks = self.max_clicks_spin.value() or None
        max_seconds = self.max_seconds_spin.value() or None
        try:
            self.engine.set_limits(max_clicks, max_seconds)
        except ValueError as exc:
            self._alert("Invalid limits", str(exc))
            return
        self._target_clicks = max_clicks
        self._start_countdown(self._begin_run, "Clicking starts")

    def _running_text(self) -> str:
        return "Status: Playing sequence" if self._run_mode == "sequence" else "Status: Clicking"

    def _begin_run(self) -> None:
        self._last_progress = None
        self.engine.start_clicking()
        self._set_state("running")
        self._set_status(self._running_text(), "run")
        self._beep()

    @Slot()
    def _emergency_stop(self) -> None:
        self.engine.emergency_stop()
        self._show_emergency_stopped(via_hotkey=False)

    @Slot()
    def _on_global_emergency_stop(self) -> None:
        # The listener has already stopped the engine directly. This queued
        # receiver only updates widgets on the main UI thread.
        self._show_emergency_stopped(via_hotkey=True)

    def _show_emergency_stopped(self, *, via_hotkey: bool) -> None:
        if self._state == "countdown":
            self._end_countdown()
        if self._state == "recording":
            self._stop_recording(via_hotkey=via_hotkey)
            return
        self._set_state("idle")
        self._set_status("Status: Emergency stop — clicking halted", "stop")
        self._beep()

    def _set_state(self, state: str) -> None:
        self._state = state
        running = state == "running"
        idle = state == "idle"
        labels = {
            "running": "Pause",
            "paused": "Resume",
            "countdown": "Cancel",
            "recording": "Stop recording",
        }
        self.toggle_button.setText(labels.get(state, "Start"))
        self.position_combo.setEnabled(not running)
        self.capture_button.setEnabled(not running)
        self.trigger_pick_button.setEnabled(not running)
        # Limits belong to a run; editing them while paused would be ignored.
        self.max_clicks_spin.setEnabled(idle)
        self.max_seconds_spin.setEnabled(idle)
        self.sequence_editor.set_editing_enabled(idle)
        self.sequence_editor.record_button.setEnabled(idle or state == "recording")
        self.sequence_editor.record_button.setText("■ Stop recording" if state == "recording" else "● Record")
        if idle:
            self.sequence_editor.model.set_current(None)
            self._set_run_mode("sequence" if self.tabs.currentIndex() == _SEQUENCE_TAB else self._run_mode)
        self._update_profile_controls()
        self._refresh_hud()

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
        self._refresh_hud()

    @Slot(int, int)
    def _on_progress(self, step: int, loops: int) -> None:
        if self._run_mode != "sequence":
            return
        self._last_progress = (step, loops)
        if self._state in {"running", "paused"}:
            self.sequence_editor.model.set_current(step)
        self._refresh_hud()

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
    def _on_condition_stopped(self, message: str) -> None:
        self._set_state("idle")
        self._set_status(f"Status: {message}", "stop")
        self._beep()

    @Slot(str)
    def _on_limit_reached(self, message: str) -> None:
        self._set_state("idle")
        self._set_status(f"Status: {message}", "done")
        self._beep()

    # -------------------------------------------------------------- recording

    @Slot()
    def _toggle_recording(self) -> None:
        if self._state == "recording":
            self._stop_recording(via_hotkey=False)
        elif self._state == "idle":
            self._start_countdown(self._begin_recording, "Recording starts")

    def _begin_recording(self) -> None:
        try:
            self._recorder.start(
                record_moves=self.sequence_editor.record_moves_check.isChecked(),
                own_pid=os.getpid(),
            )
        except OSError as exc:
            self._set_state("idle")
            self._alert("Recording failed", str(exc), "critical")
            return
        self._set_state("recording")
        toggle = parse_hotkey(self._hotkey_specs[0]).label
        self._set_status(f"Status: Recording — press {toggle} to stop", "error")
        self._record_timer.start()
        self._beep()

    def _on_record_tick(self) -> None:
        if self._recorder.full:
            self._stop_recording(via_hotkey=False)
            return
        self._refresh_hud()

    def _stop_recording(self, *, via_hotkey: bool) -> None:
        self._record_timer.stop()
        events = self._recorder.stop()
        trailing = (
            {parse_hotkey(spec).vk for spec in self._hotkey_specs} if via_hotkey else set()
        )
        steps = events_to_steps(events, trailing)
        self._set_state("idle")
        if steps:
            self.sequence_editor.append_steps(steps)
            self._set_status(f"Status: Recorded {len(steps)} step(s)", "done")
        else:
            self._set_status("Status: Nothing was recorded", "idle")
        self._beep()

    # ------------------------------------------------------------------ misc

    @Slot(str)
    def _on_hotkey_error(self, message: str) -> None:
        _logger.warning("%s", message)
        self._set_status("Status: A global hotkey is unavailable", "error")
        self._show_hotkey_problem(message)

    # ---------------------------------------------------------------- updates

    def _auto_check_updates(self) -> None:
        if not (self.updates_check.isChecked() and self._update_source_ready):
            return
        if time.time() - self._last_update_check < updater.CHECK_INTERVAL_SECONDS:
            return
        self._start_update_check(manual=False)

    @Slot()
    def _check_updates_now(self) -> None:
        self._start_update_check(manual=True)

    def _start_update_check(self, *, manual: bool) -> None:
        self._manual_update_check = manual
        if not self._update_checker.start():
            return
        self.update_button.setEnabled(False)
        self.update_label.setText("Checking for updates…")

    def _finish_update_check(self) -> None:
        self.update_button.setEnabled(self._update_source_ready)

    @Slot(object)
    def _on_update_result(self, info: object) -> None:
        self._finish_update_check()
        self._last_update_check = int(time.time())
        self._schedule_save()
        if info is None:
            self._update_url = None
            self.update_open_button.setVisible(False)
            self.update_label.setText(f"You are up to date ({__version__}).")
            return
        assert isinstance(info, updater.UpdateInfo)
        self._update_url = info.url
        self.update_open_button.setVisible(True)
        self.update_label.setText(f"Version {info.version} is available (you have {__version__}).")
        if not self._manual_update_check:
            self._tray.notify(f"AutoClick Pro {info.version} is available.", msecs=5000)

    @Slot(str)
    def _on_update_failed(self, message: str) -> None:
        self._finish_update_check()
        _logger.warning("Update check failed: %s", message)
        if self._manual_update_check:
            self.update_label.setText(message)
        else:
            self.update_label.setText(f"Installed version: {__version__}")

    @Slot()
    def _open_update_page(self) -> None:
        url = self._update_url
        if url and updater.is_safe_release_url(url, updater.UPDATE_REPO):
            QDesktopServices.openUrl(QUrl(url))

    # ------------------------------------------------------------ diagnostics

    def notify_previous_crash(self, report: Path) -> None:
        self._set_status(
            f"Status: AutoClick Pro closed unexpectedly last time. Report saved as {report.name}.", "error"
        )

    def diagnostics_text(self) -> str:
        return diagnostics.collect_diagnostics(
            settings=self._store.settings, profile_count=len(self._store.profiles)
        )

    @Slot()
    def _copy_diagnostics(self) -> None:
        QApplication.clipboard().setText(self.diagnostics_text())
        self._set_status("Status: Diagnostics copied to the clipboard", "done")

    @Slot()
    def _show_about(self) -> None:
        admin = "yes" if _is_admin() else "no"
        box = QMessageBox(
            QMessageBox.Icon.Information,
            "About AutoClick Pro",
            f"AutoClick Pro {__version__}\n\n"
            "Automatic mouse clicks for Windows.\n"
            f"Running as admin: {admin}\n"
            f"Settings: {self._store.path}\n"
            f"Log file: {log_path()}\n\n"
            "Tip: run this app and the target app at the same "
            "privilege level or clicks may be blocked.",
            QMessageBox.StandardButton.Ok,
            self,
        )
        copy_button = box.addButton("Copy diagnostics", QMessageBox.ButtonRole.ActionRole)
        box.exec()
        if box.clickedButton() is copy_button:
            self._copy_diagnostics()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._shut_down:
            event.accept()
            return
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
        self._shut_down = True
        if self._state == "recording":
            self._stop_recording(via_hotkey=False)
        self._end_countdown()
        self._save_settings()
        self._tray.hide()
        self.hud.close()
        self.hud.deleteLater()
        self.hotkeys.stop()
        self.engine.shutdown()
        event.accept()
