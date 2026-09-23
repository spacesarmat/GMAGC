"""Ручная поправка фото перед поиском: экспозиция, яркость, контраст."""

from __future__ import annotations

import numpy as np

MIDTONE = 127.0


def apply_adjustments(
    bgr: np.ndarray, *, brightness: float = 0.0, contrast: float = 1.0, exposure: float = 0.0
) -> np.ndarray:
    """Экспозиция (множитель, EV-стопы) → яркость (сложение) → контраст (растяжение вокруг середины)."""
    image = bgr.astype(np.float32)
    image *= 2.0**exposure
    image += brightness
    image = (image - MIDTONE) * contrast + MIDTONE
    return np.clip(image, 0, 255).astype(np.uint8)
