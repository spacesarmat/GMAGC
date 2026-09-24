"""Сборка и запуск ПК-приложения на Qt."""

from __future__ import annotations

import sys
from collections.abc import Callable

from PySide6.QtWidgets import QApplication, QLabel, QWidget

from gmagc_common import i18n
from gmagc_desktop import lang_en  # noqa: F401 - при импорте регистрирует английские переводы
from gmagc_desktop.qt.controller import AppController, Executor
from gmagc_desktop.qt.screens.library import LibraryScreen
from gmagc_desktop.qt.theme import stylesheet
from gmagc_desktop.qt.window import MainWindow
from gmagc_desktop.service.logging_setup import setup_logging
from gmagc_desktop.service.search_service import SearchService
from gmagc_desktop.service.settings import data_dir


def _placeholder(text: str) -> QWidget:
    """Заглушка экрана, который ещё не перенесён с Flet."""
    label = QLabel(text)
    label.setProperty("role", "muted")
    return label


def build_window(
    service: SearchService,
    executor: Executor | None = None,
    pick_directory: Callable[[QWidget | None], str] | None = None,
) -> MainWindow:
    controller = AppController(service, executor)
    library = LibraryScreen(controller, pick_directory) if pick_directory else LibraryScreen(controller)
    screens = {
        "search": _placeholder("Поиск — переносится"),
        "phone": _placeholder("Телефон — переносится"),
        "library": library,
        "settings": _placeholder("Настройки — переносятся"),
    }
    window = MainWindow(controller, screens)
    controller.load()
    return window


def run(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    service = SearchService(data_dir())
    i18n.set_language(service.saved_language())
    setup_logging(service.data_dir)
    app.setStyleSheet(stylesheet(service.settings.large_text))
    window = build_window(service)
    window.show()
    return app.exec()
