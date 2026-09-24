"""Полоса обновления ПК-приложения: предложение новой версии, загрузка, «Пропустить», ручная проверка."""

from __future__ import annotations

import os
import threading
import time
import webbrowser
from collections.abc import Callable

import flet as ft

from gmagc_common.i18n import t
from gmagc_common.updates import UpdateCheckError
from gmagc_desktop.about import VERSION
from gmagc_desktop.service.search_service import SearchService
from gmagc_desktop.update.installer import InstallCancelled, InstallError
from gmagc_desktop.update.manager import UpdateOffer

EXIT_FALLBACK_SECONDS = 4.0  # если окно не закрылось само, процесс завершается: помощнику нужно, чтобы приложение вышло


def manual_fallback() -> str:
    return t(" Можно скачать обновление вручную на странице релиза.")


class UpdateBar:
    def __init__(
        self,
        page: ft.Page,
        service: SearchService,
        updates,
        *,
        open_url: Callable[[str], object] = webbrowser.open,
        quit_app: Callable[[], None] | None = None,
        delay: float = 5.0,
    ):
        self.page = page
        self.service = service
        self.updates = updates
        self.open_url = open_url
        self.quit_app = quit_app or self._default_quit
        self.delay = delay
        self.offer: UpdateOffer | None = None
        self._cancel = False
        self._installing = False

        self.text = ft.Text("", weight=ft.FontWeight.BOLD)
        self.note = ft.Text("", size=12, visible=False, selectable=True)
        self.progress = ft.ProgressBar(value=0, visible=False)
        self.now_button = ft.Button(t("Обновить"), on_click=self.on_update_now)
        self.page_button = ft.TextButton(content=ft.Text(t("Что нового")), on_click=self.on_release_page)
        self.skip_button = ft.TextButton(content=ft.Text(t("Пропустить")), on_click=self.on_skip)
        self.cancel_button = ft.Button(t("Отмена"), on_click=self.on_cancel, visible=False)
        self.container = ft.Container(
            ft.Column(
                [
                    self.text,
                    self.note,
                    self.progress,
                    ft.Row([self.now_button, self.page_button, self.skip_button, self.cancel_button], spacing=8, wrap=True),
                ],
                spacing=6,
            ),
            padding=10,
            border_radius=6,
            bgcolor=ft.Colors.BLUE_100,
            visible=False,
        )
        self.status = ft.Text("", size=12)
        self.switch = ft.Switch(
            label=t("Проверять обновления при запуске"), value=service.settings.check_updates, on_change=self.on_toggle
        )
        self.check_button = ft.TextButton(content=ft.Text(t("Проверить обновления"), size=12), on_click=self.on_check)

    # ---- проверка ----------------------------------------------------------------
    def start(self) -> None:
        """Фоновая проверка через delay секунд после запуска (если она включена в настройках)."""
        if self.updates is not None and self.service.settings.check_updates:
            self.page.run_thread(self._startup_check)

    def _startup_check(self) -> None:
        self.updates.cleanup()
        time.sleep(self.delay)
        self._run_check(force=False)

    def on_check(self, _event) -> None:
        if self.updates is None:
            return
        self._set_status(t("Проверяю обновления…"))
        self.page.run_thread(lambda: self._run_check(force=True))

    def _run_check(self, *, force: bool) -> None:
        try:
            offer = self.updates.check(force=force)
        except UpdateCheckError as error:
            if force:
                self._set_status(str(error))
            return
        except Exception as error:  # noqa: BLE001 - проверка не должна ни ронять приложение, ни шуметь
            if force:
                self._set_status(t("Ошибка проверки обновлений: {error}", error=error))
            return
        if offer is None:
            self._set_status(t("Установлена последняя версия ({VERSION})", VERSION=VERSION) if force else "")
            return
        self._show_offer(offer)

    def _set_status(self, text: str) -> None:
        self.status.value = text
        self.page.update()

    def _show_offer(self, offer: UpdateOffer) -> None:
        self.offer = offer
        self.text.value = t("Доступна версия {version} (у вас {VERSION})", version=offer.release.version, VERSION=VERSION)
        self.note.value = offer.reason
        self.note.visible = bool(offer.reason)
        self.now_button.visible = offer.can_install
        self.page_button.content.value = t("Что нового") if offer.can_install else t("Открыть страницу релиза")
        self.container.visible = True
        self.status.value = ""
        self.page.update()

    # ---- кнопки полосы ------------------------------------------------------------------
    def on_release_page(self, _event) -> None:
        if self.offer is not None:
            self.open_url(self.offer.release.page_url)

    def on_skip(self, _event) -> None:
        if self.offer is not None:
            self.updates.skip(self.offer.release.version)
        self.container.visible = False
        self.page.update()

    def on_cancel(self, _event) -> None:
        self._cancel = True

    def on_toggle(self, _event) -> None:
        self.service.set_check_updates(bool(self.switch.value))

    def on_update_now(self, _event) -> None:
        if self.offer is None or not self.offer.can_install or self._installing:
            return
        self._installing = True
        self._cancel = False
        self.now_button.disabled = self.skip_button.disabled = self.page_button.disabled = True
        self.cancel_button.visible = True
        self.progress.value = 0
        self.progress.visible = True
        self.note.value = t("Скачивание…")
        self.note.visible = True
        self.page.update()
        self.page.run_thread(self._install_worker)

    def _install_worker(self) -> None:
        try:
            self.updates.install(self.offer, progress=self._on_progress, cancel=lambda: self._cancel)
        except InstallCancelled:
            self._install_failed(t("Загрузка отменена."))
        except (InstallError, UpdateCheckError) as error:
            self._install_failed(f"{error}.{manual_fallback()}".replace("..", "."))
        except Exception as error:  # noqa: BLE001 - рабочий поток обязан показать причину, а не пропасть
            self._install_failed(t("Ошибка обновления: {error}.{fallback}", error=error, fallback=manual_fallback()))
        else:
            self.progress.value = 1.0
            self.text.value = t("Обновление скачано, приложение перезапускается…")
            self.note.visible = False
            self.cancel_button.visible = False
            self.page.update()
            self.quit_app()

    def _on_progress(self, done: int, total: int) -> None:
        self.progress.value = done / total if total else 0
        self.note.value = (
            t("Скачивание: {done} из {total} МБ", done=done // 1_000_000, total=total // 1_000_000)
            if total
            else t("Скачивание…")
        )
        self.page.update()

    def _install_failed(self, text: str) -> None:
        self._installing = False
        self.now_button.disabled = self.skip_button.disabled = self.page_button.disabled = False
        self.cancel_button.visible = False
        self.progress.visible = False
        self.note.value = text
        self.note.visible = True
        self.page.update()

    def _default_quit(self) -> None:
        """Закрывает окно; если оно не закрылось, процесс завершается через несколько секунд."""
        timer = threading.Timer(EXIT_FALLBACK_SECONDS, os._exit, [0])
        timer.daemon = True
        timer.start()
        self.page.run_task(self.page.window.destroy)
