"""Поиск проекции гобо на фото: яркая малонасыщенная область, пятна сливаются в один кластер."""

from __future__ import annotations

import cv2
import numpy as np

MAX_SIDE = 1024
MAX_SATURATION = 110
P995_FRACTION = 0.75
MIN_AREA_FRACTION = 0.002
MERGE_FRACTION = 0.06
MIN_MERGE_KERNEL = 9
MIN_DYNAMIC_RANGE = 40  # p99.5 - p5 яркости; меньше значит «в кадре нет проекции»


def extract_projection(bgr: np.ndarray) -> np.ndarray | None:
    """Вырезка проекции (gray, вне найденной области чёрный) или None."""
    height, width = bgr.shape[:2]
    scale = MAX_SIDE / max(height, width)
    if scale < 1.0:
        bgr = cv2.resize(
            bgr, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA
        )
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    value = cv2.GaussianBlur(hsv[:, :, 2], (0, 0), 1.5)

    low, high = np.percentile(value, [5.0, 99.5])
    if high - low < MIN_DYNAMIC_RANGE:
        return None
    otsu, _ = cv2.threshold(value, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    threshold = max(float(otsu), P995_FRACTION * float(high))
    mask = ((value > threshold) & (saturation < MAX_SATURATION)).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    if not mask.any():
        return None

    kernel = max(MIN_MERGE_KERNEL, int(MERGE_FRACTION * max(mask.shape)))
    merged = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel, kernel)))
    count, labels, _, _ = cv2.connectedComponentsWithStats(merged, connectivity=8)

    foreground = mask > 0
    weight = np.clip(value.astype(np.float32) - threshold, 0.0, None)
    scores = np.bincount(labels[foreground], weights=weight[foreground], minlength=count)
    scores[0] = 0.0
    best = int(scores.argmax())
    if scores[best] <= 0.0:
        return None

    selected = (labels == best) & foreground
    if selected.sum() < MIN_AREA_FRACTION * selected.size:
        return None
    ys, xs = np.nonzero(selected)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    return np.where(selected[y0:y1, x0:x1], gray[y0:y1, x0:x1], 0).astype(np.uint8)
