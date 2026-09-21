"""Сервис поиска: настройки, индекс библиотеки и поиск по фото (без Flet)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np

from gmagc_common.protocol import is_valid_code
from gmagc_desktop.library.cache import update_index
from gmagc_desktop.library.index import LibraryIndex, ProgressCallback, load_index
from gmagc_desktop.matcher.embedder import Embedder, PixelEmbedder
from gmagc_desktop.matcher.imageio import load_library_gray, load_photo_bgr
from gmagc_desktop.matcher.pipeline import normalize_photo
from gmagc_desktop.matcher.search import DEFAULT_W_EMBED, Match, Searcher
from gmagc_desktop.matcher.thumbnail import thumbnail_png
from gmagc_desktop.service.access import generate_code
from gmagc_desktop.service.results import LOW_CONFIDENCE_SCORE, IndexStatus, Outcome, Result, SearchOutcome
from gmagc_desktop.service.settings import Settings, load_settings, save_settings

THUMBNAIL_SIZE = 96
PROJECTION_SIZE = 160
BLANK_THUMBNAIL = thumbnail_png(np.zeros((1, 1), np.uint8), THUMBNAIL_SIZE)


class PhotoError(ValueError):
    """Фото нельзя прочитать или декодировать."""


class NoIndexError(RuntimeError):
    """Индекса нет: библиотека не выбрана или индекс не построен."""


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0


class SearchService:
    def __init__(self, data_dir: str | Path, embedder: Embedder | None = None):
        self._data_dir = Path(data_dir)
        self._embedder = embedder or PixelEmbedder()
        self._settings_path = self._data_dir / "settings.json"
        self._index_path = self._data_dir / "index.npz"
        self.settings = Settings()
        self._index: LibraryIndex | None = None
        self._searcher: Searcher | None = None
        self._lock = threading.RLock()  # поиск и подмена индекса не пересекаются: UI и сервер работают из разных потоков
        self._indexing = False
        self._done = 0
        self._total = 0

    def _use(self, index: LibraryIndex | None) -> None:
        with self._lock:
            self._index = index
            self._searcher = (
                None if index is None else Searcher(index.search_data(), self._embedder, w_embed=DEFAULT_W_EMBED)
            )

    def _update_settings(self, **changes) -> None:
        with self._lock:
            self.settings = replace(self.settings, **changes)
            save_settings(self.settings, self._settings_path)

    def load(self) -> IndexStatus | None:
        """Читает настройки и кэш индекса (если библиотека выбрана и кэш совместим)."""
        self.settings = load_settings(self._settings_path)
        index = load_index(self._index_path) if self.settings.library_dir else None
        if index is not None and index.model_id != self._embedder.model_id:
            index = None
        self._use(index)
        return self.status()

    def set_library(self, path: str | Path) -> None:
        """Запоминает папку библиотеки; индекс другой папки сбрасывается вместе с кэшем."""
        path = str(path)
        with self._lock:
            if path != self.settings.library_dir:
                self._use(None)
                self._index_path.unlink(missing_ok=True)
            self._update_settings(library_dir=path)

    def build_index(
        self, progress: ProgressCallback | None = None, cancel: Callable[[], bool] | None = None
    ) -> IndexStatus:
        """Строит или дособирает индекс. LibraryNotFound, LibraryScanError, IndexCancelled пробрасываются."""
        if not self.settings.library_dir:
            raise NoIndexError("папка библиотеки не выбрана")
        self._indexing, self._done, self._total = True, 0, 0
        try:
            self._use(
                update_index(self.settings.library_dir, self._embedder, self._index_path, self._track(progress), cancel)
            )
        finally:
            self._indexing = False
        return self.status()

    def _track(self, progress: ProgressCallback | None) -> ProgressCallback:
        def report(done: int, total: int) -> None:
            self._done, self._total = done, total
            if progress is not None:
                progress(done, total)

        return report

    def indexing_state(self) -> tuple[bool, int, int]:
        """(идёт ли индексация, готово, всего) для /api/status."""
        return self._indexing, self._done, self._total

    def ensure_access_code(self) -> str:
        """Код доступа телефона: создаётся один раз и хранится в настройках."""
        with self._lock:
            if not is_valid_code(self.settings.access_code):
                self._update_settings(access_code=generate_code())
            return self.settings.access_code

    def reset_access_code(self) -> str:
        with self._lock:
            self._update_settings(access_code=generate_code())
            return self.settings.access_code

    def set_server_enabled(self, enabled: bool) -> None:
        self._update_settings(server_enabled=enabled)

    def status(self) -> IndexStatus | None:
        index = self._index
        if index is None:
            return None
        return IndexStatus(
            files=len(index),
            families=len(set(index.group_ids.tolist())),
            skipped=len(index.skipped),
            transient=len(index.transient),
        )

    def search_photo(self, photo_bgr: np.ndarray, top_n: int | None = None) -> SearchOutcome:
        with self._lock:  # индекс и папка библиотеки не меняются, пока идёт поиск
            return self._search(photo_bgr, top_n)

    def _search(self, photo_bgr: np.ndarray, top_n: int | None) -> SearchOutcome:
        searcher, index = self._searcher, self._index
        if searcher is None or index is None:
            raise NoIndexError("индекс не построен")
        started = time.perf_counter()
        normalized = normalize_photo(photo_bgr)
        if normalized is None:
            return SearchOutcome(Outcome.NO_PROJECTION, took_ms=_elapsed_ms(started))
        matches = searcher.search(normalized, top_n=top_n or self.settings.top_n)
        results = tuple(self._result(index, rank, match) for rank, match in enumerate(matches, start=1))
        confident = bool(results) and results[0].score >= LOW_CONFIDENCE_SCORE
        return SearchOutcome(
            Outcome.FOUND if confident else Outcome.LOW_CONFIDENCE,
            results,
            thumbnail_png(normalized, PROJECTION_SIZE),
            _elapsed_ms(started),
        )

    def search_file(self, path: str | Path) -> SearchOutcome:
        try:
            photo = load_photo_bgr(path)
        except (OSError, ValueError) as error:
            raise PhotoError(str(error)) from error
        return self.search_photo(photo)

    def search_image_bytes(self, data: bytes, top_n: int | None = None) -> SearchOutcome:
        photo = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR) if data else None
        if photo is None:
            raise PhotoError("не удалось прочитать изображение")
        return self.search_photo(photo, top_n)

    def _result(self, index: LibraryIndex, rank: int, match: Match) -> Result:
        rel_path = index.files[match.index].rel_path
        full_path = self._full_path(rel_path)
        copies = tuple(self._full_path(index.files[i].rel_path) for i in match.members if i != match.index)
        return Result(
            rank, Path(rel_path).name, rel_path, full_path, min(match.score, 1.0), copies, self._thumbnail(full_path)
        )

    def _full_path(self, rel_path: str) -> str:
        root = Path(self.settings.library_dir)
        path = root / rel_path
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"путь вне библиотеки: {rel_path}")
        return str(path)

    @staticmethod
    def _thumbnail(full_path: str) -> bytes:
        try:
            return thumbnail_png(load_library_gray(full_path), THUMBNAIL_SIZE)
        except (OSError, ValueError, SyntaxError):  # файл исчез или испортился после индексации
            return BLANK_THUMBNAIL
