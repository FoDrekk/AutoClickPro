import re

from autoclick_pro.ui.theme import _DARK_QSS, _LIGHT_QSS, set_app_theme, status_style


def test_refined_themes_style_tabs_focus_and_disabled_controls(qapp):
    for stylesheet in (_DARK_QSS, _LIGHT_QSS):
        assert "QTabBar::tab:selected" in stylesheet
        assert "QTabWidget::pane" in stylesheet
        assert "QPushButton:focus" in stylesheet
        assert "outline" not in stylesheet  # Qt QSS uses a two-pixel focus border.
        assert "QSpinBox:disabled" in stylesheet
        assert "border-radius: 8px" in stylesheet
    assert _DARK_QSS != _LIGHT_QSS


def _luminance(value):
    rgb = [int(value[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb]
    return sum(v * weight for v, weight in zip(linear, (0.2126, 0.7152, 0.0722), strict=True))


def test_light_status_text_meets_contrast():
    foreground = re.search(r"color: (#[0-9a-f]+)", status_style("run", "light")).group(1)
    assert (_luminance("#ffffff") + 0.05) / (_luminance(foreground) + 0.05) >= 4.5


def test_system_theme_keeps_native_stylesheet(qapp):
    assert set_app_theme(qapp, "system") == ""
