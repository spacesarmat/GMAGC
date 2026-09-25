"""Просьба поддержать автора: адрес и расписание показа окна (только стандартная библиотека)."""

from __future__ import annotations

from dataclasses import dataclass, replace

from gmagc_common.i18n import t

SUPPORT_URL = "https://boosty.to/djmaker/donate"
AUTHOR_TELEGRAM_URL = "https://t.me/Andy_bum"  # Telegram автора: постоянная ссылка на экранах
CHANNEL_URL = "https://t.me/gmagclight"  # канал о GMAGC: постоянная ссылка на экранах
FIRST_ASK_LAUNCH = 5  # первое окно не раньше пятого запуска
REMIND_AFTER_SECONDS = 30 * 24 * 60 * 60  # «Позже» напоминает через 30 суток

SUPPORT = "support"
LATER = "later"
NEVER = "never"


def dialog_title() -> str:
    return t("Поддержать автора")


def dialog_text() -> str:
    return t(
        "GMAGC бесплатна, её делает один человек. Если программа помогает вам в работе, "
        "вы можете поддержать автора добровольным взносом. Спасибо!"
    )


@dataclass(frozen=True)
class SupportState:
    launches: int = 0
    last_ask: float = 0.0
    muted: bool = False


def register_launch(state: SupportState) -> SupportState:
    return replace(state, launches=state.launches + 1)


def should_ask(state: SupportState, now: float) -> bool:
    if state.muted or state.launches < FIRST_ASK_LAUNCH:
        return False
    return state.last_ask <= 0 or state.last_ask > now or now - state.last_ask >= REMIND_AFTER_SECONDS


def after_answer(state: SupportState, now: float, answer: str) -> SupportState:
    if answer in (SUPPORT, NEVER):
        return replace(state, last_ask=now, muted=True)
    if answer == LATER:
        return replace(state, last_ask=now)
    raise ValueError(t("неизвестный ответ: {answer}", answer=answer))
