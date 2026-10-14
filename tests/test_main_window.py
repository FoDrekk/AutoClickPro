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


@pytest.fixture
def make_window(qtbot, tmp_path, mouse, dialogs):
    from autoclick_pro.ui.main_window import MainWindow

    def _make(store=None):
        store = store or SettingsStore.load(tmp_path / "settings.json")
        window = MainWindow(store, start_hotkeys=False)
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
    with qtbot.waitSignal(window.engine.limit_reached, timeout=TIMEOUT_MS):
        window._toggle_clicking()
    qtbot.waitUntil(lambda: window.toggle_button.text() == "Start", timeout=TIMEOUT_MS)
    with qtbot.waitSignal(window.engine.limit_reached, timeout=TIMEOUT_MS):
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
    assert "Capture" in window.status_label.text()
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
