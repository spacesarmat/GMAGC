"""Приём профиля прибора с телефона: запись типов grandMA3 и grandMA2 в папки пультов на этом ПК."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping
from pathlib import Path

from gmagc_common.fixtures import FixtureProfile, profile_file_name
from gmagc_common.i18n import t
from gmagc_common.ma2_export import export_ma2_files
from gmagc_common.ma3_export import ExportError, export_ma3
from gmagc_common.protocol import SKIP_CANNOT_USE, SKIP_NO_FOLDER, FixtureUploadResult, parse_skip, skip_item
from gmagc_desktop.service.settings import Settings


class NoTargetError(RuntimeError):
    """Некуда писать: ни одна папка пульта не найдена и не задана."""


def describe_skip(item: str) -> str:
    """Пропуск словами (на языке ПК): для сообщения об ошибке сервера; телефон подбирает текст по коду сам."""
    parsed = parse_skip(item)
    if parsed is None:
        return item
    code, target, detail = parsed
    console = "grandMA3" if target == "ma3" else "grandMA2"
    if code == SKIP_NO_FOLDER:
        return t("{console}: папка не найдена, укажите её в настройках ПК-приложения", console=console)
    return t("{console}: не удалось использовать папку ({detail})", console=console, detail=detail)


def _program_data(environ: Mapping[str, str]) -> Path | None:
    root = environ.get("PROGRAMDATA")
    return Path(root) if root else None


def default_ma3_dir(environ: Mapping[str, str] | None = None) -> Path | None:
    """Папка типов приборов grandMA3 (`gma3_library\\fixturetypes`), если MA3 стояла на этом ПК."""
    root = _program_data(os.environ if environ is None else environ)
    found = root / "MALightingTechnology" / "gma3_library" / "fixturetypes" if root else None
    return found if found is not None and found.is_dir() else None


def default_ma2_dir(environ: Mapping[str, str] | None = None) -> Path | None:
    """Папка `importexport` самой новой установки grandMA2 (версии сравниваются по числам)."""
    root = _program_data(os.environ if environ is None else environ)
    if root is None:
        return None
    base = root / "MA Lighting Technologies" / "grandma"
    if not base.is_dir():
        return None

    def version(path: Path) -> tuple[int, ...]:
        return tuple(int(part) for part in re.findall(r"\d+", path.name))

    candidates = [p for p in base.glob("gma2_V_*") if (p / "importexport").is_dir()]
    return max(candidates, key=version) / "importexport" if candidates else None


class FixtureExporter:
    def __init__(self, settings: Callable[[], Settings], environ: Mapping[str, str] | None = None):
        self._settings = settings
        self._environ = environ

    def _folder(self, configured: str, default: Path | None, target: str) -> tuple[Path | None, str]:
        """Папка пульта: заданная в настройках (создаётся при необходимости) или найденная сама."""
        if configured:
            folder = Path(configured)
            try:
                folder.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                return None, skip_item(SKIP_CANNOT_USE, target, f"{configured}: {error}")
            return folder, ""
        if default is not None:
            return default, ""
        return None, skip_item(SKIP_NO_FOLDER, target)

    def store(self, profile: FixtureProfile) -> FixtureUploadResult:
        """Пишет типы приборов для обоих пультов. ExportError, если профиль не готов; NoTargetError, если некуда писать."""
        ma3_xml = export_ma3(profile)  # ошибки проверки поднимаются до любой записи
        ma2_files = export_ma2_files(profile)
        settings = self._settings()
        written: list[tuple[str, str]] = []
        skipped: list[str] = []
        ma3_folder, problem = self._folder(settings.ma3_fixture_dir, default_ma3_dir(self._environ), "ma3")
        if ma3_folder is None:
            skipped.append(problem)
        else:
            path = ma3_folder / profile_file_name(profile, "xml")
            path.write_text(ma3_xml, encoding="utf-8")
            written.append(("ma3", str(path)))
        ma2_folder, problem = self._folder(settings.ma2_fixture_dir, default_ma2_dir(self._environ), "ma2")
        if ma2_folder is None:
            skipped.append(problem)
        else:
            for name, text in ma2_files:
                path = ma2_folder / name
                path.write_text(text, encoding="utf-8")
                written.append(("ma2", str(path)))
        if not written:
            raise NoTargetError("; ".join(describe_skip(item) for item in skipped))
        return FixtureUploadResult(tuple(written), tuple(skipped))


__all__ = ["ExportError", "FixtureExporter", "NoTargetError", "default_ma2_dir", "default_ma3_dir"]
