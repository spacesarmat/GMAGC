"""Проверка и установка обновлений ПК-приложения (без Flet)."""

from __future__ import annotations

import os
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from gmagc_common.updates import ReleaseInfo, check_due, fetch_latest, pick_assets, update_source
from gmagc_desktop.about import VERSION
from gmagc_desktop.service.search_service import SearchService
from gmagc_desktop.update.installer import (
    InstallError,
    backup_dir,
    current_executable,
    download,
    install_target,
    is_writable,
    launch_helper,
    platform_key,
    stage,
    write_helper,
)

NO_FILE = "Для этой платформы в релизе нет готового файла: скачайте обновление на странице релиза."
NOT_PACKAGED = "Приложение запущено не из собранной папки: обновите его вручную."
NO_CHECKSUM = "В релизе нет контрольной суммы: обновление из приложения отключено, скачайте его вручную."


@dataclass(frozen=True)
class UpdateOffer:
    release: ReleaseInfo
    can_install: bool  # можно ли поставить обновление из самого приложения
    reason: str = ""  # почему нельзя (показывается пользователю)


class UpdateManager:
    def __init__(
        self,
        service: SearchService,
        data_dir: str | Path,
        current_version: str = VERSION,
        platform: str | None = None,
        executable: Path | None = None,
        fetch: Callable[[str], ReleaseInfo | None] = fetch_latest,
        now: Callable[[], float] = time.time,
        launch: Callable[[Path, str], None] = launch_helper,
        pid: int | None = None,
    ):
        self._service = service
        self._data_dir = Path(data_dir)
        self._version = current_version
        self._platform = platform if platform is not None else platform_key()
        self._executable = executable
        self._fetch = fetch
        self._now = now
        self._launch = launch
        self._pid = pid if pid is not None else os.getpid()

    def _exe(self) -> Path | None:
        return self._executable if self._executable is not None else current_executable()

    def check(self, *, force: bool = False) -> UpdateOffer | None:
        """Новая версия или None. Без force учитываются выключатель, суточный интервал и пропущенная версия."""
        settings = self._service.settings
        now = self._now()
        if not force and (not settings.check_updates or not check_due(settings.last_update_check, now)):
            return None
        release = self._fetch(self._version)  # UpdateCheckError уходит вызывающему
        self._service.mark_update_checked(now)
        if release is None:
            return None
        if not force and release.version == settings.skipped_version:
            return None
        return self._offer(release)

    def _offer(self, release: ReleaseInfo) -> UpdateOffer:
        picked = pick_assets(release, self._platform) if self._platform else None
        if picked is None:
            return UpdateOffer(release, False, NO_FILE)
        target = install_target(self._exe(), self._platform)
        if target is None:
            return UpdateOffer(release, False, NOT_PACKAGED)
        if picked[1] is None:
            return UpdateOffer(release, False, NO_CHECKSUM)
        if not is_writable(target.parent) or (self._platform == "windows" and not is_writable(target)):
            reason = f"Нет прав на запись в папку приложения ({target}): скачайте обновление вручную."
            return UpdateOffer(release, False, reason)
        return UpdateOffer(release, True)

    def install(
        self,
        offer: UpdateOffer,
        progress: Callable[[int, int], None] | None = None,
        cancel: Callable[[], bool] | None = None,
    ) -> Path:
        """Скачивает и проверяет обновление, готовит помощника и запускает его; после этого приложение должно закрыться."""
        if not offer.can_install:
            raise InstallError(offer.reason or "Обновление из приложения недоступно")
        picked = pick_assets(offer.release, self._platform)
        exe = self._exe()
        target = install_target(exe, self._platform)
        if picked is None or target is None:
            raise InstallError(offer.reason or NOT_PACKAGED)
        asset, checksum = picked
        work = self._data_dir / "updates" / offer.release.version
        shutil.rmtree(work, ignore_errors=True)
        zip_path = download(asset, checksum, work, progress=progress, cancel=cancel, allow_local=update_source()[1])
        staged = stage(zip_path, work / "staged", self._platform)
        zip_path.unlink(missing_ok=True)
        script = write_helper(
            self._platform,
            work,
            pid=self._pid,
            staged=staged,
            target=target,
            exe=exe,
            backup=backup_dir(target),
            log=self._data_dir / "update.log",
        )
        self._launch(script, self._platform)
        return script

    def skip(self, version: str) -> None:
        self._service.skip_update(version)

    def cleanup(self) -> None:
        """Удаляет остатки прежних обновлений (распакованные файлы и скрипты)."""
        shutil.rmtree(self._data_dir / "updates", ignore_errors=True)
