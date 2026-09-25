"""Экраны результата поиска и галереи снимков сессии."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from gmagc_common.i18n import FILES_EN, FILES_RU, plural, t
from gmagc_common.phone_texts import history_text, outcome_message, score_text
from gmagc_common.protocol import MatchResponse, ResultItem
from gmagc_common.theme import score_band
from gmagc_phone import theme
from gmagc_phone.controller import MODE_SHOOT, PhoneController
from gmagc_phone.widgets import Page, button, card, label, picture


def score_badge(score: float) -> QLabel:
    background, foreground = theme.BADGE[score_band(score)]
    badge = label(score_text(score), wrap=False)
    badge.setStyleSheet(
        f"background: {background}; color: {foreground}; border-radius: 8px; padding: 2px 8px; font-weight: bold;"
    )
    return badge


class ResultCard(QFrame):
    """Карточка совпадения: миниатюра, имя, оценка, путь; нажатие копирует путь."""

    def __init__(self, item: ResultItem, on_copy: Callable[[str], None]):
        super().__init__()
        self.setProperty("role", "card")
        self.path = item.path
        self._on_copy = on_copy
        row = QHBoxLayout(self)
        row.addWidget(picture(item.thumbnail_png, 80, 80))
        col = QVBoxLayout()
        head = QHBoxLayout()
        self.name = label(item.name, "heading")
        head.addWidget(self.name, 1)
        head.addWidget(score_badge(item.score))
        col.addLayout(head)
        col.addWidget(label(item.path, "muted"))
        if item.copies:
            more = t("ещё {count} {files}", count=len(item.copies), files=plural(len(item.copies), FILES_RU, FILES_EN))
            col.addWidget(label(more, "muted"))
        col.addWidget(button(t("Копировать путь"), "", lambda: on_copy(item.path)))
        row.addLayout(col, 1)

    def mousePressEvent(self, _event) -> None:
        self._on_copy(self.path)


class ResultsScreen(Page):
    def __init__(self, controller: PhoneController, share: Callable[[str], None] | None = None):
        super().__init__(t("Результаты"))
        self.controller = controller
        self.share = share
        self.banner = label("", "toast")
        self.banner.hide()
        self.add(self.banner)
        self.add(label(t("Нажмите на карточку, чтобы скопировать путь"), "muted"))
        self.images = QWidget()
        self.images_row = QHBoxLayout(self.images)
        self.add(self.images)
        self.cards = QWidget()
        self.cards_col = QVBoxLayout(self.cards)
        self.cards_col.setContentsMargins(0, 0, 0, 0)
        self.add(self.cards)
        self.copy_note = label("", "muted")
        self.copy_note.hide()
        self.add(self.copy_note)
        self.again = button(t("Снять ещё"), "primary", lambda: controller.show_camera(MODE_SHOOT))
        self.add(self.again)
        self.share_button = button(t("Поделиться"), "", self._share)
        self.add(self.share_button)
        self.finish()
        controller.results_shown.connect(self.show_response)
        controller.copied.connect(self._copied)

    def show_response(self, photo: bytes, response: MatchResponse) -> None:
        note = outcome_message(response.outcome)
        self.banner.setText(note or "")
        self.banner.setVisible(bool(note))
        _clear(self.images_row)
        for title, data, width, height in (
            (t("Фото"), photo, 160, 120),
            (t("Найденная проекция"), response.projection_png, 120, 120),
        ):
            if data:
                box = QVBoxLayout()
                box.addWidget(label(title, "muted"))
                box.addWidget(picture(data, width, height))
                self.images_row.addLayout(box)
        _clear(self.cards_col)
        for item in response.results:
            self.cards_col.addWidget(ResultCard(item, self.controller.copy_path))
        self.copy_note.hide()

    def _copied(self, path: str) -> None:
        self.copy_note.setText(t("Путь скопирован: {path}", path=path))
        self.copy_note.show()

    def _share(self) -> None:
        text = self.controller.result_share_text()
        if text and self.share is not None:
            self.share(text)


class GalleryScreen(Page):
    def __init__(self, controller: PhoneController):
        super().__init__(t("Галерея"), controller.close_overlay)
        self.controller = controller
        self.empty = label(t("Пока нет снимков в этой сессии"), "muted")
        self.add(self.empty)
        self.list = QWidget()
        self.list_col = QVBoxLayout(self.list)
        self.list_col.setContentsMargins(0, 0, 0, 0)
        self.add(self.list)
        self.finish()
        controller.history_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        _clear(self.list_col)
        self.empty.setVisible(not self.controller.history)
        for index, (photo, response) in enumerate(self.controller.history):
            frame = card()
            row = QHBoxLayout(frame)
            row.addWidget(picture(photo, 80, 80))
            row.addWidget(label(history_text(response)), 1)
            row.addWidget(button(">", "link", lambda i=index: self.controller.open_history(i)))
            self.list_col.addWidget(frame)


def _clear(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout() is not None:
            _clear(item.layout())
