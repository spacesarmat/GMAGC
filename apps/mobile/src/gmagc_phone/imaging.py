"""Подготовка фото к отправке на ПК средствами Qt (без Pillow: на Android его нет)."""

from __future__ import annotations

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage, QImageReader

UPLOAD_LIMIT = 8 * 1024 * 1024  # запас до лимита сервера (10 МБ)
MAX_SIDE = 2560


def prepare_upload(data: bytes, limit: int = UPLOAD_LIMIT) -> bytes:
    """Файл до limit уходит как есть; больший уменьшается до JPEG не больше limit (иначе ValueError)."""
    if len(data) <= limit:
        return data
    source = QByteArray(data)  # QBuffer не владеет данными: ссылку держим до конца чтения
    buffer = QBuffer(source)
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer)
    reader.setAutoTransform(True)  # учитывает поворот из EXIF
    image = reader.read()
    if image.isNull():
        raise ValueError("файл не удалось прочитать как изображение")
    if max(image.width(), image.height()) > MAX_SIDE:
        aspect, smooth = Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        image = image.scaled(MAX_SIDE, MAX_SIDE, aspect, smooth)
    image = image.convertToFormat(QImage.Format.Format_RGB32)
    for quality in (85, 70, 55):
        out = QBuffer()
        out.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(out, "JPEG", quality)
        encoded = bytes(out.data())
        if len(encoded) <= limit:
            return encoded
    raise ValueError("изображение слишком большое даже после уменьшения")


def grayscale_frame(image: QImage, max_side: int = 640) -> tuple[bytes, int, int]:
    """Кадр камеры → серые байты (ширина × высота) для чтения QR; большие кадры уменьшаются заранее."""
    if max(image.width(), image.height()) > max_side:
        aspect, fast = Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation
        image = image.scaled(max_side, max_side, aspect, fast)
    gray = image.convertToFormat(QImage.Format.Format_Grayscale8)
    width, height = gray.width(), gray.height()
    stride = gray.bytesPerLine()
    raw = bytes(gray.constBits())
    if stride == width:
        return raw[: width * height], width, height
    return b"".join(raw[row * stride : row * stride + width] for row in range(height)), width, height
