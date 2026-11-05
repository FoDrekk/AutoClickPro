import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest


class FakeMouse:
    """Records what the engine sends instead of touching real input."""

    def __init__(self, factory):
        self._factory = factory
        self.presses = 0
        self.moves = []
        self.click_times = []
        self.events = []  # (kind, *details) in the order the engine sent them.
        self._position = factory.position
        self._click_delay = factory.click_delay

    @property
    def position(self):
        return self._position

    @position.setter
    def position(self, value):
        self._position = (int(value[0]), int(value[1]))
        self.moves.append(self._position)
        self.events.append(("move", *self._position))

    def click(self, button, count=1):
        if self._click_delay:
            time.sleep(self._click_delay)
        self.presses += count
        self.click_times.append(time.perf_counter())
        self.events.append(("click", button, count))

    def press(self, button, down):
        self.events.append(("down" if down else "up", button))

    def key(self, vk, down, extended=False):
        self.events.append(("key_down" if down else "key_up", vk))

    def pixel(self, x, y):
        return self._factory.pixel_at(x, y)

    def post_click(self, hwnd, x, y, button, count=1):
        self.presses += count
        self.events.append(("post", hwnd, x, y, button, count))


class MouseFactory:
    """Stands in for ``click_engine.create_backend`` and records every backend."""

    def __init__(self):
        self.mice: list[FakeMouse] = []
        self.position = (500, 500)
        self.click_delay = 0.0
        self.colors: dict[tuple[int, int], tuple[int, int, int]] = {}

    def pixel_at(self, x, y):
        return self.colors.get((x, y), (0, 0, 0))

    def __call__(self):
        mouse = FakeMouse(self)
        self.mice.append(mouse)
        return mouse

    @property
    def presses(self):
        return sum(m.presses for m in self.mice)

    @property
    def events(self):
        return [event for m in self.mice for event in m.events]


@pytest.fixture
def corners():
    """Failsafe corners the engine sees; tests may replace the contents."""
    return [(0, 0)]


@pytest.fixture
def mouse(monkeypatch, corners):
    import autoclick_pro.click_engine as engine_mod

    factory = MouseFactory()
    monkeypatch.setattr(engine_mod, "create_backend", factory)
    monkeypatch.setattr(engine_mod, "current_failsafe_corners", lambda: list(corners))
    return factory


@pytest.fixture
def engine(qapp, mouse):
    from autoclick_pro.click_engine import ClickEngine

    e = ClickEngine()
    yield e
    e.shutdown()


@contextmanager
def _wait_thread_signal(qtbot, signal, timeout=5000):
    """Like qtbot.waitSignal, but safe for signals emitted on worker threads.

    pytest-qt's blocker is a plain Python object, so a signal emitted on a
    worker thread calls it directly on that thread, racing its cleanup on the
    main thread (seen as a rare crash). Here the worker thread only appends
    to a list; waiting happens on the main thread.
    """
    received = []

    def record(*args):
        received.append(args)

    signal.connect(record)
    result = SimpleNamespace(args=None)
    try:
        yield result
        qtbot.waitUntil(lambda: bool(received), timeout=timeout)
        result.args = list(received[0])
    finally:
        signal.disconnect(record)


@pytest.fixture(autouse=True)
def _thread_signal_helper(request):
    if "qtbot" in request.fixturenames:
        qtbot = request.getfixturevalue("qtbot")
        qtbot.wait_thread_signal = lambda signal, timeout=5000: _wait_thread_signal(qtbot, signal, timeout)
