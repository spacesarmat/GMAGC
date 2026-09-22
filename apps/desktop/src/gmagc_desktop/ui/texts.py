"""Тексты интерфейса, которые можно проверить без окна."""

from __future__ import annotations

import time

from gmagc_desktop.service.results import LOW_CONFIDENCE_SCORE, IndexStatus, Outcome, SearchOutcome


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
    if status.stale:
        text += ". Библиотека изменилась — обновите индекс"
    return text


def score_text(score: float) -> str:
    return f"{min(max(score, 0.0), 1.0) * 100:.1f}%"


def outcome_message(kind: Outcome) -> str | None:
    if kind is Outcome.LOW_CONFIDENCE:
        return f"Оценка ниже {int(LOW_CONFIDENCE_SCORE * 100)}%: похоже, такого гобо в библиотеке нет. Ниже самые близкие."
    if kind is Outcome.NO_PROJECTION:
        return "Проекция на фото не найдена: переснимите ближе, затемните фон."
    return None


def _stamp(when: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(when))


def source_text(when: float, client: str) -> str:
    return f"Запрос с телефона {client}, {_stamp(when)}"


def history_text(when: float, client: str, outcome: SearchOutcome) -> str:
    if outcome.kind is Outcome.NO_PROJECTION or not outcome.results:
        return f"{_stamp(when)} · {client} · проекция не найдена"
    top = outcome.results[0]
    return f"{_stamp(when)} · {client} · {top.name} {score_text(top.score)}"
