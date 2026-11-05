"""Small always-on-top status overlay that can be dragged anywhere.

It never takes focus, so dragging it won't steal focus from the app
underneath. Drag with the left mouse button; double-click to snap it
back to the top-right corner.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QMouseEvent, QPainter
from PySide6.QtWidgets import QWidget

_COLORS = {
    "idle": QColor("#a8b0bd"),
    "run": QColor("#57ab5f"),
    "pause": QColor("#c79a3a"),
    "stop": QColor("#e05a52"),
    "done": QColor("#7aa5f0"),
    "error": QColor("#e05a52"),
    "record": QColor("#e05a52"),
    "countdown": QColor("#f2f4f8"),
}


class StatusHud(QWidget):
    WIDTH = 240
    HEIGHT = 64
    COUNTDOWN_SIZE = 120
    # Background alpha, out of 255. Was 215; 245 is a little less
    # transparent while keeping the rounded corners soft.
    BACKGROUND_ALPHA = 245

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        # NOTE: WindowTransparentForInput was deliberately removed here.
        # It made clicks pass straight through the overlay, which also
        # made it impossible to grab and drag. The trade-off is that
        # clicks on the overlay itself no longer reach the app behind
        # it — drag it out of the way if it covers something you need.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._title = ""
        self._detail = ""
        self._kind = "idle"
        self._countdown: int | None = None
        self._drag_offset: QPoint | None = None
        self._custom_pos: QPoint | None = None
        self._place()

    def _place(self) -> None:
        screen = QGuiApplication.primaryScreen()
        area = screen.availableGeometry() if screen else QRect(0, 0, 1280, 720)
        if self._countdown is not None:
            size = self.COUNTDOWN_SIZE
            self.setGeometry(area.center().x() - size // 2, area.center().y() - size // 2, size, size)
        elif self._custom_pos is not None:
            self.setGeometry(self._custom_pos.x(), self._custom_pos.y(), self.WIDTH, self.HEIGHT)
        else:
            self.setGeometry(area.right() - self.WIDTH - 16, area.top() + 16, self.WIDTH, self.HEIGHT)

    def _clamp_position(self, pos: QPoint, width: int, height: int) -> QPoint:
        """Keep a dragged position fully on the primary screen."""
        screen = QGuiApplication.primaryScreen()
        area = screen.availableGeometry() if screen else QRect(0, 0, 1280, 720)
        x = min(max(pos.x(), area.left()), max(area.left(), area.right() - width + 1))
        y = min(max(pos.y(), area.top()), max(area.top(), area.bottom() - height + 1))
        return QPoint(x, y)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None:
            target = self._clamp_position(
                event.globalPosition().toPoint() - self._drag_offset,
                self.width(),
                self.height(),
            )
            self.move(target)
            # A dragged countdown is temporary: don't let it overwrite
            # the position the normal overlay returns to afterwards.
            if self._countdown is None:
                self._custom_pos = self.pos()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None:
            self._drag_offset = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = None
            self._custom_pos = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self._place()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    @property
    def title(self) -> str:
        return self._title

    @property
    def detail(self) -> str:
        return self._detail

    @property
    def countdown(self) -> int | None:
        return self._countdown

    def set_status(self, title: str, detail: str, kind: str) -> None:
        self._title, self._detail, self._kind = title, detail, kind
        if self._countdown is None:
            self.update()

    def set_countdown(self, seconds: int | None) -> None:
        self._countdown = seconds
        self._place()
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(18, 20, 26, self.BACKGROUND_ALPHA))
        painter.drawRoundedRect(self.rect(), 12, 12)
        family = self.font().family()
        if self._countdown is not None:
            painter.setPen(_COLORS["countdown"])
            painter.setFont(QFont(family, 48, QFont.Weight.Bold))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, str(self._countdown))
            return
        color = _COLORS.get(self._kind, _COLORS["idle"])
        painter.setBrush(color)
        painter.drawEllipse(16, 18, 10, 10)
        painter.setPen(color)
        painter.setFont(QFont(family, 11, QFont.Weight.Bold))
        painter.drawText(QRect(34, 10, self.width() - 44, 24), Qt.AlignmentFlag.AlignVCenter, self._title)
        painter.setPen(QColor("#c8cdd6"))
        painter.setFont(QFont(family, 9))
        painter.drawText(QRect(16, 34, self.width() - 26, 22), Qt.AlignmentFlag.AlignVCenter, self._detail)
