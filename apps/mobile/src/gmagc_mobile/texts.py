"""Тексты Android-приложения, которые можно проверить без окна."""

from __future__ import annotations

from gmagc_common.protocol import OUTCOME_LOW_CONFIDENCE, OUTCOME_NO_PROJECTION, Connection, MatchResponse, Status
from gmagc_mobile import client
from gmagc_mobile.client import ClientError

NO_INDEX_NOTE = "На ПК ещё не построен индекс: выберите папку библиотеки в приложении на ПК."


def _number(value: int) -> str:
    return f"{value:,}".replace(",", "\u00a0")


def error_text(error: ClientError) -> str:
    kind = error.kind
    if kind == client.UNREACHABLE:
        return (
            "Нет связи с ПК. Телефон и ПК должны быть в одной сети Wi-Fi, GMAGC должен быть запущен на ПК, "
            f"а брандмауэр Windows должен разрешать доступ. ({error.message})"
        )
    if kind == client.UNAUTHORIZED:
        return "Неверный код доступа. Код показан в приложении на ПК; если его сменили, введите новый."
    if kind == client.RATE_LIMITED:
        return f"Слишком много неверных кодов. Подождите {error.retry_after or 30} с."
    if kind == client.NO_INDEX:
        return "На ПК не выбрана библиотека или индекс ещё не построен. Постройте индекс в приложении на ПК."
    if kind == client.BAD_IMAGE:
        return "ПК не смог прочитать изображение. Попробуйте снять ещё раз."
    if kind == client.TOO_LARGE:
        return "Изображение слишком большое для отправки."
    if kind == client.PROTOCOL:
        return error.message
    return f"Ошибка на ПК: {error.message}"


def outcome_message(outcome: str) -> str | None:
    if outcome == OUTCOME_LOW_CONFIDENCE:
        return "Совпадение ненадёжно: похоже, такого гобо в библиотеке нет. Ниже самые близкие."
    if outcome == OUTCOME_NO_PROJECTION:
        return "Проекция на фото не найдена: переснимите ближе, затемните фон."
    return None


def score_text(score: float) -> str:
    return f"{min(max(score, 0.0), 1.0) * 100:.1f}%"


def status_line(connection: Connection, status: Status) -> str:
    line = f"Подключено: {connection.host}:{connection.port}"
    if not status.indexed:
        return line + " · индекс на ПК не построен"
    line += f" · {_number(status.files)} файлов"
    if status.indexing:
        line += " (идёт индексация)"
    return line


def zoom_text(zoom: float) -> str:
    return f"×{zoom:.1f}"


def history_text(response: MatchResponse) -> str:
    if response.outcome == OUTCOME_NO_PROJECTION or not response.results:
        return "проекция не найдена"
    top = response.results[0]
    return f"{top.name} {score_text(top.score)}"


def share_text(response: MatchResponse) -> str:
    if response.outcome == OUTCOME_NO_PROJECTION or not response.results:
        return "GMAGC: проекция на фото не найдена"
    top = response.results[0]
    return f"GMAGC нашёл: {top.name} ({score_text(top.score)})\n{top.path}"
