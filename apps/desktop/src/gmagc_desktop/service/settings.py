"""Настройки приложения и каталог данных пользователя."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

APP_FOLDER = "GMAGC"
MAX_TOP_N = 50


def data_dir() -> Path:
    """Каталог настроек и кэша индекса (переопределяется переменной GMAGC_DATA_DIR)."""
    override = os.environ.get("GMAGC_DATA_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "@ANDY_BUM" / APP_FOLDER
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_FOLDER
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "gmagc"


@dataclass
class Settings:
    library_dir: str = ""
    top_n: int = 10


def load_settings(path: str | Path) -> Settings:
    """Настройки из файла; отсутствующий, повреждённый или неверный файл даёт значения по умолчанию."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    if not isinstance(raw, dict):
        return Settings()
    library_dir = raw.get("library_dir", "")
    top_n = raw.get("top_n", 10)
    return Settings(
        library_dir=library_dir if isinstance(library_dir, str) else "",
        top_n=top_n if isinstance(top_n, int) and not isinstance(top_n, bool) and 1 <= top_n <= MAX_TOP_N else 10,
    )


def save_settings(settings: Settings, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")
