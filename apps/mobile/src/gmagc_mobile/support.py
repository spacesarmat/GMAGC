"""Окно с просьбой поддержать автора (Android): расписание в SharedPreferences, кнопки, постоянная ссылка."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

import flet as ft

from gmagc_common.support import (
    AUTHOR_TELEGRAM_URL,
    CHANNEL_URL,
    DIALOG_TEXT,
    DIALOG_TITLE,
    LATER,
    NEVER,
    SUPPORT,
    SUPPORT_URL,
    SupportState,
    after_answer,
    register_launch,
    should_ask,
)

KEY_LAUNCHES = "gmagc.support.launches"
KEY_LAST = "gmagc.support.last_ask"
KEY_MUTED = "gmagc.support.muted"


class SupportPrompt:
    def __init__(
        self,
        prefs,
        launcher,
        page: ft.Page,
        *,
        now: Callable[[], float] = time.time,
        delay: float = 8.0,
        busy: Callable[[], bool] = lambda: False,
    ):
        self.prefs = prefs
        self.launcher = launcher
        self.page = page
        self.now = now
        self.delay = delay
        self.busy = busy
        # ссылки-кнопки создаёт экран (MobileApp._support_links): они нужны сразу на нескольких экранах,
        # а один и тот же контрол Flet нельзя одновременно вставить в несколько мест дерева

    async def _load(self) -> SupportState:
        try:
            launches = await self.prefs.get(KEY_LAUNCHES)
            last = await self.prefs.get(KEY_LAST)
            muted = await self.prefs.get(KEY_MUTED)
        except Exception:  # noqa: BLE001 - недоступное хранилище: просьбу не показываем
            return SupportState(0, 0.0, True)
        return SupportState(
            launches if isinstance(launches, int) and not isinstance(launches, bool) and launches >= 0 else 0,
            float(last) if isinstance(last, int | float) and not isinstance(last, bool) and last >= 0 else 0.0,
            muted is True,
        )

    async def _save(self, state: SupportState) -> None:
        await self.prefs.set(KEY_LAUNCHES, state.launches)
        await self.prefs.set(KEY_LAST, state.last_ask)
        await self.prefs.set(KEY_MUTED, state.muted)

    async def startup(self) -> None:
        """Считает запуск и, если пора, показывает окно через delay секунд (если приложение не занято)."""
        state = await self._load()
        if state.muted and state.launches == 0:  # хранилище недоступно
            return
        state = register_launch(state)
        await self._save(state)
        if not should_ask(state, self.now()):
            return
        await asyncio.sleep(self.delay)
        if not self.busy():
            self.show()

    def show(self) -> None:
        self.page.show_dialog(
            ft.AlertDialog(
                title=ft.Text(DIALOG_TITLE),
                content=ft.Text(DIALOG_TEXT),
                actions=[
                    ft.Button("Поддержать", on_click=self.on_support),
                    ft.TextButton(content=ft.Text("Позже"), on_click=self.on_later),
                    ft.TextButton(content=ft.Text("Больше не показывать"), on_click=self.on_never),
                ],
            )
        )

    async def _answer(self, answer: str) -> None:
        await self._save(after_answer(await self._load(), self.now(), answer))
        self.page.pop_dialog()

    async def on_support(self, _event) -> None:
        await self._open()
        await self._answer(SUPPORT)

    async def on_later(self, _event) -> None:
        await self._answer(LATER)

    async def on_never(self, _event) -> None:
        await self._answer(NEVER)

    async def on_open_link(self, _event) -> None:
        await self._open()

    async def on_open_telegram(self, _event) -> None:
        await self._open(AUTHOR_TELEGRAM_URL)

    async def on_open_channel(self, _event) -> None:
        await self._open(CHANNEL_URL)

    async def _open(self, url: str = SUPPORT_URL) -> None:
        try:
            await self.launcher.launch_url(url)
        except Exception:  # noqa: BLE001 - нет браузера: окно всё равно закрываем
            pass
