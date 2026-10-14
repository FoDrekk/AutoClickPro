"""Global start/pause and emergency-stop hotkeys bridged into Qt signals."""

from __future__ import annotations

import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal
from pynput import keyboard

KEY_NAMES = [f"f{i}" for i in range(1, 13)]


def key_from_name(name: str) -> keyboard.Key:
    key = getattr(keyboard.Key, name, None)
    if key is None:
        raise ValueError(f"Unsupported hotkey: {name!r}. Use F1–F12.")
    return key


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
        self._pressed: set[keyboard.Key] = set()
        self._lock = threading.Lock()
        self._emergency_stop_callback = emergency_stop_callback
        self._toggle_key = keyboard.Key.f6
        self._stop_key = keyboard.Key.f12

    def set_keys(self, toggle: str, stop: str) -> None:
        toggle_key = key_from_name(toggle)
        stop_key = key_from_name(stop)
        if toggle_key == stop_key:
            raise ValueError("Start/pause and emergency stop need different keys.")
        with self._lock:
            self._toggle_key = toggle_key
            self._stop_key = stop_key
            self._pressed.clear()

    def start(self) -> None:
        if self._listener is not None and self._listener.is_alive():
            return
        with self._lock:
            self._pressed.clear()
        try:
            listener = keyboard.Listener(
                on_press=self._on_press,
                on_release=self._on_release,
            )
            listener.start()
            self._listener = listener
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

    def _on_press(self, key) -> None:
        with self._lock:
            toggle_key = self._toggle_key
            stop_key = self._stop_key
        if key not in (toggle_key, stop_key):
            return
        with self._lock:
            if key in self._pressed:
                return
            self._pressed.add(key)

        if key == toggle_key:
            self.toggle_requested.emit()
        elif key == stop_key:
            if self._emergency_stop_callback is not None:
                try:
                    self._emergency_stop_callback()
                except Exception as exc:
                    self.error_occurred.emit(f"Emergency stop failed: {exc}")
            self.emergency_stop_requested.emit()

    def _on_release(self, key) -> None:
        with self._lock:
            self._pressed.discard(key)
