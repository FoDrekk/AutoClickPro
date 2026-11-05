import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from autoclick_pro import __version__, diagnostics


def test_clean_run_leaves_no_report(tmp_path):
    path = tmp_path / "crash.log"
    assert diagnostics.take_previous_crash(path) is None  # Missing file.
    path.write_text("", encoding="utf-8")
    assert diagnostics.take_previous_crash(path) is None  # Empty: previous run ended normally.
    assert path.exists()


def test_previous_crash_is_moved_aside(tmp_path):
    path = tmp_path / "crash.log"
    path.write_text("Windows fatal exception: access violation\n", encoding="utf-8")
    moved = diagnostics.take_previous_crash(path)
    assert moved is not None and moved.name.startswith("crash-") and moved.exists()
    assert "access violation" in moved.read_text(encoding="utf-8")
    assert not path.exists()


def test_old_crash_reports_are_pruned(tmp_path):
    for day in range(1, 6):
        (tmp_path / f"crash-2026010{day}-000000.log").write_text("old", encoding="utf-8")
    path = tmp_path / "crash.log"
    path.write_text("new crash", encoding="utf-8")
    diagnostics.take_previous_crash(path)
    kept = sorted(p.name for p in tmp_path.glob("crash-*.log"))
    assert len(kept) == diagnostics.KEEP_CRASH_REPORTS
    assert "crash-20260101-000000.log" not in kept


def test_redact_hides_home_folder():
    home = str(Path.home())
    text = f"opened {home}\\AppData\\x and {home.replace(chr(92), '/')}/y"
    redacted = diagnostics.redact(text)
    assert home not in redacted and "~" in redacted


def test_diagnostics_exclude_user_input(tmp_path):
    log = tmp_path / "app.log"
    log.write_text("\n".join(f"line {i}" for i in range(100)), encoding="utf-8")
    settings = {
        "runMode": "sequence",
        "interval": 50,
        "jitterPct": 0,
        "jitterPx": 0,
        "mode": "fixed",
        "background": False,
        "toggleKey": "f6",
        "stopKey": "f8",
        "failsafe": True,
        "trigger": {"mode": "wait", "x": 1, "y": 2, "color": "#123456"},
        "sequence": {"steps": [{"type": "key_down", "vk": 0x50}] * 7, "loops": 1},
    }
    report = diagnostics.collect_diagnostics(settings=settings, profile_count=2, log_file=log)
    assert f"AutoClick Pro {__version__}" in report
    assert "sequence steps: 7, profiles: 2" in report
    assert "line 99" in report and "line 10\n" not in report  # Only the tail.
    assert "key_down" not in report and "#123456" not in report and '"vk"' not in report


def test_diagnostics_survive_missing_log(tmp_path):
    report = diagnostics.collect_diagnostics(log_file=tmp_path / "missing.log")
    assert "(no log file)" in report


@pytest.mark.skipif(sys.platform != "win32", reason="Windows crash behaviour")
def test_native_crash_is_written_to_crash_log(tmp_path):
    """A real access violation in a child process lands in the crash log."""
    crash = tmp_path / "crash.log"
    script = textwrap.dedent(
        f"""
        import ctypes, sys
        sys.path.insert(0, {str(Path(__file__).resolve().parent.parent)!r})
        from pathlib import Path
        from autoclick_pro import diagnostics
        assert diagnostics.enable_fault_handler(Path({str(crash)!r}))
        ctypes.string_at(0)  # Read address 0: access violation.
        """
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", script], capture_output=True, timeout=60, check=False
    )
    assert result.returncode != 0
    text = crash.read_text(encoding="utf-8")
    assert "access violation" in text.lower()
    assert "File" in text  # Python traceback of the crashing thread.
    assert diagnostics.take_previous_crash(crash) is not None


def test_enable_fault_handler_failure_is_not_fatal(tmp_path, monkeypatch):
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    assert diagnostics.enable_fault_handler(blocker / "crash.log") is False  # Parent is a file.
    diagnostics.disable_fault_handler()
    assert os.path.exists(blocker)
