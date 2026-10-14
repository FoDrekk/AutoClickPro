from types import SimpleNamespace

import pytest
from pynput import keyboard

from autoclick_pro.global_hotkeys import KEY_NAMES, GlobalHotkeys, key_from_name, vk_from_name

WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101


class Suppressed(Exception):
    pass


class FakeListener:
    def suppress_event(self):
        raise Suppressed


@pytest.fixture
def hotkeys(qapp):
    stops = []
    h = GlobalHotkeys(lambda: stops.append(True))
    h.stops = stops
    h.toggles = []
    h.stop_signals = []
    h.toggle_requested.connect(lambda: h.toggles.append(True))
    h.emergency_stop_requested.connect(lambda: h.stop_signals.append(True))
    yield h
    h.stop()


def test_hotkey_names_cover_f1_to_f12():
    assert [f"f{i}" for i in range(1, 13)] == KEY_NAMES
    assert key_from_name("f6") == keyboard.Key.f6
    with pytest.raises(ValueError):
        key_from_name("bogus")
    with pytest.raises(ValueError):
        key_from_name("esc")  # A real pynput key, but not an allowed hotkey.


def test_vk_codes():
    assert vk_from_name("f1") == 0x70
    assert vk_from_name("f12") == 0x7B


def test_hotkey_conflict_guard(hotkeys):
    hotkeys.set_keys("f7", "f9")
    with pytest.raises(ValueError):
        hotkeys.set_keys("f7", "f7")


def test_toggle_fires_once_per_press(hotkeys):
    hotkeys._key_down("f6")
    hotkeys._key_down("f6")  # Auto-repeat while held.
    assert hotkeys.toggles == [True]
    hotkeys._key_up("f6")
    hotkeys._key_down("f6")
    assert len(hotkeys.toggles) == 2


def test_stop_runs_callback_and_signal(hotkeys):
    hotkeys._key_down("f12")
    assert hotkeys.stops == [True]
    assert hotkeys.stop_signals == [True]


def test_win32_filter_swallows_hotkeys(hotkeys):
    hotkeys._listener = FakeListener()
    with pytest.raises(Suppressed):
        hotkeys._win32_filter(WM_KEYDOWN, SimpleNamespace(vkCode=vk_from_name("f6")))
    assert hotkeys.toggles == [True]
    with pytest.raises(Suppressed):
        hotkeys._win32_filter(WM_KEYUP, SimpleNamespace(vkCode=vk_from_name("f6")))
    hotkeys._listener = None


def test_win32_filter_passes_other_keys(hotkeys):
    hotkeys._listener = FakeListener()
    assert hotkeys._win32_filter(WM_KEYDOWN, SimpleNamespace(vkCode=0x41)) is True  # "A"
    assert hotkeys._win32_filter(WM_KEYDOWN, SimpleNamespace(vkCode=vk_from_name("f7"))) is True
    assert hotkeys.toggles == []
    hotkeys._listener = None


def test_win32_filter_follows_remapped_keys(hotkeys):
    hotkeys.set_keys("f2", "f3")
    hotkeys._listener = FakeListener()
    assert hotkeys._win32_filter(WM_KEYDOWN, SimpleNamespace(vkCode=vk_from_name("f6"))) is True
    with pytest.raises(Suppressed):
        hotkeys._win32_filter(WM_KEYDOWN, SimpleNamespace(vkCode=vk_from_name("f3")))
    assert hotkeys.stops == [True]
    hotkeys._listener = None
