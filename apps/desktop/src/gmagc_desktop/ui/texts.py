"""Тексты интерфейса, которые можно проверить без окна."""

from __future__ import annotations

from gmagc_desktop.service.results import LOW_CONFIDENCE_SCORE, IndexStatus, Outcome


def _number(value: int) -> str:
    return f"{value:,}".replace(",", "\u00a0")


def status_text(status: IndexStatus | None) -> str:
    if status is None:
        return "Индекс не построен"
    text = f"{_number(status.files)} файлов, {_number(status.families)} семейств"
    if status.skipped:
        text += f", пропущено {_number(status.skipped)}"
    if status.transient:
        text += f", нечитаемо сейчас {_number(status.transient)} (повторю при обновлении)"
    return text


def score_text(score: float) -> str:
    return f"{min(max(score, 0.0), 1.0) * 100:.1f}%"


def outcome_message(kind: Outcome) -> str | None:
    if kind is Outcome.LOW_CONFIDENCE:
        return f"Оценка ниже {int(LOW_CONFIDENCE_SCORE * 100)}%: похоже, такого гобо в библиотеке нет. Ниже самые близкие."
    if kind is Outcome.NO_PROJECTION:
        return "Проекция на фото не найдена: переснимите ближе, затемните фон."
    return None
