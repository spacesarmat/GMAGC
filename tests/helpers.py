"""Синтетические фигуры для тестов."""

import cv2
import numpy as np

_L_POINTS = np.array([(50, 50), (90, 50), (90, 180), (200, 180), (200, 220), (50, 220)])


def l_shape(canvas=(300, 300), scale=1.0, offset=(0, 0)) -> np.ndarray:
    """Белая асимметричная L-фигура на чёрном (canvas = (высота, ширина))."""
    image = np.zeros(canvas, np.uint8)
    points = (_L_POINTS * scale + np.array(offset)).astype(np.int32)
    cv2.fillPoly(image, [points], 255)
    return image


def sample_gobo(size=256) -> np.ndarray:
    """Асимметричное «гобо»: кольцо, точки и сектор на чёрном диске."""
    image = np.zeros((size, size), np.uint8)
    c = size // 2
    cv2.circle(image, (c, c), int(size * 0.40), 255, max(2, size // 20))
    cv2.circle(image, (c + size // 5, c - size // 8), size // 12, 255, -1)
    cv2.circle(image, (c - size // 4, c + size // 6), size // 20, 255, -1)
    cv2.ellipse(image, (c, c), (size // 6, size // 12), 30, 0, 200, 255, -1)
    return image


def iou(a: np.ndarray, b: np.ndarray, threshold: int = 127) -> float:
    a, b = a > threshold, b > threshold
    union = np.logical_or(a, b).sum()
    return float(np.logical_and(a, b).sum() / union) if union else 0.0
