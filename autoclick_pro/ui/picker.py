"""Full-screen point picker with a magnifier.

The screens are captured first and the overlays show that frozen image, so
the magnifier and the color readout show the target app, not the overlay.
Coordinates come from GetCursorPos, which is in physical pixels and matches
what the click engine uses on every monitor and scaling level.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QEventLoop, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QWidget

from autoclick_pro import winapi
from autoclick_pro.steps import format_color

ZOOM = 12
ZOOM_RADIUS = 7  # Pixels on each side of the cursor inside the magnifier.


@dataclass(frozen=True)
class Pick:
    x: int
    y: int
    color: tuple[int, int, int]
    hwnd: int
    title: str


@dataclass
class _Shot:
    rect: tuple[int, int, int, int]  # Monitor rectangle, physical pixels.
    image: QImage


def image_offset(
    cursor: tuple[int, int], rect: tuple[int, int, int, int], size: tuple[int, int]
) -> tuple[int, int]:
    """Pixel in a monitor screenshot that shows the physical cursor position."""
    left, top, right, bottom = rect
    width, height = max(1, right - left), max(1, bottom - top)
    x = (cursor[0] - left) * size[0] // width
    y = (cursor[1] - top) * size[1] // height
    return min(max(x, 0), size[0] - 1), min(max(y, 0), size[1] - 1)


class _Overlay(QWidget):
    def __init__(self, controller: _PickerController, pixmap: QPixmap, geometry: QRect) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool,
        )
        self._controller = controller
        self._pixmap = pixmap
        self.setGeometry(geometry)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self._pixmap)
        local = self.mapFromGlobal(self.cursor().pos())
        if not self.rect().contains(local):
            return
        state = self._controller.state()
        painter.setPen(QPen(QColor(255, 255, 255, 160), 1, Qt.PenStyle.DashLine))
        painter.drawLine(0, local.y(), self.width(), local.y())
        painter.drawLine(local.x(), 0, local.x(), self.height())
        if state is None:
            return
        zoom_image, (px, py), rgb = state
        size = (2 * ZOOM_RADIUS + 1) * ZOOM
        box = QRect(local + QPoint(24, 24), local + QPoint(24 + size, 24 + size + 44))
        if box.right() > self.width():
            box.moveRight(local.x() - 24)
        if box.bottom() > self.height():
            box.moveBottom(local.y() - 24)
        painter.fillRect(box.adjusted(-2, -2, 2, 2), QColor(15, 17, 22, 235))
        painter.drawImage(QRect(box.topLeft(), box.topLeft() + QPoint(size - 1, size - 1)), zoom_image)
        center = QRect(box.left() + ZOOM_RADIUS * ZOOM, box.top() + ZOOM_RADIUS * ZOOM, ZOOM, ZOOM)
        painter.setPen(QPen(QColor(255, 255, 255), 2))
        painter.drawRect(center)
        painter.setPen(QColor(235, 238, 245))
        painter.setFont(QFont(self.font().family(), 10, QFont.Weight.DemiBold))
        painter.fillRect(QRect(box.left() + 6, box.top() + size + 10, 14, 14), QColor(*rgb))
        painter.drawText(box.left() + 26, box.top() + size + 22, f"{px}, {py}   {format_color(rgb)}")
        painter.setFont(QFont(self.font().family(), 8))
        painter.drawText(box.left() + 6, box.top() + size + 38, "Click to pick · arrows nudge · Esc cancels")

    def mouseMoveEvent(self, _event: QMouseEvent) -> None:
        self._controller.refresh()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._controller.finish(pick=True)
        else:
            self._controller.finish(pick=False)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = Qt.Key(event.key())
        nudges: dict[Qt.Key, tuple[int, int]] = {
            Qt.Key.Key_Left: (-1, 0),
            Qt.Key.Key_Right: (1, 0),
            Qt.Key.Key_Up: (0, -1),
            Qt.Key.Key_Down: (0, 1),
        }
        if key == Qt.Key.Key_Escape:
            self._controller.finish(pick=False)
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self._controller.finish(pick=True)
        elif key in nudges:
            dx, dy = nudges[key]
            x, y = winapi.cursor_position()
            backend = winapi.InputBackend()
            backend.position = (x + dx, y + dy)
            self._controller.refresh()


class _PickerController:
    def __init__(self) -> None:
        self._shots: list[_Shot] = []
        self._overlays: list[_Overlay] = []
        self._loop = QEventLoop()
        self._result: Pick | None = None
        self._timer = QTimer()
        self._timer.setInterval(16)
        self._timer.timeout.connect(self.refresh)

    def run(self) -> Pick | None:
        names = {name: rect for rect, name in winapi.monitors()}
        for screen in QGuiApplication.screens():
            rect = names.get(screen.name())
            if rect is None:
                continue
            pixmap = screen.grabWindow(0)
            self._shots.append(_Shot(rect, pixmap.toImage()))
            overlay = _Overlay(self, pixmap, screen.geometry())
            self._overlays.append(overlay)
        if not self._overlays:
            return None
        for overlay in self._overlays:
            overlay.show()
            overlay.raise_()
        self._focus_under_cursor()
        self._timer.start()
        self._loop.exec()
        return self._result

    def _focus_under_cursor(self) -> None:
        screen = QGuiApplication.screenAt(self._overlays[0].cursor().pos())
        for overlay in self._overlays:
            if screen is not None and overlay.geometry() == screen.geometry():
                overlay.activateWindow()
                overlay.setFocus()

    def state(self) -> tuple[QImage, tuple[int, int], tuple[int, int, int]] | None:
        try:
            cursor = winapi.cursor_position()
        except OSError:
            return None
        for shot in self._shots:
            left, top, right, bottom = shot.rect
            if left <= cursor[0] < right and top <= cursor[1] < bottom:
                ix, iy = image_offset(cursor, shot.rect, (shot.image.width(), shot.image.height()))
                region = shot.image.copy(
                    ix - ZOOM_RADIUS, iy - ZOOM_RADIUS, 2 * ZOOM_RADIUS + 1, 2 * ZOOM_RADIUS + 1
                )
                color = QColor(shot.image.pixel(ix, iy))
                return region, cursor, (color.red(), color.green(), color.blue())
        return None

    def refresh(self) -> None:
        for overlay in self._overlays:
            overlay.update()

    def finish(self, *, pick: bool) -> None:
        state = self.state() if pick else None
        self._timer.stop()
        for overlay in self._overlays:
            overlay.hide()
            overlay.deleteLater()
        if state is not None:
            _image, (x, y), rgb = state
            # Overlays are hidden, so this finds the real window under the point.
            hwnd = winapi.window_at(x, y)
            title = winapi.window_title(winapi.root_window(hwnd)) if hwnd else ""
            self._result = Pick(x, y, rgb, hwnd, title)
        self._loop.quit()


def pick_point(hide: list[QWidget] | None = None) -> Pick | None:
    """Let the user pick a screen point. Returns None when cancelled.

    ``hide`` lists windows (the main window, overlays) to hide while picking
    so they do not cover the target.
    """
    hidden = [w for w in (hide or []) if w.isVisible()]
    for widget in hidden:
        widget.hide()
    if hidden:
        # Let Windows finish the hide animation before the screens are captured.
        wait = QEventLoop()
        QTimer.singleShot(250, wait.quit)
        wait.exec()
    try:
        return _PickerController().run()
    finally:
        for widget in hidden:
            widget.show()
