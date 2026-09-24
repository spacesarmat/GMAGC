"""Экран подключения: адрес и код доступа вручную или QR-код с ПК."""

from __future__ import annotations

from PySide6.QtWidgets import QLineEdit

from gmagc_common.i18n import t
from gmagc_phone.controller import MODE_SCAN, PhoneController, scan_hint
from gmagc_phone.widgets import Page, button, label


class ConnectScreen(Page):
    def __init__(self, controller: PhoneController):
        super().__init__("GMAGC")
        self.controller = controller
        self.add(label(t("Адрес ПК"), "muted"))
        self.address = QLineEdit()
        self.address.setPlaceholderText(t("192.168.1.5 или 192.168.1.5:8765"))
        self.add(self.address)
        self.add(label(t("Код доступа"), "muted"))
        self.code = QLineEdit()
        self.code.setMaxLength(9)
        self.add(self.code)
        self.error = label("", "error")
        self.error.hide()
        self.add(self.error)
        self.scan = button(t("Считать QR-код с ПК"), "", lambda: controller.show_camera(MODE_SCAN, scan_hint()))
        self.add(self.scan)
        self.connect_button = button(t("Подключиться"), "primary", self._connect)
        self.add(self.connect_button)
        self.add(button(t("Профили приборов"), "link", lambda: controller.open_overlay("profiles")))
        self.add(button(t("Настройки"), "link", lambda: controller.open_overlay("settings")))
        self.add(button(t("Помощь"), "link", lambda: controller.open_overlay("help")))
        self.add(button(t("О программе"), "link", lambda: controller.open_overlay("about")))
        self.finish()
        self.address.returnPressed.connect(self.code.setFocus)
        self.code.returnPressed.connect(self._connect)
        controller.connect_error.connect(self.show_error)
        controller.connect_prefill.connect(self.prefill)
        controller.busy_changed.connect(self._busy)

    def _connect(self) -> None:
        self.controller.connect(self.address.text(), self.code.text())

    def show_error(self, text: str) -> None:
        self.error.setText(text)
        self.error.setVisible(bool(text))

    def prefill(self, address: str, code: str) -> None:
        self.address.setText(address)
        self.code.setText(code)

    def _busy(self, busy: bool) -> None:
        self.connect_button.setEnabled(not busy)
