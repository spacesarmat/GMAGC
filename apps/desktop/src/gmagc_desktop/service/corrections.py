"""Исправления поиска: пользователь отмечает неверный результат и указывает правильный файл.

Не переобучение модели (уже проверяли на DINOv2 — ядро/пиксельный эмбеддер остаётся быстрее и точнее
на этих данных, см. docs/benchmarks). Простая, проверяемая надстройка: пары «неверный → верный» файл.
Если неверный файл снова окажется среди результатов похожего запроса, верный показывается первым."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Correction:
    wrong_rel_path: str
    correct_rel_path: str
    created_at: float


def load_corrections(path: Path) -> list[Correction]:
    """Пустой список, если файла нет или он повреждён — исправления необязательны для работы поиска."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(raw, list):
        return []
    corrections = []
    for item in raw:
        try:
            corrections.append(
                Correction(str(item["wrong"]), str(item["correct"]), float(item["created_at"]))
            )
        except (KeyError, TypeError, ValueError):
            continue  # одна повреждённая запись не должна терять остальные
    return corrections


def save_corrections(corrections: list[Correction], path: Path) -> None:
    payload = [
        {"wrong": c.wrong_rel_path, "correct": c.correct_rel_path, "created_at": c.created_at} for c in corrections
    ]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def new_correction(wrong_rel_path: str, correct_rel_path: str, now: float | None = None) -> Correction:
    return Correction(wrong_rel_path, correct_rel_path, now if now is not None else time.time())
