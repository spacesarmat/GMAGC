"""Экран «Поиск»: фото (файл, буфер обмена), поправки, результаты карточками."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from gmagc_common.i18n import FILES_EN, FILES_RU, RESULTS_EN, RESULTS_RU, plural, t
from gmagc_common.theme import DESKTOP_MUTED, score_band
from gmagc_desktop.qt.controller import AppController
from gmagc_desktop.qt.icons import icon
from gmagc_desktop.qt.theme import BADGE
from gmagc_desktop.qt.widgets import ElidedLabel, FlowLayout, Panel, set_picture
from gmagc_desktop.service.results import Result, SearchOutcome
from gmagc_desktop.ui.texts import score_text

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.bmp *.webp)"
CARD_WIDTH = 200

BRIGHTNESS = (-80, 80, 5)  # минимум, максимум, шаг ползунка
CONTRAST = (5, 20, 1)  # в десятых доли: 0.5…2.0
EXPOSURE = (-20, 20, 1)  # в десятых EV: −2…+2


def _signed(value: float, decimals: int) -> str:
    return f"{value:+.{decimals}f}" if value else f"{value:.{decimals}f}"


def _pick_image(parent: QWidget | None, title: str) -> str:
    path, _ = QFileDialog.getOpenFileName(parent, title, "", IMAGE_FILTER)
    return path


def read_clipboard() -> tuple[bytes | None, list[str]]:
    """Картинка из буфера обмена (PNG-байты) и пути скопированных файлов."""
    mime = QGuiApplication.clipboard().mimeData()
    if mime is None:
        return None, []
    data = None
    if mime.hasImage():
        image = QGuiApplication.clipboard().image()
        if not image.isNull():
            buffer = QBuffer(QByteArray())
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            image.save(buffer, "PNG")
            data = bytes(buffer.data())
    files = [url.toLocalFile() for url in mime.urls() if url.isLocalFile()] if mime.hasUrls() else []
    return data, files


class AdjustPanel(QWidget):
    """Три ползунка поправки (яркость, контраст, экспозиция) и «Сбросить»."""

    changed = Signal(float, float, float)  # пока двигают
    committed = Signal()  # ползунок отпущен
    reset = Signal()

    def __init__(self, title: str):
        super().__init__()
        heading = QLabel(title)
        heading.setProperty("role", "heading")
        self.brightness_label = QLabel()
        self.contrast_label = QLabel()
        self.exposure_label = QLabel()
        for label in (self.brightness_label, self.contrast_label, self.exposure_label):
            label.setProperty("role", "muted")
        self.brightness = self._slider(*BRIGHTNESS, 0)
        self.contrast = self._slider(*CONTRAST, 10)
        self.exposure = self._slider(*EXPOSURE, 0)
        self.reset_button = QPushButton(t("Сбросить"))
        self.reset_button.setProperty("role", "link")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        for widget in (
            heading,
            self.brightness_label,
            self.brightness,
            self.contrast_label,
            self.contrast,
            self.exposure_label,
            self.exposure,
        ):
            layout.addWidget(widget)
        row = QHBoxLayout()
        row.addWidget(self.reset_button)
        row.addStretch(1)
        layout.addLayout(row)
        self.reset_button.clicked.connect(self.reset)
        self._update_labels()

    def _slider(self, low: int, high: int, step: int, value: int) -> QSlider:
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(low, high)
        slider.setSingleStep(step)
        slider.setPageStep(step * 4)
        slider.setValue(value)
        slider.valueChanged.connect(self._on_change)
        slider.sliderReleased.connect(self.committed)
        return slider

    def values(self) -> tuple[float, float, float]:
        return float(self.brightness.value()), self.contrast.value() / 10, self.exposure.value() / 10

    def set_values(self, brightness: float, contrast: float, exposure: float) -> None:
        """Ставит значения без сигналов (сброс из контроллера)."""
        for slider, value in ((self.brightness, brightness), (self.contrast, contrast * 10), (self.exposure, exposure * 10)):
            slider.blockSignals(True)
            slider.setValue(round(value))
            slider.blockSignals(False)
        self._update_labels()

    def _on_change(self, _value: int) -> None:
        self._update_labels()
        self.changed.emit(*self.values())

    def _update_labels(self) -> None:
        brightness, contrast, exposure = self.values()
        self.brightness_label.setText(t("Яркость: {signed}", signed=_signed(brightness, 0)))
        self.contrast_label.setText(t("Контраст: {adjust_contrast:.1f}×", adjust_contrast=contrast))
        self.exposure_label.setText(t("Экспозиция: {signed} EV", signed=_signed(exposure, 1)))


class ResultCard(QFrame):
    """Карточка результата: миниатюра с номером и бейджем оценки, имя, путь, копии, кнопки действий."""

    clicked = Signal(str)  # полный путь: по нажатию копируется
    reveal_requested = Signal(str)
    wrong_requested = Signal(object)

    def __init__(self, result: Result):
        super().__init__()
        self.result = result
        self.setProperty("role", "card")
        self.setFixedWidth(CARD_WIDTH)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(t("Нажмите, чтобы скопировать путь к файлу"))

        thumb = QWidget()
        thumb.setFixedHeight(110)
        grid = QGridLayout(thumb)
        grid.setContentsMargins(6, 6, 6, 6)
        self.thumb_label = QLabel()
        set_picture(self.thumb_label, result.thumbnail_png, CARD_WIDTH - 12, 98)
        rank = QLabel(f"{result.rank:02d}")
        rank.setProperty("role", "dim")
        self.badge = QLabel(score_text(result.score))
        background, color = BADGE[score_band(result.score)]
        self.badge.setStyleSheet(
            f"background: {background}; color: {color}; border-radius: 9px; padding: 1px 7px; font-weight: bold;"
        )
        grid.addWidget(self.thumb_label, 0, 0, Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(rank, 0, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        grid.addWidget(self.badge, 0, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)

        self.name_label = ElidedLabel(result.name)
        self.name_label.setStyleSheet("font-weight: bold;")
        self.path_label = ElidedLabel(result.full_path)
        self.path_label.setProperty("role", "muted")
        column = QVBoxLayout()
        column.setContentsMargins(10, 4, 10, 0)
        column.setSpacing(3)
        column.addWidget(self.name_label)
        column.addWidget(self.path_label)
        if result.copies:
            copies = QLabel(
                t("ещё {count} {files}", count=len(result.copies), files=plural(len(result.copies), FILES_RU, FILES_EN))
            )
            copies.setProperty("role", "dim")
            copies.setToolTip("\n".join(result.copies))
            column.addWidget(copies)

        self.reveal_button = QPushButton()
        self.reveal_button.setIcon(icon("folder", DESKTOP_MUTED, 16))
        self.reveal_button.setToolTip(t("Показать в папке"))
        self.wrong_button = QPushButton()
        self.wrong_button.setIcon(icon("thumb_down", DESKTOP_MUTED, 16))
        self.wrong_button.setToolTip(t("Это не то — указать верный файл"))
        for button in (self.reveal_button, self.wrong_button):
            button.setProperty("role", "link")
            button.setFlat(True)
        actions = QHBoxLayout()
        actions.setContentsMargins(6, 0, 6, 4)
        actions.addWidget(self.reveal_button)
        actions.addWidget(self.wrong_button)
        actions.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(thumb)
        layout.addLayout(column)
        layout.addLayout(actions)
        self.reveal_button.clicked.connect(lambda: self.reveal_requested.emit(result.full_path))
        self.wrong_button.clicked.connect(lambda: self.wrong_requested.emit(result))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.result.full_path)
        super().mousePressEvent(event)


class SearchScreen(QWidget):
    def __init__(
        self,
        controller: AppController,
        pick_image: Callable[[QWidget | None, str], str] = _pick_image,
        clipboard: Callable[[], tuple[bytes | None, list[str]]] = read_clipboard,
    ):
        super().__init__()
        self.controller = controller
        self._pick_image = pick_image
        self._clipboard = clipboard
        self.cards: list[ResultCard] = []

        title = QLabel(t("Поиск по изображению"))
        title.setProperty("role", "title")
        subtitle = QLabel(t("Загрузите фотографию проекции, чтобы найти совпадение в библиотеке."))
        subtitle.setProperty("role", "muted")
        heading = QVBoxLayout()
        heading.setSpacing(4)
        heading.addWidget(title)
        heading.addWidget(subtitle)
        self.metric_files, self.metric_time, self.metric_score = QLabel("0"), QLabel("—"), QLabel("—")
        metrics = QHBoxLayout()
        metrics.setSpacing(22)
        for value, caption in (
            (self.metric_files, t("гобо в базе")),
            (self.metric_time, t("время поиска")),
            (self.metric_score, t("совпадение")),
        ):
            column = QVBoxLayout()
            column.setSpacing(2)
            note = QLabel(caption.upper())
            note.setProperty("role", "dim")
            column.addWidget(value)
            column.addWidget(note)
            metrics.addLayout(column)
        top = QHBoxLayout()
        top.setSpacing(40)
        top.addLayout(heading)
        top.addLayout(metrics)
        top.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        layout.addLayout(top)
        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(self._build_source_panel())
        body.addWidget(self._build_results_panel(), 1)
        layout.addLayout(body, 1)

        controller.photo_shown.connect(self._on_photo)
        controller.previews_updated.connect(self._on_previews)
        controller.outcome_shown.connect(self._on_outcome)
        controller.adjustments_changed.connect(self._sync_adjustments)
        controller.metrics_changed.connect(self._update_metrics)
        controller.library_changed.connect(self._update_metrics)
        controller.busy_changed.connect(self._on_busy)
        controller.path_copied.connect(self._on_copied)
        self._update_metrics()

    # ---- построение -------------------------------------------------------------
    def _build_source_panel(self) -> QFrame:
        panel = Panel("panel")
        panel.setFixedWidth(360)
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        column = QVBoxLayout(inner)
        column.setContentsMargins(14, 14, 14, 14)
        column.setSpacing(10)
        heading = QLabel(t("Исходное изображение"))
        heading.setProperty("role", "heading")
        self.source_label = QLabel()
        self.source_label.setProperty("role", "muted")
        self.source_label.setWordWrap(True)
        self.source_label.hide()

        preview = Panel("preview")
        previews = QVBoxLayout(preview)
        previews.setContentsMargins(14, 14, 14, 14)
        previews.setSpacing(12)
        previews.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.photo_caption = QLabel(t("Фото"))
        self.photo_caption.setProperty("role", "muted")
        self.photo_label = QLabel()
        self.projection_caption = QLabel(t("Найденная проекция"))
        self.projection_caption.setProperty("role", "muted")
        self.projection_label = QLabel()
        self.photo_box = QWidget()
        photo_column = QVBoxLayout(self.photo_box)
        photo_column.setContentsMargins(0, 0, 0, 0)
        photo_column.setSpacing(4)
        photo_column.addWidget(self.photo_caption, alignment=Qt.AlignmentFlag.AlignHCenter)
        photo_column.addWidget(self.photo_label, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.projection_box = QWidget()
        projection_column = QVBoxLayout(self.projection_box)
        projection_column.setContentsMargins(0, 0, 0, 0)
        projection_column.setSpacing(4)
        projection_column.addWidget(self.projection_caption, alignment=Qt.AlignmentFlag.AlignHCenter)
        projection_column.addWidget(self.projection_label, alignment=Qt.AlignmentFlag.AlignHCenter)
        previews.addWidget(self.photo_box)
        previews.addWidget(self.projection_box)
        self.photo_box.hide()
        self.projection_box.hide()

        self.pick_button = QPushButton(t("Выбрать фото…"))
        self.paste_button = QPushButton(t("Вставить из буфера"))
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addWidget(self.pick_button)
        buttons.addWidget(self.paste_button)
        self.photo_adjust_panel = AdjustPanel(t("Поправка фото"))
        self.projection_adjust_panel = AdjustPanel(t("Поправка найденной проекции"))
        self.photo_adjust_panel.hide()
        self.projection_adjust_panel.hide()

        for widget in (heading, self.source_label, preview):
            column.addWidget(widget)
        column.addLayout(buttons)
        column.addWidget(self.photo_adjust_panel)
        column.addWidget(self.projection_adjust_panel)
        column.addStretch(1)
        scroll.setWidget(inner)
        outer.addWidget(scroll)

        self.pick_button.clicked.connect(self.on_pick)
        self.paste_button.clicked.connect(self.on_paste)
        self.photo_adjust_panel.changed.connect(self.controller.set_photo_adjust)
        self.photo_adjust_panel.committed.connect(self.controller.rerun_with_adjustments)
        self.photo_adjust_panel.reset.connect(self._on_reset_photo)
        self.projection_adjust_panel.changed.connect(self.controller.set_projection_adjust)
        self.projection_adjust_panel.committed.connect(self.controller.rerun_with_adjustments)
        self.projection_adjust_panel.reset.connect(self._on_reset_projection)
        return panel

    def _build_results_panel(self) -> QFrame:
        panel = Panel("panel2")
        column = QVBoxLayout(panel)
        column.setContentsMargins(14, 14, 14, 14)
        column.setSpacing(10)
        header = QHBoxLayout()
        title = QLabel(t("Результаты"))
        title.setProperty("role", "heading")
        self.summary_label = QLabel()
        self.summary_label.setProperty("role", "dim")
        header.addWidget(title)
        header.addWidget(self.summary_label)
        header.addStretch(1)
        self.copy_label = QLabel()
        self.copy_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.copy_label.hide()
        self.results_holder = QWidget()
        self.results_layout = FlowLayout(self.results_holder, spacing=10)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self.results_holder)
        column.addLayout(header)
        column.addWidget(self.copy_label)
        column.addWidget(scroll, 1)
        return panel

    # ---- действия ---------------------------------------------------------------
    def on_pick(self) -> None:
        path = self._pick_image(self, t("Фото проекции"))
        if path:
            self.controller.search_path(path)

    def on_paste(self) -> None:
        data, files = self._clipboard()
        if data:
            self.controller.search_bytes(data)
            return
        for name in files:
            if Path(name).suffix.lower() in IMAGE_SUFFIXES:
                self.controller.search_path(name)
                return
        self.controller.show_banner(t("В буфере обмена нет картинки или файла-изображения"), error=True)

    def _on_reset_photo(self) -> None:
        self.controller.reset_photo_adjust()
        self.controller.rerun_with_adjustments()

    def _on_reset_projection(self) -> None:
        self.controller.reset_projection_adjust()
        self.controller.rerun_with_adjustments()

    def _on_wrong(self, result: Result) -> None:
        path = self._pick_image(self, t("Выберите верный файл"))
        if path:
            self.controller.report_wrong(result.rel_path, path)

    # ---- реакция на состояние -----------------------------------------------------
    def _on_photo(self, data: bytes, source: str) -> None:
        set_picture(self.photo_label, data, 150, 110)
        self.photo_box.show()
        self.photo_adjust_panel.show()
        self.projection_box.hide()
        self.source_label.setText(source)
        self.source_label.setVisible(bool(source))
        self._clear_results()
        self.copy_label.hide()

    def _on_previews(self, photo: bytes, projection: bytes | None) -> None:
        set_picture(self.photo_label, photo, 150, 110)
        if projection:
            set_picture(self.projection_label, projection, 75, 75)
            self.projection_box.show()

    def _on_outcome(self, outcome: SearchOutcome) -> None:
        if outcome.projection_png:
            set_picture(self.projection_label, outcome.projection_png, 75, 75)
        self.projection_box.setVisible(bool(outcome.projection_png))
        self.projection_adjust_panel.setVisible(bool(outcome.projection_png))
        self._clear_results()
        for result in outcome.results:
            card = ResultCard(result)
            card.clicked.connect(self.controller.copy_path)
            card.reveal_requested.connect(self.controller.reveal)
            card.wrong_requested.connect(self._on_wrong)
            self.results_layout.addWidget(card)
            card.show()  # виджет, добавленный в уже показанный контейнер, сам не показывается
            self.cards.append(card)
        self._update_summary()

    def _clear_results(self) -> None:
        for card in self.cards:
            self.results_layout.removeWidget(card)
            card.deleteLater()
        self.cards = []
        self._update_summary()

    def _update_summary(self) -> None:
        count = len(self.cards)
        text = t("{count} {results}", count=count, results=plural(count, RESULTS_RU, RESULTS_EN)) if count else ""
        self.summary_label.setText(text)

    def _sync_adjustments(self) -> None:
        self.photo_adjust_panel.set_values(*self.controller.photo_adjust)
        self.projection_adjust_panel.set_values(*self.controller.projection_adjust)

    def _update_metrics(self) -> None:
        status = self.controller.service.status()
        self.metric_files.setText(f"{status.files:,}".replace(",", " ") if status else "0")
        ms, score = self.controller.last_search_ms, self.controller.last_score
        self.metric_time.setText(f"{ms:.0f} ms" if ms is not None else "—")
        self.metric_score.setText(score_text(score) if score is not None else "—")

    def _on_busy(self, busy: bool, _indexing: bool) -> None:
        self.pick_button.setDisabled(busy)
        self.paste_button.setDisabled(busy)

    def _on_copied(self, absolute: str) -> None:
        self.copy_label.setText(t("Путь скопирован: {absolute}", absolute=absolute))
        self.copy_label.show()

