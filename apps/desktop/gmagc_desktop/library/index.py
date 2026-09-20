"""Индекс библиотеки: эмбеддинги, маски формы, семейства дублей; кэш на диске."""

from __future__ import annotations

import os
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from gmagc_desktop.library.grouping import group_duplicates
from gmagc_desktop.library.scan import LibraryFile, scan_library
from gmagc_desktop.matcher.embedder import Embedder
from gmagc_desktop.matcher.imageio import load_library_gray
from gmagc_desktop.matcher.normalize import normalize_gray
from gmagc_desktop.matcher.search import SearchData
from gmagc_desktop.matcher.shape import MASK_SIZE, soft_mask

FORMAT_VERSION = 1
ProgressCallback = Callable[[int, int], None]


class IndexCancelled(Exception):
    """Индексация прервана по запросу пользователя."""


@dataclass
class LibraryIndex:
    model_id: str
    files: list[LibraryFile]
    embeddings: np.ndarray  # (N, D) float32
    masks: np.ndarray  # (N, 64, 64) uint8
    group_ids: np.ndarray  # (N,) int32
    skipped: list[LibraryFile] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.files)

    def search_data(self) -> SearchData:
        return SearchData(self.embeddings, self.masks, self.group_ids)


def _load_normalized(path: Path) -> np.ndarray | None:
    try:
        return normalize_gray(load_library_gray(path))
    except Exception:  # битый файл не должен ломать индексацию
        return None


def build_index(
    root: str | Path,
    embedder: Embedder,
    existing: LibraryIndex | None = None,
    progress: ProgressCallback | None = None,
    batch_size: int = 64,
    cancel: Callable[[], bool] | None = None,
) -> LibraryIndex:
    root = Path(root)
    scanned = scan_library(root)

    reusable: dict[LibraryFile, int] = {}
    known_skipped: set[LibraryFile] = set()
    if existing is not None and existing.model_id == embedder.model_id:
        reusable = {file: i for i, file in enumerate(existing.files)}
        known_skipped = set(existing.skipped)

    todo = [f for f in scanned if f not in reusable and f not in known_skipped]
    skipped = [f for f in scanned if f in known_skipped]
    fresh: dict[LibraryFile, tuple[np.ndarray, np.ndarray]] = {}

    for start in range(0, len(todo), batch_size):
        if cancel is not None and cancel():
            raise IndexCancelled()
        loaded: list[tuple[LibraryFile, np.ndarray]] = []
        for file in todo[start : start + batch_size]:
            normalized = _load_normalized(root / file.rel_path)
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
        return LibraryIndex(
            embedder.model_id,
            [],
            np.zeros((0, 0), np.float32),
            np.zeros((0, MASK_SIZE, MASK_SIZE), np.uint8),
            np.zeros(0, np.int32),
            skipped,
        )

    embeddings = np.stack(
        [existing.embeddings[reusable[f]] if f in reusable else fresh[f][1] for f in files]
    ).astype(np.float32)
    masks = np.stack([existing.masks[reusable[f]] if f in reusable else fresh[f][0] for f in files])
    return LibraryIndex(
        embedder.model_id, files, embeddings, masks, group_duplicates(embeddings, masks), skipped
    )


def save_index(index: LibraryIndex, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with open(temporary, "wb") as handle:
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


def _files(paths: np.ndarray, sizes: np.ndarray, mtimes: np.ndarray) -> list[LibraryFile]:
    return [
        LibraryFile(str(p), int(s), int(m)) for p, s, m in zip(paths, sizes, mtimes, strict=True)
    ]


def load_index(path: str | Path) -> LibraryIndex | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        with np.load(path, allow_pickle=False) as data:
            if int(data["format_version"]) != FORMAT_VERSION:
                return None
            return LibraryIndex(
                model_id=str(data["model_id"]),
                files=_files(data["rel_paths"], data["sizes"], data["mtimes"]),
                embeddings=data["embeddings"].astype(np.float32),
                masks=data["masks"],
                group_ids=data["group_ids"],
                skipped=_files(data["skipped_paths"], data["skipped_sizes"], data["skipped_mtimes"]),
            )
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return None
