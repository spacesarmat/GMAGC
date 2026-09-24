"""Полоса обновления Android-приложения: «Доступна версия…», «Скачать», «Пропустить», ручная проверка."""

from __future__ import annotations

import asyncio

import flet as ft

from gmagc_common.i18n import t
from gmagc_common.updates import UpdateCheckError
from gmagc_mobile.about import VERSION
from gmagc_mobile.updates import UpdateNotice, UpdateTracker


class UpdateBar:
    def __init__(self, tracker: UpdateTracker, launcher, page: ft.Page, delay: float = 3.0):
        self.tracker = tracker
        self.launcher = launcher
        self.page = page
        self.delay = delay
        self.notice: UpdateNotice | None = None

        self.text = ft.Text("", weight=ft.FontWeight.BOLD)
        self.download_button = ft.Button(t("Скачать"), on_click=self.on_download)
        self.skip_button = ft.TextButton(content=ft.Text(t("Пропустить")), on_click=self.on_skip)
        self.container = ft.Container(
            ft.Column([self.text, ft.Row([self.download_button, self.skip_button], spacing=8, wrap=True)], spacing=6),
            padding=10,
            border_radius=6,
            bgcolor=ft.Colors.BLUE_100,
            visible=False,
        )
        self.status = ft.Text("", size=12)
        self.check_button = ft.TextButton(content=ft.Text(t("Проверить обновления"), size=12), on_click=self.on_check_now)

    async def startup(self) -> None:
        """Фоновая проверка через delay секунд после запуска; сбой сети ничего не показывает."""
        await asyncio.sleep(self.delay)
        await self.check(force=False)

    async def check(self, *, force: bool) -> None:
        try:
            notice = await self.tracker.check(force=force)
        except UpdateCheckError as error:
            if force:
                self._status(str(error))
            return
        except Exception as error:  # noqa: BLE001
            if force:
                self._status(t("Ошибка проверки обновлений: {error}", error=error))
            return
        if notice is None:
            self._status(t("Установлена последняя версия ({VERSION})", VERSION=VERSION) if force else "")
            return
        self.notice = notice
        self.text.value = t("Доступна версия {version} (у вас {VERSION})", version=notice.version, VERSION=VERSION)
        self.container.visible = True
        self._status("")

    def _status(self, text: str) -> None:
        self.status.value = text
        self.page.update()

    async def on_check_now(self, _event) -> None:
        self._status(t("Проверяю обновления…"))
        await self.check(force=True)

    async def on_download(self, _event) -> None:
        if self.notice is None:
            return
        try:
            await self.launcher.launch_url(self.notice.url)
        except Exception as error:  # noqa: BLE001
            self._status(t("Не удалось открыть ссылку на загрузку: {error}", error=error))
            return
        try:
            # закрываем приложение: иначе после установки APK рядом с новой версией остаётся висеть старая
            await self.page.window.close()
        except Exception:  # noqa: BLE001 - закрытие не должно ронять экран, если недоступно на платформе
            pass

    async def on_skip(self, _event) -> None:
        if self.notice is not None:
            await self.tracker.skip(self.notice.version)
        self.container.visible = False
        self.page.update()
