"""Click sequences: step model, validation and pixel-color matching.

A sequence is an ordered list of steps that the click engine plays back.
Each step waits ``delay`` milliseconds after it runs. Recordings produce the
same steps, so editing, saving and playback work the same for both.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from typing import Any

STEP_TYPES = ("click", "down", "up", "move", "key_down", "key_up", "wait_color")
BUTTONS = ("left", "right", "middle")
MAX_STEPS = 100_000
MAX_DELAY_MS = 3_600_000
MAX_REPEAT = 1_000_000
MAX_LOOPS = 1_000_000
MIN_SPEED = 0.25
MAX_SPEED = 4.0
COORD_LIMIT = 100_000

_COLOR_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")


@dataclass(frozen=True)
class Step:
    type: str
    x: int | None = None
    y: int | None = None
    button: str = "left"
    double: bool = False
    repeat: int = 1
    delay: int = 100
    vk: int = 0
    extended: bool = False
    color: str = "#000000"
    tolerance: int = 0
    timeout: int = 0  # wait_color: give up after this many ms; 0 waits forever.

    @property
    def has_position(self) -> bool:
        return self.x is not None and self.y is not None

    def with_changes(self, **changes: Any) -> Step:
        return sanitize_step({**self.to_json(), **changes}) or self

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        keep = {"type", "delay"} | _FIELDS_BY_TYPE[self.type]
        return {key: value for key, value in data.items() if key in keep}


_FIELDS_BY_TYPE: dict[str, set[str]] = {
    "click": {"x", "y", "button", "double", "repeat"},
    "down": {"x", "y", "button"},
    "up": {"x", "y", "button"},
    "move": {"x", "y"},
    "key_down": {"vk", "extended"},
    "key_up": {"vk", "extended"},
    "wait_color": {"x", "y", "color", "tolerance", "timeout"},
}


@dataclass(frozen=True)
class Sequence:
    steps: tuple[Step, ...] = ()
    loops: int = 1  # 0 repeats forever.
    speed: float = 1.0

    def to_json(self) -> dict[str, Any]:
        return {"loops": self.loops, "speed": self.speed, "steps": [s.to_json() for s in self.steps]}


@dataclass(frozen=True)
class Trigger:
    """Pixel condition checked before every click in the simple clicker."""

    mode: str = "off"  # off | wait (click only while matching) | stop (stop when not matching)
    x: int | None = None
    y: int | None = None
    color: str = "#000000"
    tolerance: int = 16

    @property
    def enabled(self) -> bool:
        return self.mode != "off" and self.x is not None and self.y is not None

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def parse_color(text: str) -> tuple[int, int, int]:
    match = _COLOR_RE.match(text.strip()) if isinstance(text, str) else None
    if match is None:
        raise ValueError(f"Not a #RRGGBB color: {text!r}")
    value = int(match.group(1), 16)
    return (value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF


def format_color(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def color_matches(actual: tuple[int, int, int], expected: tuple[int, int, int], tolerance: int) -> bool:
    return all(abs(a - e) <= tolerance for a, e in zip(actual, expected, strict=True))


def _int(value: Any, default: int, low: int, high: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number) or number != int(number):
        return default
    result = int(number)
    return result if low <= result <= high else default


def _coord(value: Any) -> int | None:
    sentinel = COORD_LIMIT * 10
    result = _int(value, sentinel, -COORD_LIMIT, COORD_LIMIT)
    return None if result == sentinel else result


def _bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value) if isinstance(value, bool | int) else False


def _color(value: Any, default: str = "#000000") -> str:
    try:
        return format_color(parse_color(value))
    except ValueError:
        return default


def sanitize_step(raw: Any) -> Step | None:
    """A valid Step from untrusted data, or None when it cannot be repaired."""
    if not isinstance(raw, Mapping) or raw.get("type") not in STEP_TYPES:
        return None
    kind = raw["type"]
    x, y = _coord(raw.get("x")), _coord(raw.get("y"))
    if x is None or y is None:
        x = y = None
    if kind in {"move", "wait_color"} and x is None:
        return None
    button = str(raw.get("button")) if raw.get("button") in BUTTONS else "left"
    vk = _int(raw.get("vk"), 0, 1, 254)
    if kind in {"key_down", "key_up"} and vk == 0:
        return None
    step = Step(
        type=kind,
        x=x,
        y=y,
        button=button,
        double=_bool(raw.get("double")),
        repeat=_int(raw.get("repeat"), 1, 1, MAX_REPEAT),
        delay=_int(raw.get("delay"), 100, 0, MAX_DELAY_MS),
        vk=vk,
        extended=_bool(raw.get("extended")),
        color=_color(raw.get("color")),
        tolerance=_int(raw.get("tolerance"), 0, 0, 255),
        timeout=_int(raw.get("timeout"), 0, 0, MAX_DELAY_MS),
    )
    # Drop fields this step type does not use so equal steps compare equal.
    defaults = Step(type=kind)
    unused = {
        f: getattr(defaults, f) for f in asdict(step) if f not in _FIELDS_BY_TYPE[kind] | {"type", "delay"}
    }
    return replace(step, **unused)


def sanitize_sequence(raw: Any) -> Sequence:
    data: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
    raw_steps = data.get("steps")
    steps: list[Step] = []
    if isinstance(raw_steps, list):
        for item in raw_steps[:MAX_STEPS]:
            step = sanitize_step(item)
            if step is not None:
                steps.append(step)
    try:
        speed = float(data.get("speed", 1.0))
    except (TypeError, ValueError):
        speed = 1.0
    if not math.isfinite(speed) or not MIN_SPEED <= speed <= MAX_SPEED:
        speed = 1.0
    return Sequence(tuple(steps), _int(data.get("loops"), 1, 0, MAX_LOOPS), round(speed, 2))


def sanitize_trigger(raw: Any) -> Trigger:
    data: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
    x, y = _coord(data.get("x")), _coord(data.get("y"))
    if x is None or y is None:
        x = y = None
    mode = str(data.get("mode")) if data.get("mode") in {"off", "wait", "stop"} else "off"
    return Trigger(mode, x, y, _color(data.get("color")), _int(data.get("tolerance"), 16, 0, 255))


def _at(step: Step) -> str:
    return f" at {step.x}, {step.y}" if step.has_position else " at cursor"


def describe(step: Step) -> str:
    """One-line human description for the sequence table."""
    from autoclick_pro.global_hotkeys import key_label

    button = step.button.capitalize()
    if step.type == "click":
        what = f"{'Double-click' if step.double else 'Click'} {button.lower()}{_at(step)}"
        return what + (f" × {step.repeat}" if step.repeat > 1 else "")
    if step.type == "down":
        return f"Press {button.lower()} button{_at(step)}"
    if step.type == "up":
        return f"Release {button.lower()} button{_at(step)}"
    if step.type == "move":
        return f"Move to {step.x}, {step.y}"
    if step.type in {"key_down", "key_up"}:
        verb = "Press" if step.type == "key_down" else "Release"
        return f"{verb} key {key_label(step.vk)}"
    timeout = f", give up after {step.timeout / 1000:g} s" if step.timeout else ""
    return f"Wait until {step.x}, {step.y} is {step.color} (±{step.tolerance}){timeout}"
