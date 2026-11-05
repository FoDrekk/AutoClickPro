import time

from autoclick_pro.steps import Sequence, Step, Trigger

TIMEOUT_MS = 5000


def _play(engine, steps, loops=1, speed=1.0, **limits):
    engine.set_mode("sequence")
    engine.set_sequence(Sequence(tuple(steps), loops, speed))
    engine.set_limits(**limits)
    engine.start_clicking()


def test_steps_run_in_order(engine, mouse, qtbot):
    steps = [
        Step("move", 10, 20, delay=0),
        Step("click", 30, 40, button="right", delay=0),
        Step("key_down", vk=0x41, delay=0),
        Step("key_up", vk=0x41, delay=0),
        Step("down", 1, 1, delay=0),
        Step("up", 2, 2, delay=0),
    ]
    with qtbot.wait_thread_signal(engine.limit_reached, timeout=TIMEOUT_MS) as blocker:
        _play(engine, steps)
    assert "finished (1 loop)" in blocker.args[0]
    assert mouse.events == [
        ("move", 10, 20),
        ("move", 30, 40),
        ("click", "right", 1),
        ("key_down", 0x41),
        ("key_up", 0x41),
        ("move", 1, 1),
        ("down", "left"),
        ("move", 2, 2),
        ("up", "left"),
    ]


def test_repeat_and_loops(engine, mouse, qtbot):
    steps = [Step("click", repeat=3, delay=1), Step("click", button="right", delay=1)]
    with qtbot.wait_thread_signal(engine.limit_reached, timeout=TIMEOUT_MS) as blocker:
        _play(engine, steps, loops=2)
    clicks = [e[1] for e in mouse.events if e[0] == "click"]
    assert clicks == ["left", "left", "left", "right"] * 2
    assert "2 loops" in blocker.args[0]


def test_infinite_loops_until_stopped(engine, mouse, qtbot):
    _play(engine, [Step("click", delay=1)], loops=0)
    qtbot.waitUntil(lambda: mouse.presses >= 20, timeout=TIMEOUT_MS)
    engine.emergency_stop()


def test_max_clicks_applies_to_sequences(engine, mouse, qtbot):
    with qtbot.wait_thread_signal(engine.limit_reached, timeout=TIMEOUT_MS) as blocker:
        _play(engine, [Step("click", delay=1)], loops=0, max_clicks=7)
    assert mouse.presses == 7
    assert "7" in blocker.args[0]


def test_step_delays_and_speed(engine, mouse, qtbot):
    steps = [Step("click", delay=100), Step("click", delay=100), Step("click", delay=0)]
    started = time.monotonic()
    with qtbot.wait_thread_signal(engine.limit_reached, timeout=TIMEOUT_MS):
        _play(engine, steps, speed=2.0)
    elapsed = time.monotonic() - started
    # Two 100 ms delays at double speed.
    assert 0.09 <= elapsed <= 0.2, elapsed


def test_wait_color_blocks_until_match(engine, mouse, qtbot):
    steps = [Step("wait_color", 5, 5, color="#FF0000", delay=0), Step("click", delay=0)]
    _play(engine, steps)
    time.sleep(0.2)
    assert mouse.presses == 0
    assert engine.is_active()
    mouse.colors[(5, 5)] = (250, 5, 0)  # Close, but tolerance is 0.
    time.sleep(0.2)
    assert mouse.presses == 0
    with qtbot.wait_thread_signal(engine.limit_reached, timeout=TIMEOUT_MS):
        mouse.colors[(5, 5)] = (255, 0, 0)
    assert mouse.presses == 1


def test_wait_color_with_tolerance(engine, mouse, qtbot):
    mouse.colors[(5, 5)] = (250, 5, 0)
    steps = [Step("wait_color", 5, 5, color="#FF0000", tolerance=8, delay=0), Step("click", delay=0)]
    with qtbot.wait_thread_signal(engine.limit_reached, timeout=TIMEOUT_MS):
        _play(engine, steps)
    assert mouse.presses == 1


def test_wait_color_timeout_stops(engine, mouse, qtbot):
    steps = [Step("wait_color", 5, 5, color="#00FF00", timeout=150, delay=0), Step("click")]
    with qtbot.wait_thread_signal(engine.condition_stopped, timeout=TIMEOUT_MS) as blocker:
        _play(engine, steps)
    assert "did not appear" in blocker.args[0]
    assert mouse.presses == 0


def test_held_keys_released_on_stop(engine, mouse, qtbot):
    steps = [Step("key_down", vk=0x10, delay=0), Step("down", delay=0), Step("click", delay=10_000)]
    _play(engine, steps)
    qtbot.waitUntil(lambda: mouse.presses >= 1, timeout=TIMEOUT_MS)
    engine.emergency_stop()
    qtbot.waitUntil(lambda: ("key_up", 0x10) in mouse.events, timeout=TIMEOUT_MS)
    assert ("up", "left") in mouse.events


def test_held_keys_released_when_sequence_ends(engine, mouse, qtbot):
    with qtbot.wait_thread_signal(engine.limit_reached, timeout=TIMEOUT_MS):
        _play(engine, [Step("key_down", vk=0x11, delay=0)])
    assert mouse.events[-1] == ("key_up", 0x11)


def test_empty_sequence_reports_error(engine, mouse, qtbot):
    with qtbot.wait_thread_signal(engine.error_occurred, timeout=TIMEOUT_MS) as blocker:
        _play(engine, [])
    assert "no steps" in blocker.args[0]


def test_progress_signal(engine, mouse, qtbot):
    progress = []
    engine.progress_changed.connect(lambda i, n: progress.append((i, n)))
    with qtbot.wait_thread_signal(engine.limit_reached, timeout=TIMEOUT_MS):
        _play(engine, [Step("click", delay=0), Step("click", delay=0)], loops=2)
    qtbot.waitUntil(lambda: progress and progress[-1] == (0, 2), timeout=TIMEOUT_MS)


def test_pause_resume_continues_sequence(engine, mouse, qtbot):
    steps = [Step("click", delay=30), Step("click", button="right", delay=30)]
    _play(engine, steps, loops=3)
    qtbot.waitUntil(lambda: mouse.presses >= 3, timeout=TIMEOUT_MS)
    engine.pause_clicking()
    with qtbot.wait_thread_signal(engine.limit_reached, timeout=TIMEOUT_MS):
        engine.resume_clicking()
    clicks = [e[1] for e in mouse.events if e[0] == "click"]
    assert clicks == ["left", "right"] * 3


def test_trigger_wait_gates_simple_clicks(engine, mouse, qtbot):
    engine.set_trigger(Trigger("wait", 9, 9, "#FFFFFF", 0))
    engine.set_interval_ms(5)
    engine.start_clicking()
    time.sleep(0.15)
    assert mouse.presses == 0
    mouse.colors[(9, 9)] = (255, 255, 255)
    qtbot.waitUntil(lambda: mouse.presses >= 3, timeout=TIMEOUT_MS)
    mouse.colors[(9, 9)] = (0, 0, 0)
    time.sleep(0.1)
    stalled = mouse.presses
    time.sleep(0.15)
    assert mouse.presses == stalled
    assert engine.is_active()
    engine.emergency_stop()


def test_trigger_stop_ends_run(engine, mouse, qtbot):
    mouse.colors[(9, 9)] = (255, 255, 255)
    engine.set_trigger(Trigger("stop", 9, 9, "#FFFFFF", 0))
    engine.set_interval_ms(5)
    engine.start_clicking()
    qtbot.waitUntil(lambda: mouse.presses >= 3, timeout=TIMEOUT_MS)
    with qtbot.wait_thread_signal(engine.condition_stopped, timeout=TIMEOUT_MS) as blocker:
        mouse.colors[(9, 9)] = (1, 2, 3)
    assert "changed" in blocker.args[0]


def test_background_clicks_use_window_messages(engine, mouse, qtbot):
    engine.set_position("fixed", 100, 200)
    engine.set_background_target(0xBEEF)
    engine.set_double_click(True)
    engine.set_limits(max_clicks=4)
    with qtbot.wait_thread_signal(engine.limit_reached, timeout=TIMEOUT_MS):
        engine.start_clicking()
    assert mouse.events == [("post", 0xBEEF, 100, 200, "left", 2)] * 2
    assert mouse.mice[0].moves == []  # The cursor never moved.
