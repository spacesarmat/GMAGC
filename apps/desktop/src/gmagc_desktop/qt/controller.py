"""Контроллер ПК-приложения: состояние и логика без виджетов (индексация, занятость, баннер, метрики).

Экраны только показывают его состояние и вызывают его методы; тяжёлое идёт в фоне через подменяемый исполнитель
(в тестах — синхронный), результаты возвращаются сигналами Qt в главный поток."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from gmagc_common.i18n import t
from gmagc_desktop.library.index import IndexCancelled, LibraryNotFound, LibraryScanError
from gmagc_desktop.service.search_service import SearchService
from gmagc_desktop.ui.texts import status_text

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

    def __init__(self, service: SearchService, executor: Executor | None = None):
        super().__init__()
        self.service = service
        self.executor: Executor = executor or PoolExecutor()
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
