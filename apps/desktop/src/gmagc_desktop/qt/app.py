"""Сборка и запуск ПК-приложения на Qt."""

from __future__ import annotations

import sys
import webbrowser
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QWidget

from gmagc_common import i18n
from gmagc_desktop import lang_en  # noqa: F401 - при импорте регистрирует английские переводы
from gmagc_desktop.qt.controller import AppController, Executor
from gmagc_desktop.qt.screens.library import LibraryScreen
from gmagc_desktop.qt.screens.phone import PhoneScreen
from gmagc_desktop.qt.screens.search import SearchScreen
from gmagc_desktop.qt.screens.settings import SettingsScreen
from gmagc_desktop.qt.support import SupportLinks, SupportPrompt
from gmagc_desktop.qt.theme import stylesheet
from gmagc_desktop.qt.updates import UpdateBar, UpdateController, UpdateSettings, default_quit
from gmagc_desktop.qt.window import MainWindow
from gmagc_desktop.service.logging_setup import setup_logging
from gmagc_desktop.service.search_service import SearchService
from gmagc_desktop.service.settings import data_dir
from gmagc_desktop.update.manager import UpdateManager


def apply_theme(large_text: bool) -> None:
    app = QApplication.instance()
    if app is not None:
        app.setStyleSheet(stylesheet(large_text))


def rebuild_window(window: MainWindow, screen: str = "settings") -> MainWindow:
    """Собирает окно заново на тех же службах (язык сменился): индекс, настройки и сервер сохраняются,
    временное состояние экранов (текущее фото и результаты, история запросов) теряется."""
    service, executor, pick_directory, services = window.build_args
    services = {**services, "server": window.controller._server or services.get("server"), "support": False}
    fresh = build_window(service, executor, pick_directory, **services)
    fresh.resize(window.size())
    fresh.move(window.pos())
    fresh.show_screen(screen)
    fresh.show()
    start_services(fresh, first_run=False)
    window.hide()
    window.deleteLater()
    return fresh


def start_services(window: MainWindow, *, first_run: bool = True) -> None:
    """Сервер для телефона, проверка обновлений и (при первом запуске) окно поддержки."""
    window.controller.start_server_if_enabled()
    if window.update_controller is not None:
        window.update_controller.start()
    if first_run and window.support_prompt is not None:
        window.support_prompt.start()


def _copy_to_clipboard(text: str) -> None:
    QGuiApplication.clipboard().setText(text)


def _placeholder(text: str) -> QWidget:
    """Заглушка экрана, который ещё не перенесён с Flet."""
    label = QLabel(text)
    label.setProperty("role", "muted")
    return label


def build_window(
    service: SearchService,
    executor: Executor | None = None,
    pick_directory: Callable[[QWidget | None], str] | None = None,
    **services,
) -> MainWindow:
    """Окно со всеми экранами; `services` подменяются в тестах: server, addresses, qr, check, open_url, log_path
    для контроллера; updates, update_delay, quit_app, support, support_delay, support_ask — для обновлений и поддержки."""
    original = dict(services)
    updates = services.pop("updates", None)
    update_delay = services.pop("update_delay", 5.0)
    quit_app = services.pop("quit_app", default_quit)
    support = services.pop("support", False)
    support_delay = services.pop("support_delay", 8.0)
    support_ask = services.pop("support_ask", None)
    controller = AppController(service, executor, copy_text=_copy_to_clipboard, **services)
    open_url = services.get("open_url", webbrowser.open)
    update_controller = None
    update_bar = None
    extra: list[QWidget] = []
    if updates is not None:
        update_controller = UpdateController(
            service, updates, controller.executor, open_url=open_url, quit_app=quit_app, delay=update_delay
        )
        update_bar = UpdateBar(update_controller)
        extra.append(UpdateSettings(update_controller))
    if support:
        extra.append(SupportLinks(open_url))
    library = LibraryScreen(controller, pick_directory) if pick_directory else LibraryScreen(controller)
    search = SearchScreen(controller)
    screens = {
        "search": search,
        "phone": PhoneScreen(controller),
        "library": library,
        "settings": SettingsScreen(controller, extra_sections=extra),
    }
    window = MainWindow(controller, screens, top=update_bar)
    window.build_args = (service, executor, pick_directory, original)  # для пересборки при смене языка
    window.update_controller = update_controller
    window.support_prompt = (
        SupportPrompt(
            service,
            window,
            open_url=open_url,
            delay=support_delay,
            busy=lambda: controller.busy,
            **({"ask": support_ask} if support_ask else {}),
        )
        if support
        else None
    )
    controller.screen_requested.connect(window.show_screen)
    controller.large_text_changed.connect(apply_theme)

    def paste() -> None:
        """Ctrl+V — вставить фото из буфера обмена (в полях ввода вставка обычная)."""
        if isinstance(QApplication.focusWidget(), QLineEdit):
            return
        window.show_screen("search")
        search.on_paste()

    window.paste_shortcut = QShortcut(QKeySequence.StandardKey.Paste, window, activated=paste)
    window.refresh_shortcut = QShortcut(QKeySequence(Qt.Key.Key_F5), window, activated=controller.start_index)
    controller.load()
    return window


def run(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    service = SearchService(data_dir())
    i18n.set_language(service.saved_language())
    log_path = setup_logging(service.data_dir)
    app.setStyleSheet(stylesheet(service.settings.large_text))
    window = build_window(
        service, updates=UpdateManager(service, data_dir()), support=True, log_path=log_path, quit_app=default_quit
    )
    window.show()
    start_services(window)
    holder = {"window": window}
    app.aboutToQuit.connect(lambda: holder["window"].controller.stop_server())

    def attach(current: MainWindow) -> None:
        def on_language(_choice: str) -> None:
            fresh = rebuild_window(current)
            holder["window"] = fresh
            attach(fresh)

        current.controller.language_changed.connect(on_language)

    attach(window)
    return app.exec()
