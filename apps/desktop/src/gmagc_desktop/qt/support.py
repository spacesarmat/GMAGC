"""Просьба поддержать автора на Qt: расписание показа, диалог из трёх кнопок, постоянные ссылки в настройках."""

from __future__ import annotations

import time
import webbrowser
from collections.abc import Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox, QPushButton, QVBoxLayout, QWidget

from gmagc_common.i18n import t
from gmagc_common.support import (
    AUTHOR_TELEGRAM_URL,
    CHANNEL_URL,
    LATER,
    NEVER,
    SUPPORT,
    SUPPORT_URL,
    after_answer,
    dialog_text,
    dialog_title,
    register_launch,
    should_ask,
)
from gmagc_desktop.service.search_service import SearchService


def ask_dialog(parent: QWidget | None) -> str:
    """Показывает диалог и возвращает ответ пользователя: SUPPORT, LATER или NEVER (закрытие окна — LATER)."""
    box = QMessageBox(parent)
    box.setWindowTitle(dialog_title())
    box.setText(dialog_text())
    support = box.addButton(t("Поддержать"), QMessageBox.ButtonRole.AcceptRole)
    box.addButton(t("Позже"), QMessageBox.ButtonRole.RejectRole)
    never = box.addButton(t("Больше не показывать"), QMessageBox.ButtonRole.DestructiveRole)
    box.exec()
    clicked = box.clickedButton()
    if clicked is support:
        return SUPPORT
    if clicked is never:
        return NEVER
    return LATER


class SupportPrompt:
    def __init__(
        self,
        service: SearchService,
        parent: QWidget | None = None,
        *,
        open_url: Callable[[str], object] = webbrowser.open,
        now: Callable[[], float] = time.time,
        delay: float = 8.0,
        busy: Callable[[], bool] = lambda: False,
        ask: Callable[[QWidget | None], str] = ask_dialog,
    ):
        self.service = service
        self.parent = parent
        self.open_url = open_url
        self.now = now
        self.delay = delay
        self.busy = busy
        self.ask = ask

    def start(self) -> None:
        """Считает запуск и, если пора, показывает окно через delay секунд (если приложение не занято)."""
        state = register_launch(self.service.support_state())
        self.service.save_support_state(state)
        if not should_ask(state, self.now()):
            return
        if self.delay <= 0:
            self.show_if_idle()
        else:
            QTimer.singleShot(int(self.delay * 1000), self.show_if_idle)

    def show_if_idle(self) -> None:
        if not self.busy():
            self.show()

    def show(self) -> None:
        answer = self.ask(self.parent)
        if answer == SUPPORT:
            self.open_url(SUPPORT_URL)
        state = after_answer(self.service.support_state(), self.now(), answer)
        self.service.save_support_state(state)


class SupportLinks(QWidget):
    """Постоянные ссылки в «Настройках»: поддержать автора, его Telegram, канал."""

    def __init__(self, open_url: Callable[[str], object] = webbrowser.open):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.buttons: dict[str, QPushButton] = {}
        for key, caption, url in (
            ("support", t("Поддержать автора"), SUPPORT_URL),
            ("telegram", t("Telegram автора"), AUTHOR_TELEGRAM_URL),
            ("channel", t("Канал GMAGC"), CHANNEL_URL),
        ):
            button = QPushButton(caption)
            button.setProperty("role", "link")
            button.setStyleSheet("text-align: left;")
            button.clicked.connect(lambda _checked=False, address=url: open_url(address))
            layout.addWidget(button)
            self.buttons[key] = button
