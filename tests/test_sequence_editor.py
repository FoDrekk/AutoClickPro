import pytest
from PySide6.QtCore import QModelIndex, Qt

from autoclick_pro.steps import Sequence, Step
from autoclick_pro.ui.picker import Pick, image_offset
from autoclick_pro.ui.sequence_editor import SequenceEditor, StepTableModel

A, B, C, D = (Step("click", i, i) for i in range(4))


@pytest.fixture
def model(qapp):
    m = StepTableModel()
    m.set_steps([A, B, C, D])
    return m


def test_move_rows(model):
    assert model.move([0], 3) == [2]
    assert model.steps() == [B, C, A, D]
    assert model.move([2, 3], 0) == [0, 1]
    assert model.steps() == [A, D, B, C]
    assert model.move([1], 99) == [3]
    assert model.steps() == [A, B, C, D]


def test_drag_and_drop_round_trip(model):
    mime = model.mimeData([model.index(0, 0), model.index(1, 1)])
    model.dropMimeData(mime, Qt.DropAction.MoveAction, 4, 0, QModelIndex())
    assert model.steps() == [C, D, A, B]


def test_edit_delay_and_repeat(model):
    assert model.setData(model.index(0, StepTableModel.DELAY_COLUMN), 250)
    assert model.setData(model.index(0, StepTableModel.REPEAT_COLUMN), 5)
    assert model.step(0).delay == 250 and model.step(0).repeat == 5
    assert not model.setData(model.index(0, StepTableModel.DELAY_COLUMN), "abc")
    model.replace(1, Step("move", 1, 1))
    assert not model.setData(model.index(1, StepTableModel.REPEAT_COLUMN), 3)
    assert not model.flags(model.index(1, StepTableModel.REPEAT_COLUMN)) & Qt.ItemFlag.ItemIsEditable


def test_insert_remove(model):
    model.insert(1, [Step("move", 9, 9)])
    assert model.step(1) == Step("move", 9, 9)
    model.remove([0, 1])
    assert model.steps() == [B, C, D]


def test_display(model):
    assert model.data(model.index(0, 1)) == "Click left at 0, 0"
    assert model.data(model.index(0, 0)) == 1
    model.set_current(2)
    assert model.data(model.index(2, 1), Qt.ItemDataRole.BackgroundRole) is not None


@pytest.fixture
def editor(qtbot):
    picks = []
    e = SequenceEditor(lambda: picks.pop(0) if picks else None)
    qtbot.addWidget(e)
    e.picks = picks
    return e


def test_editor_round_trip(editor):
    seq = Sequence((A, Step("key_down", vk=65)), loops=0, speed=2.0)
    editor.set_sequence(seq)
    assert editor.sequence() == seq
    assert "2 steps" in editor.summary_label.text()


def test_add_click_and_wait_from_picker(editor):
    editor.picks.append(Pick(5, 6, (1, 2, 3), 0, ""))
    editor.add_click()
    editor.picks.append(Pick(7, 8, (255, 0, 0), 0, ""))
    editor.add_wait_color()
    steps = editor.sequence().steps
    assert steps[0] == Step("click", 5, 6)
    assert steps[1].type == "wait_color" and steps[1].color == "#FF0000"
    editor.add_click()  # Picker cancelled: nothing added.
    assert len(editor.sequence().steps) == 2


def test_repick_and_shift(editor):
    editor.set_sequence(Sequence((A, B)))
    editor.table.selectRow(1)
    editor.picks.append(Pick(50, 60, (0, 0, 0), 0, ""))
    editor.repick_selected()
    assert editor.sequence().steps[1] == Step("click", 50, 60)
    editor.shift_selected(-1)
    assert editor.sequence().steps[0] == Step("click", 50, 60)
    assert editor.selected_rows() == [0]


def test_editing_can_be_locked(editor):
    editor.set_editing_enabled(False)
    assert not editor.add_click_button.isEnabled()
    assert not editor.clear_button.isEnabled()
    editor.set_editing_enabled(True)
    assert editor.add_click_button.isEnabled()


@pytest.mark.parametrize(
    ("cursor", "rect", "size", "expected"),
    [
        ((10, 20), (0, 0, 1920, 1080), (1920, 1080), (10, 20)),
        ((-1910, 5), (-1920, 0, 0, 1080), (1920, 1080), (10, 5)),
        ((960, 540), (0, 0, 1920, 1080), (960, 540), (480, 270)),  # Half-size image.
        ((5000, -9), (0, 0, 1920, 1080), (1920, 1080), (1919, 0)),  # Clamped.
    ],
)
def test_image_offset(cursor, rect, size, expected):
    assert image_offset(cursor, rect, size) == expected
