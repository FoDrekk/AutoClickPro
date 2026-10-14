import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


class FakeMouse:
    def __init__(self):
        self.presses = 0
        self.moves = []
        self._position = (500, 500)

    @property
    def position(self):
        return self._position

    @position.setter
    def position(self, value):
        self._position = (int(value[0]), int(value[1]))
        self.moves.append(self._position)

    def click(self, button, count=1):
        self.presses += count


@pytest.fixture(scope="session")
def loop_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def engine(loop_app, monkeypatch):
    import autoclick_pro.click_engine as mod

    monkeypatch.setattr(mod, "Controller", FakeMouse)
    e = mod.ClickEngine()
    yield e
    e.shutdown()


def _run_until_idle(engine, timeout=10.0):
    deadline = time.monotonic() + timeout
    while engine.is_active() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)
    QApplication.processEvents()
    assert not engine.is_active(), "engine did not stop in time"


def test_exact_target_single(engine, monkeypatch):
    import autoclick_pro.click_engine as mod

    fakes = []
    monkeypatch.setattr(mod, "Controller", lambda: fakes.append(FakeMouse()) or fakes[-1])
    limits = []
    engine.limit_reached.connect(limits.append, Qt.ConnectionType.DirectConnection)
    engine.set_double_click(False)
    engine.set_limits(max_clicks=5)
    engine.set_interval_ms(10)
    engine.reset_count()
    engine.start_clicking()
    _run_until_idle(engine)
    assert fakes and fakes[0].presses == 5
    assert limits and "5" in limits[0]


def test_exact_target_double_no_overshoot(engine, monkeypatch):
    import autoclick_pro.click_engine as mod

    fakes = []
    monkeypatch.setattr(mod, "Controller", lambda: fakes.append(FakeMouse()) or fakes[-1])
    limits = []
    engine.limit_reached.connect(limits.append, Qt.ConnectionType.DirectConnection)
    engine.set_double_click(True)
    engine.set_limits(max_clicks=5)
    engine.set_interval_ms(10)
    engine.reset_count()
    engine.start_clicking()
    _run_until_idle(engine)
    assert fakes and fakes[0].presses == 5
    assert limits and "5" in limits[0]
    engine.set_double_click(False)


def test_failsafe_corner_stops(engine, monkeypatch):
    import autoclick_pro.click_engine as mod

    holder = {}
    Fake = FakeMouse

    class CornerMouse(Fake):
        def __init__(self):
            super().__init__()
            self._position = (0, 0)
            holder["m"] = self

    monkeypatch.setattr(mod, "Controller", CornerMouse)
    errors = []
    engine.error_occurred.connect(errors.append, Qt.ConnectionType.DirectConnection)
    engine.set_failsafe(True)
    engine.set_limits()
    engine.set_interval_ms(10)
    engine.reset_count()
    engine.start_clicking()
    _run_until_idle(engine)
    assert holder["m"].presses == 0
    assert errors and "Failsafe" in errors[0]
    engine.set_failsafe(False)


def test_emergency_stop_halts_loop(engine, monkeypatch):
    import autoclick_pro.click_engine as mod

    fakes = []
    monkeypatch.setattr(mod, "Controller", lambda: fakes.append(FakeMouse()) or fakes[-1])
    engine.set_limits()
    engine.set_interval_ms(10)
    engine.reset_count()
    engine.start_clicking()
    time.sleep(0.05)
    engine.emergency_stop()
    _run_until_idle(engine)
    assert fakes and fakes[0].presses >= 1


def test_pause_freezes_duration_budget(engine):
    import time as t

    engine.set_limits(max_seconds=60)
    engine._active = True
    engine._stop_time = t.monotonic() + 60
    engine.pause_clicking()
    assert engine._remaining is not None and 0 < engine._remaining <= 60
    engine.emergency_stop()
