import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def app():
    return QApplication([])


@pytest.fixture
def engine(app):
    from autoclick_pro.click_engine import ClickEngine

    e = ClickEngine()
    yield e
    e.shutdown()


def test_interval_accepts_valid(engine):
    assert engine.set_interval_ms(100) is True
    assert engine.set_interval_ms("250") is True


def test_interval_rejects_small_and_bad(engine):
    assert engine.set_interval_ms(9) is False
    assert engine.set_interval_ms(0) is False
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


def test_reset_count_emits_zero(engine):
    seen: list[int] = []
    engine.click_count_changed.connect(seen.append)
    engine.reset_count()
    assert seen == [0]


def test_hotkey_names_cover_f1_to_f12():
    from autoclick_pro.global_hotkeys import KEY_NAMES, key_from_name
    from pynput import keyboard

    assert KEY_NAMES == [f"f{i}" for i in range(1, 13)]
    assert key_from_name("f6") == keyboard.Key.f6
    with pytest.raises(ValueError):
        key_from_name("bogus")


def test_hotkey_conflict_guard(app):
    from autoclick_pro.global_hotkeys import GlobalHotkeys

    h = GlobalHotkeys()
    h.set_keys("f7", "f9")
    with pytest.raises(ValueError):
        h.set_keys("f7", "f7")
    h.stop()
