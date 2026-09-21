"""Приведение изображения к канонической форме: центр, масштаб, размер."""

from __future__ import annotations

import cv2
import numpy as np

NORM_SIZE = 224
FILL = 0.45
MIN_THRESHOLD = 40
MIN_BRIGHT_PIXELS = 20
MIN_RADIUS = 2.0


def bright_mask(gray: np.ndarray) -> np.ndarray:
    """Булева маска «светлой» области (Otsu, но не ниже MIN_THRESHOLD)."""
    threshold, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return gray > max(threshold, MIN_THRESHOLD)


def normalize_gray(
    gray: np.ndarray, size: int = NORM_SIZE, fill: float = FILL
) -> np.ndarray | None:
    """Центр по центроиду яркой области, радиус 99.5-го перцентиля = fill*size.

    Серые уровни сохраняются, пустое место чёрное. None, если яркой области нет.
    """
    ys, xs = np.nonzero(bright_mask(gray))
    if xs.size < MIN_BRIGHT_PIXELS:
        return None
    cx, cy = float(xs.mean()), float(ys.mean())
    radius = float(np.percentile(np.hypot(xs - cx, ys - cy), 99.5))
    if radius < MIN_RADIUS:
        return None
    scale = fill * size / radius
    matrix = np.array(
        [[scale, 0.0, size / 2 - scale * cx], [0.0, scale, size / 2 - scale * cy]],
        dtype=np.float32,
    )
    return cv2.warpAffine(gray, matrix, (size, size), flags=cv2.INTER_LINEAR, borderValue=0)
