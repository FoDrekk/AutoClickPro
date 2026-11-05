"""Versioned JSON storage for app settings and click profiles.

Every value read from disk passes through ``sanitize_*`` so a hand-edited,
truncated or legacy file can never crash the app: bad values fall back to
their defaults.
"""

from __future__ import annotations

import contextlib
import json
import logging
import math
import os
import tempfile
import unicodedata
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from autoclick_pro.global_hotkeys import DEFAULT_STOP, DEFAULT_TOGGLE, RESERVED, parse_hotkey
from autoclick_pro.steps import Sequence, Trigger, _bool, _coord, _int, sanitize_sequence, sanitize_trigger

SCHEMA_VERSION = 1
PROFILE_NAME_MAX = 64
MIN_INTERVAL_MS = 1
MAX_JITTER_PCT = 50
MAX_JITTER_PX = 50

_logger = logging.getLogger("autoclick_pro")

# Keys a profile stores: how to click, not how the app looks.
PROFILE_DEFAULTS: dict[str, Any] = {
    "interval": 100,
    "mode": "cursor",
    "fixedX": None,
    "fixedY": None,
    "button": "left",
    "double": False,
    "maxClicks": 0,
    "maxSeconds": 0.0,
    "failsafe": False,
    "jitterPct": 0,
    "jitterPx": 0,
    "background": False,
    "trigger": Trigger().to_json(),
    "sequence": Sequence().to_json(),
}

SETTINGS_DEFAULTS: dict[str, Any] = {
    **PROFILE_DEFAULTS,
    "sound": True,
    "alwaysOnTop": False,
    "minimizeToTray": False,
    "theme": "dark",
    "toggleKey": DEFAULT_TOGGLE,
    "stopKey": DEFAULT_STOP,
    "overlay": True,
    "countdown": 0,
    "recordMoves": False,
    "runMode": "simple",
    "checkUpdates": False,
    "lastUpdateCheck": 0,
}

PROFILE_KEYS = tuple(PROFILE_DEFAULTS)


# _bool, _int and _coord are shared with autoclick_pro.steps — this module
# used to define its own copies of them under _as_* names.
def _as_float(value: Any, default: float, low: float, high: float) -> float:
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return number if low <= number <= high else default


def _as_hotkey(value: Any) -> str | None:
    try:
        return str(parse_hotkey(value))
    except ValueError:
        return None


def _as_choice(value: Any, default: str, choices: set[str] | list[str]) -> str:
    return value if isinstance(value, str) and value in choices else default


def sanitize_profile(raw: Any) -> dict[str, Any]:
    data: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
    d = PROFILE_DEFAULTS
    fixed_x = _coord(data.get("fixedX"))
    fixed_y = _coord(data.get("fixedY"))
    # Coordinates are only meaningful as a pair.
    if fixed_x is None or fixed_y is None:
        fixed_x = fixed_y = None
    return {
        "interval": _int(data.get("interval"), d["interval"], MIN_INTERVAL_MS, 3_600_000),
        "mode": _as_choice(data.get("mode"), d["mode"], {"cursor", "fixed"}),
        "fixedX": fixed_x,
        "fixedY": fixed_y,
        "button": _as_choice(data.get("button"), d["button"], {"left", "right", "middle"}),
        "double": _bool(data.get("double"), d["double"]),
        "maxClicks": _int(data.get("maxClicks"), d["maxClicks"], 0, 1_000_000),
        "maxSeconds": _as_float(data.get("maxSeconds"), d["maxSeconds"], 0.0, 86_400.0),
        "failsafe": _bool(data.get("failsafe"), d["failsafe"]),
        "jitterPct": _int(data.get("jitterPct"), d["jitterPct"], 0, MAX_JITTER_PCT),
        "jitterPx": _int(data.get("jitterPx"), d["jitterPx"], 0, MAX_JITTER_PX),
        "background": _bool(data.get("background"), d["background"]),
        "trigger": sanitize_trigger(data.get("trigger")).to_json(),
        "sequence": sanitize_sequence(data.get("sequence")).to_json(),
    }


def sanitize_settings(raw: Any) -> dict[str, Any]:
    data: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
    d = SETTINGS_DEFAULTS
    toggle = _as_hotkey(data.get("toggleKey")) or d["toggleKey"]
    stop = _as_hotkey(data.get("stopKey")) or d["stopKey"]
    if toggle == stop:
        stop = next(key for key in (d["stopKey"], "f9", "f7") if key != toggle)
    return {
        **sanitize_profile(data),
        "sound": _bool(data.get("sound"), d["sound"]),
        "alwaysOnTop": _bool(data.get("alwaysOnTop"), d["alwaysOnTop"]),
        "minimizeToTray": _bool(data.get("minimizeToTray"), d["minimizeToTray"]),
        "theme": _as_choice(data.get("theme"), d["theme"], {"dark", "light", "system"}),
        "toggleKey": toggle,
        "stopKey": stop,
        "overlay": _bool(data.get("overlay"), d["overlay"]),
        "countdown": _int(data.get("countdown"), d["countdown"], 0, 10),
        "recordMoves": _bool(data.get("recordMoves"), d["recordMoves"]),
        "runMode": _as_choice(data.get("runMode"), d["runMode"], {"simple", "sequence"}),
        "checkUpdates": _bool(data.get("checkUpdates"), d["checkUpdates"]),
        "lastUpdateCheck": _int(data.get("lastUpdateCheck"), d["lastUpdateCheck"], 0, 2**40),
    }


def validate_profile_name(name: Any) -> str:
    if not isinstance(name, str):
        raise ValueError("Profile name must be text.")
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("Profile name cannot be empty.")
    if len(cleaned) > PROFILE_NAME_MAX:
        raise ValueError(f"Profile name must be at most {PROFILE_NAME_MAX} characters.")
    if any(unicodedata.category(ch) == "Cc" for ch in cleaned):
        raise ValueError("Profile name cannot contain control characters.")
    return cleaned


def _sanitize_profiles(raw: Any) -> dict[str, dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    if not isinstance(raw, Mapping):
        return profiles
    for name, data in raw.items():
        try:
            profiles[validate_profile_name(name)] = sanitize_profile(data)
        except ValueError:
            _logger.warning("Skipping profile with invalid name %r", name)
    return profiles


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.settings: dict[str, Any] = dict(SETTINGS_DEFAULTS)
        self.profiles: dict[str, dict[str, Any]] = {}
        # Shown once in the UI when the file on disk had to be discarded.
        self.load_warning: str | None = None

    @classmethod
    def load(
        cls,
        path: Path,
        legacy_loader: Callable[[], Mapping[str, Any] | None] | None = None,
    ) -> SettingsStore:
        store = cls(path)
        if not path.exists():
            legacy = None
            if legacy_loader is not None:
                try:
                    legacy = legacy_loader()
                except Exception:
                    _logger.exception("Could not read legacy settings")
            if legacy:
                store._apply_raw(legacy)
                try:
                    store.save()
                    _logger.info("Migrated legacy settings to %s", path)
                except OSError:
                    _logger.exception("Could not save migrated settings")
            return store
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, Mapping):
                raise ValueError("settings root is not an object")
        except (OSError, ValueError) as exc:
            _logger.error("Settings file unreadable (%s); using defaults", exc)
            backup = path.with_name(path.name + ".corrupt")
            try:
                os.replace(path, backup)
                store.load_warning = (
                    f"Settings were unreadable and were reset. Old file kept as {backup.name}."
                )
            except OSError:
                store.load_warning = "Settings were unreadable and were reset."
            return store
        store._apply_raw(raw)
        return store

    def _apply_raw(self, raw: Mapping[str, Any]) -> None:
        version = raw.get("version", SCHEMA_VERSION)
        if isinstance(version, int) and version > SCHEMA_VERSION:
            _logger.warning(
                "Settings schema %s is newer than %s; loading best effort", version, SCHEMA_VERSION
            )
        raw_settings = raw.get("settings")
        self.settings = sanitize_settings(raw_settings)
        if isinstance(raw_settings, Mapping):
            for field, role in (("toggleKey", "Start/pause"), ("stopKey", "Emergency stop")):
                old = raw_settings.get(field)
                if isinstance(old, str) and old.strip().lower() in RESERVED:
                    new = parse_hotkey(self.settings[field]).label
                    self.load_warning = (
                        f"{role} hotkey moved from {old.upper()} to {new}: Windows reserves {old.upper()}."
                    )
        self.profiles = _sanitize_profiles(raw.get("profiles"))

    def to_json(self) -> dict[str, Any]:
        return {
            "version": SCHEMA_VERSION,
            "settings": self.settings,
            "profiles": self.profiles,
        }

    def save(self) -> None:
        _atomic_write_json(self.path, self.to_json())

    def update_settings(self, values: Mapping[str, Any]) -> None:
        self.settings = sanitize_settings({**self.settings, **values})

    def profile_names(self) -> list[str]:
        return sorted(self.profiles, key=str.casefold)

    def set_profile(self, name: str, values: Mapping[str, Any]) -> str:
        clean = validate_profile_name(name)
        self.profiles[clean] = sanitize_profile(values)
        return clean

    def delete_profile(self, name: str) -> None:
        self.profiles.pop(name, None)

    def export_profiles(self, path: Path) -> int:
        _atomic_write_json(
            path,
            {
                "app": "AutoClick Pro",
                "kind": "profiles",
                "version": SCHEMA_VERSION,
                "profiles": self.profiles,
            },
        )
        return len(self.profiles)

    def import_profiles(self, path: Path) -> tuple[int, int]:
        """Merge profiles from an export or settings file. Returns (added, replaced)."""
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"Could not read {path.name}: {exc}") from exc
        if not isinstance(raw, Mapping) or not isinstance(raw.get("profiles"), Mapping):
            raise ValueError(f"{path.name} does not contain AutoClick Pro profiles.")
        incoming = _sanitize_profiles(raw["profiles"])
        if not incoming:
            raise ValueError(f"{path.name} has no valid profiles.")
        replaced = sum(1 for name in incoming if name in self.profiles)
        self.profiles.update(incoming)
        return len(incoming) - replaced, replaced
