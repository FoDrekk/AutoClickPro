"""Crash capture and a privacy-safe diagnostics report.

The windowed build has no console, so Python-level crashes go to the log (see
``app_logging``) and native crashes (access violations, aborts) go to
``crash.log`` through ``faulthandler``. A non-empty ``crash.log`` at the next
start means the previous run died; it is moved aside and reported once.

Diagnostics deliberately leave out anything typed or recorded by the user:
sequences and profiles can contain keystrokes, so only counts are included.
"""

from __future__ import annotations

import contextlib
import faulthandler
import os
import platform
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import IO, Any

from autoclick_pro import __version__
from autoclick_pro.paths import data_dir

KEEP_CRASH_REPORTS = 3
LOG_TAIL_LINES = 40

_fault_file: IO[str] | None = None


def crash_log_path() -> Path:
    return data_dir() / "crash.log"


def take_previous_crash(path: Path) -> Path | None:
    """Move a non-empty crash log aside and return its new path.

    Returns None when the previous run ended normally. Keeps the newest
    ``KEEP_CRASH_REPORTS`` reports.
    """
    try:
        if not path.is_file() or path.stat().st_size == 0:
            return None
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(path.stat().st_mtime))
        target = path.with_name(f"crash-{stamp}.log")
        os.replace(path, target)
    except OSError:
        return None
    reports = sorted(path.parent.glob("crash-*.log"), reverse=True)
    for old in reports[KEEP_CRASH_REPORTS:]:
        with contextlib.suppress(OSError):
            old.unlink()
    return target


def enable_fault_handler(path: Path) -> bool:
    """Send native crash tracebacks of all threads to ``path``."""
    global _fault_file
    disable_fault_handler()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _fault_file = open(path, "a", encoding="utf-8")  # noqa: SIM115 - must stay open for the process.
        faulthandler.enable(_fault_file, all_threads=True)
    except (OSError, RuntimeError):
        _fault_file = None
        return False
    return True


def disable_fault_handler() -> None:
    global _fault_file
    if _fault_file is not None:
        try:
            faulthandler.disable()
            _fault_file.close()
        except (OSError, ValueError):
            pass
        _fault_file = None


def redact(text: str) -> str:
    """Replace the user's home folder so reports can be shared safely."""
    home = str(Path.home())
    for variant in {home, home.replace("\\", "/")}:
        if variant:
            text = text.replace(variant, "~")
    return text


def _windows_version() -> str:
    getter = getattr(sys, "getwindowsversion", None)
    if getter is None:
        return platform.platform()
    v = getter()
    return f"Windows {v.major}.{v.minor} build {v.build} ({platform.machine()})"


def _tail(path: Path, lines: int) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return "".join(handle.readlines()[-lines:]).rstrip()
    except OSError:
        return "(no log file)"


def settings_summary(settings: Mapping[str, Any], profile_count: int) -> list[str]:
    """Non-sensitive facts about the configuration."""
    sequence = settings.get("sequence")
    steps = len(sequence.get("steps", [])) if isinstance(sequence, Mapping) else 0
    trigger = settings.get("trigger")
    trigger_mode = trigger.get("mode") if isinstance(trigger, Mapping) else "off"
    return [
        f"run mode: {settings.get('runMode')}",
        f"interval: {settings.get('interval')} ms, "
        f"jitter {settings.get('jitterPct')}% / {settings.get('jitterPx')} px",
        f"position mode: {settings.get('mode')}, background clicks: {settings.get('background')}",
        f"hotkeys: {settings.get('toggleKey')} / {settings.get('stopKey')}",
        f"failsafe: {settings.get('failsafe')}, trigger: {trigger_mode}",
        f"sequence steps: {steps}, profiles: {profile_count}",
    ]


def collect_diagnostics(
    *,
    settings: Mapping[str, Any] | None = None,
    profile_count: int = 0,
    log_file: Path | None = None,
    extra: Mapping[str, str] | None = None,
) -> str:
    from autoclick_pro.paths import log_path, settings_path

    lines = [
        f"AutoClick Pro {__version__}",
        f"Frozen build: {getattr(sys, 'frozen', False)}",
        f"Python: {platform.python_version()}",
        f"OS: {_windows_version()}",
        f"Time: {time.strftime('%Y-%m-%d %H:%M:%S %z')}",
    ]
    try:
        import PySide6

        lines.append(f"PySide6: {PySide6.__version__}")
    except ImportError:
        pass
    try:
        import ctypes

        lines.append(f"Running as admin: {bool(ctypes.windll.shell32.IsUserAnAdmin())}")
    except (AttributeError, OSError):
        pass
    try:
        from PySide6.QtGui import QGuiApplication

        screens = QGuiApplication.screens()
        lines.append(
            "Screens: "
            + ", ".join(f"{s.size().width()}x{s.size().height()} @{s.devicePixelRatio():g}x" for s in screens)
        )
    except Exception:
        pass
    lines.append(f"Settings file: {settings_path()}")
    if settings is not None:
        lines += [f"  {line}" for line in settings_summary(settings, profile_count)]
    for key, value in (extra or {}).items():
        lines.append(f"{key}: {value}")
    crash = crash_log_path()
    previous = sorted(crash.parent.glob("crash-*.log"), reverse=True)
    lines.append(f"Native crash reports kept: {len(previous)}")
    lines.append("")
    lines.append(f"--- last {LOG_TAIL_LINES} log lines ({log_file or log_path()}) ---")
    lines.append(_tail(log_file or log_path(), LOG_TAIL_LINES))
    return redact("\n".join(lines))
