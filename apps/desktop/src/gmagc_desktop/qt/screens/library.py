"""Экран «Библиотека»: выбор папки гобо, построение индекса с прогрессом и отменой, состояние индекса."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from gmagc_common.i18n import t
from gmagc_desktop.qt.controller import AppController


def _pick_directory(parent: QWidget | None) -> str:
    return QFileDialog.getExistingDirectory(parent, t("Папка библиотеки гобо"))


class LibraryScreen(QWidget):
    def __init__(self, controller: AppController, pick_directory: Callable[[QWidget | None], str] = _pick_directory):
        super().__init__()
        self.controller = controller
        self._pick_directory = pick_directory

        title = QLabel(t("Библиотека гобо"))
        title.setProperty("role", "title")
        heading = QLabel(t("Текущая библиотека"))
        heading.setProperty("role", "heading")
        self.path_label = QLabel(t("не выбрана"))
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.choose_button = QPushButton(t("Выбрать папку…"))
        self.rebuild_button = QPushButton(t("Обновить индекс"))
        self.status_label = QLabel(t("Индекс не построен"))
        self.status_label.setWordWrap(True)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        self.progress_label = QLabel()
        self.progress_label.hide()
        self.cancel_button = QPushButton(t("Отмена"))
        self.cancel_button.hide()

        buttons = QHBoxLayout()
        buttons.addWidget(self.choose_button)
        buttons.addWidget(self.rebuild_button)
        buttons.addStretch(1)
        cancel_row = QHBoxLayout()
        cancel_row.addWidget(self.cancel_button)
        cancel_row.addStretch(1)
        panel = QFrame()
        panel.setProperty("role", "panel")
        column = QVBoxLayout(panel)
        column.setContentsMargins(16, 16, 16, 16)
        column.setSpacing(10)
        column.addWidget(heading)
        column.addWidget(self.path_label)
        column.addLayout(buttons)
        column.addWidget(self.status_label)
        column.addWidget(self.progress_bar)
        column.addWidget(self.progress_label)
        column.addLayout(cancel_row)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        layout.addWidget(title)
        layout.addWidget(panel)
        layout.addStretch(1)

        self.choose_button.clicked.connect(self.on_choose)
        self.rebuild_button.clicked.connect(self.controller.start_index)
        self.cancel_button.clicked.connect(self.controller.cancel_index)
        self.controller.library_changed.connect(self.refresh)
        self.controller.busy_changed.connect(self._on_busy)
        self.controller.progress.connect(self._on_progress)
        self.refresh()

    def refresh(self) -> None:
        self.path_label.setText(self.controller.library_path or t("не выбрана"))
        self.status_label.setText(self.controller.status_line)

    def on_choose(self) -> None:
        folder = self._pick_directory(self)
        if folder:
            self.controller.choose_library(folder)

    def _on_busy(self, busy: bool, indexing: bool) -> None:
        self.choose_button.setDisabled(busy)
        self.rebuild_button.setDisabled(busy)
        show = busy and indexing
        self.progress_bar.setVisible(show)
        self.progress_label.setVisible(show)
        self.cancel_button.setVisible(show)
        if not show:
            self.progress_bar.setValue(0)

    def _on_progress(self, done: int, total: int) -> None:
        self.progress_bar.setMaximum(max(total, 1))
        self.progress_bar.setValue(done)
        self.progress_label.setText(t("Индексация: {done} из {total}", done=done, total=total))
