"""Окно с просьбой поддержать автора (ПК): расписание, кнопки, постоянная ссылка."""

from __future__ import annotations

import time
import webbrowser
from collections.abc import Callable

import flet as ft

from gmagc_common.i18n import t
from gmagc_common.support import (
    AUTHOR_TELEGRAM_URL,
    CHANNEL_URL,
    DIALOG_TEXT,
    DIALOG_TITLE,
    LATER,
    NEVER,
    SUPPORT,
    SUPPORT_URL,
    after_answer,
    register_launch,
    should_ask,
)
from gmagc_desktop.service.search_service import SearchService


class SupportPrompt:
    def __init__(
        self,
        page: ft.Page,
        service: SearchService,
        *,
        open_url: Callable[[str], object] = webbrowser.open,
        now: Callable[[], float] = time.time,
        delay: float = 8.0,
        busy: Callable[[], bool] = lambda: False,
    ):
        self.page = page
        self.service = service
        self.open_url = open_url
        self.now = now
        self.delay = delay
        self.busy = busy
        self.link = ft.TextButton(content=ft.Text(t("Поддержать автора"), size=12), on_click=self.on_open_link)
        self.telegram_link = ft.TextButton(content=ft.Text(t("Telegram автора"), size=12), on_click=self.on_open_telegram)
        self.channel_link = ft.TextButton(content=ft.Text(t("Канал GMAGC"), size=12), on_click=self.on_open_channel)
        self._dialog: ft.AlertDialog | None = None

    def start(self) -> None:
        """Считает запуск и, если пора, показывает окно через delay секунд (если приложение не занято)."""
        state = register_launch(self.service.support_state())
        self.service.save_support_state(state)
        if should_ask(state, self.now()):
            self.page.run_thread(self._show_later)

    def _show_later(self) -> None:
        time.sleep(self.delay)
        if not self.busy():
            self.show()

    def show(self) -> None:
        self._dialog = ft.AlertDialog(
            title=ft.Text(DIALOG_TITLE),
            content=ft.Text(DIALOG_TEXT),
            actions=[
                ft.Button(t("Поддержать"), on_click=self.on_support),
                ft.TextButton(content=ft.Text(t("Позже")), on_click=self.on_later),
                ft.TextButton(content=ft.Text(t("Больше не показывать")), on_click=self.on_never),
            ],
        )
        self.page.show_dialog(self._dialog)

    def _answer(self, answer: str) -> None:
        state = after_answer(self.service.support_state(), self.now(), answer)
        self.service.save_support_state(state)
        self.page.pop_dialog()
        self._dialog = None

    def on_support(self, _event) -> None:
        self.open_url(SUPPORT_URL)
        self._answer(SUPPORT)

    def on_later(self, _event) -> None:
        self._answer(LATER)

    def on_never(self, _event) -> None:
        self._answer(NEVER)

    def on_open_link(self, _event) -> None:
        self.open_url(SUPPORT_URL)

    def on_open_telegram(self, _event) -> None:
        self.open_url(AUTHOR_TELEGRAM_URL)

    def on_open_channel(self, _event) -> None:
        self.open_url(CHANNEL_URL)
