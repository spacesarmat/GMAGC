"""Кэш индекса на диске: загрузить, дособрать, сохранить."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from gmagc_desktop.library.index import LibraryIndex, ProgressCallback, build_index, load_index, save_index
from gmagc_desktop.matcher.embedder import Embedder


def update_index(
    root: str | Path,
    embedder: Embedder,
    index_path: str | Path,
    progress: ProgressCallback | None = None,
    cancel: Callable[[], bool] | None = None,
) -> LibraryIndex:
    """Дособирает индекс поверх кэша (новые и изменённые файлы) и сохраняет его.

    Исключения build_index (LibraryNotFound, LibraryScanError, IndexCancelled) пробрасываются, кэш при этом не трогается.
    """
    index = build_index(root, embedder, existing=load_index(index_path), progress=progress, cancel=cancel)
    save_index(index, index_path)
    return index
