"""Что телефон помнит между запусками: подключение к ПК, язык, профили приборов, состояние обновлений и поддержки.

Хранилище — QSettings (на Android это SharedPreferences приложения); в тестах подставляется ini-файл. Повреждённые
значения не ронять запуск: они читаются как «нет данных»."""

from __future__ import annotations

import json

from PySide6.QtCore import QSettings

from gmagc_common.fixtures import FixtureProfile, ProfileError, profile_from_dict, profile_to_dict
from gmagc_common.i18n import normalize_choice
from gmagc_common.protocol import Connection, is_valid_code, normalize_code, parse_address
from gmagc_common.support import SupportState

KEY_HOST = "connection/host"
KEY_PORT = "connection/port"
KEY_CODE = "connection/code"
KEY_LANGUAGE = "language"
KEY_PROFILES = "profiles"
KEY_SKIPPED = "updates/skipped"
KEY_LAST_CHECK = "updates/last_check"
KEY_LAUNCHES = "support/launches"
KEY_LAST_ASK = "support/last_ask"
KEY_MUTED = "support/muted"


def _as_port(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return None


class PhoneSettings:
    def __init__(self, store: QSettings | None = None):
        self._store = store if store is not None else QSettings("spacesarmat", "GMAGC")

    # ---- подключение ---------------------------------------------------------
    def load_connection(self) -> Connection | None:
        """Сохранённое подключение; повреждённые данные дают None."""
        host = self._store.value(KEY_HOST)
        port = _as_port(self._store.value(KEY_PORT))
        code = self._store.value(KEY_CODE)
        if not isinstance(host, str) or port is None or not isinstance(code, str):
            return None
        address = parse_address(f"{host}:{port}")
        if address is None or not is_valid_code(code):
            return None
        return Connection(address[0], address[1], normalize_code(code))

    def save_connection(self, connection: Connection) -> None:
        self._store.setValue(KEY_HOST, connection.host)
        self._store.setValue(KEY_PORT, connection.port)
        self._store.setValue(KEY_CODE, connection.code)
        self._store.sync()

    def clear_connection(self) -> None:
        for key in (KEY_HOST, KEY_PORT, KEY_CODE):
            self._store.remove(key)
        self._store.sync()

    # ---- язык ----------------------------------------------------------------
    def load_language(self) -> str:
        return normalize_choice(self._store.value(KEY_LANGUAGE))

    def save_language(self, choice: str) -> None:
        self._store.setValue(KEY_LANGUAGE, normalize_choice(choice))
        self._store.sync()

    # ---- профили приборов ------------------------------------------------------
    def load_profiles(self) -> list[FixtureProfile]:
        raw = self._store.value(KEY_PROFILES)
        try:
            items = json.loads(raw) if isinstance(raw, str) and raw else []
        except ValueError:
            return []
        profiles = []
        for item in items if isinstance(items, list) else []:
            try:
                profiles.append(profile_from_dict(item))
            except ProfileError:
                continue  # повреждённый профиль пропускается, остальные остаются
        return profiles

    def save_profiles(self, profiles: list[FixtureProfile]) -> None:
        self._store.setValue(KEY_PROFILES, json.dumps([profile_to_dict(p) for p in profiles], ensure_ascii=False))
        self._store.sync()

    # ---- обновления и поддержка ------------------------------------------------
    def load_skipped_version(self) -> str:
        value = self._store.value(KEY_SKIPPED)
        return value if isinstance(value, str) else ""

    def save_skipped_version(self, version: str) -> None:
        self._store.setValue(KEY_SKIPPED, version)
        self._store.sync()

    def load_last_check(self) -> float:
        try:
            return float(self._store.value(KEY_LAST_CHECK, 0.0))
        except (TypeError, ValueError):
            return 0.0

    def save_last_check(self, when: float) -> None:
        self._store.setValue(KEY_LAST_CHECK, when)
        self._store.sync()

    def load_support_state(self) -> SupportState:
        try:
            return SupportState(
                launches=int(self._store.value(KEY_LAUNCHES, 0)),
                last_ask=float(self._store.value(KEY_LAST_ASK, 0.0)),
                muted=str(self._store.value(KEY_MUTED, "false")).lower() in ("true", "1"),
            )
        except (TypeError, ValueError):
            return SupportState()

    def save_support_state(self, state: SupportState) -> None:
        self._store.setValue(KEY_LAUNCHES, state.launches)
        self._store.setValue(KEY_LAST_ASK, state.last_ask)
        self._store.setValue(KEY_MUTED, state.muted)
        self._store.sync()
