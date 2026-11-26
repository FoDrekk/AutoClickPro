import re

from autoclick_pro.ui.theme import (
    _DARK_QSS,
    _LIGHT_QSS,
    STATUS_COLORS,
    set_app_theme,
    status_style,
)


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


def _contrast(a, b):
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _pill_background(rgba, base):
    """Composite the pill's translucent tint over the group box it sits on."""
    r, g, b, a = map(float, re.fullmatch(r"rgba\((\d+),(\d+),(\d+),([\d.]+)\)", rgba).groups())
    over = tuple(int(base[i:i + 2], 16) for i in (1, 3, 5))
    mixed = (round(c * a + d * (1 - a)) for c, d in zip((r, g, b), over, strict=True))
    return "#" + "".join(f"{channel:02x}" for channel in mixed)


def test_every_status_text_meets_contrast_in_both_themes():
    dark_base = re.search(r"QGroupBox \{\s*background: (#[0-9a-f]+)", _DARK_QSS).group(1)
    light_base = re.search(r"QGroupBox \{\s*background: (#[0-9a-f]+)", _LIGHT_QSS).group(1)
    for kind in STATUS_COLORS:
        dark_fg = re.search(r"color: (#[0-9a-f]+)", status_style(kind, "dark")).group(1)
        light_fg = re.search(r"color: (#[0-9a-f]+)", status_style(kind, "light")).group(1)
        assert _contrast(dark_fg, _pill_background(STATUS_COLORS[kind][0], dark_base)) >= 4.5, kind
        assert _contrast(light_fg, light_base) >= 4.5, kind


def test_recording_is_not_shown_in_the_error_colour():
    """Red means something went wrong; recording is an intended state."""
    for mode in ("dark", "light"):
        record = re.search(r"color: (#[0-9a-f]+)", status_style("record", mode)).group(1)
        assert record != re.search(r"color: (#[0-9a-f]+)", status_style("error", mode)).group(1)
        assert record != re.search(r"color: (#[0-9a-f]+)", status_style("stop", mode)).group(1)


def test_light_status_text_meets_contrast():
    foreground = re.search(r"color: (#[0-9a-f]+)", status_style("run", "light")).group(1)
    assert (_luminance("#ffffff") + 0.05) / (_luminance(foreground) + 0.05) >= 4.5


def test_system_theme_keeps_native_stylesheet(qapp):
    assert set_app_theme(qapp, "system") == ""
