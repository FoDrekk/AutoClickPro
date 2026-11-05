import pytest


def test_interval_accepts_valid(engine):
    assert engine.set_interval_ms(100) is True
    assert engine.set_interval_ms("250") is True


def test_interval_rejects_small_and_bad(engine):
    assert engine.set_interval_ms(1) is True
    assert engine.set_interval_ms(0) is False
    assert engine.set_interval_ms(-5) is False
    assert engine.set_interval_ms("bogus") is False
    assert engine.set_interval_ms(None) is False


def test_button_defaults_left(engine):
    assert engine._button == "left"


def test_button_accepts_all(engine):
    for name in ("left", "right", "middle"):
        engine.set_button(name)
        assert engine._button == name


def test_button_rejects_unknown(engine):
    with pytest.raises(ValueError):
        engine.set_button("bogus")


def test_double_click_toggle(engine):
    engine.set_double_click(True)
    assert engine._double is True
    engine.set_double_click(False)
    assert engine._double is False


def test_limits_accept_valid(engine):
    engine.set_limits(max_clicks=10, max_seconds=5)
    assert engine._max_clicks == 10
    assert engine._max_seconds == 5.0
    engine.set_limits()
    assert engine._max_clicks is None
    assert engine._max_seconds is None


def test_limits_reject_zero_clicks(engine):
    with pytest.raises(ValueError):
        engine.set_limits(max_clicks=0)


def test_limits_reject_bad_duration(engine):
    with pytest.raises(ValueError):
        engine.set_limits(max_seconds=0)
    with pytest.raises(ValueError):
        engine.set_limits(max_seconds=-1)


def test_position_mode_guard(engine):
    with pytest.raises(ValueError):
        engine.set_position("bogus")


def test_position_fixed_stores_coords(engine):
    engine.set_position("fixed", 11, 22)
    assert engine._fixed_position == (11, 22)
    engine.set_position("cursor")
    assert engine._position_mode == "cursor"


def test_failsafe_toggle(engine):
    engine.set_failsafe(True)
    assert engine._failsafe is True
    engine.set_failsafe(False)
    assert engine._failsafe is False


def test_resume_without_pause_is_noop(engine):
    assert engine.resume_clicking() is False
    assert not engine.is_active()


def test_jitter_validation(engine):
    engine.set_jitter(50, 50)
    assert (engine._jitter_pct, engine._jitter_px) == (50, 50)
    with pytest.raises(ValueError):
        engine.set_jitter(51, 0)
    with pytest.raises(ValueError):
        engine.set_jitter(0, -1)


def test_jitter_offset_stays_in_radius():
    import random

    from autoclick_pro.click_engine import jitter_offset

    rng = random.Random(7)
    points = [jitter_offset(rng, 10) for _ in range(500)]
    assert all(dx * dx + dy * dy <= 10**2 for dx, dy in points)
    assert len(set(points)) > 50
    assert jitter_offset(rng, 0) == (0, 0)


@pytest.mark.parametrize(
    ("x", "y", "corners", "expected"),
    [
        (0, 0, [(0, 0)], True),
        (3, 3, [(0, 0)], True),
        (4, 0, [(0, 0)], False),
        (0, 4, [(0, 0)], False),
        (500, 500, [(0, 0)], False),
        # Primary-only corner: other monitors never trigger it.
        (-1920, 0, [(0, 0)], False),
        (-5, 2, [(0, 0)], False),
        # Monitor left of the primary owns the desktop corner instead.
        (-1920, 0, [(-1920, 0)], True),
        (-1917, 3, [(-1920, 0)], True),
        (0, 0, [(-1920, 0)], False),
        # Two independent corners (staggered monitors).
        (-1920, 200, [(-1920, 200), (0, 0)], True),
        (1, 1, [(-1920, 200), (0, 0)], True),
    ],
)
def test_failsafe_corner(x, y, corners, expected):
    from autoclick_pro.click_engine import in_failsafe_corner

    assert in_failsafe_corner(x, y, corners) is expected
