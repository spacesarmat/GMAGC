"""Поиск: эмбеддинги по 48 вариантам запроса -> shortlist -> уточнение формы -> семейства."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from gmagc_desktop.matcher.embedder import Embedder
from gmagc_desktop.matcher.shape import ShapeMatcher, soft_mask
from gmagc_desktop.matcher.variants import DEFAULT_ROTATIONS, query_variants


@dataclass(frozen=True)
class SearchData:
    embeddings: np.ndarray  # (N, D) float32, L2-нормализованные
    masks: np.ndarray  # (N, 64, 64) uint8
    group_ids: np.ndarray  # (N,) int32


@dataclass(frozen=True)
class Match:
    index: int  # лучший (по эмбеддингу) файл семейства
    score: float
    embed_score: float
    shape_score: float
    angle: float
    mirrored: bool
    members: tuple[int, ...]  # все файлы семейства, включая index


class Searcher:
    def __init__(
        self,
        data: SearchData,
        embedder: Embedder,
        n_rotations: int = DEFAULT_ROTATIONS,
        shortlist: int = 20,
        w_embed: float = 0.5,
    ):
        self._data = data
        self._embedder = embedder
        self._n_rotations = n_rotations
        self._shortlist = shortlist
        self._w_embed = w_embed
        self._members: dict[int, list[int]] = defaultdict(list)
        for index, group in enumerate(data.group_ids.tolist()):
            self._members[group].append(index)

    def search(self, normalized_query: np.ndarray, top_n: int = 10) -> list[Match]:
        data = self._data
        if len(data.embeddings) == 0:
            return []

        variants = query_variants(normalized_query, self._n_rotations, mirror=True)
        query_vectors = self._embedder.embed(variants)  # (V, D)
        best_embed = (data.embeddings @ query_vectors.T).max(axis=1)  # (N,)

        candidates: list[int] = []
        seen_groups: set[int] = set()
        for index in np.argsort(-best_embed):
            group = int(data.group_ids[index])
            if group in seen_groups:
                continue
            seen_groups.add(group)
            candidates.append(int(index))
            if len(candidates) >= self._shortlist:
                break

        shape = ShapeMatcher(soft_mask(normalized_query))
        matches = []
        for index in candidates:
            found = shape.score(data.masks[index])
            embed_score = float(best_embed[index])
            score = self._w_embed * max(embed_score, 0.0) + (1.0 - self._w_embed) * found.score
            matches.append(
                Match(
                    index=index,
                    score=score,
                    embed_score=embed_score,
                    shape_score=found.score,
                    angle=found.angle,
                    mirrored=found.mirrored,
                    members=tuple(self._members[int(data.group_ids[index])]),
                )
            )
        matches.sort(key=lambda m: m.score, reverse=True)
        return matches[:top_n]
