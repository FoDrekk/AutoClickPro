"""Hotkey picker: modifier toggles plus a key list.

Capturing keystrokes directly would not work for keys that are already
registered as global hotkeys, since Windows swallows those before the
widget sees them.
"""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QPushButton, QWidget

from autoclick_pro.global_hotkeys import KEY_NAMES, MODIFIER_ORDER, Hotkey, parse_hotkey


class HotkeyEdit(QWidget):
    changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._modifier_buttons: dict[str, QPushButton] = {}
        for name in MODIFIER_ORDER:
            button = QPushButton(name.capitalize())
            button.setObjectName("modifier")
            button.setCheckable(True)
            button.setToolTip(f"Hold {name.capitalize()} as part of the hotkey.")
            button.toggled.connect(self._emit_changed)
            layout.addWidget(button)
            self._modifier_buttons[name] = button
        self._key_combo = QComboBox()
        for name in KEY_NAMES:
            self._key_combo.addItem(Hotkey(name).label, name)
        self._key_combo.currentIndexChanged.connect(self._emit_changed)
        layout.addWidget(self._key_combo, 1)

    def hotkey(self) -> str:
        """Current selection as "ctrl+alt+f6" text. It may not be a valid hotkey."""
        parts = [name for name in MODIFIER_ORDER if self._modifier_buttons[name].isChecked()]
        return "+".join([*parts, str(self._key_combo.currentData())])

    def set_hotkey(self, text: str) -> None:
        hotkey = parse_hotkey(text)
        blockers = [QSignalBlocker(self._key_combo)] + [
            QSignalBlocker(button) for button in self._modifier_buttons.values()
        ]
        self._key_combo.setCurrentIndex(self._key_combo.findData(hotkey.key))
        for name, button in self._modifier_buttons.items():
            button.setChecked(name in hotkey.modifiers)
        del blockers

    def _emit_changed(self, *_args) -> None:
        self.changed.emit(self.hotkey())
