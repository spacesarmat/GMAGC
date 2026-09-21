"""Индекс библиотеки: эмбеддинги, маски формы, семейства дублей; кэш на диске."""

from __future__ import annotations

import logging
import os
import tempfile
import tokenize
import zipfile
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError

from gmagc_desktop.library.grouping import group_duplicates
from gmagc_desktop.library.scan import LibraryFile, scan_library_checked
from gmagc_desktop.matcher.embedder import Embedder
from gmagc_desktop.matcher.imageio import load_library_gray
from gmagc_desktop.matcher.normalize import normalize_gray
from gmagc_desktop.matcher.search import SearchData
from gmagc_desktop.matcher.shape import soft_mask

logger = logging.getLogger(__name__)

FORMAT_VERSION = 1
ProgressCallback = Callable[[int, int], None]


class IndexCancelled(Exception):
    """Индексация прервана по запросу пользователя."""


class LibraryNotFound(FileNotFoundError):
    """Папка библиотеки не существует (например, отключён диск)."""


class LibraryScanError(RuntimeError):
    """Библиотеку нельзя надёжно проиндексировать: частичный или пустой результат не сохраняем."""


@dataclass
class LibraryIndex:
    model_id: str
    files: list[LibraryFile]
    embeddings: np.ndarray  # (N, D) float32
    masks: np.ndarray  # (N, 64, 64) uint8
    group_ids: np.ndarray  # (N,) int32
    skipped: list[LibraryFile] = field(default_factory=list)
    # Не удалось прочитать сейчас (временный сбой). В кэш не сохраняется: следующая сборка попробует снова.
    transient: list[LibraryFile] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.files)

    def search_data(self) -> SearchData:
        return SearchData(self.embeddings, self.masks, self.group_ids)


# Окончательные сбои декодирования: файл испорчен, повторное открытие ничего не изменит.
# UnidentifiedImageError — подкласс OSError, поэтому перехватывается раньше общего OSError.
_DEFINITIVE = (UnidentifiedImageError, ValueError, SyntaxError, cv2.error, Image.DecompressionBombError)


class _TransientReadError(Exception):
    """Временный сбой чтения (устройство не готово, сетевой сбой, блокировка): файл повторят при следующей сборке."""


# Сообщения PIL об окончательно повреждённых (обрезанных) файлах: у них errno нет, а у сбоев ОС он есть.
_CORRUPT_MARKERS = ("truncated", "broken data stream", "decoder error")


def _is_corrupt_file_error(error: OSError) -> bool:
    return error.errno is None and any(marker in str(error).lower() for marker in _CORRUPT_MARKERS)


def _load_normalized(path: Path) -> np.ndarray | None:
    """Нормализованное изображение или None, если файл окончательно нечитаем (испорчен или пустой).

    Прочие OSError — временный сбой: _TransientReadError. PermissionError и ошибки программы не глотаются.
    """
    try:
        normalized = normalize_gray(load_library_gray(path))
    except PermissionError:
        raise
    except _DEFINITIVE as error:
        logger.warning("skipping unreadable library file %s: %s", path, error)
        return None
    except OSError as error:
        if _is_corrupt_file_error(error):
            logger.warning("skipping corrupt library file %s: %s", path, error)
            return None
        logger.warning("library file %s cannot be read right now, will retry next time: %s", path, error)
        raise _TransientReadError(str(error)) from error
    return normalized


def build_index(
    root: str | Path,
    embedder: Embedder,
    existing: LibraryIndex | None = None,
    progress: ProgressCallback | None = None,
    batch_size: int = 64,
    cancel: Callable[[], bool] | None = None,
) -> LibraryIndex:
    root = Path(root)
    if not root.is_dir():
        raise LibraryNotFound(f"library folder not found: {root}")
    scanned, problems = scan_library_checked(root)
    if problems:
        raise LibraryScanError(
            f"{len(problems)} problem(s) while scanning {root}: {'; '.join(problems[:3])}; "
            "refusing to build a partial index"
        )
    if not scanned:
        raise LibraryScanError(f"no PNG/BMP files found in {root}")

    reusable: dict[LibraryFile, int] = {}
    known_skipped: set[LibraryFile] = set()
    if existing is not None and existing.model_id == embedder.model_id:
        reusable = {file: i for i, file in enumerate(existing.files)}
        known_skipped = set(existing.skipped)

    todo = [f for f in scanned if f not in reusable and f not in known_skipped]
    skipped = [f for f in scanned if f in known_skipped]
    transient: list[LibraryFile] = []
    fresh: dict[LibraryFile, tuple[np.ndarray, np.ndarray]] = {}

    for start in range(0, len(todo), batch_size):
        if cancel is not None and cancel():
            raise IndexCancelled()
        loaded: list[tuple[LibraryFile, np.ndarray]] = []
        for file in todo[start : start + batch_size]:
            try:
                normalized = _load_normalized(root / file.rel_path)
            except _TransientReadError:
                transient.append(file)
                continue
            if normalized is None:
                skipped.append(file)
            else:
                loaded.append((file, normalized))
        if loaded:
            vectors = embedder.embed(np.stack([normalized for _, normalized in loaded]))
            for (file, normalized), vector in zip(loaded, vectors, strict=True):
                fresh[file] = (soft_mask(normalized), vector)
        if progress is not None:
            progress(min(start + batch_size, len(todo)), len(todo))

    skipped.sort(key=lambda f: f.rel_path)
    files = [f for f in scanned if f in reusable or f in fresh]
    if not files:
        raise LibraryScanError(f"none of the {len(scanned)} library files could be read")

    embeddings = np.stack(
        [existing.embeddings[reusable[f]] if f in reusable else fresh[f][1] for f in files]
    ).astype(np.float32)
    masks = np.stack([existing.masks[reusable[f]] if f in reusable else fresh[f][0] for f in files])
    return LibraryIndex(
        embedder.model_id, files, embeddings, masks, group_duplicates(embeddings, masks), skipped, transient
    )


def save_index(index: LibraryIndex, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            np.savez_compressed(
                handle,
                format_version=np.array(FORMAT_VERSION),
                model_id=np.array(index.model_id),
                rel_paths=np.array([f.rel_path for f in index.files], dtype=str),
                sizes=np.array([f.size for f in index.files], dtype=np.int64),
                mtimes=np.array([f.mtime_ns for f in index.files], dtype=np.int64),
                embeddings=index.embeddings.astype(np.float16),
                masks=index.masks,
                group_ids=index.group_ids.astype(np.int32),
                skipped_paths=np.array([f.rel_path for f in index.skipped], dtype=str),
                skipped_sizes=np.array([f.size for f in index.skipped], dtype=np.int64),
                skipped_mtimes=np.array([f.mtime_ns for f in index.skipped], dtype=np.int64),
            )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _files(paths: np.ndarray, sizes: np.ndarray, mtimes: np.ndarray) -> list[LibraryFile]:
    return [
        LibraryFile(str(p), int(s), int(m)) for p, s, m in zip(paths, sizes, mtimes, strict=True)
    ]


def _is_safe_rel_path(rel_path: str) -> bool:
    """Относительный путь внутри библиотеки: без диска, абсолютного начала и `..`."""
    normalized = rel_path.replace("\\", "/")
    posix = PurePosixPath(normalized)
    return bool(normalized) and not posix.is_absolute() and not PureWindowsPath(normalized).drive and ".." not in posix.parts


def load_index(path: str | Path) -> LibraryIndex | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        with np.load(path, allow_pickle=False) as data:
            if int(data["format_version"]) != FORMAT_VERSION:
                return None
            files = _files(data["rel_paths"], data["sizes"], data["mtimes"])
            skipped = _files(data["skipped_paths"], data["skipped_sizes"], data["skipped_mtimes"])
            if not all(_is_safe_rel_path(f.rel_path) for f in files + skipped):
                return None  # кэш с путями за пределами библиотеки не используем: индекс построится заново
            return LibraryIndex(
                model_id=str(data["model_id"]),
                files=files,
                embeddings=data["embeddings"].astype(np.float32),
                masks=data["masks"],
                group_ids=data["group_ids"],
                skipped=skipped,
            )
    except (
        OSError,
        KeyError,
        ValueError,
        EOFError,
        NotImplementedError,
        zipfile.BadZipFile,
        zlib.error,
        tokenize.TokenError,  # numpy разбирает заголовок .npy токенайзером
    ):
        return None
