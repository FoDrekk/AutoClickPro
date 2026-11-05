"""Thin ctypes bindings for the Win32 calls the app needs.

Mouse and keyboard input goes through SendInput (or PostMessage for
background clicks), monitors through EnumDisplayMonitors, screen colors
through GetPixel, and precise waits through a high-resolution waitable timer.
Importing this module is safe on other platforms; calling into it there
raises OSError.
"""

from __future__ import annotations

import ctypes
import sys
import threading
from collections.abc import Sequence

IS_WINDOWS = sys.platform == "win32"

# Marks events we inject so they can be told apart from real input.
EXTRA_INFO_TAG = 0x41434B50  # "ACKP"

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
SM_SWAPBUTTON = 23
DOUBLE_CLICK_GAP_MS = 20
MAX_STAMP_LEAD_MS = 250

_BUTTON_FLAGS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}

WM_QUIT = 0x0012
WM_HOTKEY = 0x0312
WM_USER = 0x0400
PM_NOREMOVE = 0x0000
MOD_NOREPEAT = 0x4000
ERROR_HOTKEY_ALREADY_REGISTERED = 1409

WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
LLMHF_INJECTED = 0x00000001
LLKHF_EXTENDED = 0x00000001
LLKHF_INJECTED = 0x00000010

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_RBUTTONDBLCLK = 0x0206
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MBUTTONDBLCLK = 0x0209

# Key-state flags carried in wParam of button messages.
MK_LBUTTON = 0x0001
MK_RBUTTON = 0x0002
MK_MBUTTON = 0x0010

# Window messages for background clicks: (down, up, double-click, MK_* flag).
_BUTTON_MESSAGES = {
    "left": (WM_LBUTTONDOWN, WM_LBUTTONUP, WM_LBUTTONDBLCLK, MK_LBUTTON),
    "right": (WM_RBUTTONDOWN, WM_RBUTTONUP, WM_RBUTTONDBLCLK, MK_RBUTTON),
    "middle": (WM_MBUTTONDOWN, WM_MBUTTONUP, WM_MBUTTONDBLCLK, MK_MBUTTON),
}
# GetAncestor flag: the root (top-level ancestor) window.
_GA_ROOT = 2
_CLR_INVALID = 0xFFFFFFFF

_INFINITE = 0xFFFFFFFF
_WAIT_FAILED = 0xFFFFFFFF
_CREATE_WAITABLE_TIMER_HIGH_RESOLUTION = 0x00000002
_TIMER_ALL_ACCESS = 0x1F0003


def button_flag_sequence(button: str, count: int, swapped: bool = False) -> list[int]:
    """SendInput flags for ``count`` presses of a logical button.

    "left" means the primary button. With swapped buttons (left-handed
    setting) Windows remaps physical events, so the primary button must be
    sent as the physical right one and vice versa.
    """
    if button not in _BUTTON_FLAGS:
        raise ValueError(f"Unknown mouse button: {button!r}")
    if count < 1:
        raise ValueError("Click count must be at least 1.")
    if swapped and button in {"left", "right"}:
        button = "right" if button == "left" else "left"
    down, up = _BUTTON_FLAGS[button]
    return [down, up] * count


def press_timestamps(tick: int, last: int | None, count: int) -> list[int]:
    """Message timestamps (ms) for ``count`` presses sent in one batch.

    Presses of a double-click get distinct times: with identical stamps some
    apps (Qt among them) see two single clicks even though Windows reports a
    double-click. Stamps do not go backwards across calls unless that would
    run more than MAX_STAMP_LEAD_MS ahead of the clock (fast double-clicking).
    GetTickCount wraps every 49.7 days, hence the modular arithmetic.
    """
    base = tick & 0xFFFFFFFF
    if last is not None:
        lead = (last - base) & 0xFFFFFFFF  # How far the last stamp is ahead of now.
        if lead < MAX_STAMP_LEAD_MS:
            base = (last + 1) & 0xFFFFFFFF
    return [(base + i * DOUBLE_CLICK_GAP_MS) & 0xFFFFFFFF for i in range(count)]


if IS_WINDOWS:
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    ULONG_PTR = ctypes.c_size_t

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ("uMsg", wintypes.DWORD),
            ("wParamL", wintypes.WORD),
            ("wParamH", wintypes.WORD),
        ]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]

    _MONITORENUMPROC = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM
    )

    def _bind(dll, name, restype, *argtypes):
        func = getattr(dll, name)
        func.restype = restype
        func.argtypes = list(argtypes)
        return func

    _SendInput = _bind(
        _user32, "SendInput", wintypes.UINT, wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int
    )
    _GetCursorPos = _bind(_user32, "GetCursorPos", wintypes.BOOL, ctypes.POINTER(wintypes.POINT))
    _SetCursorPos = _bind(_user32, "SetCursorPos", wintypes.BOOL, ctypes.c_int, ctypes.c_int)
    _GetSystemMetrics = _bind(_user32, "GetSystemMetrics", ctypes.c_int, ctypes.c_int)
    _EnumDisplayMonitors = _bind(
        _user32,
        "EnumDisplayMonitors",
        wintypes.BOOL,
        wintypes.HDC,
        ctypes.POINTER(wintypes.RECT),
        _MONITORENUMPROC,
        wintypes.LPARAM,
    )
    RegisterHotKey = _bind(
        _user32, "RegisterHotKey", wintypes.BOOL, wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT
    )
    UnregisterHotKey = _bind(_user32, "UnregisterHotKey", wintypes.BOOL, wintypes.HWND, ctypes.c_int)
    GetMessageW = _bind(
        _user32,
        "GetMessageW",
        wintypes.BOOL,
        ctypes.POINTER(wintypes.MSG),
        wintypes.HWND,
        wintypes.UINT,
        wintypes.UINT,
    )
    PeekMessageW = _bind(
        _user32,
        "PeekMessageW",
        wintypes.BOOL,
        ctypes.POINTER(wintypes.MSG),
        wintypes.HWND,
        wintypes.UINT,
        wintypes.UINT,
        wintypes.UINT,
    )
    PostThreadMessageW = _bind(
        _user32,
        "PostThreadMessageW",
        wintypes.BOOL,
        wintypes.DWORD,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    )
    GetCurrentThreadId = _bind(_kernel32, "GetCurrentThreadId", wintypes.DWORD)
    _GetTickCount = _bind(_kernel32, "GetTickCount", wintypes.DWORD)

    _CreateWaitableTimerExW = _bind(
        _kernel32,
        "CreateWaitableTimerExW",
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    )
    _SetWaitableTimer = _bind(
        _kernel32,
        "SetWaitableTimer",
        wintypes.BOOL,
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.LARGE_INTEGER),
        wintypes.LONG,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.BOOL,
    )
    _CreateEventW = _bind(
        _kernel32,
        "CreateEventW",
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.BOOL,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    )
    _SetEvent = _bind(_kernel32, "SetEvent", wintypes.BOOL, wintypes.HANDLE)
    _WaitForMultipleObjects = _bind(
        _kernel32,
        "WaitForMultipleObjects",
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.BOOL,
        wintypes.DWORD,
    )
    _CloseHandle = _bind(_kernel32, "CloseHandle", wintypes.BOOL, wintypes.HANDLE)

    _gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    LRESULT = ctypes.c_ssize_t
    HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

    class MSLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("pt", wintypes.POINT),
            ("mouseData", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("vkCode", wintypes.DWORD),
            ("scanCode", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class MONITORINFOEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
            ("szDevice", wintypes.WCHAR * 32),
        ]

    _MapVirtualKeyW = _bind(_user32, "MapVirtualKeyW", wintypes.UINT, wintypes.UINT, wintypes.UINT)
    _GetDC = _bind(_user32, "GetDC", wintypes.HDC, wintypes.HWND)
    _ReleaseDC = _bind(_user32, "ReleaseDC", ctypes.c_int, wintypes.HWND, wintypes.HDC)
    _GetPixel = _bind(_gdi32, "GetPixel", wintypes.DWORD, wintypes.HDC, ctypes.c_int, ctypes.c_int)
    _WindowFromPoint = _bind(_user32, "WindowFromPoint", wintypes.HWND, wintypes.POINT)
    _GetAncestor = _bind(_user32, "GetAncestor", wintypes.HWND, wintypes.HWND, wintypes.UINT)
    _GetWindowThreadProcessId = _bind(
        _user32, "GetWindowThreadProcessId", wintypes.DWORD, wintypes.HWND, ctypes.POINTER(wintypes.DWORD)
    )
    _GetForegroundWindow = _bind(_user32, "GetForegroundWindow", wintypes.HWND)
    _IsWindow = _bind(_user32, "IsWindow", wintypes.BOOL, wintypes.HWND)
    _GetWindowTextW = _bind(
        _user32, "GetWindowTextW", ctypes.c_int, wintypes.HWND, wintypes.LPWSTR, ctypes.c_int
    )
    _ScreenToClient = _bind(
        _user32, "ScreenToClient", wintypes.BOOL, wintypes.HWND, ctypes.POINTER(wintypes.POINT)
    )
    _PostMessageW = _bind(
        _user32, "PostMessageW", wintypes.BOOL, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
    )
    _GetMonitorInfoW = _bind(
        _user32, "GetMonitorInfoW", wintypes.BOOL, wintypes.HMONITOR, ctypes.POINTER(MONITORINFOEXW)
    )
    SetWindowsHookExW = _bind(
        _user32,
        "SetWindowsHookExW",
        wintypes.HHOOK,
        ctypes.c_int,
        HOOKPROC,
        wintypes.HINSTANCE,
        wintypes.DWORD,
    )
    UnhookWindowsHookEx = _bind(_user32, "UnhookWindowsHookEx", wintypes.BOOL, wintypes.HHOOK)
    CallNextHookEx = _bind(
        _user32, "CallNextHookEx", LRESULT, wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
    )
    GetModuleHandleW = _bind(_kernel32, "GetModuleHandleW", wintypes.HMODULE, wintypes.LPCWSTR)


def _last_error(what: str) -> OSError:
    code = ctypes.get_last_error() if IS_WINDOWS else 0
    return OSError(code, f"{what} failed (Windows error {code})")


def _require_windows() -> None:
    if not IS_WINDOWS:
        raise OSError("AutoClick Pro input control requires Windows.")


def cursor_position() -> tuple[int, int]:
    _require_windows()
    point = wintypes.POINT()
    if not _GetCursorPos(ctypes.byref(point)):
        raise _last_error("GetCursorPos")
    return point.x, point.y


def buttons_swapped() -> bool:
    _require_windows()
    return bool(_GetSystemMetrics(SM_SWAPBUTTON))


def _make_lparam(x: int, y: int) -> int:
    return ((y & 0xFFFF) << 16) | (x & 0xFFFF)


class InputBackend:
    """Mouse, keyboard and screen access the click engine drives."""

    def __init__(self) -> None:
        _require_windows()
        self._last_stamp: int | None = None

    @property
    def position(self) -> tuple[int, int]:
        return cursor_position()

    @position.setter
    def position(self, value: tuple[int, int]) -> None:
        if not _SetCursorPos(int(value[0]), int(value[1])):
            raise _last_error("SetCursorPos")

    def _send(self, events) -> None:
        sent = _SendInput(len(events), events, ctypes.sizeof(INPUT))
        if sent != len(events):
            raise _last_error("SendInput")

    def click(self, button: str, count: int = 1) -> None:
        flags = button_flag_sequence(button, count, buttons_swapped())
        stamps = press_timestamps(_GetTickCount(), self._last_stamp, count)
        self._last_stamp = stamps[-1]
        events = (INPUT * len(flags))()
        for index, (event, flag) in enumerate(zip(events, flags, strict=True)):
            event.type = INPUT_MOUSE
            event.u.mi.time = stamps[index // 2]
            event.u.mi.dwFlags = flag
            event.u.mi.dwExtraInfo = EXTRA_INFO_TAG
        self._send(events)

    def press(self, button: str, down: bool) -> None:
        """Press or release one mouse button (drags, recorded input)."""
        down_flag, up_flag = button_flag_sequence(button, 1, buttons_swapped())
        events = (INPUT * 1)()
        events[0].type = INPUT_MOUSE
        events[0].u.mi.dwFlags = down_flag if down else up_flag
        events[0].u.mi.dwExtraInfo = EXTRA_INFO_TAG
        self._send(events)

    def key(self, vk: int, down: bool, extended: bool = False) -> None:
        events = (INPUT * 1)()
        events[0].type = INPUT_KEYBOARD
        ki = events[0].u.ki
        ki.wVk = vk
        ki.wScan = _MapVirtualKeyW(vk, 0)  # MAPVK_VK_TO_VSC; games often read scan codes.
        ki.dwFlags = (0 if down else KEYEVENTF_KEYUP) | (KEYEVENTF_EXTENDEDKEY if extended else 0)
        ki.dwExtraInfo = EXTRA_INFO_TAG
        self._send(events)

    def pixel(self, x: int, y: int) -> tuple[int, int, int]:
        return pixel_color(x, y)

    def post_click(self, hwnd: int, x: int, y: int, button: str, count: int = 1) -> None:
        """Click a window through its message queue without moving the cursor.

        ``x``/``y`` are screen coordinates. Apps that read raw input or the
        cursor position (most games) ignore these messages.
        """
        if not _IsWindow(hwnd):
            raise OSError("The target window was closed. Pick the window again.")
        point = wintypes.POINT(int(x), int(y))
        _ScreenToClient(hwnd, ctypes.byref(point))
        lparam = _make_lparam(point.x, point.y)
        down, up, double, mk = _BUTTON_MESSAGES[button]
        messages = [(WM_MOUSEMOVE, 0), (down, mk), (up, 0)]
        if count >= 2:
            messages += [(double, mk), (up, 0)]
        for message, wparam in messages:
            if not _PostMessageW(hwnd, message, wparam, lparam):
                raise _last_error("PostMessage")


def pixel_color(x: int, y: int) -> tuple[int, int, int]:
    _require_windows()
    hdc = _GetDC(None)
    if not hdc:
        raise _last_error("GetDC")
    try:
        value = _GetPixel(hdc, int(x), int(y))
    finally:
        _ReleaseDC(None, hdc)
    if value == _CLR_INVALID:
        raise OSError(f"Cannot read the screen color at {x}, {y}.")
    return value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF


def window_at(x: int, y: int) -> int:
    """Deepest visible window under a screen point (0 when none)."""
    _require_windows()
    return int(_WindowFromPoint(wintypes.POINT(int(x), int(y))) or 0)


def root_window(hwnd: int) -> int:
    _require_windows()
    return int(_GetAncestor(hwnd, _GA_ROOT) or 0) if hwnd else 0


def window_pid(hwnd: int) -> int:
    _require_windows()
    pid = wintypes.DWORD()
    _GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def window_title(hwnd: int) -> str:
    _require_windows()
    buffer = ctypes.create_unicode_buffer(256)
    _GetWindowTextW(hwnd, buffer, len(buffer))
    return buffer.value


def is_window(hwnd: int) -> bool:
    return IS_WINDOWS and bool(hwnd) and bool(_IsWindow(hwnd))


def foreground_window() -> int:
    _require_windows()
    return int(_GetForegroundWindow() or 0)


def monitor_rects() -> list[tuple[int, int, int, int]]:
    """(left, top, right, bottom) of every monitor in virtual-desktop pixels."""
    _require_windows()
    rects: list[tuple[int, int, int, int]] = []

    def _collect(_monitor, _hdc, rect_ptr, _data):
        r = rect_ptr.contents
        rects.append((r.left, r.top, r.right, r.bottom))
        return True

    if not _EnumDisplayMonitors(None, None, _MONITORENUMPROC(_collect), 0):
        raise _last_error("EnumDisplayMonitors")
    return rects


def monitors() -> list[tuple[tuple[int, int, int, int], str]]:
    """(rect, device name) of every monitor; the name matches QScreen.name()."""
    _require_windows()
    found: list[tuple[tuple[int, int, int, int], str]] = []

    def _collect(monitor, _hdc, _rect, _data):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if _GetMonitorInfoW(monitor, ctypes.byref(info)):
            r = info.rcMonitor
            found.append(((r.left, r.top, r.right, r.bottom), info.szDevice))
        return True

    if not _EnumDisplayMonitors(None, None, _MONITORENUMPROC(_collect), 0):
        raise _last_error("EnumDisplayMonitors")
    return found


def _on_any_monitor(x: int, y: int, rects: Sequence[tuple[int, int, int, int]]) -> bool:
    return any(left <= x < right and top <= y < bottom for left, top, right, bottom in rects)


def desktop_corners(rects: Sequence[tuple[int, int, int, int]]) -> list[tuple[int, int]]:
    """Top-left monitor corners the cursor stops at when pushed up and left.

    A monitor's top-left corner qualifies when no monitor continues to its
    left or above it, so slamming the mouse up-left really lands there.
    """
    corners = [
        (left, top)
        for left, top, _right, _bottom in rects
        if not _on_any_monitor(left - 1, top, rects) and not _on_any_monitor(left, top - 1, rects)
    ]
    return sorted(set(corners)) or [(0, 0)]


class HighResWaiter:
    """Sleep with sub-millisecond precision, interruptible by ``wake()``."""

    def __init__(self) -> None:
        _require_windows()
        timer = _CreateWaitableTimerExW(None, None, _CREATE_WAITABLE_TIMER_HIGH_RESOLUTION, _TIMER_ALL_ACCESS)
        if not timer:  # Windows 10 before 1803 lacks high-resolution timers.
            timer = _CreateWaitableTimerExW(None, None, 0, _TIMER_ALL_ACCESS)
        event = _CreateEventW(None, False, False, None)
        if not timer or not event:
            raise _last_error("Creating timer")
        self._timer = timer
        self._event = event
        self._handles = (wintypes.HANDLE * 2)(event, timer)

    def wait(self, timeout: float | None) -> None:
        """Return after ``timeout`` seconds, or sooner when woken."""
        count = 1
        if timeout is not None:
            if timeout <= 0:
                return
            due = wintypes.LARGE_INTEGER(-max(1, int(timeout * 10_000_000)))  # Relative, 100 ns units.
            if not _SetWaitableTimer(self._timer, ctypes.byref(due), 0, None, None, False):
                raise _last_error("SetWaitableTimer")
            count = 2
        if _WaitForMultipleObjects(count, self._handles, False, _INFINITE) == _WAIT_FAILED:
            raise _last_error("WaitForMultipleObjects")

    def wake(self) -> None:
        _SetEvent(self._event)

    def close(self) -> None:
        for name in ("_timer", "_event"):
            handle = getattr(self, name, None)
            if handle:
                _CloseHandle(handle)
                setattr(self, name, None)

    def __del__(self) -> None:
        self.close()


class EventWaiter:
    """Portable fallback with the HighResWaiter interface."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def wait(self, timeout: float | None) -> None:
        if timeout is not None and timeout <= 0:
            return
        self._event.wait(timeout)
        self._event.clear()

    def wake(self) -> None:
        self._event.set()

    def close(self) -> None:
        pass


def create_waiter() -> HighResWaiter | EventWaiter:
    return HighResWaiter() if IS_WINDOWS else EventWaiter()
