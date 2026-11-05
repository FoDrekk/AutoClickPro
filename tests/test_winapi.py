import ctypes
import statistics
import sys
import threading
import time

import pytest

from autoclick_pro import winapi
from autoclick_pro.winapi import button_flag_sequence, desktop_corners, press_timestamps

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Win32 only")

LEFT = (winapi.MOUSEEVENTF_LEFTDOWN, winapi.MOUSEEVENTF_LEFTUP)
RIGHT = (winapi.MOUSEEVENTF_RIGHTDOWN, winapi.MOUSEEVENTF_RIGHTUP)
MIDDLE = (winapi.MOUSEEVENTF_MIDDLEDOWN, winapi.MOUSEEVENTF_MIDDLEUP)


def test_button_flags():
    assert button_flag_sequence("left", 1) == [*LEFT]
    assert button_flag_sequence("right", 2) == [*RIGHT, *RIGHT]
    assert button_flag_sequence("middle", 1) == [*MIDDLE]


def test_button_flags_follow_swapped_buttons():
    # "Left" means the primary button, which is the physical right one for
    # left-handed users.
    assert button_flag_sequence("left", 1, swapped=True) == [*RIGHT]
    assert button_flag_sequence("right", 1, swapped=True) == [*LEFT]
    assert button_flag_sequence("middle", 1, swapped=True) == [*MIDDLE]


def test_button_flags_reject_bad_input():
    with pytest.raises(ValueError):
        button_flag_sequence("thumb", 1)
    with pytest.raises(ValueError):
        button_flag_sequence("left", 0)


def test_press_timestamps():
    assert press_timestamps(1000, None, 1) == [1000]
    assert press_timestamps(1000, None, 2) == [1000, 1020]
    # A fast follow-up click never gets an older stamp than the last press.
    assert press_timestamps(1005, 1020, 1) == [1021]
    assert press_timestamps(1020, 1020, 2) == [1021, 1041]
    assert press_timestamps(5000, 1020, 1) == [5000]
    # GetTickCount wraps around after 49.7 days.
    assert press_timestamps(5, 0xFFFFFFF0, 1) == [5]
    assert press_timestamps(0xFFFFFFFF, None, 2) == [0xFFFFFFFF, 19]
    assert press_timestamps(3, 0xFFFFFFFE, 1) == [3]
    # Rapid double-clicks cannot drag the stamps arbitrarily far ahead.
    assert press_timestamps(1000, 1249, 1) == [1250]
    assert press_timestamps(1000, 1250, 1) == [1000]


@pytest.mark.parametrize(
    ("rects", "expected"),
    [
        # Single monitor.
        ([(0, 0, 1920, 1080)], [(0, 0)]),
        # Second monitor to the right: the primary keeps the corner.
        ([(0, 0, 1920, 1080), (1920, 0, 3840, 1080)], [(0, 0)]),
        # Monitor to the left, tops aligned: the corner moves left.
        ([(0, 0, 1920, 1080), (-1920, 0, 0, 1080)], [(-1920, 0)]),
        # Monitor above and shifted left: its corner only.
        ([(0, 0, 1920, 1080), (-1000, -1080, 920, 0)], [(-1000, -1080)]),
        # Monitors touching only diagonally: both corners are dead ends.
        ([(0, 0, 1920, 1080), (-1920, -1080, 0, 0)], [(-1920, -1080), (0, 0)]),
        # Monitor directly above.
        ([(0, 0, 1920, 1080), (0, -1080, 1920, 0)], [(0, -1080)]),
        # Left monitor lower than the primary: both corners are dead ends.
        ([(0, 0, 1920, 1080), (-1280, 300, 0, 1324)], [(-1280, 300), (0, 0)]),
        # Left monitor higher than the primary: the primary corner is reachable
        # only by sliding past the neighbour, so it does not count.
        ([(0, 0, 1920, 1080), (-1280, -300, 0, 724)], [(-1280, -300)]),
        ([], [(0, 0)]),
    ],
)
def test_desktop_corners(rects, expected):
    assert desktop_corners(rects) == expected


def test_event_waiter_wakes_early():
    waiter = winapi.EventWaiter()
    threading.Timer(0.05, waiter.wake).start()
    started = time.monotonic()
    waiter.wait(5)
    assert time.monotonic() - started < 1


@windows_only
def test_input_struct_matches_win32_layout():
    assert ctypes.sizeof(winapi.INPUT) == (40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)


@windows_only
def test_monitors_and_cursor():
    rects = winapi.monitor_rects()
    assert rects and all(r[2] > r[0] and r[3] > r[1] for r in rects)
    x, y = winapi.cursor_position()
    assert isinstance(x, int) and isinstance(y, int)


@windows_only
def test_high_res_waiter_precision():
    waiter = winapi.HighResWaiter()
    durations = []
    for _ in range(100):
        started = time.perf_counter()
        waiter.wait(0.002)
        durations.append((time.perf_counter() - started) * 1000)
    waiter.close()
    # Kernel waits overshoot by well under a millisecond; a 15.6 ms system
    # tick would make the median about 15 ms.
    median = statistics.median(durations)
    assert 2.0 <= median <= 3.5, f"median 2 ms wait took {median:.2f} ms"


@windows_only
def test_high_res_waiter_wake_interrupts():
    waiter = winapi.HighResWaiter()
    threading.Timer(0.05, waiter.wake).start()
    started = time.monotonic()
    waiter.wait(5)
    assert time.monotonic() - started < 1
    threading.Timer(0.05, waiter.wake).start()
    started = time.monotonic()
    waiter.wait(None)
    assert time.monotonic() - started < 1
    waiter.close()


@windows_only
def test_high_res_waiter_ignores_stale_timer():
    waiter = winapi.HighResWaiter()
    waiter.wake()
    waiter.wait(0.001)  # Returns on the pending wake; the timer stays armed.
    time.sleep(0.01)  # Let the stale timer fire.
    started = time.monotonic()
    waiter.wait(0.05)  # Re-arming must clear the stale signal.
    assert time.monotonic() - started >= 0.04
    waiter.close()
