import ctypes
import sys
import time

import pytest

import autoclick_pro.recorder as rec
from autoclick_pro import winapi
from autoclick_pro.recorder import InputRecorder, RawEvent, events_to_steps
from autoclick_pro.steps import Step

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Low-level hooks are Windows-only")


def test_quick_press_release_becomes_click():
    events = [
        RawEvent(0.000, "down", 10, 20),
        RawEvent(0.080, "move", 11, 21),  # Hand jitter inside the slop.
        RawEvent(0.090, "up", 11, 21),
        RawEvent(0.500, "key_down", vk=0x41),
        RawEvent(0.560, "key_up", vk=0x41),
    ]
    steps = events_to_steps(events)
    assert steps == [
        Step("click", 10, 20, delay=500),
        Step("key_down", vk=0x41, delay=60),
        Step("key_up", vk=0x41, delay=100),
    ]


def test_drag_and_long_press_stay_down_up():
    events = [
        RawEvent(0.0, "down", 0, 0),
        RawEvent(0.1, "up", 200, 0),  # Dragged.
        RawEvent(1.0, "down", 5, 5, button="right"),
        RawEvent(2.0, "up", 5, 5, button="right"),  # Held a second.
    ]
    kinds = [(s.type, s.button) for s in events_to_steps(events)]
    assert kinds == [("down", "left"), ("up", "left"), ("down", "right"), ("up", "right")]


def test_stop_hotkey_is_stripped_only_when_given():
    events = [
        RawEvent(0.0, "down", 1, 1),
        RawEvent(0.05, "up", 1, 1),
        RawEvent(1.0, "key_down", vk=0x11),  # Ctrl of Ctrl+F6.
        RawEvent(1.1, "key_down", vk=0x75),
    ]
    assert [s.type for s in events_to_steps(events, trailing_vks={0x75})] == ["click"]
    # Stopped with the button: the keys were real input and are kept (and released).
    kept = events_to_steps(events)
    assert [s.type for s in kept] == ["click", "key_down", "key_down", "key_up", "key_up"]


def test_held_inputs_are_released_at_the_end():
    events = [RawEvent(0.0, "key_down", vk=0x10), RawEvent(0.2, "down", 3, 4, button="middle")]
    steps = events_to_steps(events)
    assert steps[-2:] == [Step("key_up", vk=0x10, delay=0), Step("up", 3, 4, button="middle", delay=100)]


def test_delays_follow_timing_and_are_clamped():
    events = [RawEvent(0.0, "move", 1, 1), RawEvent(5000.0, "move", 2, 2)]
    steps = events_to_steps(events)
    assert steps[0].delay == 3_600_000


@pytest.fixture
def recorder(monkeypatch):
    r = InputRecorder()
    r._own_pid = 42
    windows = {}  # point -> pid
    monkeypatch.setattr(rec.winapi, "window_at", lambda x, y: (x, y))
    monkeypatch.setattr(rec.winapi, "root_window", lambda h: h)
    monkeypatch.setattr(rec.winapi, "window_pid", lambda h: windows.get(h, 7))
    monkeypatch.setattr(rec.winapi, "foreground_window", lambda: "fg")
    r.windows = windows
    return r


def test_own_window_clicks_are_ignored(recorder):
    recorder.windows[(5, 5)] = 42
    recorder._on_mouse(winapi.WM_LBUTTONDOWN, 5, 5)
    recorder._on_mouse(winapi.WM_LBUTTONUP, 5, 5)
    recorder._on_mouse(winapi.WM_LBUTTONDOWN, 9, 9)
    recorder._on_mouse(winapi.WM_LBUTTONUP, 9, 9)
    assert [(e.kind, e.x) for e in recorder._events] == [("down", 9), ("up", 9)]


def test_typing_into_own_window_is_ignored(recorder):
    recorder.windows["fg"] = 42
    recorder._on_key(winapi.WM_KEYDOWN, 0x41, 0)
    assert recorder._events == []


def test_key_autorepeat_recorded_once(recorder):
    for _ in range(5):
        recorder._on_key(winapi.WM_KEYDOWN, 0x41, 0)
    recorder._on_key(winapi.WM_KEYUP, 0x41, 0)
    recorder._on_key(winapi.WM_SYSKEYDOWN, 0x25, winapi.LLKHF_EXTENDED)
    assert [(e.kind, e.vk, e.extended) for e in recorder._events] == [
        ("key_down", 0x41, False),
        ("key_up", 0x41, False),
        ("key_down", 0x25, True),
    ]


def test_moves_only_when_enabled_and_sampled(recorder):
    recorder._on_mouse(winapi.WM_MOUSEMOVE, 1, 1)
    assert recorder._events == []
    recorder._record_moves = True
    for i in range(10):
        recorder._on_mouse(winapi.WM_MOUSEMOVE, i, i)
    assert len(recorder._events) == 1  # 10 moves within one 15 ms sample window.


@windows_only
def test_hooks_install_and_ignore_injected_input():
    r = InputRecorder()
    r.start(record_moves=True, own_pid=0)
    assert r.is_recording()
    # Injected input (like our own playback) must not be recorded.
    events = (winapi.INPUT * 2)()
    for i, flags in enumerate((0, winapi.KEYEVENTF_KEYUP)):
        events[i].type = winapi.INPUT_KEYBOARD
        events[i].u.ki.wVk = 0x87  # F24, which nothing uses.
        events[i].u.ki.dwFlags = flags
    assert winapi._SendInput(2, events, ctypes.sizeof(winapi.INPUT)) == 2
    time.sleep(0.2)
    recorded = r.stop()
    assert not r.is_recording()
    assert all(e.vk != 0x87 for e in recorded)
