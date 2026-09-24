"""Общие виджеты Qt-интерфейса: обрезаемая подпись, картинка из байтов, сетка карточек с переносом по ширине."""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QLayout, QSizePolicy, QWidget


class ElidedLabel(QLabel):
    """Подпись в одну строку: длинный текст обрезается «…» по ширине, полный виден в подсказке."""

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.set_full_text(text)

    def set_full_text(self, text: str) -> None:
        self._full = text
        self.setToolTip(text)
        self.update()

    def full_text(self) -> str:
        return self._full

    def paintEvent(self, _event) -> None:  # noqa: N802 - имя задаёт Qt
        painter = QPainter(self)
        elided = self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, self.width())
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawText(self.rect(), int(self.alignment()) | Qt.AlignmentFlag.AlignVCenter, elided)
        painter.end()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, self.fontMetrics().height() + 2)


def pixmap_from_bytes(data: bytes | None) -> QPixmap:
    """QPixmap из байтов PNG/JPEG; пустые или повреждённые данные дают пустую картинку."""
    pixmap = QPixmap()
    if data:
        pixmap.loadFromData(data)
    return pixmap


def set_picture(label: QLabel, data: bytes | None, width: int, height: int) -> None:
    """Показывает картинку в подписи, вписывая её в width×height с сохранением пропорций."""
    label.setFixedSize(width, height)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    pixmap = pixmap_from_bytes(data)
    if pixmap.isNull():
        label.clear()
        return
    ratio = label.devicePixelRatioF() or 1.0
    keep, smooth = Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
    scaled = pixmap.scaled(int(width * ratio), int(height * ratio), keep, smooth)
    scaled.setDevicePixelRatio(ratio)
    label.setPixmap(scaled)


class FlowLayout(QLayout):
    """Раскладка «слева направо с переносом строк» (карточки результатов занимают всю ширину панели)."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 10):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._layout(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _layout(self, rect: QRect, *, apply: bool) -> int:
        x, y, row_height = rect.x(), rect.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > rect.right() + 1 and row_height > 0:
                x, y, row_height = rect.x(), y + row_height + self._spacing, 0
            if apply:
                item.setGeometry(QRect(x, y, hint.width(), hint.height()))
            x += hint.width() + self._spacing
            row_height = max(row_height, hint.height())
        return y + row_height - rect.y()


class Panel(QFrame):
    """Плоская панель-секция с рамкой (role=panel/panel2)."""

    def __init__(self, role: str = "panel"):
        super().__init__()
        self.setProperty("role", role)
