"""Самопроверка ядра: пайплайн работает, а упакованные зависимости загружаются."""

from __future__ import annotations

import platform

import cv2
import numpy as np

from gmagc_desktop.matcher.pipeline import normalize_photo
from gmagc_desktop.matcher.synthetic import simulate_photo


def _sample_gobo(size: int = 256) -> np.ndarray:
    """Небольшое асимметричное «гобо»: кольцо и две точки на чёрном фоне."""
    image = np.zeros((size, size), np.uint8)
    centre = size // 2
    cv2.circle(image, (centre, centre), int(size * 0.4), 255, size // 16)
    cv2.circle(image, (centre + size // 5, centre - size // 8), size // 12, 255, -1)
    cv2.circle(image, (centre - size // 4, centre + size // 6), size // 20, 255, -1)
    return image


def run_core_check() -> dict:
    """Строит синтетическое фото, прогоняет его через ядро и возвращает итог и версии библиотек."""
    photo = simulate_photo(_sample_gobo(), np.random.default_rng(1))
    normalized = normalize_photo(photo)
    shape = None if normalized is None else tuple(int(n) for n in normalized.shape)
    return {
        "ok": shape == (224, 224),
        "shape": shape,
        "versions": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "opencv": cv2.__version__,
        },
    }
