"""Обновления ПК-приложения на Qt: логика (проверка, скачивание, установка), полоса над окном и секция настроек."""

from __future__ import annotations

import os
import threading
import webbrowser
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gmagc_common.i18n import t
from gmagc_common.updates import UpdateCheckError
from gmagc_desktop.about import VERSION
from gmagc_desktop.qt.controller import Executor, InlineExecutor
from gmagc_desktop.service.search_service import SearchService
from gmagc_desktop.update.installer import InstallCancelled, InstallError
from gmagc_desktop.update.manager import UpdateOffer

EXIT_FALLBACK_SECONDS = 4.0  # если окно не закрылось само, процесс завершается: помощнику нужно, чтобы приложение вышло


def manual_fallback() -> str:
    return t(" Можно скачать обновление вручную на странице релиза.")


def default_quit() -> None:
    """Закрывает приложение; если оно не закрылось, процесс завершается через несколько секунд."""
    timer = threading.Timer(EXIT_FALLBACK_SECONDS, os._exit, [0])
    timer.daemon = True
    timer.start()
    QApplication.quit()


class UpdateController(QObject):
    offer_changed = Signal(object)  # UpdateOffer или None (скрыть полосу)
    headline_changed = Signal(str)
    note_changed = Signal(str)  # пустая строка — скрыть
    status_changed = Signal(str)
    progress_changed = Signal(int, int)
    installing_changed = Signal(bool)

    def __init__(
        self,
        service: SearchService,
        updates,
        executor: Executor | None = None,
        *,
        open_url: Callable[[str], object] = webbrowser.open,
        quit_app: Callable[[], None] = default_quit,
        delay: float = 5.0,
    ):
        super().__init__()
        self.service = service
        self.updates = updates
        self.executor = executor or InlineExecutor()
        self.open_url = open_url
        self.quit_app = quit_app
        self.delay = delay
        self.offer: UpdateOffer | None = None
        self._cancel = False
        self._installing = False

    # ---- проверка ----------------------------------------------------------------
    def start(self) -> None:
        """Фоновая проверка через delay секунд после запуска (если она включена в настройках)."""
        if self.updates is None or not self.service.settings.check_updates:
            return
        if self.delay <= 0:
            self.executor.submit(self._startup_check)
        else:
            QTimer.singleShot(int(self.delay * 1000), lambda: self.executor.submit(self._startup_check))

    def _startup_check(self) -> None:
        self.updates.cleanup()
        self._run_check(force=False)

    def check_now(self) -> None:
        if self.updates is None:
            return
        self.status_changed.emit(t("Проверяю обновления…"))
        self.executor.submit(lambda: self._run_check(force=True))

    def _run_check(self, *, force: bool) -> None:
        try:
            offer = self.updates.check(force=force)
        except UpdateCheckError as error:
            if force:
                self.status_changed.emit(str(error))
            return
        except Exception as error:  # noqa: BLE001 - проверка не должна ни ронять приложение, ни шуметь
            if force:
                self.status_changed.emit(t("Ошибка проверки обновлений: {error}", error=error))
            return
        if offer is None:
            self.status_changed.emit(t("Установлена последняя версия ({VERSION})", VERSION=VERSION) if force else "")
            return
        self.show_offer(offer)

    def show_offer(self, offer: UpdateOffer) -> None:
        self.offer = offer
        self.headline_changed.emit(
            t("Доступна версия {version} (у вас {VERSION})", version=offer.release.version, VERSION=VERSION)
        )
        self.note_changed.emit(offer.reason)
        self.status_changed.emit("")
        self.offer_changed.emit(offer)

    # ---- действия полосы ------------------------------------------------------------
    def open_release_page(self) -> None:
        if self.offer is not None:
            self.open_url(self.offer.release.page_url)

    def skip(self) -> None:
        if self.offer is not None:
            self.updates.skip(self.offer.release.version)
        self.offer = None
        self.offer_changed.emit(None)

    def cancel(self) -> None:
        self._cancel = True

    def set_check_on_start(self, enabled: bool) -> None:
        self.service.set_check_updates(enabled)

    def install_now(self) -> None:
        if self.offer is None or not self.offer.can_install or self._installing:
            return
        self._installing = True
        self._cancel = False
        self.installing_changed.emit(True)
        self.progress_changed.emit(0, 0)
        self.note_changed.emit(t("Скачивание…"))
        self.executor.submit(self._install_worker)

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
            self.progress_changed.emit(1, 1)
            self.headline_changed.emit(t("Обновление скачано, приложение перезапускается…"))
            self.note_changed.emit("")
            self.quit_app()

    def _on_progress(self, done: int, total: int) -> None:
        self.progress_changed.emit(done, total)
        self.note_changed.emit(
            t("Скачивание: {done} из {total} МБ", done=done // 1_000_000, total=total // 1_000_000)
            if total
            else t("Скачивание…")
        )

    def _install_failed(self, text: str) -> None:
        self._installing = False
        self.installing_changed.emit(False)
        self.note_changed.emit(text)


class UpdateBar(QFrame):
    """Полоса вверху окна: предложение новой версии, скачивание, «Пропустить»."""

    def __init__(self, controller: UpdateController):
        super().__init__()
        self.controller = controller
        self.setProperty("role", "banner")
        self.setProperty("error", "false")
        self.setStyleSheet("QFrame[role='banner'] { background: #bbdefb; } QLabel { color: #000; }")
        self.text = QLabel()
        self.text.setStyleSheet("font-weight: bold; color: #000;")
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.hide()
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        self.now_button = QPushButton(t("Обновить"))
        self.page_button = QPushButton(t("Что нового"))
        self.skip_button = QPushButton(t("Пропустить"))
        self.cancel_button = QPushButton(t("Отмена"))
        self.cancel_button.hide()
        buttons = QHBoxLayout()
        for button in (self.now_button, self.page_button, self.skip_button, self.cancel_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        for widget in (self.text, self.note, self.progress):
            layout.addWidget(widget)
        layout.addLayout(buttons)
        self.hide()

        self.now_button.clicked.connect(controller.install_now)
        self.page_button.clicked.connect(controller.open_release_page)
        self.skip_button.clicked.connect(controller.skip)
        self.cancel_button.clicked.connect(controller.cancel)
        controller.offer_changed.connect(self._on_offer)
        controller.headline_changed.connect(self.text.setText)
        controller.note_changed.connect(self._on_note)
        controller.progress_changed.connect(self._on_progress)
        controller.installing_changed.connect(self._on_installing)

    def _on_offer(self, offer: UpdateOffer | None) -> None:
        if offer is None:
            self.hide()
            return
        self.now_button.setVisible(offer.can_install)
        self.page_button.setText(t("Что нового") if offer.can_install else t("Открыть страницу релиза"))
        self.show()

    def _on_note(self, text: str) -> None:
        self.note.setText(text)
        self.note.setVisible(bool(text))

    def _on_progress(self, done: int, total: int) -> None:
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(done if total else 0)
        self.progress.show()

    def _on_installing(self, installing: bool) -> None:
        for button in (self.now_button, self.skip_button, self.page_button):
            button.setDisabled(installing)
        self.cancel_button.setVisible(installing)
        if not installing:
            self.progress.hide()


class UpdateSettings(QWidget):
    """Секция «Настройки»: проверять при запуске, «Проверить обновления», статус."""

    def __init__(self, controller: UpdateController):
        super().__init__()
        self.controller = controller
        self.check_on_start = QCheckBox(t("Проверять обновления при запуске"))
        self.check_on_start.setChecked(controller.service.settings.check_updates)
        self.check_button = QPushButton(t("Проверить обновления"))
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        row = QHBoxLayout()
        row.addWidget(QLabel(t("Проверить сейчас")), 1)
        row.addWidget(self.check_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self.check_on_start)
        layout.addLayout(row)
        layout.addWidget(self.status_label)
        self.check_on_start.toggled.connect(controller.set_check_on_start)
        self.check_button.clicked.connect(controller.check_now)
        controller.status_changed.connect(self.status_label.setText)
