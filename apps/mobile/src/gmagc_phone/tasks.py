"""Фоновые задачи телефона: сеть и тяжёлая работа идут не в потоке интерфейса; результаты возвращаются сигналами Qt."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from PySide6.QtCore import QRunnable, QThreadPool


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
    """Задачи в общем пуле потоков Qt."""

    def __init__(self, pool: QThreadPool | None = None):
        self._pool = pool or QThreadPool.globalInstance()

    def submit(self, task: Callable[[], None]) -> None:
        self._pool.start(_Task(task))
