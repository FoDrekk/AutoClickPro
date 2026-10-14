import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time

import pytest


class FakeMouse:
    def __init__(self, position=(500, 500), click_delay=0.0):
        self.presses = 0
        self.moves = []
        self._position = position
        self._click_delay = click_delay

    @property
    def position(self):
        return self._position

    @position.setter
    def position(self, value):
        self._position = (int(value[0]), int(value[1]))
        self.moves.append(self._position)

    def click(self, button, count=1):
        if self._click_delay:
            time.sleep(self._click_delay)
        self.presses += count


class MouseFactory:
    """Stands in for pynput's Controller class and records every instance."""

    def __init__(self):
        self.mice: list[FakeMouse] = []
        self.position = (500, 500)
        self.click_delay = 0.0

    def __call__(self):
        mouse = FakeMouse(self.position, self.click_delay)
        self.mice.append(mouse)
        return mouse

    @property
    def presses(self):
        return sum(m.presses for m in self.mice)


@pytest.fixture
def mouse(monkeypatch):
    import autoclick_pro.click_engine as engine_mod

    factory = MouseFactory()
    monkeypatch.setattr(engine_mod, "Controller", factory)
    return factory


@pytest.fixture
def engine(qapp, mouse):
    from autoclick_pro.click_engine import ClickEngine

    e = ClickEngine()
    yield e
    e.shutdown()
