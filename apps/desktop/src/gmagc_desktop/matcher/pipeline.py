"""Фото -> нормализованное изображение, готовое к поиску."""

from __future__ import annotations

import numpy as np

from gmagc_desktop.matcher.normalize import normalize_gray
from gmagc_desktop.matcher.segment import extract_projection


def normalize_photo(bgr: np.ndarray) -> np.ndarray | None:
    """Сегментация проекции + нормализация 224x224; None, если проекция не найдена."""
    crop = extract_projection(bgr)
    return None if crop is None else normalize_gray(crop)
