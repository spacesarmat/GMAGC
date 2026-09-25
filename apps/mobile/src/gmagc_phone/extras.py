"""Обновления (проверка релизов на GitHub, скачивание APK браузером) и просьба поддержать автора."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QMessageBox, QVBoxLayout, QWidget

from gmagc_common.i18n import t
from gmagc_common.support import (
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
from gmagc_common.updates import ReleaseInfo, UpdateCheckError, check_due, fetch_latest, pick_assets
from gmagc_phone.about import VERSION
from gmagc_phone.settings import PhoneSettings
from gmagc_phone.tasks import Executor
from gmagc_phone.widgets import button, label


@dataclass(frozen=True)
class UpdateNotice:
    version: str
    url: str  # APK для загрузки (или страница релиза, если APK в релизе нет)
    page_url: str


class UpdateController(QObject):
    notice_changed = Signal(object)  # UpdateNotice или None
    status_changed = Signal(str)
    _main = Signal(object)

    def __init__(
        self,
        settings: PhoneSettings,
        executor: Executor,
        open_url: Callable[[str], object],
        quit_app: Callable[[], None],
        fetch: Callable[[str], ReleaseInfo | None] = fetch_latest,
        now: Callable[[], float] = time.time,
        version: str = VERSION,
    ):
        super().__init__()
        self.settings = settings
        self.executor = executor
        self.open_url = open_url
        self.quit_app = quit_app
        self._fetch = fetch
        self._now = now
        self._version = version
        self.notice: UpdateNotice | None = None
        self._main.connect(lambda fn: fn())

    def startup(self) -> None:
        """Фоновая проверка не чаще раза в сутки; сбой сети ничего не показывает."""
        self.check(force=False)

    def check(self, *, force: bool) -> None:
        now = self._now()
        if not force and not check_due(self.settings.load_last_check(), now):
            return
        if force:
            self.status_changed.emit(t("Проверяю обновления…"))

        def work() -> None:
            notice, message = None, ""
            try:
                release = self._fetch(self._version)
                self.settings.save_last_check(now)
                if release is not None and (force or release.version != self.settings.load_skipped_version()):
                    picked = pick_assets(release, "android")
                    notice = UpdateNotice(release.version, picked[0].url if picked else release.page_url, release.page_url)
                elif force:
                    message = t("Установлена последняя версия ({VERSION})", VERSION=self._version)
            except UpdateCheckError as error:
                message = str(error) if force else ""
            except Exception as error:  # noqa: BLE001
                message = t("Ошибка проверки обновлений: {error}", error=error) if force else ""
            self._main.emit(lambda: self._done(notice, message))

        self.executor.submit(work)

    def _done(self, notice: UpdateNotice | None, message: str) -> None:
        if notice is not None:
            self.notice = notice
            self.notice_changed.emit(notice)
            self.status_changed.emit("")
        else:
            self.status_changed.emit(message)

    def download(self) -> None:
        if self.notice is None:
            return
        try:
            self.open_url(self.notice.url)
        except Exception as error:  # noqa: BLE001
            self.status_changed.emit(t("Не удалось открыть ссылку на загрузку: {error}", error=error))
            return
        self.quit_app()  # иначе после установки APK рядом с новой версией остаётся висеть старая

    def skip(self) -> None:
        if self.notice is not None:
            self.settings.save_skipped_version(self.notice.version)
        self.notice = None
        self.notice_changed.emit(None)


class UpdateBar(QWidget):
    """Полоса «Доступна версия…» с кнопками «Скачать» и «Пропустить»; скрыта, пока обновления нет."""

    def __init__(self, controller: UpdateController):
        super().__init__()
        self.controller = controller
        box = QVBoxLayout(self)
        self.text = label("", "toast")
        box.addWidget(self.text)
        row = QHBoxLayout()
        self.download_button = button(t("Скачать"), "primary", controller.download)
        self.skip_button = button(t("Пропустить"), "", controller.skip)
        row.addWidget(self.download_button)
        row.addWidget(self.skip_button)
        box.addLayout(row)
        self.hide()
        controller.notice_changed.connect(self.show_notice)

    def show_notice(self, notice: UpdateNotice | None) -> None:
        if notice is None:
            self.hide()
            return
        self.text.setText(t("Доступна версия {version} (у вас {VERSION})", version=notice.version, VERSION=VERSION))
        self.show()


def ask_dialog(parent: QWidget | None) -> str:
    """Диалог из трёх кнопок; закрытие окна — «Позже»."""
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
        settings: PhoneSettings,
        parent: QWidget | None,
        open_url: Callable[[str], object],
        *,
        now: Callable[[], float] = time.time,
        delay: float = 8.0,
        busy: Callable[[], bool] = lambda: False,
        ask: Callable[[QWidget | None], str] = ask_dialog,
    ):
        self.settings = settings
        self.parent = parent
        self.open_url = open_url
        self.now = now
        self.delay = delay
        self.busy = busy
        self.ask = ask

    def start(self) -> None:
        """Считает запуск и, если пора, показывает окно через delay секунд (если приложение не занято)."""
        state = register_launch(self.settings.load_support_state())
        self.settings.save_support_state(state)
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
        self.settings.save_support_state(after_answer(self.settings.load_support_state(), self.now(), answer))
