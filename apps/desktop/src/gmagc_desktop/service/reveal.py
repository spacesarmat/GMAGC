"""Показ файла в файловом менеджере ОС."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def reveal_in_file_manager(path: str | Path) -> bool:
    """Показывает файл в Проводнике / Finder (на других ОС открывает папку). True, если команда запущена."""
    target = Path(path)
    try:
        if sys.platform == "win32":
            # Проводник разбирает `/select,"путь"` сам: список аргументов заключил бы в кавычки и ключ
            subprocess.Popen(f'explorer /select,"{target}"')
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target.parent)])
    except OSError:
        return False
    return True
