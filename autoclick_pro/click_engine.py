"""Background auto-click worker."""

from __future__ import annotations

import logging
import threading
import time

from pynput.mouse import Button, Controller
from PySide6.QtCore import QThread, Signal

_logger = logging.getLogger("autoclick_pro")

_BUTTONS = {"left": Button.left, "right": Button.right, "middle": Button.middle}

FAILSAFE_MARGIN = 3


def in_failsafe_corner(x: int, y: int) -> bool:
    """True when the cursor sits in the primary monitor's top-left corner.

    Negative coordinates belong to monitors placed left of or above the
    primary one, so they never count as the corner.
    """
    return 0 <= x <= FAILSAFE_MARGIN and 0 <= y <= FAILSAFE_MARGIN


class ClickEngine(QThread):
    """Run mouse clicks away from the GUI thread with synchronized controls."""

    click_count_changed = Signal(int)
    error_occurred = Signal(str)
    limit_reached = Signal(str)
    failsafe_triggered = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._condition = threading.Condition()
        self._active = False
        self._paused = False
        self._shutdown_requested = False
        self._interval_ms = 100
        self._position_mode = "cursor"
        self._fixed_position: tuple[int, int] | None = None
        self._click_count = 0
        self._button = "left"
        self._double = False
        self._max_clicks: int | None = None
        self._max_seconds: float | None = None
        self._failsafe = False
        self._stop_at: int | None = None
        self._stop_time: float | None = None
        self._remaining: float | None = None

    def is_active(self) -> bool:
        with self._condition:
            return self._active

    def is_paused(self) -> bool:
        with self._condition:
            return self._paused

    def start_clicking(self) -> None:
        """Begin a fresh run: zero the counter and arm the configured limits."""
        with self._condition:
            if self._shutdown_requested:
                return
            self._click_count = 0
            self._stop_at = self._max_clicks
            self._stop_time = (
                time.monotonic() + self._max_seconds if self._max_seconds else None
            )
            self._remaining = None
            self._paused = False
            self._active = True
            should_start_thread = not self.isRunning()
            self._condition.notify_all()

        self.click_count_changed.emit(0)
        if should_start_thread:
            self.start()

    def resume_clicking(self) -> bool:
        """Continue a paused run, keeping its count and remaining limits."""
        with self._condition:
            if self._shutdown_requested or not self._paused:
                return False
            if self._remaining is not None:
                self._stop_time = time.monotonic() + self._remaining
            self._remaining = None
            self._paused = False
            self._active = True
            should_start_thread = not self.isRunning()
            self._condition.notify_all()

        if should_start_thread:
            self.start()
        return True

    def pause_clicking(self) -> None:
        with self._condition:
            if not self._active:
                return
            if self._stop_time is not None:
                self._remaining = max(0.0, self._stop_time - time.monotonic())
            self._active = False
            self._paused = True
            self._condition.notify_all()

    def emergency_stop(self) -> None:
        # The worker holds this same lock while issuing a click, so returning
        # from this method guarantees that no later click can start first.
        with self._condition:
            self._active = False
            self._paused = False
            self._remaining = None
            self._condition.notify_all()

    def set_interval_ms(self, interval_ms: int) -> bool:
        try:
            value = int(interval_ms)
        except (TypeError, ValueError):
            return False
        if value < 10:
            return False
        with self._condition:
            self._interval_ms = value
            self._condition.notify_all()
        return True

    def set_position(
        self, mode: str, x: int | None = None, y: int | None = None
    ) -> None:
        if mode not in {"cursor", "fixed"}:
            raise ValueError("Position mode must be 'cursor' or 'fixed'.")
        fixed_position = None
        if mode == "fixed" and x is not None and y is not None:
            fixed_position = (int(x), int(y))
        with self._condition:
            self._position_mode = mode
            self._fixed_position = fixed_position
            self._condition.notify_all()

    def set_button(self, button: str) -> None:
        if button not in _BUTTONS:
            raise ValueError("Button must be 'left', 'right' or 'middle'.")
        with self._condition:
            self._button = button
            self._condition.notify_all()

    def set_double_click(self, enabled: bool) -> None:
        with self._condition:
            self._double = bool(enabled)
            self._condition.notify_all()

    def set_limits(
        self, max_clicks: int | None = None, max_seconds: float | None = None
    ) -> None:
        clicks = int(max_clicks) if max_clicks is not None else None
        if clicks is not None and clicks < 1:
            raise ValueError("Max clicks must be at least 1.")
        seconds = float(max_seconds) if max_seconds is not None else None
        if seconds is not None and seconds <= 0:
            raise ValueError("Max duration must be positive.")
        with self._condition:
            self._max_clicks = clicks
            self._max_seconds = seconds
            self._condition.notify_all()

    def set_failsafe(self, enabled: bool) -> None:
        with self._condition:
            self._failsafe = bool(enabled)
            self._condition.notify_all()

    def shutdown(self) -> None:
        with self._condition:
            self._active = False
            self._paused = False
            self._shutdown_requested = True
            self._condition.notify_all()
        if self.isRunning():
            self.wait()

    def _wait_until_due(self, last_due: float) -> bool:
        """Sleep until the next click or the duration limit is due.

        Caller holds the lock. Re-reads the interval after every wake-up so
        UI changes apply to the very next click. Returns False when the run
        was paused, stopped or shut down while waiting.
        """
        while self._active and not self._shutdown_requested:
            due = last_due + self._interval_ms / 1000.0
            if self._stop_time is not None:
                due = min(due, self._stop_time)
            remaining = due - time.monotonic()
            if remaining <= 0:
                return True
            self._condition.wait(timeout=remaining)
        return False

    def run(self) -> None:
        try:
            mouse = Controller()
        except Exception as exc:
            with self._condition:
                self._active = False
                self._paused = False
            _logger.exception("Mouse engine failed to start")
            self.error_occurred.emit(f"Mouse engine failed to start: {exc}")
            return

        # Scheduled time of the previous click; None means click immediately.
        last_due: float | None = None
        while True:
            error_message: str | None = None
            failsafe_message: str | None = None
            limit_message: str | None = None
            click_count: int | None = None

            with self._condition:
                while not self._active and not self._shutdown_requested:
                    last_due = None
                    self._condition.wait()
                if self._shutdown_requested:
                    return
                if last_due is not None and not self._wait_until_due(last_due):
                    continue

                now = time.monotonic()
                try:
                    if self._stop_time is not None and now >= self._stop_time:
                        self._active = False
                        limit_message = "Duration limit reached — clicking stopped."
                    elif self._failsafe and in_failsafe_corner(*map(int, mouse.position)):
                        self._active = False
                        failsafe_message = "Failsafe corner reached — clicking stopped."
                    elif self._position_mode == "fixed" and self._fixed_position is None:
                        self._active = False
                        error_message = "Capture the mouse position before using fixed coordinates."
                    else:
                        if self._position_mode == "fixed":
                            mouse.position = self._fixed_position
                        presses = 2 if self._double else 1
                        if self._stop_at is not None:
                            presses = max(1, min(presses, self._stop_at - self._click_count))
                        mouse.click(_BUTTONS[self._button], presses)
                        self._click_count += presses
                        click_count = self._click_count
                        if self._stop_at is not None and self._click_count >= self._stop_at:
                            self._active = False
                            limit_message = (
                                f"Click target reached ({self._click_count}) — clicking stopped."
                            )
                        # Fixed-rate schedule: anchor to the previous due time so
                        # click cost does not add drift, but never burst to catch
                        # up after a stall longer than one interval.
                        interval = self._interval_ms / 1000.0
                        scheduled = now if last_due is None else last_due + interval
                        last_due = now if now - scheduled >= interval else scheduled
                except Exception as exc:  # Surface OS/input errors in the UI.
                    self._active = False
                    error_message = f"Click failed: {exc}"
                    _logger.exception("Click failed")

            if click_count is not None:
                self.click_count_changed.emit(click_count)
            if error_message is not None:
                _logger.error("%s", error_message)
                self.error_occurred.emit(error_message)
            if failsafe_message is not None:
                _logger.info("%s", failsafe_message)
                self.failsafe_triggered.emit(failsafe_message)
            if limit_message is not None:
                _logger.info("%s", limit_message)
                self.limit_reached.emit(limit_message)
