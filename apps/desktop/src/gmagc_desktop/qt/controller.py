"""Контроллер ПК-приложения: состояние и логика без виджетов (индексация, занятость, баннер, метрики).

Экраны только показывают его состояние и вызывают его методы; тяжёлое идёт в фоне через подменяемый исполнитель
(в тестах — синхронный), результаты возвращаются сигналами Qt в главный поток."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from gmagc_common.i18n import t
from gmagc_desktop.library.index import IndexCancelled, LibraryNotFound, LibraryScanError
from gmagc_desktop.matcher.adjust import apply_adjustments
from gmagc_desktop.matcher.pipeline import normalize_photo
from gmagc_desktop.matcher.thumbnail import thumbnail_png
from gmagc_desktop.service.results import Outcome, SearchOutcome
from gmagc_desktop.service.reveal import reveal_in_file_manager
from gmagc_desktop.service.search_service import (
    PROJECTION_SIZE,
    CorrectionError,
    NoIndexError,
    PhotoError,
    SearchService,
)
from gmagc_desktop.ui.texts import outcome_message, status_text

logger = logging.getLogger("gmagc.desktop")


class Executor(Protocol):
    def submit(self, task: Callable[[], None]) -> None: ...


class InlineExecutor:
    """Выполняет задачу сразу в том же потоке: для тестов и отладки."""

    def submit(self, task: Callable[[], None]) -> None:
        task()


class _Task(QRunnable):
    def __init__(self, task: Callable[[], None]):
        super().__init__()
        self._task = task

    def run(self) -> None:
        self._task()


class PoolExecutor:
    """Фоновые задачи в общем пуле потоков Qt."""

    def __init__(self, pool: QThreadPool | None = None):
        self._pool = pool or QThreadPool.globalInstance()

    def submit(self, task: Callable[[], None]) -> None:
        self._pool.start(_Task(task))


def no_library_hint() -> str:
    return t("Сначала выберите папку библиотеки и постройте индекс")


class AppController(QObject):
    busy_changed = Signal(bool, bool)  # занято, идёт индексация
    banner_shown = Signal(str, bool)  # текст, это ошибка
    banner_hidden = Signal()
    progress = Signal(int, int)  # обработано, всего
    library_changed = Signal()  # путь библиотеки или состояние индекса изменились
    metrics_changed = Signal()
    photo_shown = Signal(bytes, str)  # снимок для превью, подпись источника (пусто — фото выбрано на ПК)
    previews_updated = Signal(bytes, object)  # превью фото и проекции (PNG или None) пока двигают ползунки
    outcome_shown = Signal(object)  # SearchOutcome
    adjustments_changed = Signal()  # значения поправок изменились не пользователем (сброс)
    path_copied = Signal(str)

    def __init__(
        self,
        service: SearchService,
        executor: Executor | None = None,
        reveal: Callable[[str], bool] = reveal_in_file_manager,
        copy_text: Callable[[str], None] | None = None,
    ):
        super().__init__()
        self.service = service
        self.executor: Executor = executor or PoolExecutor()
        self.reveal = reveal
        self._copy_text = copy_text or (lambda text: None)
        self.last_query_photo: bytes | None = None  # для повтора поиска сразу после «Это не то»
        self.photo_adjust = (0.0, 1.0, 0.0)  # яркость, контраст, экспозиция поправки фото
        self.projection_adjust = (0.0, 1.0, 0.0)  # то же для найденной проекции
        self.busy = False
        self.indexing = False
        self._cancel = False
        self.last_search_ms: float | None = None
        self.last_score: float | None = None

    # ---- запуск и состояние ---------------------------------------------------
    def load(self) -> None:
        """Читает настройки и кэш индекса; после этого экраны перечитывают состояние."""
        self.service.load()
        self.library_changed.emit()

    @property
    def library_path(self) -> str:
        return self.service.settings.library_dir

    @property
    def status_line(self) -> str:
        return status_text(self.service.status())

    def set_busy(self, busy: bool, *, indexing: bool = False) -> None:
        self.busy, self.indexing = busy, busy and indexing
        self.busy_changed.emit(self.busy, self.indexing)

    def show_banner(self, text: str, *, error: bool) -> None:
        if error:
            logger.error(text)  # попадает в лог-файл — можно приложить письмом («Отправить лог по почте»)
        self.banner_shown.emit(text, error)

    def hide_banner(self) -> None:
        self.banner_hidden.emit()

    # ---- библиотека и индекс ----------------------------------------------------
    def choose_library(self, folder: str | Path) -> None:
        """Запоминает папку библиотеки и сразу строит индекс."""
        self.service.set_library(folder)
        self.library_changed.emit()
        self.start_index()

    def start_index(self) -> None:
        if self.busy:
            return
        if not self.service.settings.library_dir:
            self.show_banner(no_library_hint(), error=True)
            return
        self._cancel = False
        self.hide_banner()
        self.set_busy(True, indexing=True)
        self.executor.submit(self._index_worker)

    def cancel_index(self) -> None:
        self._cancel = True

    def _index_worker(self) -> None:
        try:
            self.service.build_index(progress=self._on_progress, cancel=lambda: self._cancel)
        except IndexCancelled:
            self.show_banner(t("Индексация отменена"), error=False)
        except (LibraryNotFound, LibraryScanError) as error:
            self.show_banner(str(error), error=True)
        except Exception as error:  # noqa: BLE001 - рабочий поток обязан показать причину, а не пропасть
            self.show_banner(t("Ошибка индексации: {error}", error=error), error=True)
        finally:
            self.library_changed.emit()
            self.metrics_changed.emit()
            self.set_busy(False)

    def _on_progress(self, done: int, total: int) -> None:
        self.progress.emit(done, total)

    # ---- поиск ----------------------------------------------------------------
    def search_path(self, path: str | Path) -> None:
        try:
            data = Path(path).read_bytes()
        except OSError as error:
            self.show_banner(t("Не удалось прочитать файл: {error}", error=error), error=True)
            return
        self.search_bytes(data)

    def search_bytes(self, data: bytes, source: str = "") -> None:
        """Ищет по фото (файл, буфер обмена): новый снимок сбрасывает поправки."""
        if self.busy:
            return
        if self.service.status() is None:
            self.show_banner(no_library_hint(), error=True)
            return
        self.hide_banner()
        self.last_query_photo = data
        self.reset_adjustments()
        self.photo_shown.emit(data, source)
        self.set_busy(True)
        self.executor.submit(lambda: self._search_worker(lambda: self._search_bytes(data)))

    def show_phone_record(self, photo: bytes, outcome: SearchOutcome, source: str) -> None:
        """Показывает запрос с телефона: снимок и уже готовый результат."""
        self.hide_banner()
        self.last_query_photo = photo
        self.reset_adjustments()
        self.photo_shown.emit(photo, source)
        self.show_outcome(outcome)

    def _search_bytes(self, data: bytes) -> SearchOutcome:
        brightness, contrast, exposure = self.projection_adjust
        return self.service.search_image_bytes(
            data,
            top_n=self.service.settings.results_count,
            projection_brightness=brightness,
            projection_contrast=contrast,
            projection_exposure=exposure,
        )

    def _search_array(self, photo_bgr: np.ndarray) -> SearchOutcome:
        brightness, contrast, exposure = self.projection_adjust
        return self.service.search_photo(
            photo_bgr,
            top_n=self.service.settings.results_count,
            projection_brightness=brightness,
            projection_contrast=contrast,
            projection_exposure=exposure,
        )

    def _search_worker(self, run: Callable[[], SearchOutcome]) -> None:
        try:
            outcome = run()
        except NoIndexError:
            self.show_banner(no_library_hint(), error=True)
        except PhotoError as error:
            self.show_banner(t("Не удалось прочитать фото: {error}", error=error), error=True)
        except Exception as error:  # noqa: BLE001 - рабочий поток обязан показать причину, а не пропасть
            self.show_banner(t("Ошибка поиска: {error}", error=error), error=True)
        else:
            self.show_outcome(outcome)
        finally:
            self.set_busy(False)

    def show_outcome(self, outcome: SearchOutcome) -> None:
        self.last_search_ms = outcome.took_ms
        self.last_score = outcome.results[0].score if outcome.results else None
        self.metrics_changed.emit()
        message = outcome_message(outcome.kind)
        if message:
            self.show_banner(message, error=outcome.kind is Outcome.NO_PROJECTION)
        self.outcome_shown.emit(outcome)

    # ---- поправки ---------------------------------------------------------------
    @staticmethod
    def _changed(values: tuple[float, float, float]) -> bool:
        return values != (0.0, 1.0, 0.0)

    def reset_adjustments(self) -> None:
        self.photo_adjust = (0.0, 1.0, 0.0)
        self.projection_adjust = (0.0, 1.0, 0.0)
        self.adjustments_changed.emit()

    def reset_photo_adjust(self) -> None:
        self.photo_adjust = (0.0, 1.0, 0.0)
        self.adjustments_changed.emit()

    def reset_projection_adjust(self) -> None:
        self.projection_adjust = (0.0, 1.0, 0.0)
        self.adjustments_changed.emit()

    def set_photo_adjust(self, brightness: float, contrast: float, exposure: float) -> None:
        self.photo_adjust = (brightness, contrast, exposure)
        self.update_live_previews()

    def set_projection_adjust(self, brightness: float, contrast: float, exposure: float) -> None:
        self.projection_adjust = (brightness, contrast, exposure)
        self.update_live_previews()

    def _decode_last_photo(self) -> np.ndarray | None:
        if self.last_query_photo is None:
            return None
        return cv2.imdecode(np.frombuffer(self.last_query_photo, np.uint8), cv2.IMREAD_COLOR)

    def current_photo_array(self) -> np.ndarray | None:
        """Оригинальное фото с уже применённой поправкой фото (не проекции)."""
        photo = self._decode_last_photo()
        if photo is None or not self._changed(self.photo_adjust):
            return photo
        brightness, contrast, exposure = self.photo_adjust
        return apply_adjustments(photo, brightness=brightness, contrast=contrast, exposure=exposure)

    def update_live_previews(self) -> None:
        """Пока ползунок ещё двигают: пересчитывает превью фото и проекции без поиска по библиотеке."""
        photo = self.current_photo_array()
        if photo is None:
            return
        ok, encoded = cv2.imencode(".png", photo)
        if not ok:
            return
        projection = None
        normalized = normalize_photo(photo)
        if normalized is not None:
            if self._changed(self.projection_adjust):
                brightness, contrast, exposure = self.projection_adjust
                normalized = apply_adjustments(normalized, brightness=brightness, contrast=contrast, exposure=exposure)
            projection = thumbnail_png(normalized, PROJECTION_SIZE)
        self.previews_updated.emit(bytes(encoded), projection)

    def rerun_with_adjustments(self) -> None:
        """Ползунок отпущен: повторный поиск по тому же фото с новыми поправками."""
        if self.busy:
            return
        photo = self.current_photo_array()
        if photo is None:
            return
        ok, encoded = cv2.imencode(".png", photo)
        self.photo_shown.emit(bytes(encoded) if ok else (self.last_query_photo or b""), "")
        self.set_busy(True)
        self.executor.submit(lambda: self._search_worker(lambda: self._search_array(photo)))

    # ---- результаты --------------------------------------------------------------
    def copy_path(self, path: str) -> None:
        """Копирует абсолютный путь файла (вместе с именем) в буфер обмена."""
        absolute = os.path.abspath(path)
        self._copy_text(absolute)
        self.path_copied.emit(absolute)

    def report_wrong(self, wrong_rel_path: str, correct_path: str) -> None:
        """«Это не то»: верный файл запоминается и учитывается при похожих запросах."""
        try:
            self.service.add_correction(wrong_rel_path, correct_path)
        except CorrectionError as error:
            self.show_banner(str(error), error=True)
            return
        self.show_banner(t("Запомнено: при похожих запросах теперь будет показан верный файл"), error=False)
        if self.last_query_photo is not None:
            self.search_bytes(self.last_query_photo)
