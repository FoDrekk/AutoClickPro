"""Sequence tab: step table with drag-to-reorder, step dialog and toolbar."""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Sequence as SequenceABC
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QByteArray,
    QMimeData,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from autoclick_pro.steps import (
    MAX_DELAY_MS,
    MAX_LOOPS,
    MAX_REPEAT,
    Sequence,
    Step,
    describe,
    format_color,
)
from autoclick_pro.ui.picker import Pick

_MIME = "application/x-autoclick-step-rows"
SPEEDS = (0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0)

_Index = QModelIndex | QPersistentModelIndex
_ROOT = QModelIndex()


class StepTableModel(QAbstractTableModel):
    COLUMNS = ("#", "Action", "Delay after (ms)", "Repeat")
    DELAY_COLUMN = 2
    REPEAT_COLUMN = 3

    steps_changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._steps: list[Step] = []
        self._current: int | None = None

    # ------------------------------------------------------------ queries

    def steps(self) -> list[Step]:
        return list(self._steps)

    def step(self, row: int) -> Step:
        return self._steps[row]

    def rowCount(self, parent: _Index = _ROOT) -> int:
        return 0 if parent.isValid() else len(self._steps)

    def columnCount(self, parent: _Index = _ROOT) -> int:
        return 0 if parent.isValid() else len(self.COLUMNS)

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.COLUMNS[section]
        return None

    def data(self, index: _Index, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        step = self._steps[index.row()]
        column = index.column()
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if column == 0:
                return index.row() + 1
            if column == 1:
                return describe(step)
            if column == self.DELAY_COLUMN:
                return step.delay
            if column == self.REPEAT_COLUMN:
                return (
                    step.repeat
                    if step.type == "click"
                    else ("" if role == Qt.ItemDataRole.DisplayRole else 1)
                )
        if role == Qt.ItemDataRole.BackgroundRole and index.row() == self._current:
            return QColor(37, 99, 201, 90)
        if role == Qt.ItemDataRole.DecorationRole and column == 1 and step.type == "wait_color":
            return QColor(step.color)
        return None

    def flags(self, index: _Index) -> Qt.ItemFlag:
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if not index.isValid():
            return base | Qt.ItemFlag.ItemIsDropEnabled
        flags = base | Qt.ItemFlag.ItemIsDragEnabled
        step = self._steps[index.row()]
        if index.column() == self.DELAY_COLUMN or (
            index.column() == self.REPEAT_COLUMN and step.type == "click"
        ):
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    # ------------------------------------------------------------ editing

    def setData(self, index: _Index, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if role != Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        try:
            number = int(value)
        except (TypeError, ValueError):
            return False
        step = self._steps[index.row()]
        if index.column() == self.DELAY_COLUMN:
            changed = step.with_changes(delay=max(0, min(MAX_DELAY_MS, number)))
        elif index.column() == self.REPEAT_COLUMN and step.type == "click":
            changed = step.with_changes(repeat=max(1, min(MAX_REPEAT, number)))
        else:
            return False
        self.replace(index.row(), changed)
        return True

    def set_steps(self, steps: SequenceABC[Step]) -> None:
        self.beginResetModel()
        self._steps = list(steps)
        self._current = None
        self.endResetModel()
        self.steps_changed.emit()

    def insert(self, row: int, steps: SequenceABC[Step]) -> None:
        if not steps:
            return
        row = max(0, min(row, len(self._steps)))
        self.beginInsertRows(QModelIndex(), row, row + len(steps) - 1)
        self._steps[row:row] = list(steps)
        self.endInsertRows()
        self.steps_changed.emit()

    def replace(self, row: int, step: Step) -> None:
        self._steps[row] = step
        self.dataChanged.emit(self.index(row, 0), self.index(row, self.columnCount() - 1))
        self.steps_changed.emit()

    def remove(self, rows: SequenceABC[int]) -> None:
        for row in sorted(set(rows), reverse=True):
            if 0 <= row < len(self._steps):
                self.beginRemoveRows(QModelIndex(), row, row)
                del self._steps[row]
                self.endRemoveRows()
        self.steps_changed.emit()

    def move(self, rows: SequenceABC[int], target: int) -> list[int]:
        """Move ``rows`` so they start at ``target`` (index before removal). Returns new rows."""
        picked = sorted({r for r in rows if 0 <= r < len(self._steps)})
        if not picked:
            return []
        moving = [self._steps[r] for r in picked]
        target -= sum(1 for r in picked if r < target)
        remaining = [s for i, s in enumerate(self._steps) if i not in set(picked)]
        target = max(0, min(target, len(remaining)))
        self.beginResetModel()
        self._steps = remaining[:target] + moving + remaining[target:]
        self._current = None
        self.endResetModel()
        self.steps_changed.emit()
        return list(range(target, target + len(moving)))

    def set_current(self, row: int | None) -> None:
        previous, self._current = self._current, row
        for r in (previous, row):
            if r is not None and 0 <= r < len(self._steps):
                self.dataChanged.emit(self.index(r, 0), self.index(r, self.columnCount() - 1))

    # --------------------------------------------------------- drag & drop

    def supportedDropActions(self) -> Qt.DropAction:
        return Qt.DropAction.MoveAction

    def mimeTypes(self) -> list[str]:
        return [_MIME]

    def mimeData(self, indexes: SequenceABC[QModelIndex]) -> QMimeData:
        rows = sorted({i.row() for i in indexes if i.isValid()})
        mime = QMimeData()
        mime.setData(_MIME, QByteArray(",".join(map(str, rows)).encode()))
        return mime

    def dropMimeData(
        self, data: QMimeData, action: Qt.DropAction, row: int, column: int, parent: _Index
    ) -> bool:
        if action != Qt.DropAction.MoveAction or not data.hasFormat(_MIME):
            return False
        raw = bytes(data.data(_MIME).data()).decode()
        rows = [int(r) for r in raw.split(",") if r]
        if row < 0:
            row = parent.row() if parent.isValid() else len(self._steps)
        self.move(rows, row)
        # The move is done here, so the view must not remove the source rows.
        return False


class StepDialog(QDialog):
    """Edit the fields a step type has beyond delay and repeat."""

    def __init__(self, step: Step, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit step")
        self._step = step
        form = QFormLayout(self)
        self.delay_spin = QSpinBox()
        self.delay_spin.setRange(0, MAX_DELAY_MS)
        self.delay_spin.setSuffix(" ms")
        self.delay_spin.setValue(step.delay)
        self.button_combo = QComboBox()
        for name in ("left", "right", "middle"):
            self.button_combo.addItem(name.capitalize(), name)
        self.button_combo.setCurrentIndex(self.button_combo.findData(step.button))
        self.double_check = QCheckBox("Double-click")
        self.double_check.setChecked(step.double)
        self.repeat_spin = QSpinBox()
        self.repeat_spin.setRange(1, MAX_REPEAT)
        self.repeat_spin.setValue(step.repeat)
        self.tolerance_spin = QSpinBox()
        self.tolerance_spin.setRange(0, 255)
        self.tolerance_spin.setValue(step.tolerance)
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(0, MAX_DELAY_MS)
        self.timeout_spin.setSuffix(" ms")
        self.timeout_spin.setSpecialValueText("Wait forever")
        self.timeout_spin.setValue(step.timeout)

        form.addRow("Action:", QLabel(describe(step)))
        if step.type in {"click", "down", "up"}:
            form.addRow("Button:", self.button_combo)
        if step.type == "click":
            form.addRow("", self.double_check)
            form.addRow("Repeat:", self.repeat_spin)
        if step.type == "wait_color":
            form.addRow("Tolerance:", self.tolerance_spin)
            form.addRow("Give up after:", self.timeout_spin)
        form.addRow("Delay after:", self.delay_spin)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def result_step(self) -> Step:
        return self._step.with_changes(
            delay=self.delay_spin.value(),
            button=self.button_combo.currentData(),
            double=self.double_check.isChecked(),
            repeat=self.repeat_spin.value(),
            tolerance=self.tolerance_spin.value(),
            timeout=self.timeout_spin.value(),
        )


class SequenceEditor(QWidget):
    changed = Signal()
    record_requested = Signal()

    def __init__(self, pick: Callable[[], Pick | None], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pick = pick
        self.model = StepTableModel(self)
        self.model.steps_changed.connect(self._on_steps_changed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        record_row = QHBoxLayout()
        self.record_button = self._button("● Record", self.record_requested.emit)
        self.record_button.setToolTip(
            "Record your clicks and key presses. Stop with the Start/pause or Emergency stop hotkey."
        )
        self.record_moves_check = QCheckBox("Record mouse movement")
        self.record_moves_check.toggled.connect(self.changed)
        record_row.addWidget(self.record_button)
        record_row.addWidget(self.record_moves_check, 1)
        layout.addLayout(record_row)

        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.table.setDragDropOverwriteMode(False)
        self.table.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.table.setDropIndicatorShown(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(240)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.doubleClicked.connect(self._on_double_clicked)
        self.table.selectionModel().selectionChanged.connect(self._update_buttons)
        layout.addWidget(self.table, 1)

        add_row = QHBoxLayout()
        self.add_click_button = self._button("+ Click…", self.add_click)
        self.add_click_button.setToolTip("Pick a point on screen to click.")
        self.add_wait_button = self._button("+ Wait for color…", self.add_wait_color)
        self.add_wait_button.setToolTip("Pick a pixel; playback waits until it has that color.")
        self.edit_button = self._button("Edit…", self.edit_selected)
        self.repick_button = self._button("Re-pick", self.repick_selected)
        self.repick_button.setToolTip("Pick a new position for the selected step.")
        for button in (self.add_click_button, self.add_wait_button, self.edit_button, self.repick_button):
            add_row.addWidget(button)
        layout.addLayout(add_row)

        order_row = QHBoxLayout()
        self.up_button = self._button("▲ Up", lambda: self.shift_selected(-1))
        self.down_button = self._button("▼ Down", lambda: self.shift_selected(1))
        self.remove_button = self._button("Remove", self.remove_selected)
        self.clear_button = self._button("Clear all", self.clear)
        for button in (self.up_button, self.down_button, self.remove_button, self.clear_button):
            order_row.addWidget(button)
        layout.addLayout(order_row)

        options = QFormLayout()
        self.loops_spin = QSpinBox()
        self.loops_spin.setRange(0, MAX_LOOPS)
        self.loops_spin.setValue(1)
        self.loops_spin.setSpecialValueText("Forever")
        self.loops_spin.setSuffix(" ×")
        self.loops_spin.valueChanged.connect(self.changed)
        self.speed_combo = QComboBox()
        for speed in SPEEDS:
            self.speed_combo.addItem(f"{speed:g}×", speed)
        self.speed_combo.setCurrentIndex(self.speed_combo.findData(1.0))
        self.speed_combo.currentIndexChanged.connect(self.changed)
        options.addRow("Play:", self.loops_spin)
        options.addRow("Speed:", self.speed_combo)
        self.summary_label = QLabel()
        options.addRow("", self.summary_label)
        layout.addLayout(options)
        self._update_buttons()
        self._update_summary()

    def _button(self, text: str, slot) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("ghost")
        button.clicked.connect(slot)
        return button

    # ------------------------------------------------------------ state

    def sequence(self) -> Sequence:
        return Sequence(
            tuple(self.model.steps()), self.loops_spin.value(), float(self.speed_combo.currentData())
        )

    def set_sequence(self, sequence: Sequence) -> None:
        self.model.set_steps(sequence.steps)
        self.loops_spin.setValue(sequence.loops)
        index = self.speed_combo.findData(sequence.speed)
        if index < 0:
            self.speed_combo.addItem(f"{sequence.speed:g}×", sequence.speed)
            index = self.speed_combo.count() - 1
        self.speed_combo.setCurrentIndex(index)

    def append_steps(self, steps: SequenceABC[Step]) -> None:
        self.model.insert(self.model.rowCount(), steps)

    def set_editing_enabled(self, enabled: bool) -> None:
        for widget in (
            self.add_click_button,
            self.add_wait_button,
            self.edit_button,
            self.repick_button,
            self.up_button,
            self.down_button,
            self.remove_button,
            self.clear_button,
            self.loops_spin,
            self.speed_combo,
            self.record_moves_check,
        ):
            widget.setEnabled(enabled)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed
            if enabled
            else QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.table.setDragEnabled(enabled)
        if enabled:
            self._update_buttons()

    def selected_rows(self) -> list[int]:
        return sorted({index.row() for index in self.table.selectionModel().selectedRows()})

    def _select(self, rows: SequenceABC[int]) -> None:
        self.table.clearSelection()
        for row in rows:
            self.table.selectRow(row)

    def _on_steps_changed(self) -> None:
        self._update_buttons()
        self._update_summary()
        self.changed.emit()

    def _update_buttons(self, *_args) -> None:
        rows = self.selected_rows()
        single = len(rows) == 1
        has_position = single and self.model.step(rows[0]).type in {
            "click",
            "down",
            "up",
            "move",
            "wait_color",
        }
        self.edit_button.setEnabled(single)
        self.repick_button.setEnabled(has_position)
        self.remove_button.setEnabled(bool(rows))
        self.up_button.setEnabled(bool(rows) and rows[0] > 0)
        self.down_button.setEnabled(bool(rows) and rows[-1] < self.model.rowCount() - 1)
        self.clear_button.setEnabled(self.model.rowCount() > 0)

    def _update_summary(self) -> None:
        steps = self.model.steps()
        total_ms = sum(s.delay * (s.repeat if s.type == "click" else 1) for s in steps)
        self.summary_label.setText(
            f"{len(steps)} step{'s' if len(steps) != 1 else ''} · "
            f"about {total_ms / 1000:.1f} s per loop at 1×"
        )

    # ---------------------------------------------------------- actions

    def _insert_row(self) -> int:
        rows = self.selected_rows()
        return rows[-1] + 1 if rows else self.model.rowCount()

    def add_click(self) -> None:
        pick = self._pick()
        if pick is None:
            return
        row = self._insert_row()
        self.model.insert(row, [Step("click", pick.x, pick.y)])
        self._select([row])

    def add_wait_color(self) -> None:
        pick = self._pick()
        if pick is None:
            return
        row = self._insert_row()
        self.model.insert(
            row, [Step("wait_color", pick.x, pick.y, color=format_color(pick.color), tolerance=16, delay=0)]
        )
        self._select([row])

    def repick_selected(self) -> None:
        rows = self.selected_rows()
        if len(rows) != 1:
            return
        pick = self._pick()
        if pick is None:
            return
        step = self.model.step(rows[0])
        changes: dict[str, Any] = {"x": pick.x, "y": pick.y}
        if step.type == "wait_color":
            changes["color"] = format_color(pick.color)
        self.model.replace(rows[0], step.with_changes(**changes))

    def edit_selected(self) -> None:
        rows = self.selected_rows()
        if len(rows) != 1:
            return
        dialog = StepDialog(self.model.step(rows[0]), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.model.replace(rows[0], dialog.result_step())

    def _on_double_clicked(self, index: QModelIndex) -> None:
        if index.column() == 1 and self.edit_button.isEnabled():
            self.edit_selected()

    def shift_selected(self, delta: int) -> None:
        rows = self.selected_rows()
        if not rows:
            return
        target = rows[0] + delta if delta < 0 else rows[-1] + 1 + delta
        self._select(self.model.move(rows, target))

    def remove_selected(self) -> None:
        self.model.remove(self.selected_rows())

    def clear(self) -> None:
        self.model.set_steps([])
