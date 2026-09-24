"""Сервис поиска: настройки, индекс библиотеки и поиск по фото (без Flet)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np

from gmagc_common.i18n import normalize_choice, t
from gmagc_common.protocol import is_valid_code
from gmagc_common.support import SupportState
from gmagc_common.updates import parse_version
from gmagc_desktop.library.cache import update_index
from gmagc_desktop.library.index import LibraryIndex, ProgressCallback, load_index
from gmagc_desktop.library.scan import scan_library
from gmagc_desktop.matcher.adjust import apply_adjustments
from gmagc_desktop.matcher.embedder import Embedder, PixelEmbedder
from gmagc_desktop.matcher.imageio import load_library_gray, load_photo_bgr
from gmagc_desktop.matcher.pipeline import normalize_photo
from gmagc_desktop.matcher.search import DEFAULT_W_EMBED, Match, Searcher
from gmagc_desktop.matcher.thumbnail import thumbnail_png
from gmagc_desktop.service.access import generate_code
from gmagc_desktop.service.corrections import Correction, load_corrections, new_correction, save_corrections
from gmagc_desktop.service.results import LOW_CONFIDENCE_SCORE, IndexStatus, Outcome, Result, SearchOutcome
from gmagc_desktop.service.settings import Settings, load_settings, save_settings, settings_from_json, settings_to_json

CORRECTION_SCORE = 0.95  # оценка, с которой показывается результат, продвинутый исправлением пользователя

THUMBNAIL_SIZE = 96
PROJECTION_SIZE = 160
BLANK_THUMBNAIL = thumbnail_png(np.zeros((1, 1), np.uint8), THUMBNAIL_SIZE)


class PhotoError(ValueError):
    """Фото нельзя прочитать или декодировать."""


class NoIndexError(RuntimeError):
    """Индекса нет: библиотека не выбрана или индекс не построен."""


class CorrectionError(ValueError):
    """Указанный «верный» файл не в библиотеке или не входит в текущий индекс — исправление не сохранено."""


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0


class SearchService:
    def __init__(self, data_dir: str | Path, embedder: Embedder | None = None):
        self._data_dir = Path(data_dir)
        self._embedder = embedder or PixelEmbedder()
        self._settings_path = self._data_dir / "settings.json"
        self._index_path = self._data_dir / "index.npz"
        self._corrections_path = self._data_dir / "corrections.json"
        self._corrections: list[Correction] = []
        self.settings = Settings()
        self._index: LibraryIndex | None = None
        self._searcher: Searcher | None = None
        self._lock = threading.RLock()  # поиск и подмена индекса не пересекаются: UI и сервер работают из разных потоков
        self._indexing = False
        self._done = 0
        self._total = 0

    @property
    def data_dir(self) -> Path:
        return self._data_dir

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
        """Читает настройки и кэш индекса (если библиотека выбрана и кэш совместим).

        Если основной файл индекса отсутствует или повреждён, пробует резервную копию (.previous),
        оставленную перед прошлой перезаписью."""
        self.settings = load_settings(self._settings_path)
        index = None
        if self.settings.library_dir:
            index = load_index(self._index_path)
            if index is None:
                index = load_index(self._index_path.with_name(self._index_path.name + ".previous"))
        if index is not None and index.model_id != self._embedder.model_id:
            index = None
        self._use(index)
        self._corrections = load_corrections(self._corrections_path)
        return self.status()

    def set_library(self, path: str | Path) -> None:
        """Запоминает папку библиотеки; индекс и исправления другой папки сбрасываются вместе с кэшем
        (пути в исправлениях относительны конкретной библиотеки — для другой они не имеют смысла)."""
        path = str(path)
        with self._lock:
            if path != self.settings.library_dir:
                self._use(None)
                self._index_path.unlink(missing_ok=True)
                self._corrections = []
                self._corrections_path.unlink(missing_ok=True)
            self._update_settings(library_dir=path)

    def build_index(self, progress: ProgressCallback | None = None, cancel: Callable[[], bool] | None = None) -> IndexStatus:
        """Строит или дособирает индекс. LibraryNotFound, LibraryScanError, IndexCancelled пробрасываются."""
        if not self.settings.library_dir:
            raise NoIndexError(t("папка библиотеки не выбрана"))
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

    def saved_language(self) -> str:
        """Язык из файла настроек: нужен до сборки интерфейса, когда `load()` ещё не выполнялся."""
        return load_settings(self._settings_path).language

    def set_language(self, choice: str) -> None:
        """Язык интерфейса: «auto» (по системе), «ru» или «en»; неизвестное значение сводится к «auto»."""
        self._update_settings(language=normalize_choice(choice))

    def set_fixture_dirs(self, ma3: str, ma2: str) -> None:
        """Папки для типов приборов, присланных с телефона (пустая строка — искать самому)."""
        self._update_settings(ma3_fixture_dir=ma3.strip(), ma2_fixture_dir=ma2.strip())

    def set_cloud_key(self, key: str) -> None:
        """Ключ Anthropic для облачного распознавания инструкций (пустая строка — облако выключено)."""
        self._update_settings(anthropic_api_key=key.strip())

    def set_server_enabled(self, enabled: bool) -> None:
        self._update_settings(server_enabled=enabled)

    def set_check_updates(self, enabled: bool) -> None:
        self._update_settings(check_updates=enabled)

    def set_large_text(self, enabled: bool) -> None:
        self._update_settings(large_text=enabled)

    def set_results_count(self, count: int) -> None:
        self._update_settings(results_count=count)

    def mark_update_checked(self, when: float) -> None:
        self._update_settings(last_update_check=float(when))

    def support_state(self) -> SupportState:
        s = self.settings
        return SupportState(s.launches, s.support_last_ask, s.support_muted)

    def save_support_state(self, state: SupportState) -> None:
        self._update_settings(launches=state.launches, support_last_ask=state.last_ask, support_muted=state.muted)

    def export_settings_json(self) -> str:
        return settings_to_json(replace(self.settings, anthropic_api_key=""))  # ключ в файл для переноса не попадает

    def import_settings_json(self, text: str) -> Settings:
        """Заменяет настройки импортированными. Если библиотека при этом изменилась, забывает загруженный
        индекс и его файл на диске (он собран для прежней библиотеки, а не для новой)."""
        imported = replace(settings_from_json(text), anthropic_api_key=self.settings.anthropic_api_key)
        with self._lock:
            if imported.library_dir != self.settings.library_dir:
                self._use(None)
                self._index_path.unlink(missing_ok=True)
            self.settings = imported
            save_settings(self.settings, self._settings_path)
        return self.settings

    def skip_update(self, version: str) -> None:
        """Запоминает версию, о которой больше не напоминать (неверный формат сбрасывает пропуск)."""
        self._update_settings(skipped_version=version if parse_version(version) else "")

    def status(self) -> IndexStatus | None:
        index = self._index
        if index is None:
            return None
        return IndexStatus(
            files=len(index),
            families=len(set(index.group_ids.tolist())),
            skipped=len(index.skipped),
            transient=len(index.transient),
            stale=self.index_is_stale(),
        )

    def index_is_stale(self) -> bool:
        """Изменилась ли библиотека с последней сборки индекса (новые, изменённые или удалённые файлы).

        Папку, которую сейчас не открыть (например, отключён диск), не считает изменившейся — настоящую
        причину покажет сама сборка индекса, если пользователь попробует его обновить.
        """
        index = self._index
        if index is None or not self.settings.library_dir:
            return False
        root = Path(self.settings.library_dir)
        if not root.is_dir():
            return False
        current = {(f.rel_path, f.size, f.mtime_ns) for f in scan_library(root)}
        known = {(f.rel_path, f.size, f.mtime_ns) for f in (*index.files, *index.skipped, *index.transient)}
        return current != known

    def add_correction(self, wrong_rel_path: str, correct_full_path: str) -> None:
        """Запоминает: показанный `wrong_rel_path` неверен, правильный файл — `correct_full_path` (внутри
        библиотеки и текущего индекса). Впредь, если `wrong_rel_path` снова окажется среди результатов
        похожего запроса, верный файл будет показан первым — без переобучения модели."""
        with self._lock:
            index = self._index
            if index is None or not self.settings.library_dir:
                raise CorrectionError(t("индекс не построен"))
            root = Path(self.settings.library_dir).resolve()
            try:
                rel = str(Path(correct_full_path).resolve().relative_to(root)).replace("\\", "/")
            except ValueError:
                raise CorrectionError(t("выбранный файл не в папке библиотеки")) from None
            if not any(f.rel_path == rel for f in index.files):
                raise CorrectionError(t("выбранный файл не входит в текущий индекс: обновите его и попробуйте снова"))
            self._corrections.append(new_correction(wrong_rel_path, rel))
            save_corrections(self._corrections, self._corrections_path)

    def _apply_corrections(self, results: tuple[Result, ...], index: LibraryIndex) -> tuple[Result, ...]:
        if not self._corrections:
            return results
        shown = {r.rel_path for r in results}
        promoted: list[Result] = []
        promoted_paths: set[str] = set()
        for correction in self._corrections:
            if correction.wrong_rel_path not in shown or correction.correct_rel_path in promoted_paths:
                continue  # неверный файл не всплыл в этом поиске — исправление сейчас не нужно
            fixed = self._lookup_result(index, correction.correct_rel_path)
            if fixed is not None:
                promoted.append(fixed)
                promoted_paths.add(correction.correct_rel_path)
        if not promoted:
            return results
        combined = promoted + [r for r in results if r.rel_path not in promoted_paths]
        return tuple(replace(r, rank=i) for i, r in enumerate(combined, start=1))

    def _lookup_result(self, index: LibraryIndex, rel_path: str) -> Result | None:
        for i, file in enumerate(index.files):
            if file.rel_path == rel_path:
                group = int(index.group_ids[i])
                members = tuple(j for j, g in enumerate(index.group_ids.tolist()) if g == group)
                match = Match(i, CORRECTION_SCORE, CORRECTION_SCORE, CORRECTION_SCORE, 0.0, False, members)
                return self._result(index, 0, match)
        return None

    def search_photo(
        self,
        photo_bgr: np.ndarray,
        top_n: int | None = None,
        *,
        projection_brightness: float = 0.0,
        projection_contrast: float = 1.0,
        projection_exposure: float = 0.0,
    ) -> SearchOutcome:
        with self._lock:  # индекс и папка библиотеки не меняются, пока идёт поиск
            return self._search(photo_bgr, top_n, projection_brightness, projection_contrast, projection_exposure)

    def _search(
        self,
        photo_bgr: np.ndarray,
        top_n: int | None,
        projection_brightness: float = 0.0,
        projection_contrast: float = 1.0,
        projection_exposure: float = 0.0,
    ) -> SearchOutcome:
        searcher, index = self._searcher, self._index
        if searcher is None or index is None:
            raise NoIndexError(t("индекс не построен"))
        started = time.perf_counter()
        normalized = normalize_photo(photo_bgr)
        if normalized is None:
            return SearchOutcome(Outcome.NO_PROJECTION, took_ms=_elapsed_ms(started))
        if projection_brightness or projection_contrast != 1.0 or projection_exposure:
            normalized = apply_adjustments(
                normalized,
                brightness=projection_brightness,
                contrast=projection_contrast,
                exposure=projection_exposure,
            )
        matches = searcher.search(normalized, top_n=top_n or self.settings.top_n)
        results = tuple(self._result(index, rank, match) for rank, match in enumerate(matches, start=1))
        results = self._apply_corrections(results, index)
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

    def search_image_bytes(
        self,
        data: bytes,
        top_n: int | None = None,
        *,
        projection_brightness: float = 0.0,
        projection_contrast: float = 1.0,
        projection_exposure: float = 0.0,
    ) -> SearchOutcome:
        photo = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR) if data else None
        if photo is None:
            raise PhotoError(t("не удалось прочитать изображение"))
        return self.search_photo(
            photo,
            top_n,
            projection_brightness=projection_brightness,
            projection_contrast=projection_contrast,
            projection_exposure=projection_exposure,
        )

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
            raise ValueError(t("путь вне библиотеки: {rel_path}", rel_path=rel_path))
        return str(path)

    @staticmethod
    def _thumbnail(full_path: str) -> bytes:
        try:
            return thumbnail_png(load_library_gray(full_path), THUMBNAIL_SIZE)
        except (OSError, ValueError, SyntaxError):  # файл исчез или испортился после индексации
            return BLANK_THUMBNAIL
