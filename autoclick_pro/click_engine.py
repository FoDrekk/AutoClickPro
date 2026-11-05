"""Background worker that plays clicks and click sequences.

The simple clicker is a one-step program (click, wait the interval, repeat).
Sequences and recordings are longer programs. Both share one scheduler, so
pause/resume, limits, failsafe, jitter and fixed-rate timing apply to all.
"""

from __future__ import annotations

import logging
import math
import random
import threading
import time
from collections.abc import Sequence as SequenceABC
from typing import Any

from PySide6.QtCore import QThread, Signal

from autoclick_pro import winapi
from autoclick_pro.steps import Sequence, Step, Trigger, color_matches, parse_color

_logger = logging.getLogger("autoclick_pro")

_BUTTONS = {"left", "right", "middle"}

MIN_INTERVAL_MS = 1
FAILSAFE_MARGIN = 3
# The counter label cannot change faster than the screen refreshes anyway.
COUNT_SIGNAL_PERIOD = 1 / 30
# How often pixel conditions are re-checked while waiting for them.
POLL_INTERVAL = 0.05


def create_backend() -> Any:
    return winapi.InputBackend()


def current_failsafe_corners() -> list[tuple[int, int]]:
    try:
        return winapi.desktop_corners(winapi.monitor_rects())
    except OSError:
        return [(0, 0)]


def in_failsafe_corner(x: int, y: int, corners: SequenceABC[tuple[int, int]] = ((0, 0),)) -> bool:
    """True when the cursor sits in the top-left corner of the desktop.

    ``corners`` are the points the cursor stops at when pushed up and left,
    see :func:`winapi.desktop_corners`.
    """
    return any(
        cx <= x <= cx + FAILSAFE_MARGIN and cy <= y <= cy + FAILSAFE_MARGIN for cx, cy in corners
    )


def jitter_offset(rng: random.Random, radius: int) -> tuple[int, int]:
    """Uniform random point inside a disc of ``radius`` pixels."""
    if radius <= 0:
        return 0, 0
    while True:
        angle = rng.uniform(0, 2 * math.pi)
        distance = radius * math.sqrt(rng.random())
        dx, dy = round(distance * math.cos(angle)), round(distance * math.sin(angle))
        # Rounding near the rim can step just outside the disc; draw again.
        if dx * dx + dy * dy <= radius * radius:
            return dx, dy


class _Outcome:
    ADVANCE = "advance"
    POLL = "poll"
    STOP = "stop"


class ClickEngine(QThread):
    """Run mouse clicks away from the GUI thread with synchronized controls."""

    click_count_changed = Signal(int)
    # Current step index and completed loops while a sequence plays.
    progress_changed = Signal(int, int)
    error_occurred = Signal(str)
    limit_reached = Signal(str)
    failsafe_triggered = Signal(str)
    # A pixel condition ended the run (trigger mismatch, color wait timeout).
    condition_stopped = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._lock = threading.Lock()
        self._waiter = winapi.create_waiter()
        self._rng = random.Random()
        self._active = False
        self._paused = False
        self._shutdown_requested = False
        # Simple clicker settings.
        self._interval_ms = 100
        self._jitter_pct = 0
        self._jitter_px = 0
        self._position_mode = "cursor"
        self._fixed_position: tuple[int, int] | None = None
        self._background_hwnd: int | None = None
        self._button = "left"
        self._double = False
        self._trigger = Trigger()
        # Sequence settings.
        self._mode = "simple"
        self._sequence = Sequence()
        # Run limits and safety.
        self._max_clicks: int | None = None
        self._max_seconds: float | None = None
        self._failsafe = False
        self._failsafe_corners: list[tuple[int, int]] = [(0, 0)]
        # Run state, reset by start_clicking() and kept across pause/resume.
        self._click_count = 0
        self._stop_at: int | None = None
        self._stop_time: float | None = None
        self._remaining: float | None = None
        self._step_index = 0
        self._repeat_done = 0
        self._loops_done = 0
        self._wait_since: float | None = None
        # Inputs a sequence left pressed; released whenever the run stops.
        self._held_keys: set[tuple[int, bool]] = set()
        self._held_buttons: set[str] = set()

    def _update(self, **fields) -> None:
        with self._lock:
            for name, value in fields.items():
                setattr(self, name, value)
        self._waiter.wake()

    def is_active(self) -> bool:
        with self._lock:
            return self._active

    def is_paused(self) -> bool:
        with self._lock:
            return self._paused

    def start_clicking(self) -> None:
        """Begin a fresh run: zero the counter and arm the configured limits."""
        corners = current_failsafe_corners()
        with self._lock:
            if self._shutdown_requested:
                return
            self._failsafe_corners = corners
            self._click_count = 0
            self._stop_at = self._max_clicks
            self._stop_time = time.monotonic() + self._max_seconds if self._max_seconds else None
            self._remaining = None
            self._step_index = 0
            self._repeat_done = 0
            self._loops_done = 0
            self._wait_since = None
            self._paused = False
            self._active = True
            should_start_thread = not self.isRunning()
        self._waiter.wake()

        self.click_count_changed.emit(0)
        if should_start_thread:
            self.start()

    def resume_clicking(self) -> bool:
        """Continue a paused run, keeping its count and remaining limits."""
        corners = current_failsafe_corners()
        with self._lock:
            if self._shutdown_requested or not self._paused:
                return False
            self._failsafe_corners = corners
            if self._remaining is not None:
                self._stop_time = time.monotonic() + self._remaining
            self._remaining = None
            self._wait_since = None
            self._paused = False
            self._active = True
            should_start_thread = not self.isRunning()
        self._waiter.wake()

        if should_start_thread:
            self.start()
        return True

    def pause_clicking(self) -> None:
        with self._lock:
            if not self._active:
                return
            if self._stop_time is not None:
                self._remaining = max(0.0, self._stop_time - time.monotonic())
            self._active = False
            self._paused = True
        self._waiter.wake()

    def emergency_stop(self) -> None:
        # The worker holds this same lock while issuing input, so returning
        # from this method guarantees that no later input can start first.
        self._update(_active=False, _paused=False, _remaining=None)

    def set_interval_ms(self, interval_ms: int) -> bool:
        try:
            value = int(interval_ms)
        except (TypeError, ValueError):
            return False
        if value < MIN_INTERVAL_MS:
            return False
        self._update(_interval_ms=value)
        return True

    def set_jitter(self, interval_pct: int = 0, position_px: int = 0) -> None:
        pct = int(interval_pct)
        px = int(position_px)
        if not 0 <= pct <= 50:
            raise ValueError("Interval jitter must be between 0 and 50 percent.")
        if not 0 <= px <= 50:
            raise ValueError("Position jitter must be between 0 and 50 pixels.")
        self._update(_jitter_pct=pct, _jitter_px=px)

    def set_position(
        self, mode: str, x: int | None = None, y: int | None = None
    ) -> None:
        if mode not in {"cursor", "fixed"}:
            raise ValueError("Position mode must be 'cursor' or 'fixed'.")
        fixed_position = None
        if mode == "fixed" and x is not None and y is not None:
            fixed_position = (int(x), int(y))
        self._update(_position_mode=mode, _fixed_position=fixed_position)

    def set_background_target(self, hwnd: int | None) -> None:
        """Send simple-mode clicks to this window by message (None: real input)."""
        self._update(_background_hwnd=int(hwnd) if hwnd else None)

    def set_button(self, button: str) -> None:
        if button not in _BUTTONS:
            raise ValueError("Button must be 'left', 'right' or 'middle'.")
        self._update(_button=button)

    def set_double_click(self, enabled: bool) -> None:
        self._update(_double=bool(enabled))

    def set_trigger(self, trigger: Trigger) -> None:
        self._update(_trigger=trigger)

    def set_mode(self, mode: str) -> None:
        if mode not in {"simple", "sequence"}:
            raise ValueError("Mode must be 'simple' or 'sequence'.")
        self._update(_mode=mode)

    def set_sequence(self, sequence: Sequence) -> None:
        self._update(_sequence=sequence)

    def set_limits(
        self, max_clicks: int | None = None, max_seconds: float | None = None
    ) -> None:
        clicks = int(max_clicks) if max_clicks is not None else None
        if clicks is not None and clicks < 1:
            raise ValueError("Max clicks must be at least 1.")
        seconds = float(max_seconds) if max_seconds is not None else None
        if seconds is not None and seconds <= 0:
            raise ValueError("Max duration must be positive.")
        self._update(_max_clicks=clicks, _max_seconds=seconds)

    def set_failsafe(self, enabled: bool) -> None:
        self._update(_failsafe=bool(enabled))

    def shutdown(self) -> None:
        self._update(_active=False, _paused=False, _shutdown_requested=True)
        if self.isRunning():
            self.wait()

    # ----------------------------------------------------------- worker side
    # Everything below runs on the worker thread with self._lock held.

    def _draw_gap_factor(self) -> float:
        spread = self._jitter_pct / 100.0
        return 1.0 + self._rng.uniform(-spread, spread) if spread else 1.0

    def _current_step(self) -> Step:
        if self._mode == "sequence":
            return self._sequence.steps[self._step_index]
        fixed = self._fixed_position if self._position_mode == "fixed" else None
        return Step(
            "click",
            x=fixed[0] if fixed else None,
            y=fixed[1] if fixed else None,
            button=self._button,
            double=self._double,
        )

    def _step_gap(self, step: Step, factor: float) -> float | None:
        """Seconds to wait after ``step``; None follows the live simple interval."""
        if self._mode == "simple":
            return None
        return step.delay / 1000.0 * factor / self._sequence.speed

    def _release_held(self, backend: Any) -> None:
        for vk, extended in list(self._held_keys):
            try:
                backend.key(vk, False, extended)
            except OSError:
                _logger.exception("Could not release key %s", vk)
        for button in list(self._held_buttons):
            try:
                backend.press(button, False)
            except OSError:
                _logger.exception("Could not release %s button", button)
        self._held_keys.clear()
        self._held_buttons.clear()

    def _advance(self, step: Step) -> str | None:
        """Move to the next step; returns a message when the sequence ends."""
        if self._mode == "simple":
            return None
        self._repeat_done += 1
        if self._repeat_done < step.repeat:
            return None
        self._repeat_done = 0
        self._step_index += 1
        if self._step_index < len(self._sequence.steps):
            return None
        self._step_index = 0
        self._loops_done += 1
        loops = self._sequence.loops
        if loops and self._loops_done >= loops:
            return f"Sequence finished ({self._loops_done} loop{'s' if self._loops_done != 1 else ''})."
        return None

    def _run_step(self, backend: Any, step: Step, now: float) -> tuple[str, str | None]:
        trigger = self._trigger
        if step.type == "click":
            if self._mode == "simple" and trigger.enabled:
                assert trigger.x is not None and trigger.y is not None
                seen = backend.pixel(trigger.x, trigger.y)
                if not color_matches(seen, parse_color(trigger.color), trigger.tolerance):
                    if trigger.mode == "wait":
                        return _Outcome.POLL, None
                    return _Outcome.STOP, (
                        f"Trigger color at {trigger.x}, {trigger.y} changed — clicking stopped."
                    )
            presses = 2 if step.double else 1
            if self._stop_at is not None:
                presses = max(1, min(presses, self._stop_at - self._click_count))
            if step.x is not None and step.y is not None:
                dx, dy = jitter_offset(self._rng, self._jitter_px)
                x, y = step.x + dx, step.y + dy
                if self._mode == "simple" and self._background_hwnd:
                    backend.post_click(self._background_hwnd, x, y, step.button, presses)
                else:
                    backend.position = (x, y)
                    backend.click(step.button, presses)
            else:
                backend.click(step.button, presses)
            self._click_count += presses
        elif step.type in {"down", "up"}:
            if step.x is not None and step.y is not None:
                backend.position = (step.x, step.y)
            down = step.type == "down"
            backend.press(step.button, down)
            if down:
                self._held_buttons.add(step.button)
                self._click_count += 1
            else:
                self._held_buttons.discard(step.button)
        elif step.type == "move":
            backend.position = (step.x, step.y)
        elif step.type in {"key_down", "key_up"}:
            down = step.type == "key_down"
            backend.key(step.vk, down, step.extended)
            if down:
                self._held_keys.add((step.vk, step.extended))
            else:
                self._held_keys.discard((step.vk, step.extended))
        elif step.type == "wait_color":
            assert step.x is not None and step.y is not None
            if self._wait_since is None:
                self._wait_since = now
            if not color_matches(backend.pixel(step.x, step.y), parse_color(step.color), step.tolerance):
                if step.timeout and (now - self._wait_since) * 1000 >= step.timeout:
                    return _Outcome.STOP, (
                        f"Step {self._step_index + 1}: {step.color} did not appear at "
                        f"{step.x}, {step.y} within {step.timeout / 1000:g} s — sequence stopped."
                    )
                return _Outcome.POLL, None
            self._wait_since = None
        return _Outcome.ADVANCE, None

    def run(self) -> None:
        try:
            backend = create_backend()
        except Exception as exc:
            self._update(_active=False, _paused=False)
            _logger.exception("Mouse engine failed to start")
            self.error_occurred.emit(f"Mouse engine failed to start: {exc}")
            return

        # Scheduled time of the previous step; None means run immediately.
        last_due: float | None = None
        # Seconds until the next step; None follows the live simple interval.
        pending_gap: float | None = None
        gap_factor = 1.0
        dirty = False
        last_emit = 0.0
        while True:
            error_message: str | None = None
            failsafe_message: str | None = None
            limit_message: str | None = None
            condition_message: str | None = None
            timeout: float | None = None
            snapshot: tuple[int, int, int] | None = None

            with self._lock:
                if self._shutdown_requested:
                    self._release_held(backend)
                    return
                if not self._active:
                    self._release_held(backend)
                    last_due = None
                    pending_gap = None
                    wait = True
                else:
                    now = time.monotonic()
                    gap = pending_gap if pending_gap is not None else self._interval_ms / 1000.0 * gap_factor
                    due = now if last_due is None else last_due + gap
                    if self._stop_time is not None:
                        due = min(due, self._stop_time)
                    wait = now < due
                    timeout = due - now
                if not wait:
                    try:
                        if self._stop_time is not None and now >= self._stop_time:
                            self._active = False
                            limit_message = "Duration limit reached — clicking stopped."
                        elif self._failsafe and in_failsafe_corner(
                            backend.position[0], backend.position[1], self._failsafe_corners
                        ):
                            self._active = False
                            failsafe_message = "Failsafe corner reached — clicking stopped."
                        elif (
                            self._mode == "simple"
                            and self._position_mode == "fixed"
                            and self._fixed_position is None
                        ):
                            self._active = False
                            error_message = "Capture the mouse position before using fixed coordinates."
                        elif self._mode == "sequence" and not self._sequence.steps:
                            self._active = False
                            error_message = "The sequence has no steps."
                        else:
                            step = self._current_step()
                            outcome, message = self._run_step(backend, step, now)
                            dirty = True
                            if outcome == _Outcome.STOP:
                                self._active = False
                                condition_message = message
                            elif outcome == _Outcome.POLL:
                                last_due, pending_gap = now, POLL_INTERVAL
                            else:
                                if self._stop_at is not None and self._click_count >= self._stop_at:
                                    self._active = False
                                    limit_message = (
                                        f"Click target reached ({self._click_count}) — clicking stopped."
                                    )
                                else:
                                    finished = self._advance(step)
                                    if finished:
                                        self._active = False
                                        limit_message = finished
                                # Fixed-rate schedule: anchor to the previous due time so
                                # wake-up latency and input cost do not add drift, but
                                # never burst to catch up after a stall of a whole gap.
                                last_due = now if last_due is None or now - due >= gap else due
                                gap_factor = self._draw_gap_factor()
                                pending_gap = self._step_gap(step, gap_factor)
                    except Exception as exc:  # Surface OS/input errors in the UI.
                        self._active = False
                        error_message = f"Click failed: {exc}"
                        _logger.exception("Click failed")
                    if not self._active:
                        self._release_held(backend)
                if dirty and (not self._active or time.monotonic() - last_emit >= COUNT_SIGNAL_PERIOD):
                    snapshot = (self._click_count, self._step_index, self._loops_done)
                    dirty = False

            if snapshot is not None:
                last_emit = time.monotonic()
                self.click_count_changed.emit(snapshot[0])
                self.progress_changed.emit(snapshot[1], snapshot[2])
            if error_message is not None:
                _logger.error("%s", error_message)
                self.error_occurred.emit(error_message)
            if failsafe_message is not None:
                _logger.info("%s", failsafe_message)
                self.failsafe_triggered.emit(failsafe_message)
            if condition_message is not None:
                _logger.info("%s", condition_message)
                self.condition_stopped.emit(condition_message)
            if limit_message is not None:
                _logger.info("%s", limit_message)
                self.limit_reached.emit(limit_message)
            if wait:
                self._waiter.wait(timeout)
