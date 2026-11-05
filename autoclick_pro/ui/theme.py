"""Dark/light/system themes: palette, stylesheet and accent label styles."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

STATUS_COLORS = {
    "idle": ("rgba(139,147,163,0.12)", "#a8b0bd"),
    "run": ("rgba(63,185,80,0.12)", "#57ab5f"),
    "pause": ("rgba(210,153,34,0.12)", "#c79a3a"),
    "stop": ("rgba(248,81,73,0.12)", "#e05a52"),
    "done": ("rgba(88,140,255,0.12)", "#7aa5f0"),
    "error": ("rgba(248,81,73,0.12)", "#e05a52"),
}

_DARK_QSS = """
QGroupBox {
    background: #1e2129;
    border: 1px solid #2c313c;
    border-radius: 4px;
    margin-top: 12px;
    padding: 12px 12px 10px 12px;
    font-size: 13px;
    font-weight: 600;
    color: #c8cdd6;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 4px;
}
QSpinBox, QDoubleSpinBox, QComboBox {
    background: #15171d;
    border: 1px solid #333947;
    border-radius: 4px;
    padding: 5px 8px;
    color: #dce1ea;
    selection-background-color: #2563c9;
    min-height: 22px;
}
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border: 1px solid #2563c9;
}
QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {
    color: #6a7180;
}
QComboBox QAbstractItemView {
    background: #15171d;
    color: #dce1ea;
    selection-background-color: #2563c9;
    border: 1px solid #333947;
}
QCheckBox {
    color: #dce1ea;
    spacing: 8px;
    font-size: 13px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #4a5162;
    background: #15171d;
}
QCheckBox::indicator:checked {
    background: #2563c9;
    border: 1px solid #2563c9;
}
QCheckBox::indicator:disabled {
    background: #1a1d24;
    border: 1px solid #262b36;
}
QSlider::groove:horizontal {
    height: 4px;
    background: #333947;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: #2563c9;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    width: 14px;
    height: 14px;
    background: #dce1ea;
    border-radius: 7px;
    margin: -5px 0;
}
QSlider::handle:horizontal:hover {
    background: #ffffff;
}
QPushButton#primary {
    background: #2563c9;
    color: white;
    font-size: 14px;
    font-weight: 600;
    border: 1px solid #2563c9;
    border-radius: 4px;
    padding: 10px 14px;
}
QPushButton#primary:hover {
    background: #1d4fa3;
}
QPushButton#primary:disabled {
    background: #2c313c;
    color: #6a7180;
    border-color: #2c313c;
}
QPushButton#danger {
    background: #b02a25;
    color: white;
    font-size: 13px;
    font-weight: 600;
    border: 1px solid #b02a25;
    border-radius: 4px;
    padding: 10px 14px;
}
QPushButton#danger:hover {
    background: #8f221e;
}
QPushButton#ghost {
    background: #15171d;
    color: #dce1ea;
    border: 1px solid #333947;
    border-radius: 4px;
    padding: 7px 12px;
}
QPushButton#ghost:hover {
    border: 1px solid #4a5162;
    color: #ffffff;
}
QPushButton#modifier {
    background: #15171d;
    color: #6a7180;
    border: 1px solid #333947;
    border-radius: 4px;
    padding: 5px 8px;
    min-width: 34px;
}
QPushButton#modifier:checked {
    background: #2563c9;
    color: white;
    border: 1px solid #2563c9;
}
QPushButton#modifier:hover {
    border: 1px solid #4a5162;
}
QPushButton#primary:focus, QPushButton#danger:focus, QPushButton#ghost:focus, QPushButton#modifier:focus {
    border: 1px solid #dce1ea;
}
QMenu {
    background: #1e2129;
    color: #dce1ea;
    border: 1px solid #2c313c;
}
QMenu::item {
    padding: 5px 12px;
}
QMenu::item:selected {
    background: #2563c9;
}
QProgressBar {
    background: #15171d;
    border: 1px solid #333947;
    border-radius: 2px;
    max-height: 10px;
}
QProgressBar::chunk {
    background: #2563c9;
    border-radius: 2px;
}
QScrollArea {
    background: transparent;
}
QScrollBar:vertical {
    background: transparent;
    width: 12px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #333947;
    min-height: 40px;
}
QScrollBar::handle:vertical:hover {
    background: #4a5162;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
"""

_LIGHT_SWAP = {
    "#1e2129": "#ffffff",
    "#2c313c": "#d5dae2",
    "#15171d": "#f5f6f9",
    "#333947": "#c2c9d4",
    "#4a5162": "#9aa3b0",
    "#1a1d24": "#e9ebf0",
    "#262b36": "#d5dae2",
    "#dce1ea": "#1a1a1a",
    "#c8cdd6": "#3c4350",
    "#6a7180": "#9aa0a6",
}

_LIGHT_QSS = _DARK_QSS
for _dark_hex, _light_hex in _LIGHT_SWAP.items():
    _LIGHT_QSS = _LIGHT_QSS.replace(_dark_hex, _light_hex)

_DEFAULT_STYLE: str | None = None
_DEFAULT_PALETTE: QPalette | None = None


def _palette(ink: str, faint: str, window: str, base: str, alt: str, button: str) -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(window))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(ink))
    palette.setColor(QPalette.ColorRole.Base, QColor(base))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(alt))
    palette.setColor(QPalette.ColorRole.Text, QColor(ink))
    palette.setColor(QPalette.ColorRole.Button, QColor(button))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(ink))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#2f81f7"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Link, QColor("#58a6ff"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(button))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(ink))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(faint))
    disabled = QPalette.ColorGroup.Disabled
    palette.setColor(disabled, QPalette.ColorRole.WindowText, QColor(faint))
    palette.setColor(disabled, QPalette.ColorRole.Text, QColor(faint))
    palette.setColor(disabled, QPalette.ColorRole.ButtonText, QColor(faint))
    return palette


_APPLIED: tuple[int, str] | None = None
_QSS = {"light": _LIGHT_QSS, "system": "", "dark": _DARK_QSS}


def set_app_theme(app: QApplication, mode: str) -> str:
    """Apply a theme to the application and return the window stylesheet.

    Re-applying the current theme is skipped: changing the app style
    re-polishes every widget, which is slow.
    """
    global _DEFAULT_STYLE, _DEFAULT_PALETTE, _APPLIED
    if mode not in _QSS:
        mode = "dark"
    if (id(app), mode) == _APPLIED:
        return _QSS[mode]
    _APPLIED = (id(app), mode)
    if _DEFAULT_STYLE is None:
        _DEFAULT_STYLE = app.style().objectName()
        _DEFAULT_PALETTE = QPalette(app.palette())
    if mode == "light":
        app.setStyle("Fusion")
        app.setPalette(
            _palette("#1a1a1a", "#9aa0a6", "#f0f0f0", "#ffffff", "#f5f5f5", "#f0f0f0")
        )
        return _LIGHT_QSS
    if mode == "system":
        app.setStyle(_DEFAULT_STYLE)
        if _DEFAULT_PALETTE is not None:
            app.setPalette(_DEFAULT_PALETTE)
        return ""
    app.setStyle("Fusion")
    app.setPalette(
        _palette("#e8ebf0", "#5b6270", "#121418", "#1a1d23", "#20242c", "#23262e")
    )
    return _DARK_QSS


def label_styles(mode: str) -> dict[str, str]:
    """Inline styles for header, counter and accent labels in each theme."""
    ink = "#f2f4f8" if mode == "dark" else "#14161b" if mode == "light" else ""
    blue = "#dce1ea" if mode == "dark" else "#0b3d91" if mode == "light" else ""
    muted = "#8b93a3" if mode == "dark" else "#5b6270" if mode == "light" else ""
    coord = "#6ea8fe" if mode == "dark" else "#0b3d91" if mode == "light" else ""
    hero_bg = (
        "background: #1e2129; border: 1px solid #2c313c;"
        if mode == "dark"
        else "background: #ffffff; border: 1px solid #d5dae2;"
    )
    ink_css = f" color: {ink};" if ink else ""
    muted_css = f" color: {muted};" if muted else ""
    return {
        "heading": f"font-size: 22px; font-weight: 700;{ink_css}",
        "count": f"font-size: 30px; font-weight: 700;{ink_css}",
        "subtitle": f"font-size: 13px;{muted_css}",
        "stats": f"font-size: 12px; font-weight: 600;{muted_css}",
        "note": f"font-size: 12px;{muted_css}",
        "position": "font-size: 13px; font-weight: 600;" + (f" color: {coord};" if coord else ""),
        "version": "font-size: 12px; font-weight: 700; border-radius: 10px; padding: 5px 12px;"
        + (f" background: rgba(47,129,247,0.16); color: {blue};" if blue else ""),
        "hero": f"QGroupBox {{ border: 0; margin-top: 0; {hero_bg}}}",
    }


def status_style(kind: str) -> str:
    bg, fg = STATUS_COLORS.get(kind, STATUS_COLORS["idle"])
    return (
        f"background: {bg}; color: {fg}; font-size: 13px; "
        "font-weight: 700; border-radius: 10px; padding: 8px 12px;"
    )
