"""Загрузка файлов библиотеки и фото в numpy-массивы."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image

LIBRARY_EXTENSIONS = frozenset({".png", ".bmp"})
IGNORED_LIBRARY_NAMES = frozenset({"question.bmp"})


def load_library_gray(path: str | Path) -> np.ndarray:
    """Файл гобо -> uint8 2D. Прозрачность композитится на чёрный."""
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
    canvas = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
    canvas.alpha_composite(rgba)
    return np.array(canvas.convert("L"), dtype=np.uint8)


def load_photo_bgr(path: str | Path) -> np.ndarray:
    """Фото -> uint8 HxWx3 BGR (с учётом EXIF-ориентации, поддерживает не-ASCII пути)."""
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"cannot decode image: {path}")
    return image
