"""Record real mouse and keyboard input into sequence steps.

Low-level hooks are installed only while recording and removed right after.
They never block input: every event is passed on unchanged. Injected events
(our own playback, other automation tools) and input aimed at AutoClick Pro's
own windows are ignored.
"""

from __future__ import annotations

import ctypes
import logging
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass

from autoclick_pro import winapi
from autoclick_pro.global_hotkeys import MODIFIER_VKS
from autoclick_pro.steps import MAX_DELAY_MS, MAX_STEPS, Step

_logger = logging.getLogger("autoclick_pro")

MAX_EVENTS = MAX_STEPS
MOVE_SAMPLE_SECONDS = 0.015
CLICK_MAX_MS = 300
CLICK_SLOP_PX = 3
TAIL_DELAY_MS = 100

_MOUSE_MESSAGES = {
    winapi.WM_LBUTTONDOWN: ("down", "left"),
    winapi.WM_LBUTTONUP: ("up", "left"),
    winapi.WM_RBUTTONDOWN: ("down", "right"),
    winapi.WM_RBUTTONUP: ("up", "right"),
    winapi.WM_MBUTTONDOWN: ("down", "middle"),
    winapi.WM_MBUTTONUP: ("up", "middle"),
}


@dataclass(frozen=True)
class RawEvent:
    t: float  # Seconds, perf_counter clock.
    kind: str  # move | down | up | key_down | key_up
    x: int = 0
    y: int = 0
    button: str = "left"
    vk: int = 0
    extended: bool = False


def _strip_trailing_keys(events: list[RawEvent], vks: set[int]) -> list[RawEvent]:
    """Drop the hotkey (and its modifiers) that ended the recording."""
    end = len(events)
    while end and events[end - 1].kind in {"key_down", "key_up"} and events[end - 1].vk in vks:
        end -= 1
    return events[:end]


def _close_held(events: list[RawEvent]) -> list[RawEvent]:
    """Release keys and buttons still held when recording stopped."""
    keys: dict[tuple[int, bool], None] = {}
    buttons: dict[str, tuple[int, int]] = {}
    for e in events:
        if e.kind == "key_down":
            keys[(e.vk, e.extended)] = None
        elif e.kind == "key_up":
            keys.pop((e.vk, e.extended), None)
        elif e.kind == "down":
            buttons[e.button] = (e.x, e.y)
        elif e.kind == "up":
            buttons.pop(e.button, None)
    if not keys and not buttons:
        return events
    t = events[-1].t if events else 0.0
    closing = [RawEvent(t, "key_up", vk=vk, extended=ext) for vk, ext in keys]
    closing += [RawEvent(t, "up", x, y, button=b) for b, (x, y) in buttons.items()]
    return events + closing


def _merge_clicks(events: list[RawEvent]) -> list[RawEvent | Step]:
    """Turn quick press/release pairs at one spot into click steps."""
    out: list[RawEvent | Step] = []
    i = 0
    while i < len(events):
        e = events[i]
        if e.kind == "down":
            j = i + 1
            while (
                j < len(events)
                and events[j].kind == "move"
                and (abs(events[j].x - e.x) <= CLICK_SLOP_PX and abs(events[j].y - e.y) <= CLICK_SLOP_PX)
            ):
                j += 1
            if j < len(events):
                up = events[j]
                if (
                    up.kind == "up"
                    and up.button == e.button
                    and (up.t - e.t) * 1000 <= CLICK_MAX_MS
                    and abs(up.x - e.x) <= CLICK_SLOP_PX
                    and abs(up.y - e.y) <= CLICK_SLOP_PX
                ):
                    out.append(RawEvent(e.t, "click", e.x, e.y, button=e.button))
                    i = j + 1
                    continue
        out.append(e)
        i += 1
    return out


def events_to_steps(events: Iterable[RawEvent], trailing_vks: Iterable[int] = ()) -> list[Step]:
    """Convert recorded events into steps whose delays reproduce the timing.

    ``trailing_vks`` are the keys of the hotkey that stopped the recording;
    they and any modifiers are removed from the end.
    """
    ordered = sorted(events, key=lambda e: e.t)
    strip = set(trailing_vks)
    if strip:
        ordered = _strip_trailing_keys(ordered, strip | set(MODIFIER_VKS))
    merged = _merge_clicks(_close_held(ordered))
    steps: list[Step] = []
    for index, e in enumerate(merged):
        assert isinstance(e, RawEvent)
        if index + 1 < len(merged):
            following = merged[index + 1]
            assert isinstance(following, RawEvent)
            delay = round((following.t - e.t) * 1000)
        else:
            delay = TAIL_DELAY_MS
        delay = max(0, min(MAX_DELAY_MS, delay))
        if e.kind in {"click", "down", "up", "move"}:
            steps.append(Step(e.kind, e.x, e.y, button=e.button if e.kind != "move" else "left", delay=delay))
        else:
            steps.append(Step(e.kind, vk=e.vk, extended=e.extended, delay=delay))
    return steps[:MAX_STEPS]


class InputRecorder:
    """Low-level mouse/keyboard hooks on a dedicated message-loop thread."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._error: str | None = None
        self._events: list[RawEvent] = []
        self._record_moves = False
        self._own_pid = 0
        self._last_move = 0.0
        self._ignored_buttons: set[str] = set()
        self._keys_down: set[int] = set()
        self._procs: list = []

    @property
    def event_count(self) -> int:
        return len(self._events)

    @property
    def full(self) -> bool:
        return len(self._events) >= MAX_EVENTS

    def is_recording(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, *, record_moves: bool, own_pid: int) -> None:
        """Install the hooks. Raises OSError when Windows refuses them."""
        if self.is_recording():
            return
        if not winapi.IS_WINDOWS:
            raise OSError("Recording requires Windows.")
        self._events = []
        self._record_moves = record_moves
        self._own_pid = own_pid
        self._ignored_buttons.clear()
        self._keys_down.clear()
        self._error = None
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, name="InputRecorder", daemon=True)
        self._thread.start()
        self._ready.wait(2.0)
        if self._error:
            self._thread.join(2.0)
            self._thread = None
            raise OSError(self._error)

    def stop(self) -> list[RawEvent]:
        thread = self._thread
        self._thread = None
        if thread is not None:
            if self._thread_id:
                winapi.PostThreadMessageW(self._thread_id, winapi.WM_QUIT, 0, 0)
            thread.join(2.0)
        return list(self._events)

    def _append(self, event: RawEvent) -> None:
        if len(self._events) < MAX_EVENTS:
            self._events.append(event)

    def _on_mouse(self, message: int, x: int, y: int) -> None:
        now = time.perf_counter()
        if message == winapi.WM_MOUSEMOVE:
            if self._record_moves and now - self._last_move >= MOVE_SAMPLE_SECONDS:
                self._last_move = now
                self._append(RawEvent(now, "move", x, y))
            return
        mapped = _MOUSE_MESSAGES.get(message)
        if mapped is None:
            return
        kind, button = mapped
        if kind == "down":
            target = winapi.root_window(winapi.window_at(x, y))
            if target and winapi.window_pid(target) == self._own_pid:
                self._ignored_buttons.add(button)  # Clicks on our own window.
                return
        elif button in self._ignored_buttons:
            self._ignored_buttons.discard(button)
            return
        self._append(RawEvent(now, kind, x, y, button=button))

    def _on_key(self, message: int, vk: int, flags: int) -> None:
        foreground = winapi.foreground_window()
        if foreground and winapi.window_pid(foreground) == self._own_pid:
            return  # Typing into AutoClick Pro itself.
        extended = bool(flags & winapi.LLKHF_EXTENDED)
        if message in (winapi.WM_KEYDOWN, winapi.WM_SYSKEYDOWN):
            if vk in self._keys_down:
                return  # Keyboard auto-repeat.
            self._keys_down.add(vk)
            self._append(RawEvent(time.perf_counter(), "key_down", vk=vk, extended=extended))
        elif message in (winapi.WM_KEYUP, winapi.WM_SYSKEYUP):
            self._keys_down.discard(vk)
            self._append(RawEvent(time.perf_counter(), "key_up", vk=vk, extended=extended))

    def _run(self) -> None:
        from ctypes import wintypes

        def mouse_proc(code, wparam, lparam):
            if code >= 0:
                try:
                    data = ctypes.cast(lparam, ctypes.POINTER(winapi.MSLLHOOKSTRUCT)).contents
                    if not data.flags & winapi.LLMHF_INJECTED:
                        self._on_mouse(int(wparam), data.pt.x, data.pt.y)
                except Exception:
                    _logger.exception("Mouse hook failed")
            return winapi.CallNextHookEx(None, code, wparam, lparam)

        def key_proc(code, wparam, lparam):
            if code >= 0:
                try:
                    data = ctypes.cast(lparam, ctypes.POINTER(winapi.KBDLLHOOKSTRUCT)).contents
                    if not data.flags & winapi.LLKHF_INJECTED:
                        self._on_key(int(wparam), int(data.vkCode), int(data.flags))
                except Exception:
                    _logger.exception("Keyboard hook failed")
            return winapi.CallNextHookEx(None, code, wparam, lparam)

        # Keep the ctypes callbacks alive for as long as the hooks exist.
        self._procs = [winapi.HOOKPROC(mouse_proc), winapi.HOOKPROC(key_proc)]
        msg = wintypes.MSG()
        winapi.PeekMessageW(ctypes.byref(msg), None, winapi.WM_USER, winapi.WM_USER, winapi.PM_NOREMOVE)
        self._thread_id = winapi.GetCurrentThreadId()
        module = winapi.GetModuleHandleW(None)
        hooks = [
            winapi.SetWindowsHookExW(winapi.WH_MOUSE_LL, self._procs[0], module, 0),
            winapi.SetWindowsHookExW(winapi.WH_KEYBOARD_LL, self._procs[1], module, 0),
        ]
        if not all(hooks):
            self._error = f"Windows refused the input hooks (error {ctypes.get_last_error()})."
        self._ready.set()
        try:
            if not self._error:
                while winapi.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                    pass
        finally:
            for hook in hooks:
                if hook:
                    winapi.UnhookWindowsHookEx(hook)
            self._thread_id = 0
            self._procs = []
