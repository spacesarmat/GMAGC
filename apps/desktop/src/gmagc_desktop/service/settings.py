"""Настройки приложения и каталог данных пользователя."""

from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from gmagc_common.protocol import DEFAULT_PORT, is_valid_code, normalize_code
from gmagc_common.updates import parse_version

APP_FOLDER = "GMAGC"
MAX_TOP_N = 50
MAX_PORT = 65525  # запас под перебор соседних портов при занятом


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
    server_enabled: bool = True
    port: int = DEFAULT_PORT
    access_code: str = ""
    check_updates: bool = True
    skipped_version: str = ""
    last_update_check: float = 0.0
    launches: int = 0
    support_last_ask: float = 0.0
    support_muted: bool = False
    dark_theme: bool = False
    large_text: bool = False  # крупный шрифт и более контрастные цвета, для тёмных залов


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def load_settings(path: str | Path) -> Settings:
    """Настройки из файла; отсутствующий, повреждённый или неверный файл даёт значения по умолчанию."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return Settings()
    return settings_from_json(text)


def settings_from_json(text: str) -> Settings:
    """Разбирает текст того же вида, что хранится в settings.json (используется и при импорте настроек).

    Как и load_settings: неверный JSON, не-словарь и любое отдельное поле не подходящего вида просто
    заменяются значением по умолчанию, а не бросают исключение."""
    try:
        raw = json.loads(text)
    except ValueError:
        return Settings()
    if not isinstance(raw, dict):
        return Settings()
    library_dir = raw.get("library_dir", "")
    top_n = raw.get("top_n", 10)
    server_enabled = raw.get("server_enabled", True)
    port = raw.get("port", DEFAULT_PORT)
    access_code = raw.get("access_code", "")
    check_updates = raw.get("check_updates", True)
    skipped_version = raw.get("skipped_version", "")
    last_update_check = raw.get("last_update_check", 0.0)
    launches = raw.get("launches", 0)
    support_last_ask = raw.get("support_last_ask", 0.0)
    support_muted = raw.get("support_muted", False)
    dark_theme = raw.get("dark_theme", False)
    large_text = raw.get("large_text", False)
    return Settings(
        library_dir=library_dir if isinstance(library_dir, str) else "",
        top_n=top_n if _is_int(top_n) and 1 <= top_n <= MAX_TOP_N else 10,
        server_enabled=server_enabled if isinstance(server_enabled, bool) else True,
        port=port if _is_int(port) and 1024 <= port <= MAX_PORT else DEFAULT_PORT,
        access_code=normalize_code(access_code) if isinstance(access_code, str) and is_valid_code(access_code) else "",
        check_updates=check_updates if isinstance(check_updates, bool) else True,
        skipped_version=skipped_version if isinstance(skipped_version, str) and parse_version(skipped_version) else "",
        last_update_check=(
            float(last_update_check)
            if isinstance(last_update_check, int | float)
            and not isinstance(last_update_check, bool)
            and math.isfinite(last_update_check)
            and last_update_check >= 0
            else 0.0
        ),
        launches=launches if _is_int(launches) and launches >= 0 else 0,
        support_last_ask=(
            float(support_last_ask)
            if isinstance(support_last_ask, int | float)
            and not isinstance(support_last_ask, bool)
            and math.isfinite(support_last_ask)
            and support_last_ask >= 0
            else 0.0
        ),
        support_muted=support_muted if isinstance(support_muted, bool) else False,
        dark_theme=dark_theme if isinstance(dark_theme, bool) else False,
        large_text=large_text if isinstance(large_text, bool) else False,
    )


def settings_to_json(settings: Settings) -> str:
    return json.dumps(asdict(settings), ensure_ascii=False, indent=2)


def save_settings(settings: Settings, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(settings_to_json(settings), encoding="utf-8")
