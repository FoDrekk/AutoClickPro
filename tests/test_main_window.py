import json

import pytest
from PySide6.QtWidgets import QInputDialog, QMessageBox

from autoclick_pro.settings_store import SettingsStore

TIMEOUT_MS = 5000


@pytest.fixture
def dialogs(monkeypatch):
    """Record modal dialogs instead of blocking the test run on them."""
    shown = []

    def record(kind, answer=None):
        def _show(*args, **kwargs):
            shown.append((kind, args[1] if len(args) > 1 else ""))
            return answer

        return _show

    monkeypatch.setattr(QMessageBox, "warning", record("warning"))
    monkeypatch.setattr(QMessageBox, "information", record("information"))
    monkeypatch.setattr(QMessageBox, "critical", record("critical"))
    monkeypatch.setattr(QMessageBox, "question", record("question", QMessageBox.StandardButton.Yes))
    return shown


class FakeRecorder:
    """Replaces the low-level hooks; tests feed it events directly."""

    def __init__(self):
        self.events = []
        self.recording = False
        self.started_with = None

    @property
    def event_count(self):
        return len(self.events)

    @property
    def full(self):
        return False

    def is_recording(self):
        return self.recording

    def start(self, *, record_moves, own_pid):
        self.recording = True
        self.started_with = (record_moves, own_pid)

    def stop(self):
        self.recording = False
        return list(self.events)


@pytest.fixture
def make_window(qtbot, tmp_path, mouse, dialogs):
    from autoclick_pro.ui.main_window import MainWindow

    def _make(store=None, recorder=None, update_checker=None):
        store = store or SettingsStore.load(tmp_path / "settings.json")
        window = MainWindow(
            store, start_hotkeys=False, recorder=recorder or FakeRecorder(), update_checker=update_checker
        )
        qtbot.addWidget(window)
        return window

    return _make


@pytest.fixture
def window(make_window):
    return make_window()


def _settings_file(window):
    return json.loads(window._store.path.read_text(encoding="utf-8"))


def test_pause_then_resume_keeps_count(window, mouse, qtbot):
    counts = []
    window.engine.click_count_changed.connect(counts.append)
    window.interval_spin.setValue(10)
    window._toggle_clicking()
    qtbot.waitUntil(lambda: mouse.presses >= 3, timeout=TIMEOUT_MS)

    window._toggle_clicking()
    assert window.toggle_button.text() == "Resume"
    assert not window.max_clicks_spin.isEnabled()
    paused_at = mouse.presses

    window._toggle_clicking()
    assert window.toggle_button.text() == "Pause"
    qtbot.waitUntil(lambda: mouse.presses > paused_at + 2, timeout=TIMEOUT_MS)
    window._emergency_stop()
    assert counts.count(0) == 1
    assert window.toggle_button.text() == "Start"
    assert window.max_clicks_spin.isEnabled()


def test_restart_after_limit_starts_fresh(window, mouse, qtbot):
    window.interval_spin.setValue(10)
    window.max_clicks_spin.setValue(3)
    with qtbot.wait_thread_signal(window.engine.limit_reached, timeout=TIMEOUT_MS):
        window._toggle_clicking()
    qtbot.waitUntil(lambda: window.toggle_button.text() == "Start", timeout=TIMEOUT_MS)
    with qtbot.wait_thread_signal(window.engine.limit_reached, timeout=TIMEOUT_MS):
        window._toggle_clicking()
    assert mouse.presses == 6
    qtbot.waitUntil(lambda: window.count_label.text() == "3 / 3", timeout=TIMEOUT_MS)


def test_failsafe_shows_status_not_error_dialog(window, mouse, dialogs, qtbot):
    mouse.position = (0, 0)
    window.failsafe_check.setChecked(True)
    window._toggle_clicking()
    qtbot.waitUntil(lambda: "Failsafe" in window.status_label.text(), timeout=TIMEOUT_MS)
    assert dialogs == []
    assert window.toggle_button.text() == "Start"


def test_hotkey_start_without_coordinates_does_not_block(window, dialogs):
    # The window is not active (a hotkey fired from another app): no modal box.
    window.position_combo.setCurrentIndex(window.position_combo.findData("fixed"))
    window._fixed_position = None
    window._toggle_clicking()
    assert dialogs == []
    assert "Pick a position" in window.status_label.text()
    assert not window.engine.is_active()


def test_always_on_top_keeps_window_visible(window, qtbot):
    window.show()
    qtbot.waitExposed(window)
    window.top_check.setChecked(True)
    assert window.isVisible()
    window.top_check.setChecked(False)
    assert window.isVisible()


def test_settings_autosave(window, qtbot):
    window.interval_spin.setValue(321)
    qtbot.waitUntil(lambda: window._store.path.exists(), timeout=TIMEOUT_MS)
    assert _settings_file(window)["settings"]["interval"] == 321


def test_corrupt_settings_warns_and_starts(make_window, tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("\x00garbage", encoding="utf-8")
    window = make_window(SettingsStore.load(path))
    assert "reset" in window.status_label.text()
    assert window.interval_spin.value() == 100


def test_profile_with_slash_saves_and_loads(window, monkeypatch, qtbot):
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("games/fast", True))
    window.interval_spin.setValue(25)
    window.button_combo.setCurrentIndex(window.button_combo.findData("right"))
    window._save_profile()
    assert window.profile_combo.findData("games/fast") >= 0
    assert "games/fast" in _settings_file(window)["profiles"]

    window.interval_spin.setValue(900)
    window.button_combo.setCurrentIndex(0)
    window._load_profile(window.profile_combo.findData("games/fast"))
    assert window.interval_spin.value() == 25
    assert window.button_combo.currentData() == "right"


def test_profile_does_not_change_theme_or_hotkeys(window, monkeypatch):
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("p", True))
    window._save_profile()
    window.theme_combo.setCurrentIndex(window.theme_combo.findData("light"))
    window._load_profile(window.profile_combo.findData("p"))
    assert window.theme_combo.currentData() == "light"


def test_profiles_locked_while_running(window, monkeypatch, qtbot, mouse):
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("p", True))
    window._save_profile()
    assert window.profile_combo.isEnabled()
    window._toggle_clicking()
    assert not window.profile_combo.isEnabled()
    window._toggle_clicking()  # Pause.
    assert not window.profile_combo.isEnabled()
    window._emergency_stop()
    assert window.profile_combo.isEnabled()


def test_invalid_profile_name_rejected(window, monkeypatch, dialogs):
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("   ", True))
    window._save_profile()
    assert dialogs and dialogs[0][0] == "warning"
    assert window._store.profiles == {}


def test_close_saves_and_stops_engine(window, mouse, qtbot):
    window.interval_spin.setValue(10)
    window._toggle_clicking()
    qtbot.waitUntil(lambda: mouse.presses >= 1, timeout=TIMEOUT_MS)
    window.close()
    assert not window.engine.isRunning()
    assert _settings_file(window)["settings"]["interval"] == 10


def test_incomplete_hotkey_keeps_previous_until_valid(window):
    window.toggle_edit.set_hotkey("f6")
    window._sync_hotkeys()
    # Picking a letter first is an incomplete combo: the old hotkey stays.
    window.toggle_edit._key_combo.setCurrentIndex(window.toggle_edit._key_combo.findData("s"))
    assert not window.hotkey_hint.isHidden()
    assert window._hotkey_specs[0] == "f6"
    window.toggle_edit._modifier_buttons["ctrl"].setChecked(True)
    window.toggle_edit._modifier_buttons["alt"].setChecked(True)
    assert window.hotkey_hint.isHidden()
    assert window._hotkey_specs[0] == "ctrl+alt+s"
    assert "Ctrl+Alt+S" in window.hotkey_note.text()


def test_hotkey_conflict_is_shown_inline(window, dialogs):
    window.stop_edit.set_hotkey("f6")
    window._sync_hotkeys()
    assert not window.hotkey_hint.isHidden()
    assert dialogs == []


def test_hotkey_registration_error_shown_inline(window, dialogs):
    window._on_hotkey_error("Could not register F6 for start/pause: another program already uses it.")
    assert "another program" in window.hotkey_hint.text()
    assert dialogs == []


def test_jitter_and_rate_persist(window, qtbot):
    window.interval_spin.setValue(4)
    assert window.rate_label.text() == "250.0 clicks/s"
    window.interval_spin.setValue(120_000)
    assert window.rate_label.text() == "0.5 clicks/min"
    window.jitter_pct_spin.setValue(20)
    window.jitter_px_spin.setValue(5)
    assert (window.engine._jitter_pct, window.engine._jitter_px) == (20, 5)
    qtbot.waitUntil(lambda: window._store.path.exists(), timeout=TIMEOUT_MS)
    qtbot.waitUntil(lambda: _settings_file(window)["settings"]["jitterPx"] == 5, timeout=TIMEOUT_MS)
    assert _settings_file(window)["settings"]["jitterPct"] == 20


# ------------------------------------------------------------------ phase 2.1


def _use_sequence(window, steps, loops=1):
    from autoclick_pro.steps import Sequence

    window.tabs.setCurrentIndex(1)
    window.sequence_editor.set_sequence(Sequence(tuple(steps), loops))


def test_sequence_tab_plays_sequence(window, mouse, qtbot):
    from autoclick_pro.steps import Step

    _use_sequence(window, [Step("click", 10, 10, delay=1), Step("click", 20, 20, button="right", delay=1)], 2)
    assert window.mode_label.text() == "Mode: Sequence"
    window._toggle_clicking()
    assert not window.sequence_editor.add_click_button.isEnabled()  # Locked while playing.
    qtbot.waitUntil(lambda: "Sequence finished" in window.status_label.text(), timeout=TIMEOUT_MS)
    assert [e[1] for e in mouse.events if e[0] == "click"] == ["left", "right", "left", "right"]
    assert window.sequence_editor.add_click_button.isEnabled()


def test_empty_sequence_does_not_start(window):
    window.tabs.setCurrentIndex(1)
    window._toggle_clicking()
    assert "Add or record steps" in window.status_label.text()
    assert window.toggle_button.text() == "Start"


def test_clicker_tab_ignores_sequence(window, mouse, qtbot):
    from autoclick_pro.steps import Step

    _use_sequence(window, [Step("click", button="right", delay=1)])
    window.tabs.setCurrentIndex(0)
    window.max_clicks_spin.setValue(2)
    with qtbot.wait_thread_signal(window.engine.limit_reached, timeout=TIMEOUT_MS):
        window._toggle_clicking()
    assert [e[1] for e in mouse.events if e[0] == "click"] == ["left", "left"]


def test_countdown_then_start(window, mouse, qtbot):
    window.countdown_spin.setValue(1)
    window._toggle_clicking()
    assert window.toggle_button.text() == "Cancel"
    assert window.hud.countdown == 1
    assert mouse.presses == 0
    qtbot.waitUntil(lambda: window.toggle_button.text() == "Pause", timeout=TIMEOUT_MS)
    assert window.hud.countdown is None
    window._emergency_stop()


def test_countdown_can_be_cancelled(window, mouse, qtbot):
    window.countdown_spin.setValue(2)
    window._toggle_clicking()
    window._toggle_clicking()
    assert window.toggle_button.text() == "Start"
    assert "cancelled" in window.status_label.text()
    qtbot.wait(300)
    assert mouse.presses == 0
    assert not window.engine.is_active()


def test_recording_adds_steps_and_strips_hotkey(make_window):
    from autoclick_pro.recorder import RawEvent
    from autoclick_pro.steps import Step

    recorder = FakeRecorder()
    window = make_window(recorder=recorder)
    window.sequence_editor.record_moves_check.setChecked(True)
    window._toggle_recording()
    assert window.toggle_button.text() == "Stop recording"
    assert recorder.started_with[0] is True
    recorder.events = [
        RawEvent(0.0, "down", 4, 5),
        RawEvent(0.05, "up", 4, 5),
        RawEvent(0.5, "key_down", vk=0x75),  # The F6 stop hotkey.
    ]
    window._on_hotkey_toggle()
    assert window.toggle_button.text() == "Start"
    assert window.sequence_editor.sequence().steps == (Step("click", 4, 5, delay=100),)
    assert "Recorded 1 step" in window.status_label.text()


def test_emergency_stop_ends_recording(make_window):
    recorder = FakeRecorder()
    window = make_window(recorder=recorder)
    window._toggle_recording()
    window._emergency_stop()
    assert not recorder.recording
    assert "Nothing was recorded" in window.status_label.text()


def test_trigger_requires_pixel(window):
    window.trigger_combo.setCurrentIndex(window.trigger_combo.findData("wait"))
    window._toggle_clicking()
    assert "trigger pixel" in window.status_label.text()
    assert not window.engine.is_active()


def test_picked_trigger_reaches_engine(window, monkeypatch):
    import autoclick_pro.ui.main_window as mw
    from autoclick_pro.ui.picker import Pick

    monkeypatch.setattr(mw, "pick_point", lambda hide=None: Pick(3, 4, (255, 0, 0), 0, ""))
    window._pick_trigger()
    assert window.trigger_combo.currentData() == "wait"
    assert window.engine._trigger.color == "#FF0000"
    assert "#FF0000" in window.trigger_label.text()


def test_background_needs_target_window(window, monkeypatch):
    import autoclick_pro.ui.main_window as mw
    from autoclick_pro.ui.picker import Pick

    window.background_check.setChecked(True)
    assert window.position_combo.currentData() == "fixed"
    monkeypatch.setattr(mw, "pick_point", lambda hide=None: Pick(30, 40, (0, 0, 0), 0, ""))
    window._capture_position()
    window._toggle_clicking()
    assert "target window" in window.status_label.text()


def test_background_clicks_use_picked_window(window, mouse, monkeypatch, qtbot):
    import autoclick_pro.ui.main_window as mw
    from autoclick_pro.ui.picker import Pick

    monkeypatch.setattr(mw, "pick_point", lambda hide=None: Pick(30, 40, (0, 0, 0), 0xABC, "Notepad"))
    monkeypatch.setattr(mw.winapi, "is_window", lambda hwnd: hwnd == 0xABC)
    window.background_check.setChecked(True)
    window._capture_position()
    assert "Notepad" in window.target_label.text()
    window.max_clicks_spin.setValue(1)
    with qtbot.wait_thread_signal(window.engine.limit_reached, timeout=TIMEOUT_MS):
        window._toggle_clicking()
    assert mouse.events == [("post", 0xABC, 30, 40, "left", 1)]


def test_overlay_follows_state(window, qtbot):
    window.overlay_check.setChecked(True)
    window.interval_spin.setValue(50)
    window._toggle_clicking()
    assert window.hud.isVisible()
    assert window.hud.title == "Clicking"
    window._toggle_clicking()
    assert window.hud.title == "Paused"
    window._emergency_stop()
    assert not window.hud.isVisible()
    window.overlay_check.setChecked(False)
    window._toggle_clicking()
    assert not window.hud.isVisible()
    window._emergency_stop()


def test_profile_keeps_sequence_and_trigger(window, monkeypatch):
    from autoclick_pro.steps import Sequence, Step, Trigger

    window.sequence_editor.set_sequence(Sequence((Step("key_down", vk=65),), loops=3))
    window._apply_trigger(Trigger("stop", 1, 2, "#00FF00", 5))
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("macro", True))
    window._save_profile()
    window.sequence_editor.clear()
    window._apply_trigger(Trigger())
    window._load_profile(window.profile_combo.findData("macro"))
    assert window.sequence_editor.sequence() == Sequence((Step("key_down", vk=65),), loops=3)
    assert window._trigger == Trigger("stop", 1, 2, "#00FF00", 5)


def test_run_mode_persists(make_window, tmp_path, qtbot):
    window = make_window()
    window.tabs.setCurrentIndex(1)
    window._save_settings()
    again = make_window(SettingsStore.load(tmp_path / "settings.json"))
    assert again.tabs.currentIndex() == 1
    assert again.mode_label.text() == "Mode: Sequence"


# ------------------------------------------------------------------ phase 2.2

REPO = "me/autoclick"


def test_unconfigured_update_source_disables_checks(window):
    assert not window.update_button.isEnabled()
    assert not window.updates_check.isEnabled()
    assert "no update source" in window.update_label.text()


def test_manual_check_up_to_date(make_window, qtbot):
    window = make_window(update_checker=lambda: None)
    window.update_button.click()
    qtbot.waitUntil(lambda: "up to date" in window.update_label.text(), timeout=TIMEOUT_MS)
    assert window.update_button.isEnabled()
    assert window.update_open_button.isHidden()
    assert window._last_update_check > 0


def test_manual_check_finds_update_and_opens_page(make_window, monkeypatch, qtbot):
    from autoclick_pro import updater
    from autoclick_pro.updater import UpdateInfo

    opened = []
    monkeypatch.setattr(updater, "UPDATE_REPO", REPO)
    monkeypatch.setattr(
        "autoclick_pro.ui.main_window.QDesktopServices.openUrl", lambda url: opened.append(url.toString())
    )
    page = f"https://github.com/{REPO}/releases/tag/v9.0.0"
    window = make_window(update_checker=lambda: UpdateInfo("9.0.0", page, "Notes"))
    window.update_button.click()
    qtbot.waitUntil(lambda: "9.0.0 is available" in window.update_label.text(), timeout=TIMEOUT_MS)
    assert not window.update_open_button.isHidden()
    window.update_open_button.click()
    assert opened == [page]


def test_update_page_must_belong_to_the_repo(make_window, monkeypatch, qtbot):
    from autoclick_pro import updater
    from autoclick_pro.updater import UpdateInfo

    opened = []
    monkeypatch.setattr(updater, "UPDATE_REPO", REPO)
    monkeypatch.setattr(
        "autoclick_pro.ui.main_window.QDesktopServices.openUrl", lambda url: opened.append(url)
    )
    window = make_window(update_checker=lambda: UpdateInfo("9.0.0", "https://evil.example/x.exe", ""))
    window.update_button.click()
    qtbot.waitUntil(lambda: not window.update_open_button.isHidden(), timeout=TIMEOUT_MS)
    window.update_open_button.click()
    assert opened == []


def test_failed_check_is_reported(make_window, qtbot):
    from autoclick_pro.updater import UpdateError

    def fail():
        raise UpdateError("Could not reach the update server: offline")

    window = make_window(update_checker=fail)
    window.update_button.click()
    qtbot.waitUntil(lambda: "offline" in window.update_label.text(), timeout=TIMEOUT_MS)
    assert window.update_button.isEnabled()


def test_unexpected_checker_error_does_not_crash(make_window, qtbot):
    def bug():
        raise RuntimeError("boom")

    window = make_window(update_checker=bug)
    window.update_button.click()
    qtbot.waitUntil(lambda: "boom" in window.update_label.text(), timeout=TIMEOUT_MS)


def test_auto_check_needs_opt_in_and_respects_interval(make_window, qtbot):
    import time

    calls = []
    window = make_window(update_checker=lambda: calls.append(1))
    window._auto_check_updates()  # Not opted in.
    qtbot.wait(100)
    assert calls == []
    window.updates_check.setChecked(True)
    window._last_update_check = int(time.time()) - 60  # Checked a minute ago.
    window._auto_check_updates()
    qtbot.wait(100)
    assert calls == []
    window._last_update_check = int(time.time()) - 8 * 24 * 3600
    window._auto_check_updates()
    qtbot.waitUntil(lambda: calls == [1], timeout=TIMEOUT_MS)


def test_update_preferences_persist(make_window, tmp_path, qtbot):
    import time

    window = make_window(update_checker=lambda: None)
    window.updates_check.setChecked(True)
    window.update_button.click()
    qtbot.waitUntil(lambda: "up to date" in window.update_label.text(), timeout=TIMEOUT_MS)
    window._save_settings()
    again = make_window(SettingsStore.load(tmp_path / "settings.json"), update_checker=lambda: None)
    assert again.updates_check.isChecked()
    assert again._last_update_check >= int(time.time()) - 30


def test_copy_diagnostics(window):
    from PySide6.QtWidgets import QApplication

    from autoclick_pro import __version__

    window._copy_diagnostics()
    text = QApplication.clipboard().text()
    assert f"AutoClick Pro {__version__}" in text
    assert "sequence steps: 0, profiles: 0" in text
    assert "copied" in window.status_label.text()


def test_previous_crash_is_reported(window, tmp_path):
    window.notify_previous_crash(tmp_path / "crash-20261015-120000.log")
    assert "closed unexpectedly" in window.status_label.text()
    assert "crash-20261015-120000.log" in window.status_label.text()
