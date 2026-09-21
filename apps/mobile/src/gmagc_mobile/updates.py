"""Проверка обновлений Android-приложения: раз в сутки, ссылка на APK нового релиза."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass

from gmagc_common.updates import ReleaseInfo, check_due, fetch_latest, pick_assets
from gmagc_mobile.about import VERSION

KEY_ENABLED = "gmagc.updates.enabled"
KEY_LAST = "gmagc.updates.last_check"
KEY_SKIPPED = "gmagc.updates.skipped"


@dataclass(frozen=True)
class UpdateNotice:
    version: str
    url: str  # APK для загрузки (или страница релиза, если APK в релизе нет)
    page_url: str


class UpdateTracker:
    def __init__(
        self,
        prefs,
        current_version: str = VERSION,
        fetch: Callable[[str], ReleaseInfo | None] = fetch_latest,
        now: Callable[[], float] = time.time,
    ):
        self._prefs = prefs
        self._version = current_version
        self._fetch = fetch
        self._now = now

    async def _get(self, key: str):
        try:
            return await self._prefs.get(key)
        except Exception:  # noqa: BLE001 - недоступное хранилище не должно мешать
            return None

    async def enabled(self) -> bool:
        value = await self._get(KEY_ENABLED)
        return value if isinstance(value, bool) else True

    async def set_enabled(self, enabled: bool) -> None:
        await self._prefs.set(KEY_ENABLED, enabled)

    async def check(self, *, force: bool = False) -> UpdateNotice | None:
        """Уведомление о новой версии или None. Без force учитываются выключатель, интервал и пропущенная версия."""
        now = self._now()
        if not force:
            if not await self.enabled():
                return None
            last = await self._get(KEY_LAST)
            last = float(last) if isinstance(last, int | float) and not isinstance(last, bool) else 0.0
            if not check_due(last, now):
                return None
        release = await asyncio.to_thread(self._fetch, self._version)  # UpdateCheckError уходит вызывающему
        await self._prefs.set(KEY_LAST, float(now))
        if release is None:
            return None
        if not force and release.version == await self._get(KEY_SKIPPED):
            return None
        picked = pick_assets(release, "android")
        return UpdateNotice(release.version, picked[0].url if picked else release.page_url, release.page_url)

    async def skip(self, version: str) -> None:
        await self._prefs.set(KEY_SKIPPED, version)
