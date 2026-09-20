"""Shared thumbnail utilities."""

import numpy as np


def square_pad(gray: np.ndarray) -> np.ndarray:
    """Дополняет изображение чёрным до квадрата, оригинал по центру."""
    side = max(gray.shape)
    square = np.zeros((side, side), np.uint8)
    y, x = (side - gray.shape[0]) // 2, (side - gray.shape[1]) // 2
    square[y : y + gray.shape[0], x : x + gray.shape[1]] = gray
    return square
