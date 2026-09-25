"""Экран «Телефон»: сервер, QR-код подключения, код доступа, адреса ПК и история запросов с телефона."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from gmagc_common.i18n import t
from gmagc_desktop.qt.controller import AppController
from gmagc_desktop.qt.widgets import Panel, set_picture
from gmagc_desktop.ui.texts import history_text


def phone_hint() -> str:
    return t("Телефон и ПК должны быть в одной сети Wi-Fi. При первом запуске разрешите доступ в брандмауэре Windows.")


class PhoneScreen(QWidget):
    def __init__(self, controller: AppController):
        super().__init__()
        self.controller = controller

        title = QLabel(t("Подключение телефона"))
        title.setProperty("role", "title")

        self.server_switch = QCheckBox(t("Сервер для телефона"))
        self.status_label = QLabel(t("Выключен"))
        self.status_label.setWordWrap(True)
        self.code_label = QLabel()
        self.code_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.code_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.copy_button = QPushButton(t("Копировать код"))
        self.copy_button.setProperty("role", "link")
        self.new_button = QPushButton(t("Новый код"))
        self.new_button.setProperty("role", "link")
        self.code_row = QWidget()
        row = QHBoxLayout(self.code_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.copy_button)
        row.addWidget(self.new_button)
        row.addStretch(1)
        self.note_label = QLabel()
        self.addresses_label = QLabel()
        self.addresses_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.addresses_label.setWordWrap(True)
        hint = QLabel(phone_hint())
        hint.setProperty("role", "muted")
        hint.setWordWrap(True)

        connection = Panel("panel")
        column = QVBoxLayout(connection)
        column.setContentsMargins(16, 16, 16, 16)
        column.setSpacing(10)
        heading = QLabel(t("Параметры подключения"))
        heading.setProperty("role", "heading")
        for widget in (
            heading,
            self.server_switch,
            self.status_label,
            self.code_label,
            self.code_row,
            self.note_label,
            self.addresses_label,
            hint,
        ):
            column.addWidget(widget)
        column.addStretch(1)

        qr_card = Panel("panel")
        qr_card.setFixedWidth(280)
        qr_column = QVBoxLayout(qr_card)
        qr_column.setContentsMargins(16, 16, 16, 16)
        qr_column.setSpacing(10)
        qr_heading = QLabel(t("QR-код подключения"))
        qr_heading.setProperty("role", "heading")
        self.qr_label = QLabel()
        qr_column.addWidget(qr_heading)
        qr_column.addWidget(self.qr_label, alignment=Qt.AlignmentFlag.AlignHCenter)
        qr_column.addStretch(1)

        self.history_card = Panel("panel")
        history_column = QVBoxLayout(self.history_card)
        history_column.setContentsMargins(16, 16, 16, 16)
        history_column.setSpacing(0)
        self.history_title = QLabel(t("Запросы с телефона"))
        self.history_title.setProperty("role", "heading")
        history_column.addWidget(self.history_title)
        self.history_layout = QVBoxLayout()
        self.history_layout.setSpacing(0)
        history_column.addLayout(self.history_layout)
        self.history_buttons: list[QPushButton] = []
        self.history_card.hide()

        top = QHBoxLayout()
        top.setSpacing(14)
        top.addWidget(connection, 1)
        top.addWidget(qr_card)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        layout.addWidget(title)
        layout.addLayout(top)
        layout.addWidget(self.history_card)
        layout.addStretch(1)

        self.server_switch.toggled.connect(self._on_toggle)
        self.copy_button.clicked.connect(self.controller.copy_code)
        self.new_button.clicked.connect(self.controller.new_code)
        controller.server_changed.connect(self.refresh)
        controller.history_changed.connect(self._refresh_history)
        controller.note_shown.connect(self._show_note)
        controller.library_changed.connect(self._sync_switch)
        self._sync_switch()
        self.refresh()

    def _sync_switch(self) -> None:
        self.server_switch.blockSignals(True)
        self.server_switch.setChecked(self.controller.service.settings.server_enabled)
        self.server_switch.blockSignals(False)

    def _on_toggle(self, enabled: bool) -> None:
        self.controller.set_server_enabled(enabled)

    def refresh(self) -> None:
        view = self.controller.server_view()
        self.status_label.setText(view.status)
        has_link = view.qr_png is not None
        self.note_label.hide()
        self.code_label.setText(view.code_text)
        self.code_label.setVisible(has_link)
        self.code_row.setVisible(has_link)
        self.addresses_label.setText(view.other_addresses)
        self.addresses_label.setVisible(bool(view.other_addresses))
        if has_link:
            set_picture(self.qr_label, view.qr_png, 220, 220)
        else:
            self.qr_label.clear()
            self.qr_label.setFixedSize(0, 0)
        self.qr_label.setVisible(has_link)

    def _show_note(self, text: str) -> None:
        self.note_label.setText(text)
        self.note_label.show()

    def _refresh_history(self) -> None:
        for button in self.history_buttons:
            self.history_layout.removeWidget(button)
            button.deleteLater()
        self.history_buttons = []
        for record in self.controller.history:
            button = QPushButton(history_text(record.time, record.client, record.outcome))
            button.setProperty("role", "link")
            button.setStyleSheet("text-align: left;")
            button.clicked.connect(lambda _checked=False, r=record: self.controller.show_record(r))
            self.history_layout.addWidget(button)
            self.history_buttons.append(button)
        self.history_card.setVisible(bool(self.history_buttons))

