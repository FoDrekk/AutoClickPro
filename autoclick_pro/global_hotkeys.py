"""Global start/pause and emergency-stop hotkeys bridged into Qt signals.

Hotkeys are registered with RegisterHotKey on a dedicated thread that runs
its own message loop. Windows delivers them as WM_HOTKEY and never passes
the key on to the focused app. Unlike a low-level keyboard hook, there is no
callback timeout that can silently unhook the app, and the emergency stop
does not depend on the GUI thread being responsive.
"""

from __future__ import annotations

import ctypes
import threading
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from autoclick_pro import winapi

MODIFIER_FLAGS = {"ctrl": 0x0002, "alt": 0x0001, "shift": 0x0004, "win": 0x0008}
MODIFIER_ORDER = ("ctrl", "alt", "shift", "win")
_MODIFIER_ALIASES = {"control": "ctrl", "ctl": "ctrl", "meta": "win", "super": "win", "windows": "win"}

# Keys allowed without a modifier: they do not type text.
_BARE_KEYS: dict[str, int] = {f"f{i}": 0x6F + i for i in range(1, 25)}
_BARE_KEYS.update(
    {
        "pause": 0x13,
        "scrolllock": 0x91,
        "insert": 0x2D,
        "home": 0x24,
        "end": 0x23,
        "pageup": 0x21,
        "pagedown": 0x22,
    }
)
_TYPING_KEYS: dict[str, int] = {chr(c).lower(): c for c in range(ord("A"), ord("Z") + 1)}
_TYPING_KEYS.update({str(d): ord(str(d)) for d in range(10)})
_TYPING_KEYS["space"] = 0x20

KEY_CODES = {**_BARE_KEYS, **_TYPING_KEYS}
KEY_NAMES = list(KEY_CODES)
_KEY_LABELS = {"scrolllock": "ScrollLock", "pageup": "PageUp", "pagedown": "PageDown"}

# Windows reserves bare F12 for debuggers; RegisterHotKey refuses it.
RESERVED = {"f12"}

DEFAULT_TOGGLE = "f6"
DEFAULT_STOP = "f8"

_TOGGLE_ID = 1
_STOP_ID = 2
_WM_REREGISTER = winapi.WM_USER + 1


_VK_NAMES = {
    0x08: "Backspace",
    0x09: "Tab",
    0x0D: "Enter",
    0x10: "Shift",
    0x11: "Ctrl",
    0x12: "Alt",
    0x14: "CapsLock",
    0x1B: "Esc",
    0x25: "Left",
    0x26: "Up",
    0x27: "Right",
    0x28: "Down",
    0x2C: "PrintScreen",
    0x2E: "Delete",
    0x5B: "Win",
    0x5C: "Win",
    0x6A: "Num *",
    0x6B: "Num +",
    0x6D: "Num -",
    0x6E: "Num .",
    0x6F: "Num /",
    0x90: "NumLock",
    0xA0: "Shift",
    0xA1: "Right Shift",
    0xA2: "Ctrl",
    0xA3: "Right Ctrl",
    0xA4: "Alt",
    0xA5: "Right Alt",
    0xBA: ";",
    0xBB: "=",
    0xBC: ",",
    0xBD: "-",
    0xBE: ".",
    0xBF: "/",
    0xC0: "`",
    0xDB: "[",
    0xDC: "\\",
    0xDD: "]",
    0xDE: "'",
}
_VK_NAMES.update({0x60 + n: f"Num {n}" for n in range(10)})

# Virtual keys of modifier keys, generic and left/right specific.
MODIFIER_VKS = frozenset({0x10, 0x11, 0x12, 0x5B, 0x5C, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5})


def key_label(vk: int) -> str:
    """Readable name of a Windows virtual-key code."""
    if vk in _VK_NAMES:
        return _VK_NAMES[vk]
    for name, code in KEY_CODES.items():
        if code == vk:
            return Hotkey(name).label
    return f"VK 0x{vk:02X}"


@dataclass(frozen=True)
class Hotkey:
    key: str
    modifiers: frozenset[str] = frozenset()

    def __str__(self) -> str:
        return "+".join([m for m in MODIFIER_ORDER if m in self.modifiers] + [self.key])

    @property
    def label(self) -> str:
        key = _KEY_LABELS.get(self.key, self.key.upper() if len(self.key) <= 3 else self.key.capitalize())
        return "+".join([m.capitalize() for m in MODIFIER_ORDER if m in self.modifiers] + [key])

    @property
    def vk(self) -> int:
        return KEY_CODES[self.key]

    @property
    def modifier_flags(self) -> int:
        flags = 0
        for name in self.modifiers:
            flags |= MODIFIER_FLAGS[name]
        return flags


def parse_hotkey(text: str) -> Hotkey:
    """Parse "ctrl+alt+f6"-style text. Raises ValueError with a readable reason."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Hotkey cannot be empty.")
    parts = [p.strip().lower() for p in text.replace(" ", "").split("+")]
    if any(not p for p in parts):
        raise ValueError(f"Malformed hotkey: {text!r}.")
    *mods, key = parts
    modifiers = set()
    for raw in mods:
        name = _MODIFIER_ALIASES.get(raw, raw)
        if name not in MODIFIER_FLAGS:
            raise ValueError(f"Unknown modifier {raw!r} in {text!r}.")
        modifiers.add(name)
    if key not in KEY_CODES:
        raise ValueError(f"Unsupported key {key!r}. Use F1–F24, A–Z, 0–9 or a navigation key.")
    hotkey = Hotkey(key, frozenset(modifiers))
    if key in _TYPING_KEYS and not modifiers:
        raise ValueError(f"{hotkey.label} would block normal typing. Add Ctrl, Alt, Shift or Win.")
    if key in _TYPING_KEYS and modifiers == {"shift"}:
        raise ValueError(f"{hotkey.label} would block typing capitals. Add Ctrl, Alt or Win.")
    if str(hotkey) in RESERVED:
        raise ValueError(f"Windows reserves {hotkey.label} for debuggers. Pick another key.")
    return hotkey


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
        self._emergency_stop_callback = emergency_stop_callback
        self._lock = threading.Lock()
        self._toggle = parse_hotkey(DEFAULT_TOGGLE)
        self._stop = parse_hotkey(DEFAULT_STOP)
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()

    def set_keys(self, toggle: str, stop: str) -> None:
        toggle_key = parse_hotkey(toggle)
        stop_key = parse_hotkey(stop)
        if toggle_key == stop_key:
            raise ValueError("Start/pause and emergency stop need different keys.")
        with self._lock:
            self._toggle = toggle_key
            self._stop = stop_key
            thread_id = self._thread_id
        if thread_id:
            # RegisterHotKey must run on the thread that owns the hotkeys.
            winapi.PostThreadMessageW(thread_id, _WM_REREGISTER, 0, 0)

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running():
            return
        if not winapi.IS_WINDOWS:
            self.error_occurred.emit("Global hotkeys require Windows.")
            return
        self._ready.clear()
        thread = threading.Thread(target=self._run, name="GlobalHotkeys", daemon=True)
        self._thread = thread
        thread.start()
        self._ready.wait(2.0)

    def stop(self) -> None:
        thread = self._thread
        self._thread = None
        if thread is None:
            return
        with self._lock:
            thread_id = self._thread_id
        if thread_id:
            winapi.PostThreadMessageW(thread_id, winapi.WM_QUIT, 0, 0)
        if thread is not threading.current_thread():
            thread.join(2.0)

    def _run(self) -> None:
        from ctypes import wintypes

        msg = wintypes.MSG()
        # Create this thread's message queue before anyone posts to it.
        winapi.PeekMessageW(ctypes.byref(msg), None, winapi.WM_USER, winapi.WM_USER, winapi.PM_NOREMOVE)
        with self._lock:
            self._thread_id = winapi.GetCurrentThreadId()
        self._ready.set()
        try:
            self._register()
            while winapi.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == winapi.WM_HOTKEY:
                    self._dispatch(int(msg.wParam))
                elif msg.message == _WM_REREGISTER:
                    self._register()
        finally:
            winapi.UnregisterHotKey(None, _TOGGLE_ID)
            winapi.UnregisterHotKey(None, _STOP_ID)
            with self._lock:
                self._thread_id = 0

    def _register(self) -> None:
        with self._lock:
            keys = ((_TOGGLE_ID, self._toggle, "start/pause"), (_STOP_ID, self._stop, "emergency stop"))
        for hotkey_id, _hotkey, _role in keys:
            winapi.UnregisterHotKey(None, hotkey_id)
        for hotkey_id, hotkey, role in keys:
            flags = hotkey.modifier_flags | winapi.MOD_NOREPEAT
            if not winapi.RegisterHotKey(None, hotkey_id, flags, hotkey.vk):
                code = ctypes.get_last_error()
                reason = (
                    "another program already uses it"
                    if code == winapi.ERROR_HOTKEY_ALREADY_REGISTERED
                    else f"Windows error {code}"
                )
                self.error_occurred.emit(
                    f"Could not register {hotkey.label} for {role}: {reason}. Pick a different hotkey."
                )

    def _dispatch(self, hotkey_id: int) -> None:
        if hotkey_id == _TOGGLE_ID:
            self.toggle_requested.emit()
        elif hotkey_id == _STOP_ID:
            if self._emergency_stop_callback is not None:
                try:
                    self._emergency_stop_callback()
                except Exception as exc:
                    self.error_occurred.emit(f"Emergency stop failed: {exc}")
            self.emergency_stop_requested.emit()
