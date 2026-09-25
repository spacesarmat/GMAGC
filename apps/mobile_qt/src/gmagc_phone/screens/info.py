"""Настройки, «О программе» и помощь."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QComboBox

from gmagc_common import i18n
from gmagc_common.i18n import t
from gmagc_common.support import AUTHOR_TELEGRAM_URL, CHANNEL_URL, SUPPORT_URL
from gmagc_phone.about import AUTHOR, VERSION
from gmagc_phone.controller import PhoneController
from gmagc_phone.widgets import Page, button, label

LANGUAGES = (i18n.LANG_AUTO, i18n.LANG_RU, i18n.LANG_EN)


def open_url(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))


class SettingsScreen(Page):
    def __init__(self, controller: PhoneController):
        super().__init__(t("Настройки"), controller.close_overlay)
        self.controller = controller
        self.add(label(t("Язык"), "muted"))
        self.language = QComboBox()
        for choice in LANGUAGES:
            self.language.addItem(i18n.language_name(choice), choice)
        self.language.setCurrentIndex(LANGUAGES.index(controller.settings.load_language()))
        self.language.activated.connect(self._language_picked)
        self.add(self.language)
        self.change_pc = button(t("Сменить ПК"), "", controller.change_pc)
        self.add(self.change_pc)
        self.diag = label("", "muted")
        self.diag.hide()
        self.add(self.diag)
        self.finish()
        controller.diag_changed.connect(self._diag)

    def add_update_controls(self, updates) -> None:
        """Ручная проверка обновлений: кнопка и строка состояния."""
        status = label("", "muted")
        status.hide()
        updates.status_changed.connect(lambda text: (status.setText(text), status.setVisible(bool(text))))
        check = button(t("Проверить обновления"), "", lambda: updates.check(force=True))
        self.layout_.insertWidget(self.layout_.count() - 1, check)
        self.layout_.insertWidget(self.layout_.count() - 1, status)

    def _language_picked(self, index: int) -> None:
        self.controller.set_language(self.language.itemData(index))

    def _diag(self, text: str) -> None:
        self.diag.setText(text)
        self.diag.setVisible(bool(text))


class AboutScreen(Page):
    def __init__(self, controller: PhoneController, open_link: Callable[[str], None] = open_url):
        super().__init__(t("О программе"), controller.close_overlay)
        self.add(label(t("Версия {VERSION}. Автор: {AUTHOR}", VERSION=VERSION, AUTHOR=AUTHOR)))
        self.links = []
        for text, url in (
            (t("Поддержать автора"), SUPPORT_URL),
            (t("Telegram автора"), AUTHOR_TELEGRAM_URL),
            (t("Канал GMAGC"), CHANNEL_URL),
        ):
            link = button(text, "link", lambda u=url: open_link(u))
            self.links.append((link, url))
            self.add(link)
        self.finish()


class HelpScreen(Page):
    def __init__(self, controller: PhoneController):
        super().__init__(t("Помощь"), controller.close_overlay)
        self.add(
            label(
                t(
                    "Подключитесь к ПК с запущенным GMAGC в той же сети Wi-Fi: наведите камеру на QR-код в его "
                    "окне (подключение произойдёт само) или введите адрес и код вручную. Дальше наводите камеру "
                    "на проекцию и снимайте — совпадения из библиотеки на ПК придут в ответ."
                )
            )
        )
        self.add(
            label(
                t(
                    "«Профили»: создание профиля прибора для grandMA2 и grandMA3 с нуля (режимы, каналы из шаблонов, "
                    "диапазоны значений). Все правки сохраняются сразу. Кнопки «Поделиться» отправляют готовые файлы: "
                    "JSON профиля, XML для grandMA3 и по одному XML на режим для grandMA2 (положите их в fixturetypes "
                    "библиотеки MA3 или в importexport MA2 и импортируйте в пульте)."
                )
            )
        )
        self.finish()
