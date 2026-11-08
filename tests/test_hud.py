from autoclick_pro.ui.hud import StatusHud


def test_hud_excludes_native_window_from_capture(monkeypatch, qtbot):
    excluded = []
    monkeypatch.setattr("autoclick_pro.ui.hud.exclude_from_capture", excluded.append)

    hud = StatusHud()
    qtbot.addWidget(hud)
    hud.show()

    assert excluded == [int(hud.winId())]
