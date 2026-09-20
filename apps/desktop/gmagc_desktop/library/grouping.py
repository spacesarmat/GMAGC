"""Группировка визуальных дублей (одно гобо у разных производителей)."""

from __future__ import annotations

import numpy as np

PAIR_CHUNK = 100_000


def _find(parent: np.ndarray, item: int) -> int:
    root = item
    while parent[root] != root:
        root = parent[root]
    while parent[item] != root:
        parent[item], item = root, parent[item]
    return int(root)


def _soft_iou_pairs(flat_masks: np.ndarray, left: np.ndarray, right: np.ndarray) -> np.ndarray:
    inter = np.minimum(flat_masks[left], flat_masks[right]).sum(axis=1)
    union = np.maximum(flat_masks[left], flat_masks[right]).sum(axis=1)
    return inter / np.maximum(union, 1e-6)


def group_duplicates(
    embeddings: np.ndarray,
    masks: np.ndarray,
    cosine_threshold: float = 0.97,
    iou_threshold: float = 0.85,
    block: int = 512,
) -> np.ndarray:
    """Идентификаторы семейств: наименьший индекс участника. Объединение транзитивно."""
    count = len(embeddings)
    parent = np.arange(count, dtype=np.int64)
    if count == 0:
        return parent.astype(np.int32)
    vectors = embeddings.astype(np.float32)
    flat = masks.reshape(count, -1).astype(np.float32) / 255.0

    for start in range(0, count, block):
        similarity = vectors[start : start + block] @ vectors.T
        rows, cols = np.nonzero(similarity >= cosine_threshold)
        rows = rows + start
        keep = cols > rows
        rows, cols = rows[keep], cols[keep]
        for chunk in range(0, len(rows), PAIR_CHUNK):
            left = rows[chunk : chunk + PAIR_CHUNK]
            right = cols[chunk : chunk + PAIR_CHUNK]
            similar = _soft_iou_pairs(flat, left, right) >= iou_threshold
            for a, b in zip(left[similar], right[similar], strict=True):
                root_a, root_b = _find(parent, int(a)), _find(parent, int(b))
                if root_a != root_b:
                    parent[max(root_a, root_b)] = min(root_a, root_b)

    return np.array([_find(parent, i) for i in range(count)], dtype=np.int32)
