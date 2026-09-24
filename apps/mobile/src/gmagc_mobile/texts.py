"""Тексты Android-приложения, которые можно проверить без окна."""

from __future__ import annotations

from gmagc_common.i18n import FILES_EN, FILES_RU, plural, t
from gmagc_common.protocol import OUTCOME_LOW_CONFIDENCE, OUTCOME_NO_PROJECTION, Connection, MatchResponse, Status
from gmagc_mobile import client
from gmagc_mobile.client import ClientError


def _number(value: int) -> str:
    return f"{value:,}".replace(",", "\u00a0")


def error_text(error: ClientError) -> str:
    kind = error.kind
    if kind == client.UNREACHABLE:
        return t(
            "Нет связи с ПК. Телефон и ПК должны быть в одной сети Wi-Fi, GMAGC должен быть запущен на ПК, "
            "а брандмауэр Windows должен разрешать доступ. ({message})",
            message=error.message,
        )
    if kind == client.UNAUTHORIZED:
        return t("Неверный код доступа. Код показан в приложении на ПК; если его сменили, введите новый.")
    if kind == client.RATE_LIMITED:
        return t("Слишком много неверных кодов. Подождите {seconds} с.", seconds=error.retry_after or 30)
    if kind == client.NO_INDEX:
        return t("На ПК не выбрана библиотека или индекс ещё не построен. Постройте индекс в приложении на ПК.")
    if kind == client.BAD_IMAGE:
        return t("ПК не смог прочитать изображение. Попробуйте снять ещё раз.")
    if kind == client.TOO_LARGE:
        return t("Изображение слишком большое для отправки.")
    if kind == client.NO_TARGET:
        return t("На ПК не найдена папка для grandMA3 или grandMA2: укажите её на экране «Настройки» ПК-приложения.")
    if kind == client.BAD_PROFILE:
        return t("ПК не принял профиль: {message}", message=error.message)
    if kind == client.PROTOCOL:
        return error.message
    return t("Ошибка на ПК: {message}", message=error.message)


def outcome_message(outcome: str) -> str | None:
    if outcome == OUTCOME_LOW_CONFIDENCE:
        return t("Совпадение ненадёжно: похоже, такого гобо в библиотеке нет. Ниже самые близкие.")
    if outcome == OUTCOME_NO_PROJECTION:
        return t("Проекция на фото не найдена: переснимите ближе, затемните фон.")
    return None


def score_text(score: float) -> str:
    return f"{min(max(score, 0.0), 1.0) * 100:.1f}%"


def status_line(connection: Connection, status: Status) -> str:
    line = t("Подключено: {host}:{port}", host=connection.host, port=connection.port)
    if not status.indexed:
        return line + t(" · индекс на ПК не построен")
    line += t(" · {number} {files}", number=_number(status.files), files=plural(status.files, FILES_RU, FILES_EN))
    if status.indexing:
        line += t(" (идёт индексация)")
    return line


def zoom_text(zoom: float) -> str:
    return f"×{zoom:.1f}"


def history_text(response: MatchResponse) -> str:
    if response.outcome == OUTCOME_NO_PROJECTION or not response.results:
        return t("проекция не найдена")
    top = response.results[0]
    return f"{top.name} {score_text(top.score)}"


def share_text(response: MatchResponse) -> str:
    if response.outcome == OUTCOME_NO_PROJECTION or not response.results:
        return t("GMAGC: проекция на фото не найдена")
    top = response.results[0]
    return t(
        "GMAGC нашёл: {name} ({score_text})\n{path}", name=top.name, score_text=score_text(top.score), path=top.path
    )


def no_index_note() -> str:
    return t("На ПК ещё не построен индекс: выберите папку библиотеки в приложении на ПК.")
