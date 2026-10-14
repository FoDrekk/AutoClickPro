"""System tray icon and its context menu."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

_MESSAGE_ICONS = {
    "info": QSystemTrayIcon.MessageIcon.Information,
    "warning": QSystemTrayIcon.MessageIcon.Warning,
    "critical": QSystemTrayIcon.MessageIcon.Critical,
}


class TrayIcon(QObject):
    show_toggle_requested = Signal()
    toggle_click_requested = Signal()
    emergency_stop_requested = Signal()
    quit_requested = Signal()

    def __init__(self, icon: QIcon, parent: QWidget) -> None:
        super().__init__(parent)
        self._tray = QSystemTrayIcon(icon, parent)
        self._tray.setToolTip("AutoClick Pro")
        menu = QMenu(parent)
        self._show_action = menu.addAction("Hide", self.show_toggle_requested.emit)
        self._toggle_action = menu.addAction("Start/Pause", self.toggle_click_requested.emit)
        self._stop_action = menu.addAction("Emergency Stop", self.emergency_stop_requested.emit)
        menu.addSeparator()
        menu.addAction("Quit", self.quit_requested.emit)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_activated)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._tray.show()

    def is_visible(self) -> bool:
        return self._tray.isVisible()

    def hide(self) -> None:
        self._tray.hide()

    def set_window_shown(self, shown: bool) -> None:
        self._show_action.setText("Hide" if shown else "Show")

    def set_hotkey_labels(self, toggle: str, stop: str) -> None:
        self._toggle_action.setText(f"Start/Pause ({toggle.upper()})")
        self._stop_action.setText(f"Emergency Stop ({stop.upper()})")

    def notify(self, text: str, level: str = "info", msecs: int = 2000) -> None:
        if self._tray.isVisible():
            self._tray.showMessage(
                "AutoClick Pro",
                text,
                _MESSAGE_ICONS.get(level, QSystemTrayIcon.MessageIcon.Information),
                msecs,
            )

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_toggle_requested.emit()
