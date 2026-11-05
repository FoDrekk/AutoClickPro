import pytest

from autoclick_pro.steps import (
    MAX_STEPS,
    Sequence,
    Step,
    color_matches,
    describe,
    format_color,
    parse_color,
    sanitize_sequence,
    sanitize_step,
    sanitize_trigger,
)


def test_color_round_trip():
    assert parse_color("#1a2B3c") == (0x1A, 0x2B, 0x3C)
    assert parse_color("ff0000") == (255, 0, 0)
    assert format_color((1, 2, 255)) == "#0102FF"
    for bad in ("", "#12345", "#GG0000", None, 5):
        with pytest.raises(ValueError):
            parse_color(bad)


def test_color_tolerance():
    assert color_matches((100, 100, 100), (100, 100, 100), 0)
    assert color_matches((110, 95, 100), (100, 100, 100), 10)
    assert not color_matches((111, 100, 100), (100, 100, 100), 10)


def test_sanitize_click_step():
    step = sanitize_step({"type": "click", "x": "10", "y": 20, "button": "right", "repeat": 3, "delay": 50})
    assert step == Step("click", 10, 20, "right", repeat=3, delay=50)


def test_sanitize_drops_unused_fields():
    step = sanitize_step({"type": "move", "x": 1, "y": 2, "button": "right", "vk": 65, "color": "#FFFFFF"})
    assert step == Step("move", 1, 2)
    assert step.to_json() == {"type": "move", "x": 1, "y": 2, "delay": 100}


@pytest.mark.parametrize(
    "raw",
    [
        None,
        {},
        {"type": "explode"},
        {"type": "move"},  # Needs a position.
        {"type": "move", "x": 5},
        {"type": "wait_color", "x": None, "y": 3},
        {"type": "key_down"},  # Needs a key.
        {"type": "key_down", "vk": 999},
    ],
)
def test_sanitize_rejects(raw):
    assert sanitize_step(raw) is None


def test_sanitize_repairs_bad_values():
    step = sanitize_step({"type": "click", "button": "thumb", "repeat": 0, "delay": -5, "x": "nope", "y": 1})
    assert step == Step("click")


def test_sequence_sanitize():
    seq = sanitize_sequence(
        {
            "loops": 3,
            "speed": 2,
            "steps": [{"type": "click"}, {"type": "bogus"}, {"type": "key_up", "vk": 13}],
        }
    )
    assert seq.loops == 3
    assert seq.speed == 2.0
    assert [s.type for s in seq.steps] == ["click", "key_up"]
    assert sanitize_sequence({"loops": -1, "speed": 99}) == Sequence((), 1, 1.0)
    assert sanitize_sequence("junk") == Sequence()


def test_sequence_step_cap():
    seq = sanitize_sequence({"steps": [{"type": "click"}] * (MAX_STEPS + 5)})
    assert len(seq.steps) == MAX_STEPS


def test_sequence_json_round_trip():
    seq = Sequence(
        (
            Step("click", 1, 2, double=True),
            Step("key_down", vk=0x41),
            Step("wait_color", 5, 6, color="#ABCDEF", tolerance=4, timeout=2000),
        ),
        loops=0,
        speed=0.5,
    )
    assert sanitize_sequence(seq.to_json()) == seq


def test_trigger_sanitize():
    trig = sanitize_trigger({"mode": "wait", "x": 1, "y": 2, "color": "00ff00", "tolerance": 300})
    assert trig.mode == "wait" and trig.color == "#00FF00" and trig.tolerance == 16
    assert trig.enabled
    assert not sanitize_trigger({"mode": "wait"}).enabled
    assert sanitize_trigger({"mode": "nope"}).mode == "off"


@pytest.mark.parametrize(
    ("step", "text"),
    [
        (Step("click", 5, 6), "Click left at 5, 6"),
        (Step("click", button="right", double=True, repeat=3), "Double-click right at cursor × 3"),
        (Step("down", 1, 2), "Press left button at 1, 2"),
        (Step("move", 7, 8), "Move to 7, 8"),
        (Step("key_down", vk=0x41), "Press key A"),
        (Step("key_up", vk=0x0D), "Release key Enter"),
        (
            Step("wait_color", 3, 4, color="#FF0000", tolerance=8, timeout=1500),
            "Wait until 3, 4 is #FF0000 (±8), give up after 1.5 s",
        ),
    ],
)
def test_describe(step, text):
    assert describe(step) == text
