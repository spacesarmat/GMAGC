"""Типы результатов поиска для интерфейса (и будущего сервера)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# Верные попадания на реальных фото имели оценку не ниже 70,5%, ложные не выше 71,3%: порог нестрогий.
LOW_CONFIDENCE_SCORE = 0.72


class Outcome(Enum):
    FOUND = "found"
    LOW_CONFIDENCE = "low_confidence"
    NO_PROJECTION = "no_projection"


@dataclass(frozen=True)
class Result:
    rank: int
    name: str
    rel_path: str
    full_path: str
    score: float  # доля от 0 до 1
    copies: tuple[str, ...]  # полные пути остальных файлов семейства
    thumbnail_png: bytes


@dataclass(frozen=True)
class SearchOutcome:
    kind: Outcome
    results: tuple[Result, ...] = ()
    projection_png: bytes | None = None
    took_ms: float = 0.0


@dataclass(frozen=True)
class IndexStatus:
    files: int
    families: int
    skipped: int
    transient: int
