import sys

import pytest

from autoclick_pro import winapi
from autoclick_pro.global_hotkeys import GlobalHotkeys, Hotkey, parse_hotkey

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="RegisterHotKey is Windows-only")

# Rare keys so tests never collide with hotkeys the user actually has.
COMBO_A = "ctrl+alt+shift+f21"
COMBO_B = "ctrl+alt+shift+f22"
COMBO_C = "ctrl+alt+shift+f23"
TIMEOUT_MS = 3000


@pytest.mark.parametrize(
    ("text", "canonical", "label"),
    [
        ("f6", "f6", "F6"),
        ("F6", "f6", "F6"),
        ("Ctrl+Alt+F6", "ctrl+alt+f6", "Ctrl+Alt+F6"),
        ("alt+ctrl+a", "ctrl+alt+a", "Ctrl+Alt+A"),
        ("control + shift + f1", "ctrl+shift+f1", "Ctrl+Shift+F1"),
        ("win+space", "win+space", "Win+Space"),
        ("ctrl+f12", "ctrl+f12", "Ctrl+F12"),
        ("pause", "pause", "Pause"),
        ("scrolllock", "scrolllock", "ScrollLock"),
        ("ctrl+0", "ctrl+0", "Ctrl+0"),
    ],
)
def test_parse_hotkey(text, canonical, label):
    hotkey = parse_hotkey(text)
    assert str(hotkey) == canonical
    assert hotkey.label == label
    assert parse_hotkey(str(hotkey)) == hotkey


@pytest.mark.parametrize(
    "text",
    ["", "   ", "a", "shift+a", "space", "ctrl+", "+f1", "hyper+f1", "ctrl+f99", "esc", "f12", None, 6],
)
def test_parse_hotkey_rejects(text):
    with pytest.raises(ValueError):
        parse_hotkey(text)


def test_virtual_key_and_flags():
    assert Hotkey("f1").vk == 0x70
    assert Hotkey("f24").vk == 0x87
    assert Hotkey("a").vk == ord("A")
    assert parse_hotkey("ctrl+alt+f6").modifier_flags == 0x0003
    assert parse_hotkey("shift+win+f6").modifier_flags == 0x000C


def test_set_keys_validates(qapp):
    h = GlobalHotkeys()
    h.set_keys("f7", "ctrl+f9")
    with pytest.raises(ValueError):
        h.set_keys("f7", "F7")
    with pytest.raises(ValueError):
        h.set_keys("a", "f9")


@pytest.fixture
def make_hotkeys(qapp):
    created = []

    def _make(toggle=COMBO_A, stop=COMBO_B, callback=None):
        h = GlobalHotkeys(callback)
        h.set_keys(toggle, stop)
        created.append(h)
        return h

    yield _make
    for h in created:
        h.stop()


def _post(h, hotkey_id):
    assert winapi.PostThreadMessageW(h._thread_id, winapi.WM_HOTKEY, hotkey_id, 0)


@windows_only
def test_listener_dispatches_hotkeys(make_hotkeys, qtbot):
    stops = []
    h = make_hotkeys(callback=lambda: stops.append(True))
    errors = []
    h.error_occurred.connect(errors.append)
    h.start()
    assert h.is_running()

    with qtbot.wait_thread_signal(h.toggle_requested, timeout=TIMEOUT_MS):
        _post(h, 1)
    with qtbot.wait_thread_signal(h.emergency_stop_requested, timeout=TIMEOUT_MS):
        _post(h, 2)
    assert stops == [True]
    assert errors == []


@windows_only
def test_conflict_with_other_program_is_reported(make_hotkeys, qtbot):
    first = make_hotkeys()
    first.start()
    second = make_hotkeys()
    with qtbot.wait_thread_signal(second.error_occurred, timeout=TIMEOUT_MS) as blocker:
        second.start()
    assert "already uses it" in blocker.args[0]


@windows_only
def test_set_keys_reregisters_and_releases_old_keys(make_hotkeys, qtbot):
    first = make_hotkeys(COMBO_A, COMBO_B)
    first.start()
    first.set_keys(COMBO_C, COMBO_B)
    qtbot.wait(200)  # Re-registration happens on the listener thread.

    second = make_hotkeys(COMBO_A, "ctrl+alt+shift+f24")
    errors = []
    second.error_occurred.connect(errors.append)
    second.start()
    qtbot.wait(200)
    assert errors == []


@windows_only
def test_stop_unregisters(make_hotkeys, qtbot):
    first = make_hotkeys()
    first.start()
    first.stop()
    assert not first.is_running()

    second = make_hotkeys()
    errors = []
    second.error_occurred.connect(errors.append)
    second.start()
    qtbot.wait(200)
    assert errors == []
