"""Экран «Настройки»: внешний вид, язык, папки MA2/MA3, ключ облака, перенос настроек, проверка ядра, диагностика."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from gmagc_common.i18n import CHOICES, language_name, t
from gmagc_desktop.qt.controller import AppController
from gmagc_desktop.qt.widgets import Panel
from gmagc_desktop.service import autostart
from gmagc_desktop.service.fixture_export import default_ma2_dir, default_ma3_dir
from gmagc_desktop.service.settings import RESULTS_COUNT_CHOICES


def _save_json(parent: QWidget | None, name: str) -> str:
    path, _ = QFileDialog.getSaveFileName(parent, t("Экспорт настроек"), name, "JSON (*.json)")
    return path


def _open_json(parent: QWidget | None) -> str:
    path, _ = QFileDialog.getOpenFileName(parent, t("Импорт настроек"), "", "JSON (*.json)")
    return path


def _fixture_hint(found) -> str:
    return t("по умолчанию: {found}", found=found) if found else t("папка не найдена, укажите её")


def _divider() -> QFrame:
    line = QFrame()
    line.setProperty("role", "line")
    return line


class SettingsScreen(QWidget):
    def __init__(
        self,
        controller: AppController,
        save_json: Callable[[QWidget | None, str], str] = _save_json,
        open_json: Callable[[QWidget | None], str] = _open_json,
        extra_sections: list[QWidget] | None = None,
    ):
        super().__init__()
        self.controller = controller
        self._save_json = save_json
        self._open_json = open_json
        settings = controller.service.settings

        title = QLabel(t("Настройки"))
        title.setProperty("role", "title")

        self.large_text_check = QCheckBox(t("Крупный текст"))
        self.autostart_check = QCheckBox(t("Автозапуск при включении компьютера"))
        self.results_combo = QComboBox()
        for count in RESULTS_COUNT_CHOICES:
            self.results_combo.addItem(str(count), count)
        self.language_combo = QComboBox()
        for choice in CHOICES:
            self.language_combo.addItem(language_name(choice), choice)
        self.ma3_field = QLineEdit()
        self.ma3_field.setPlaceholderText(_fixture_hint(default_ma3_dir()))
        self.ma2_field = QLineEdit()
        self.ma2_field.setPlaceholderText(_fixture_hint(default_ma2_dir()))
        self.cloud_field = QLineEdit()
        self.cloud_field.setEchoMode(QLineEdit.EchoMode.Password)
        self.export_button = QPushButton(t("Экспорт…"))
        self.import_button = QPushButton(t("Импорт…"))
        self.check_button = QPushButton(t("Проверить"))
        self.check_label = QLabel()
        self.check_label.setWordWrap(True)
        self.log_button = QPushButton(t("Отправить лог по почте"))

        panel = Panel("panel")
        column = QVBoxLayout(panel)
        column.setContentsMargins(16, 16, 16, 16)
        column.setSpacing(10)
        column.addWidget(self.large_text_check)
        if autostart.is_supported():
            column.addWidget(self.autostart_check)
        else:
            self.autostart_check.hide()
        column.addLayout(self._labelled(t("Число результатов поиска"), self.results_combo))
        column.addLayout(self._labelled("Язык / Language", self.language_combo))
        column.addWidget(_divider())
        column.addLayout(self._labelled(t("Папка типов приборов grandMA3"), self.ma3_field))
        column.addLayout(self._labelled(t("Папка типов приборов grandMA2 (importexport)"), self.ma2_field))
        cloud = self._labelled(t("Ключ Anthropic для облачного распознавания инструкций"), self.cloud_field)
        column.addLayout(cloud)
        note = QLabel(t("Необязательно. Файл уходит в облако только по кнопке на телефоне и после подтверждения."))
        note.setProperty("role", "muted")
        note.setWordWrap(True)
        column.addWidget(note)
        column.addWidget(_divider())
        column.addLayout(self._row(t("Экспорт настроек"), self.export_button))
        column.addLayout(self._row(t("Импорт настроек"), self.import_button))
        column.addWidget(_divider())
        column.addLayout(self._row(t("Проверить ядро"), self.check_button))
        column.addWidget(self.check_label)
        for section in extra_sections or []:
            column.addWidget(_divider())
            column.addWidget(section)
        column.addWidget(_divider())
        column.addLayout(self._row(t("Диагностика"), self.log_button))
        self.extra_layout = column

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        holder = QWidget()
        holder_layout = QVBoxLayout(holder)
        holder_layout.setContentsMargins(0, 0, 0, 0)
        holder_layout.setSpacing(16)
        holder_layout.addWidget(title)
        holder_layout.addWidget(panel)
        holder_layout.addStretch(1)
        scroll.setWidget(holder)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)

        self.refresh(settings)
        self.large_text_check.toggled.connect(controller.set_large_text)
        self.autostart_check.toggled.connect(self._on_autostart)
        self.results_combo.currentIndexChanged.connect(self._on_results)
        self.language_combo.currentIndexChanged.connect(self._on_language)
        self.ma3_field.editingFinished.connect(self._on_dirs)
        self.ma2_field.editingFinished.connect(self._on_dirs)
        self.cloud_field.editingFinished.connect(lambda: controller.set_cloud_key(self.cloud_field.text()))
        self.export_button.clicked.connect(self.on_export)
        self.import_button.clicked.connect(self.on_import)
        self.check_button.clicked.connect(lambda: self.check_label.setText(controller.check_core()))
        self.log_button.clicked.connect(controller.send_log)
        controller.library_changed.connect(lambda: self.refresh(controller.service.settings))

    @staticmethod
    def _labelled(caption: str, field: QWidget) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(4)
        label = QLabel(caption)
        label.setProperty("role", "muted")
        box.addWidget(label)
        box.addWidget(field)
        return box

    @staticmethod
    def _row(caption: str, button: QPushButton) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel(caption), 1)
        row.addWidget(button)
        return row

    def _block(self, widgets: list[QWidget], blocked: bool) -> None:
        for widget in widgets:
            widget.blockSignals(blocked)

    def refresh(self, settings) -> None:
        """Показывает сохранённые настройки, не вызывая их повторного сохранения."""
        widgets = [self.large_text_check, self.autostart_check, self.results_combo, self.language_combo]
        self._block(widgets, True)
        self.large_text_check.setChecked(settings.large_text)
        if autostart.is_supported():
            self.autostart_check.setChecked(autostart.is_autostart_enabled())
        self.results_combo.setCurrentIndex(max(self.results_combo.findData(settings.results_count), 0))
        self.language_combo.setCurrentIndex(max(self.language_combo.findData(settings.language), 0))
        self._block(widgets, False)
        self.ma3_field.setText(settings.ma3_fixture_dir)
        self.ma2_field.setText(settings.ma2_fixture_dir)
        self.cloud_field.setText(settings.anthropic_api_key)

    # ---- действия ---------------------------------------------------------------
    def _on_autostart(self, enabled: bool) -> None:
        if not self.controller.set_autostart(enabled):
            self.autostart_check.blockSignals(True)
            self.autostart_check.setChecked(False)
            self.autostart_check.blockSignals(False)

    def _on_results(self, _index: int) -> None:
        self.controller.set_results_count(int(self.results_combo.currentData()))

    def _on_language(self, _index: int) -> None:
        self.controller.set_language(str(self.language_combo.currentData()))

    def _on_dirs(self) -> None:
        self.controller.set_fixture_dirs(self.ma3_field.text(), self.ma2_field.text())

    def on_export(self) -> None:
        path = self._save_json(self, "gmagc-settings.json")
        if path:
            self.controller.export_settings(path)

    def on_import(self) -> None:
        path = self._open_json(self)
        if path:
            self.controller.import_settings(path)


__all__ = ["SettingsScreen"]
