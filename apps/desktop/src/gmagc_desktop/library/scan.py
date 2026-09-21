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


def scan_library_checked(root: str | Path) -> tuple[list[LibraryFile], list[str]]:
    """Файлы библиотеки (отсортированы по rel_path) и список проблем обхода.

    Непрочитанная папка (нет доступа, отключённый диск и т. п.) попадает в problems, а не молча пропускается.
    Файл, исчезнувший между обходом и stat(), просто пропускается: его уже нет, это не проблема.
    """
    root = Path(root)
    found: list[LibraryFile] = []
    problems: list[str] = []

    def on_error(error: OSError) -> None:
        problems.append(f"cannot list directory {error.filename}: {error}")

    for dirpath, _dirnames, names in os.walk(root, onerror=on_error):
        directory = Path(dirpath)
        for name in names:
            if Path(name).suffix.lower() not in LIBRARY_EXTENSIONS:
                continue
            if directory == root and name.lower() in IGNORED_LIBRARY_NAMES:
                continue
            try:
                stat = (directory / name).stat()
            except FileNotFoundError:
                continue
            rel = (directory / name).relative_to(root).as_posix()
            found.append(LibraryFile(rel, stat.st_size, stat.st_mtime_ns))
    found.sort(key=lambda f: f.rel_path)
    return found, problems


def scan_library(root: str | Path) -> list[LibraryFile]:
    """Все поддерживаемые файлы библиотеки, отсортированные по rel_path (без сведений о проблемах обхода)."""
    return scan_library_checked(root)[0]
