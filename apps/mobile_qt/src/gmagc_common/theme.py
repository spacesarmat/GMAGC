"""Цвета темы: раньше общие для ПК и телефона, теперь у каждой платформы свой акцент/палитра."""

from __future__ import annotations

# Затравка для Material 3 (color_scheme_seed у Flet) — используется телефоном (тема всегда тёмная).
# Синий в тон фона значка (#040c1f).
SEED_COLOR = "#2F6FED"

# Акцент экрана камеры/подключения на телефоне (рамка-видоискатель, кольцо кнопки съёмки) — всегда
# тёмный фон с этим цианом, независимо от системной темы (решение пользователя по референсу дизайна).
MOBILE_ACCENT_COLOR = "#29D9FF"

# Палитра ПК-приложения — из макета пользователя (боковая панель, тёмная тема без переключателя,
# бирюзовый акцент), отдельная от синей SEED_COLOR телефона.
DESKTOP_BG = "#090c10"
DESKTOP_PANEL = "#0d1117"
DESKTOP_PANEL2 = "#11171e"
DESKTOP_LINE = "#242d36"
DESKTOP_STRONG = "#394551"
DESKTOP_TEXT = "#f2f5f7"
DESKTOP_MUTED = "#8995a2"
DESKTOP_DIM = "#56616d"
DESKTOP_ACCENT = "#36c5ef"
DESKTOP_OK = "#63d3a0"

# Пороги совпадения, при которых оценка результата подсвечивается как надёжная/сомнительная/ненадёжная.
# SCORE_LOW совпадает с LOW_CONFIDENCE_SCORE ядра — там же, где решают, показывать ли предупреждение
# "совпадение ненадёжно" (gmagc_desktop.service.results.LOW_CONFIDENCE_SCORE).
SCORE_GOOD = 0.85
SCORE_LOW = 0.72


def score_band(score: float) -> str:
    """"good" / "low" / "bad" — для цвета бейджа оценки на карточке результата (ПК и телефон)."""
    if score >= SCORE_GOOD:
        return "good"
    if score >= SCORE_LOW:
        return "low"
    return "bad"
