"""Global start/pause and emergency-stop hotkeys bridged into Qt signals."""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable
from typing import Any

from pynput import keyboard
from PySide6.QtCore import QObject, Signal

KEY_NAMES = [f"f{i}" for i in range(1, 13)]

_VK_F1 = 0x70
_KEY_DOWN_MESSAGES = {0x0100, 0x0104}  # WM_KEYDOWN, WM_SYSKEYDOWN
_KEY_UP_MESSAGES = {0x0101, 0x0105}  # WM_KEYUP, WM_SYSKEYUP


def key_from_name(name: str) -> keyboard.Key:
    key = getattr(keyboard.Key, name, None) if name in KEY_NAMES else None
    if key is None:
        raise ValueError(f"Unsupported hotkey: {name!r}. Use F1–F12.")
    return key


def vk_from_name(name: str) -> int:
    key_from_name(name)
    return _VK_F1 + KEY_NAMES.index(name)


class GlobalHotkeys(QObject):
    toggle_requested = Signal()
    emergency_stop_requested = Signal()
    error_occurred = Signal(str)

    def __init__(
        self,
        emergency_stop_callback: Callable[[], None] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._listener: keyboard.Listener | None = None
        self._pressed: set[str] = set()
        self._lock = threading.Lock()
        self._emergency_stop_callback = emergency_stop_callback
        self._toggle = "f6"
        self._stop = "f12"

    def set_keys(self, toggle: str, stop: str) -> None:
        key_from_name(toggle)
        key_from_name(stop)
        if toggle == stop:
            raise ValueError("Start/pause and emergency stop need different keys.")
        with self._lock:
            self._toggle = toggle
            self._stop = stop
            self._pressed.clear()

    def start(self) -> None:
        if self._listener is not None and self._listener.is_alive():
            return
        with self._lock:
            self._pressed.clear()
        options: dict[str, Any] = {}
        if sys.platform == "win32":
            options["win32_event_filter"] = self._win32_filter
        try:
            listener = keyboard.Listener(
                on_press=self._on_press,
                on_release=self._on_release,
                **options,
            )
            # Set before start() so the filter can reach it on the first event.
            self._listener = listener
            listener.start()
        except Exception as exc:
            self._listener = None
            self.error_occurred.emit(f"Could not start global hotkeys: {exc}")

    def stop(self) -> None:
        listener = self._listener
        self._listener = None
        if listener is None:
            return
        listener.stop()
        if listener.ident != threading.get_ident():
            listener.join()
        with self._lock:
            self._pressed.clear()

    def _hotkey_name(self, name: str | None) -> str | None:
        with self._lock:
            return name if name in (self._toggle, self._stop) else None

    def _win32_filter(self, msg: int, data: Any) -> bool:
        """Handle hotkeys inside the hook and swallow them system-wide.

        Runs on the hook thread, so it must stay fast: Windows silently drops
        low-level hooks that stall. Without suppression F6 would also reach
        the focused app (a browser jumps to its address bar).
        """
        vk = int(data.vkCode)
        index = vk - _VK_F1
        name = self._hotkey_name(KEY_NAMES[index] if 0 <= index < len(KEY_NAMES) else None)
        if name is None:
            return True
        if msg in _KEY_DOWN_MESSAGES:
            self._key_down(name)
        elif msg in _KEY_UP_MESSAGES:
            self._key_up(name)
        listener = self._listener
        if listener is not None:
            listener.suppress_event()  # Raises; the event never reaches other apps.
        return False

    def _on_press(self, key) -> None:
        name = self._hotkey_name(getattr(key, "name", None))
        if name is not None:
            self._key_down(name)

    def _on_release(self, key) -> None:
        name = getattr(key, "name", None)
        if name is not None:
            self._key_up(name)

    def _key_down(self, name: str) -> None:
        with self._lock:
            if name in self._pressed:  # Ignore keyboard auto-repeat.
                return
            self._pressed.add(name)
            is_toggle = name == self._toggle
            is_stop = name == self._stop

        if is_toggle:
            self.toggle_requested.emit()
        elif is_stop:
            if self._emergency_stop_callback is not None:
                try:
                    self._emergency_stop_callback()
                except Exception as exc:
                    self.error_occurred.emit(f"Emergency stop failed: {exc}")
            self.emergency_stop_requested.emit()

    def _key_up(self, name: str) -> None:
        with self._lock:
            self._pressed.discard(name)
