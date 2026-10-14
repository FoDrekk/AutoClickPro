"""Background auto-click worker."""

from __future__ import annotations

import logging
import os
import threading
import time
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import QThread, Signal
from pynput.mouse import Button, Controller

_logger = logging.getLogger("autoclick_pro")
if not _logger.handlers:
    _handler = RotatingFileHandler(
        os.path.join(os.path.expanduser("~"), ".autoclick_pro.log"),
        maxBytes=512_000,
        backupCount=2,
        encoding="utf-8",
    )
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    _logger.addHandler(_handler)
    _logger.setLevel(logging.INFO)

_BUTTONS = {"left": Button.left, "right": Button.right, "middle": Button.middle}


class ClickEngine(QThread):
    """Run mouse clicks away from the GUI thread with synchronized controls."""

    click_count_changed = Signal(int)
    error_occurred = Signal(str)
    limit_reached = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._condition = threading.Condition()
        self._active = False
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

    def start_clicking(self) -> None:
        with self._condition:
            if self._shutdown_requested:
                return
            self._active = True
            self._stop_at = (
                self._click_count + self._max_clicks if self._max_clicks else None
            )
            if self._max_seconds:
                if self._remaining is not None:
                    self._stop_time = time.monotonic() + self._remaining
                else:
                    self._stop_time = time.monotonic() + self._max_seconds
            else:
                self._stop_time = None
            self._remaining = None
            should_start_thread = not self.isRunning()
            self._condition.notify_all()

        if should_start_thread:
            self.start()

    def pause_clicking(self) -> None:
        with self._condition:
            if self._active and self._stop_time is not None:
                self._remaining = max(0.0, self._stop_time - time.monotonic())
            self._active = False
            self._condition.notify_all()

    def emergency_stop(self) -> None:
        # The worker holds this same lock while issuing a click, so returning
        # from this method guarantees that no later click can start first.
        with self._condition:
            self._active = False
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

    def reset_count(self) -> None:
        with self._condition:
            self._click_count = 0
            self._stop_at = None
            self._stop_time = None
            self._remaining = None
        self.click_count_changed.emit(0)

    def shutdown(self) -> None:
        with self._condition:
            self._active = False
            self._shutdown_requested = True
            self._condition.notify_all()
        if self.isRunning():
            self.wait()

    def run(self) -> None:
        try:
            mouse = Controller()
            while True:
                error_message: str | None = None
                click_count: int | None = None
                limit_message: str | None = None

                with self._condition:
                    while not self._active and not self._shutdown_requested:
                        self._condition.wait()
                    if self._shutdown_requested:
                        return

                    try:
                        if (
                            self._stop_time is not None
                            and time.monotonic() >= self._stop_time
                        ):
                            self._active = False
                            limit_message = "Duration limit reached — clicking stopped."
                        if self._active and self._failsafe:
                            pos = mouse.position
                            if pos[0] <= 3 and pos[1] <= 3:
                                self._active = False
                                error_message = "Failsafe corner reached — clicking stopped."
                        if self._active and error_message is None and limit_message is None:
                            if self._position_mode == "fixed":
                                if self._fixed_position is None:
                                    self._active = False
                                    error_message = "Capture the mouse position before using fixed coordinates."
                                else:
                                    mouse.position = self._fixed_position
                        if self._active and error_message is None and limit_message is None:
                            presses = 2 if self._double else 1
                            if self._stop_at is not None:
                                presses = max(
                                    1, min(presses, self._stop_at - self._click_count)
                                )
                            mouse.click(_BUTTONS[self._button], presses)
                            self._click_count += presses
                            click_count = self._click_count
                            if (
                                self._stop_at is not None
                                and self._click_count >= self._stop_at
                            ):
                                self._active = False
                                limit_message = (
                                    f"Click target reached ({self._click_count}) — clicking stopped."
                                )
                    except Exception as exc:  # Surface OS/input errors in the UI.
                        self._active = False
                        error_message = f"Click failed: {exc}"
                        _logger.exception("Click failed")

                    interval_seconds = self._interval_ms / 1000.0
                    if error_message is None:
                        deadline = time.monotonic() + interval_seconds
                        while self._active and not self._shutdown_requested:
                            remaining = deadline - time.monotonic()
                            if remaining <= 0:
                                break
                            notified = self._condition.wait(timeout=remaining)
                            if notified and self._active and not self._shutdown_requested:
                                # Apply interval/position changes from the UI before
                                # the next click and avoid an unexpectedly short burst.
                                deadline = time.monotonic() + self._interval_ms / 1000.0

                if click_count is not None:
                    self.click_count_changed.emit(click_count)
                if error_message is not None:
                    _logger.error("%s", error_message)
                    self.error_occurred.emit(error_message)
                if limit_message is not None:
                    _logger.info("%s", limit_message)
                    self.limit_reached.emit(limit_message)
        except Exception as exc:
            with self._condition:
                self._active = False
            _logger.exception("Mouse engine failed to start")
            self.error_occurred.emit(f"Mouse engine failed to start: {exc}")
