"""Мягкое сравнение формы: размытые маски, перебор поворота и зеркала."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from gmagc_desktop.matcher.variants import rotate_image

MASK_SIZE = 64
BLUR_SIGMA = 1.2


@dataclass(frozen=True)
class ShapeMatch:
    score: float
    angle: float
    mirrored: bool


def soft_mask(normalized: np.ndarray, size: int = MASK_SIZE) -> np.ndarray:
    """Нормализованное 224x224 -> uint8 (size, size). Такие маски хранятся в индексе."""
    return cv2.resize(normalized, (size, size), interpolation=cv2.INTER_AREA)


def _blurred(mask: np.ndarray) -> np.ndarray:
    return cv2.GaussianBlur(mask.astype(np.float32) / 255.0, (0, 0), BLUR_SIGMA)


def _soft_iou(stack: np.ndarray, target: np.ndarray) -> np.ndarray:
    inter = np.minimum(stack, target).sum(axis=(1, 2))
    union = np.maximum(stack, target).sum(axis=(1, 2))
    return inter / np.maximum(union, 1e-6)


class ShapeMatcher:
    """Сравнивает один запрос со многими кандидатами, кэшируя повороты запроса."""

    def __init__(
        self,
        query_mask: np.ndarray,
        coarse_step: float = 5.0,
        fine_radius: float = 4.0,
        fine_step: float = 1.0,
    ):
        plain = _blurred(query_mask)
        self._bases = {False: plain, True: np.ascontiguousarray(plain[:, ::-1])}
        self._poses = [
            (float(angle), mirrored)
            for mirrored in (False, True)
            for angle in np.arange(0.0, 360.0, coarse_step)
        ]
        self._coarse = np.stack(
            [rotate_image(self._bases[m], a) for a, m in self._poses]
        )
        self._fine_offsets = np.arange(-fine_radius, fine_radius + 1e-6, fine_step)

    def score(self, candidate_mask: np.ndarray) -> ShapeMatch:
        target = _blurred(candidate_mask)
        best = int(np.argmax(_soft_iou(self._coarse, target)))
        angle0, mirrored = self._poses[best]
        angles = angle0 + self._fine_offsets
        fine = np.stack([rotate_image(self._bases[mirrored], a) for a in angles])
        scores = _soft_iou(fine, target)
        j = int(np.argmax(scores))
        return ShapeMatch(float(scores[j]), float(angles[j] % 360.0), mirrored)
