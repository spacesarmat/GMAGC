"""Миниатюры гобо для интерфейса и отчётов."""

from __future__ import annotations

import cv2
import numpy as np


def square_pad(gray: np.ndarray) -> np.ndarray:
    """Дополняет изображение чёрным до квадрата, оригинал по центру."""
    side = max(gray.shape)
    square = np.zeros((side, side), np.uint8)
    y, x = (side - gray.shape[0]) // 2, (side - gray.shape[1]) // 2
    square[y : y + gray.shape[0], x : x + gray.shape[1]] = gray
    return square


def thumbnail_png(gray: np.ndarray, size: int = 96) -> bytes:
    """PNG-миниатюра size x size: изображение вписано в квадрат с чёрными полями."""
    small = cv2.resize(square_pad(gray), (size, size), interpolation=cv2.INTER_AREA)
    ok, buffer = cv2.imencode(".png", small)
    if not ok:
        raise ValueError("не удалось закодировать миниатюру")
    return buffer.tobytes()
