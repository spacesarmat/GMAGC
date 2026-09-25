"""Общие виджеты телефона: заголовок с «Назад», подпись-картинка, предпросмотр камеры, всплывающее сообщение."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from gmagc_common.i18n import t
from gmagc_phone import theme


def label(text: str = "", role: str = "", wrap: bool = True) -> QLabel:
    widget = QLabel(text)
    widget.setWordWrap(wrap)
    if role:
        widget.setProperty("role", role)
    return widget


def button(text: str, role: str = "", on_click=None) -> QPushButton:
    widget = QPushButton(text)
    if role:
        widget.setProperty("role", role)
    if on_click is not None:
        widget.clicked.connect(lambda _checked=False: on_click())
    return widget


def card() -> QFrame:
    frame = QFrame()
    frame.setProperty("role", "card")
    return frame


def picture(data: bytes | None, width: int, height: int) -> QLabel:
    """Картинка из байтов, вписанная в width×height."""
    widget = QLabel()
    widget.setFixedSize(width, height)
    widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
    pixmap = QPixmap()
    if data and pixmap.loadFromData(data):
        keep, smooth = Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        widget.setPixmap(pixmap.scaled(width, height, keep, smooth))
    return widget


def scrolling(content: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setWidget(content)
    return area


class Page(QWidget):
    """Экран: заголовок с кнопкой «Назад» и прокручиваемое содержимое."""

    def __init__(self, title: str, on_back=None):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        bar = QFrame()
        bar.setProperty("role", "bar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(8, 4, 8, 4)
        self.back = button("‹", "link", on_back)
        self.back.setAccessibleName(t("Назад"))
        self.back.setVisible(on_back is not None)
        row.addWidget(self.back)
        self.title = label(title, "heading")
        row.addWidget(self.title, 1)
        outer.addWidget(bar)
        self.body = QWidget()
        self.layout_ = QVBoxLayout(self.body)
        self.layout_.setContentsMargins(16, 16, 16, 16)
        self.layout_.setSpacing(12)
        outer.addWidget(scrolling(self.body), 1)

    def add(self, widget: QWidget) -> None:
        self.layout_.addWidget(widget)

    def finish(self) -> None:
        self.layout_.addStretch(1)


class Toast(QLabel):
    """Короткое сообщение поверх экрана, гаснет само."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setProperty("role", "toast")
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_text(self, text: str, milliseconds: int = 3000) -> None:
        self.setText(text)
        parent = self.parentWidget()
        width = max(parent.width() - 32, 100)
        self.setFixedWidth(width)
        self.adjustSize()
        self.move(16, max(parent.height() - self.height() - 24, 0))
        self.style().unpolish(self)
        self.style().polish(self)
        self.show()
        self.raise_()
        self._timer.start(milliseconds)


class Preview(QWidget):
    """Кадр камеры на весь экран (с обрезкой по краям), рамка-видоискатель и касание для фокуса."""

    tapped = Signal(float, float)

    def __init__(self):
        super().__init__()
        self._image: QImage | None = None
        self.frame_visible = False  # рамка-видоискатель
        self.setMinimumHeight(240)

    def set_image(self, image: QImage | None) -> None:
        self._image = image
        self.update()

    def _target(self) -> QRectF:
        return QRectF(self.rect())

    def mousePressEvent(self, event) -> None:
        pos: QPointF = event.position()
        if self.width() and self.height():
            self.tapped.emit(pos.x() / self.width(), pos.y() / self.height())

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(theme.BG))
        if self._image is not None and not self._image.isNull():
            target = self._target()
            scale = max(target.width() / self._image.width(), target.height() / self._image.height())
            width, height = self._image.width() * scale, self._image.height() * scale
            left, top = target.center().x() - width / 2, target.center().y() - height / 2
            painter.drawImage(QRectF(left, top, width, height), self._image)
        if self.frame_visible:
            side = min(self.width(), self.height()) * 0.7
            pen = QPen(QColor(theme.ACCENT))
            pen.setWidth(3)
            painter.setPen(pen)
            painter.drawRoundedRect(QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side), 16, 16)
        painter.end()
