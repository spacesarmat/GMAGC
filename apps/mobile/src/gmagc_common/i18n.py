"""Русский и английский языки интерфейса: `t("русский текст")` возвращает перевод на текущий язык.

Только стандартная библиотека: пакет без изменений копируется в приложения (scripts/sync_common.py).
Ключ перевода — сам русский текст (как в gettext); английские переводы — словари «русский → английский»,
которые модули регистрируют через `register("en", {...})`. Непереведённый текст остаётся русским.
"""

from __future__ import annotations

import contextlib
import locale
import sys

LANG_AUTO = "auto"
LANG_RU = "ru"
LANG_EN = "en"
CHOICES = (LANG_AUTO, LANG_RU, LANG_EN)

FILES_RU = ("файл", "файла", "файлов")  # слово «файл» в формах для plural(): встречается на многих экранах
FILES_EN = ("file", "files")
FAMILIES_RU = ("семейство", "семейства", "семейств")
FAMILIES_EN = ("family", "families")
RESULTS_RU = ("результат", "результата", "результатов")
RESULTS_EN = ("result", "results")

_current = LANG_RU
_catalogs: dict[str, dict[str, str]] = {}


def normalize_choice(value: object) -> str:
    """Выбор языка из настроек: «auto», «ru» или «en»; всё остальное считается «auto»."""
    text = str(value).strip().lower() if value is not None else ""
    return text if text in CHOICES else LANG_AUTO


def detect_system_locale() -> str | None:
    """Имя языка системы (например, «ru-RU») или None, если определить не удалось."""
    if sys.platform == "win32":
        with contextlib.suppress(Exception):
            import ctypes

            buffer = ctypes.create_unicode_buffer(85)
            if ctypes.windll.kernel32.GetUserDefaultLocaleName(buffer, len(buffer)):
                return buffer.value
    with contextlib.suppress(Exception):
        name = locale.getlocale()[0]
        if name:
            return name
    return None


def detect_system_language(locale_name: str | None) -> str:
    """Язык интерфейса по имени локали: русский для русских локалей и когда язык неизвестен, иначе английский."""
    name = (locale_name or "").strip().lower()
    if not name:
        return LANG_RU
    return LANG_RU if name.startswith("ru") or name.startswith("russian") else LANG_EN


def set_language(choice: object, system_locale: str | None = None) -> str:
    """Включает язык («auto» — по системе; `system_locale` подменяет определение, для тестов и событий Flet)."""
    global _current
    picked = normalize_choice(choice)
    if picked == LANG_AUTO:
        picked = detect_system_language(system_locale if system_locale is not None else detect_system_locale())
    _current = picked
    return _current


def current_language() -> str:
    return _current


def register(language: str, catalog: dict[str, str]) -> None:
    """Добавляет переводы (несколько вызовов дополняют друг друга)."""
    _catalogs.setdefault(language, {}).update(catalog)


def reset_catalogs() -> None:
    """Забывает все переводы (нужно тестам)."""
    _catalogs.clear()


def t(text: str, /, **params: object) -> str:
    """Текст на текущем языке; `{имя}` в тексте подставляется из параметров уже после перевода."""
    translated = text if _current == LANG_RU else _catalogs.get(_current, {}).get(text, text)
    if not params:
        return translated
    try:
        return translated.format(**params)
    except (KeyError, IndexError, ValueError):  # сбой шаблона не должен ронять интерфейс
        return translated


def plural(number: int, ru: tuple[str, str, str], en: tuple[str, str]) -> str:
    """Форма слова по числу: русские (1 / 2–4 / 5 и более) или английские (1 / остальные) по текущему языку."""
    if _current != LANG_RU:
        return en[0] if number == 1 else en[1]
    tail, hundreds = number % 10, number % 100
    if tail == 1 and hundreds != 11:
        return ru[0]
    if 2 <= tail <= 4 and not 12 <= hundreds <= 14:
        return ru[1]
    return ru[2]


def language_name(choice: str) -> str:
    """Название варианта в списке выбора: языки — на своём языке, «авто» — на текущем."""
    if choice == LANG_RU:
        return "Русский"
    if choice == LANG_EN:
        return "English"
    return "Авто (как в системе)" if _current == LANG_RU else "Auto (system)"
