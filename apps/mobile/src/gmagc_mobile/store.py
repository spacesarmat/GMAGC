"""Запоминает подключение к ПК (адрес, порт, код) в SharedPreferences."""

from __future__ import annotations

from gmagc_common.protocol import Connection, is_valid_code, normalize_code, parse_address

KEY_HOST = "gmagc.host"
KEY_PORT = "gmagc.port"
KEY_CODE = "gmagc.code"


def _as_port(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


class ConnectionStore:
    def __init__(self, prefs):
        self._prefs = prefs

    async def load(self) -> Connection | None:
        """Сохранённое подключение; повреждённые или недоступные данные дают None."""
        try:
            host = await self._prefs.get(KEY_HOST)
            port = _as_port(await self._prefs.get(KEY_PORT))
            code = await self._prefs.get(KEY_CODE)
        except Exception:  # noqa: BLE001 - недоступное хранилище не должно ронять запуск
            return None
        if not isinstance(host, str) or port is None or not isinstance(code, str):
            return None
        address = parse_address(f"{host}:{port}")
        if address is None or not is_valid_code(code):
            return None
        return Connection(address[0], address[1], normalize_code(code))

    async def save(self, connection: Connection) -> None:
        await self._prefs.set(KEY_HOST, connection.host)
        await self._prefs.set(KEY_PORT, connection.port)
        await self._prefs.set(KEY_CODE, connection.code)

    async def clear(self) -> None:
        for key in (KEY_HOST, KEY_PORT, KEY_CODE):
            await self._prefs.remove(key)
