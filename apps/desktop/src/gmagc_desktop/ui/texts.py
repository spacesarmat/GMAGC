"""Тексты интерфейса, которые можно проверить без окна."""

from __future__ import annotations

import time

from gmagc_common.i18n import FAMILIES_EN, FAMILIES_RU, FILES_EN, FILES_RU, plural, t
from gmagc_desktop.service.results import LOW_CONFIDENCE_SCORE, IndexStatus, Outcome, SearchOutcome


def _number(value: int) -> str:
    return f"{value:,}".replace(",", "\u00a0")


def status_text(status: IndexStatus | None) -> str:
    if status is None:
        return t("Индекс не построен")
    text = t(
        "{number} {files}, {number2} {families}",
        number=_number(status.files),
        files=plural(status.files, FILES_RU, FILES_EN),
        number2=_number(status.families),
        families=plural(status.families, FAMILIES_RU, FAMILIES_EN),
    )
    if status.skipped:
        text += t(", пропущено {number}", number=_number(status.skipped))
    if status.transient:
        text += t(", нечитаемо сейчас {number} (повторю при обновлении)", number=_number(status.transient))
    if status.stale:
        text += t(". Библиотека изменилась — обновите индекс")
    return text


def score_text(score: float) -> str:
    return f"{min(max(score, 0.0), 1.0) * 100:.1f}%"


def outcome_message(kind: Outcome) -> str | None:
    if kind is Outcome.LOW_CONFIDENCE:
        return t(
            "Оценка ниже {percent}%: похоже, такого гобо в библиотеке нет. Ниже самые близкие.",
            percent=int(LOW_CONFIDENCE_SCORE * 100),
        )
    if kind is Outcome.NO_PROJECTION:
        return t("Проекция на фото не найдена: переснимите ближе, затемните фон.")
    return None


def _stamp(when: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(when))


def source_text(when: float, client: str) -> str:
    return t("Запрос с телефона {client}, {stamp}", client=client, stamp=_stamp(when))


def history_text(when: float, client: str, outcome: SearchOutcome) -> str:
    if outcome.kind is Outcome.NO_PROJECTION or not outcome.results:
        return t("{stamp} · {client} · проекция не найдена", stamp=_stamp(when), client=client)
    top = outcome.results[0]
    return f"{_stamp(when)} · {client} · {top.name} {score_text(top.score)}"
