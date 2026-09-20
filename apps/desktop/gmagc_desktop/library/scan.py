"""Обход папки библиотеки гобо."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from gmagc_desktop.matcher.imageio import IGNORED_LIBRARY_NAMES, LIBRARY_EXTENSIONS


@dataclass(frozen=True)
class LibraryFile:
    rel_path: str  # POSIX-вид, относительно корня библиотеки
    size: int
    mtime_ns: int


def scan_library(root: str | Path) -> list[LibraryFile]:
    """Все поддерживаемые файлы библиотеки, отсортированные по rel_path."""
    root = Path(root)
    found: list[LibraryFile] = []
    for dirpath, _dirnames, names in os.walk(root):
        directory = Path(dirpath)
        for name in names:
            if Path(name).suffix.lower() not in LIBRARY_EXTENSIONS:
                continue
            if directory == root and name.lower() in IGNORED_LIBRARY_NAMES:
                continue
            stat = (directory / name).stat()
            rel = (directory / name).relative_to(root).as_posix()
            found.append(LibraryFile(rel, stat.st_size, stat.st_mtime_ns))
    found.sort(key=lambda f: f.rel_path)
    return found
