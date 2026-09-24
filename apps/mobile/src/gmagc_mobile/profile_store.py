"""Профили приборов на телефоне: JSON в SharedPreferences (индекс + по ключу на профиль)."""

from __future__ import annotations

import json

from gmagc_common.fixtures import FixtureProfile, profile_from_dict, profile_to_dict

INDEX_KEY = "gmagc.profiles.index"


def profile_key(profile_id: str) -> str:
    return f"gmagc.profile.{profile_id}"


class MemoryPrefs:
    """Хранилище в памяти: запасной вариант, когда приложению не передали настоящие prefs."""

    def __init__(self):
        self.data: dict = {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value):
        self.data[key] = value
        return True

    async def remove(self, key):
        return self.data.pop(key, None) is not None


class ProfileStore:
    def __init__(self, prefs):
        self._prefs = prefs

    async def _index(self) -> list[str]:
        try:
            raw = await self._prefs.get(INDEX_KEY)
            ids = json.loads(raw) if isinstance(raw, str) else []
        except Exception:  # noqa: BLE001 - недоступное или повреждённое хранилище = пустой список
            return []
        return [item for item in ids if isinstance(item, str)] if isinstance(ids, list) else []

    async def list(self) -> list[FixtureProfile]:
        profiles = []
        for profile_id in await self._index():
            try:
                raw = await self._prefs.get(profile_key(profile_id))
                profiles.append(profile_from_dict(json.loads(raw)))
            except Exception:  # noqa: BLE001 - повреждённый или недоступный профиль пропускаем, остальные живут
                continue
        return profiles

    async def save(self, profile: FixtureProfile) -> None:
        await self._prefs.set(profile_key(profile.id), json.dumps(profile_to_dict(profile), ensure_ascii=False))
        index = await self._index()
        if profile.id not in index:
            index.append(profile.id)
            await self._prefs.set(INDEX_KEY, json.dumps(index))

    async def delete(self, profile_id: str) -> None:
        await self._prefs.remove(profile_key(profile_id))
        index = [item for item in await self._index() if item != profile_id]
        await self._prefs.set(INDEX_KEY, json.dumps(index))
