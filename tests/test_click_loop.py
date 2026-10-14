import time

SIGNAL_TIMEOUT_MS = 5000


def _start(engine, *, interval=10, max_clicks=None, max_seconds=None, double=False):
    engine.set_double_click(double)
    engine.set_limits(max_clicks=max_clicks, max_seconds=max_seconds)
    engine.set_interval_ms(interval)
    engine.start_clicking()


def test_exact_target_single(engine, mouse, qtbot):
    with qtbot.waitSignal(engine.limit_reached, timeout=SIGNAL_TIMEOUT_MS) as blocker:
        _start(engine, max_clicks=5)
    assert mouse.presses == 5
    assert "5" in blocker.args[0]
    assert not engine.is_active()


def test_exact_target_double_no_overshoot(engine, mouse, qtbot):
    with qtbot.waitSignal(engine.limit_reached, timeout=SIGNAL_TIMEOUT_MS) as blocker:
        _start(engine, max_clicks=5, double=True)
    assert mouse.presses == 5
    assert "5" in blocker.args[0]


def test_failsafe_corner_stops_without_error(engine, mouse, qtbot):
    mouse.position = (0, 0)
    errors = []
    engine.error_occurred.connect(errors.append)
    engine.set_failsafe(True)
    with qtbot.waitSignal(engine.failsafe_triggered, timeout=SIGNAL_TIMEOUT_MS) as blocker:
        _start(engine)
    assert mouse.presses == 0
    assert "Failsafe" in blocker.args[0]
    assert errors == []


def test_failsafe_ignores_negative_coordinates(engine, mouse, qtbot):
    mouse.position = (-1500, -200)  # A monitor above-left of the primary one.
    engine.set_failsafe(True)
    with qtbot.waitSignal(engine.limit_reached, timeout=SIGNAL_TIMEOUT_MS):
        _start(engine, max_clicks=3)
    assert mouse.presses == 3


def test_fixed_mode_without_position_reports_error(engine, mouse, qtbot):
    engine.set_position("fixed")
    with qtbot.waitSignal(engine.error_occurred, timeout=SIGNAL_TIMEOUT_MS) as blocker:
        _start(engine)
    assert "Capture" in blocker.args[0]
    assert mouse.presses == 0


def test_fixed_mode_moves_to_position(engine, mouse, qtbot):
    engine.set_position("fixed", 40, 60)
    with qtbot.waitSignal(engine.limit_reached, timeout=SIGNAL_TIMEOUT_MS):
        _start(engine, max_clicks=2)
    assert mouse.mice[0].moves == [(40, 60), (40, 60)]


def test_emergency_stop_halts_loop(engine, mouse, qtbot):
    _start(engine)
    qtbot.waitUntil(lambda: mouse.presses >= 1, timeout=SIGNAL_TIMEOUT_MS)
    engine.emergency_stop()
    stopped_at = mouse.presses
    time.sleep(0.1)
    assert not engine.is_active()
    assert not engine.is_paused()
    assert mouse.presses == stopped_at
    assert engine.resume_clicking() is False


def test_pause_resume_keeps_count_and_target(engine, mouse, qtbot):
    counts = []
    engine.click_count_changed.connect(counts.append)
    _start(engine, max_clicks=20)
    qtbot.waitUntil(lambda: mouse.presses >= 5, timeout=SIGNAL_TIMEOUT_MS)
    engine.pause_clicking()
    assert engine.is_paused()
    paused_at = mouse.presses
    time.sleep(0.1)
    assert mouse.presses == paused_at

    with qtbot.waitSignal(engine.limit_reached, timeout=SIGNAL_TIMEOUT_MS) as blocker:
        assert engine.resume_clicking() is True
    assert mouse.presses == 20
    assert "20" in blocker.args[0]
    qtbot.waitUntil(lambda: counts and counts[-1] == 20, timeout=SIGNAL_TIMEOUT_MS)
    # The counter is zeroed once at start and never again on resume.
    assert counts.count(0) == 1


def test_pause_freezes_duration_budget(engine, mouse, qtbot):
    _start(engine, max_seconds=0.4)
    time.sleep(0.15)
    engine.pause_clicking()
    time.sleep(0.5)  # Longer than the whole budget; must not count.
    resumed = time.monotonic()
    with qtbot.waitSignal(engine.limit_reached, timeout=SIGNAL_TIMEOUT_MS) as blocker:
        engine.resume_clicking()
    ran_after_resume = time.monotonic() - resumed
    assert "Duration" in blocker.args[0]
    assert 0.12 <= ran_after_resume <= 1.0


def test_duration_limit_does_not_wait_for_long_interval(engine, mouse, qtbot):
    started = time.monotonic()
    with qtbot.waitSignal(engine.limit_reached, timeout=SIGNAL_TIMEOUT_MS):
        _start(engine, interval=60_000, max_seconds=0.2)
    assert time.monotonic() - started < 1.5
    assert mouse.presses == 1


def test_fixed_rate_schedule_absorbs_click_cost(engine, mouse, qtbot):
    # Each click takes 10 ms. A 20 ms schedule anchored to the previous due
    # time keeps a 20 ms cadence; the old "wait after click" loop took 30 ms.
    mouse.click_delay = 0.010
    started = time.monotonic()
    with qtbot.waitSignal(engine.limit_reached, timeout=SIGNAL_TIMEOUT_MS):
        _start(engine, interval=20, max_clicks=20)
    elapsed = time.monotonic() - started
    assert elapsed < 0.5, f"20 clicks at 20 ms took {elapsed:.3f}s"


def test_interval_change_applies_while_running(engine, mouse, qtbot):
    _start(engine, interval=60_000)
    qtbot.waitUntil(lambda: mouse.presses == 1, timeout=SIGNAL_TIMEOUT_MS)
    engine.set_interval_ms(10)
    qtbot.waitUntil(lambda: mouse.presses >= 5, timeout=SIGNAL_TIMEOUT_MS)
    engine.emergency_stop()
