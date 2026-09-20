"""Повороты и зеркало запроса: гобо вращается и проецируется зеркально."""

from __future__ import annotations

import cv2
import numpy as np

DEFAULT_ROTATIONS = 24


def rotate_image(image: np.ndarray, angle_degrees: float) -> np.ndarray:
    """Поворот вокруг центра, положительный угол против часовой стрелки."""
    height, width = image.shape[:2]
    matrix = cv2.getRotationMatrix2D(
        ((width - 1) / 2.0, (height - 1) / 2.0), float(angle_degrees), 1.0
    )
    return cv2.warpAffine(image, matrix, (width, height), flags=cv2.INTER_LINEAR, borderValue=0)


def query_variants(
    image: np.ndarray, n_rotations: int = DEFAULT_ROTATIONS, mirror: bool = True
) -> np.ndarray:
    """Все повороты оригинала, затем (если mirror) все повороты зеркального отражения."""
    bases = [image]
    if mirror:
        bases.append(np.ascontiguousarray(image[:, ::-1]))
    variants = []
    for base in bases:
        for k in range(n_rotations):
            variants.append(base if k == 0 else rotate_image(base, k * 360.0 / n_rotations))
    return np.stack(variants)


def variant_pose(index: int, n_rotations: int = DEFAULT_ROTATIONS) -> tuple[float, bool]:
    """(угол, зеркало) для индекса из query_variants."""
    mirrored, k = divmod(index, n_rotations)
    return k * 360.0 / n_rotations, bool(mirrored)
