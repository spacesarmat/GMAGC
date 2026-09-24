"""Протокол связи телефона и ПК: константы, код доступа, ссылка подключения, ответы API.

Только стандартная библиотека: пакет без изменений копируется в приложения (scripts/sync_common.py).
"""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import NamedTuple
from urllib.parse import parse_qs, urlencode, urlsplit

from gmagc_common.i18n import t

API_VERSION = 1
APP_NAME = "GMAGC"
DEFAULT_PORT = 8765
CODE_LENGTH = 8
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # без похожих 0/O и 1/I/L
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_SCAN_BYTES = 20 * 1024 * 1024  # фото или PDF инструкции для автозаполнения профиля
MAX_PROFILE_BYTES = 1024 * 1024  # профиль прибора в JSON: килобайты, мегабайт с большим запасом
LINK_SCHEME = "gmagc"
OUTCOME_FOUND = "found"
OUTCOME_LOW_CONFIDENCE = "low_confidence"
OUTCOME_NO_PROJECTION = "no_projection"

ERROR_STATUS = {
    "unauthorized": 401,
    "bad_request": 400,
    "bad_image": 400,
    "not_found": 404,
    "too_large": 413,
    "rate_limited": 429,
    "no_index": 409,
    "bad_profile": 400,
    "no_target": 409,
    "bad_scan": 400,
    "scan_unavailable": 409,
    "server_error": 500,
}

_HOST = re.compile(r"[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?")


class ProtocolError(ValueError):
    """Ответ сервера не соответствует протоколу."""


class Connection(NamedTuple):
    host: str
    port: int
    code: str


# ---- код доступа -----------------------------------------------------------
def normalize_code(text: str) -> str:
    """Верхний регистр без пробелов и дефисов: `abcd-2345` -> `ABCD2345`."""
    return "".join(ch for ch in text.upper() if not ch.isspace() and ch != "-")


def is_valid_code(text: str) -> bool:
    code = normalize_code(text)
    return len(code) == CODE_LENGTH and all(ch in CODE_ALPHABET for ch in code)


def format_code(text: str) -> str:
    """Код для показа человеку: `ABCD-2345`."""
    code = normalize_code(text)
    return f"{code[:4]}-{code[4:]}" if len(code) > 4 else code


# ---- подключение -----------------------------------------------------------
def _valid_host(host: str) -> bool:
    return _HOST.fullmatch(host) is not None


def _valid_port(port: int) -> bool:
    return 1 <= port <= 65535


def build_link(host: str, port: int, code: str) -> str:
    """Ссылка для QR: gmagc://connect?host=…&port=…&code=…"""
    return f"{LINK_SCHEME}://connect?{urlencode({'host': host, 'port': port, 'code': normalize_code(code)})}"


def parse_link(text: str) -> Connection | None:
    try:
        parts = urlsplit(text.strip())
        query = parse_qs(parts.query)
        host, port, code = query["host"][0], int(query["port"][0]), normalize_code(query["code"][0])
    except (AttributeError, KeyError, IndexError, ValueError):
        return None
    if parts.scheme != LINK_SCHEME or parts.netloc != "connect":
        return None
    if not (_valid_host(host) and _valid_port(port) and is_valid_code(code)):
        return None
    return Connection(host, port, code)


def parse_address(text: str) -> tuple[str, int] | None:
    """Ручной ввод адреса ПК: `192.168.1.5` или `192.168.1.5:8765` (порт по умолчанию 8765)."""
    if not isinstance(text, str):
        return None
    value = text.strip().removeprefix("http://").rstrip("/")
    host, separator, port_text = value.partition(":")
    try:
        port = int(port_text) if separator else DEFAULT_PORT
    except ValueError:
        return None
    if not (_valid_host(host) and _valid_port(port)):
        return None
    return host, port


# ---- ответы API -------------------------------------------------------------
def _encode(data: bytes | None) -> str | None:
    return None if data is None else base64.b64encode(data).decode("ascii")


def _decode(value: str | None) -> bytes | None:
    if value is None:
        return None
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, TypeError, ValueError) as error:
        raise ProtocolError(t("повреждённое изображение в ответе")) from error


def _parse[T](build: Callable[[], T]) -> T:
    """Вызывает build() и превращает любые ошибки разбора в ProtocolError."""
    try:
        return build()
    except ProtocolError:
        raise
    except (KeyError, TypeError, AttributeError, ValueError) as error:
        raise ProtocolError(t("неверный ответ сервера: {error}", error=repr(error))) from error


@dataclass(frozen=True)
class ResultItem:
    rank: int
    name: str
    path: str  # полный путь файла на ПК
    score: float  # доля от 0 до 1
    copies: tuple[str, ...]
    thumbnail_png: bytes

    def to_dict(self) -> dict:
        return {
            "rank": self.rank,
            "name": self.name,
            "path": self.path,
            "score": self.score,
            "copies": list(self.copies),
            "thumbnail_png": _encode(self.thumbnail_png),
        }

    @classmethod
    def from_dict(cls, data: dict) -> ResultItem:
        return _parse(
            lambda: cls(
                int(data["rank"]),
                str(data["name"]),
                str(data["path"]),
                float(data["score"]),
                tuple(str(path) for path in data.get("copies", [])),
                _decode(data.get("thumbnail_png")) or b"",
            )
        )


@dataclass(frozen=True)
class MatchResponse:
    request_id: str
    outcome: str  # found / low_confidence / no_projection
    took_ms: float
    results: tuple[ResultItem, ...]
    projection_png: bytes | None

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "outcome": self.outcome,
            "took_ms": self.took_ms,
            "results": [item.to_dict() for item in self.results],
            "projection_png": _encode(self.projection_png),
        }

    @classmethod
    def from_dict(cls, data: dict) -> MatchResponse:
        return _parse(
            lambda: cls(
                str(data["request_id"]),
                str(data["outcome"]),
                float(data["took_ms"]),
                tuple(ResultItem.from_dict(item) for item in data["results"]),
                _decode(data.get("projection_png")),
            )
        )


@dataclass(frozen=True)
class Health:
    app: str
    api: int
    version: str
    indexed: bool
    files: int

    def to_dict(self) -> dict:
        return {"app": self.app, "api": self.api, "version": self.version, "indexed": self.indexed, "files": self.files}

    @classmethod
    def from_dict(cls, data: dict) -> Health:
        return _parse(
            lambda: cls(str(data["app"]), int(data["api"]), str(data["version"]), bool(data["indexed"]), int(data["files"]))
        )


SKIP_NO_FOLDER = "no_folder"  # для пульта нет папки: не найдена и не задана
SKIP_CANNOT_USE = "cannot_use"  # заданную папку нельзя использовать (подробности в третьей части)
SKIP_NO_GOBO = "no_gobo"  # файла гобо нет в библиотеке на ПК: в пульте у этого слота не будет картинки (имя — в детали)
SKIP_TARGETS = ("ma3", "ma2")


def skip_item(code: str, target: str, detail: str = "") -> str:
    """Запись о пропущенном пульте: `код:пульт[:подробности]`."""
    return f"{code}:{target}:{detail}" if detail else f"{code}:{target}"


def parse_skip(item: str) -> tuple[str, str, str] | None:
    """(код, пульт, подробности) или None, если запись не в этом виде (старый ПК присылает готовый текст)."""
    parts = item.split(":", 2)
    if len(parts) >= 2 and parts[0] in (SKIP_NO_FOLDER, SKIP_CANNOT_USE, SKIP_NO_GOBO) and parts[1] in SKIP_TARGETS:
        return parts[0], parts[1], parts[2] if len(parts) == 3 else ""
    return None


@dataclass(frozen=True)
class FixtureUploadResult:
    """Итог отправки профиля прибора: какие файлы записал ПК (пульт, путь) и какие пульты пропустил (см. skip_item)."""

    written: tuple[tuple[str, str], ...]
    skipped: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "written": [{"target": target, "path": path} for target, path in self.written],
            "skipped": list(self.skipped),
        }

    @classmethod
    def from_dict(cls, data: dict) -> FixtureUploadResult:
        def build() -> FixtureUploadResult:
            written, skipped = data["written"], data["skipped"]
            if not isinstance(written, list) or not isinstance(skipped, list):
                raise TypeError(t("ожидались списки"))
            return cls(
                tuple((str(item["target"]), str(item["path"])) for item in written),
                tuple(str(item) for item in skipped),
            )

        return _parse(build)


@dataclass(frozen=True)
class GoboItem:
    """Гобо из библиотеки на ПК для слота колеса: путь в библиотеке, путь картинки в типе, превью и миниатюра слота."""

    name: str
    source: str  # путь относительно библиотеки
    path: str  # путь картинки в файле типа (media_filename)
    png: bytes  # превью для списка на телефоне
    thumb: str  # base64(zlib(RGBA 64×64)) для файла типа

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "source": self.source,
            "path": self.path,
            "png": _encode(self.png),
            "thumb": self.thumb,
        }

    @classmethod
    def from_dict(cls, data: dict) -> GoboItem:
        return _parse(
            lambda: cls(
                str(data["name"]),
                str(data["source"]),
                str(data["path"]),
                _decode(data["png"]) or b"",
                str(data["thumb"]),
            )
        )


@dataclass(frozen=True)
class GoboList:
    items: tuple[GoboItem, ...]
    total: int  # сколько нашлось всего (в ответе не больше limit)

    def to_dict(self) -> dict:
        return {"items": [item.to_dict() for item in self.items], "total": self.total}

    @classmethod
    def from_dict(cls, data: dict) -> GoboList:
        def build() -> GoboList:
            items = data["items"]
            if not isinstance(items, list):
                raise TypeError(t("ожидался список"))
            return cls(tuple(GoboItem.from_dict(item) for item in items), int(data["total"]))

        return _parse(build)


@dataclass(frozen=True)
class Status:
    indexed: bool
    files: int
    families: int
    indexing: bool
    done: int
    total: int

    def to_dict(self) -> dict:
        return {
            "indexed": self.indexed,
            "files": self.files,
            "families": self.families,
            "indexing": self.indexing,
            "done": self.done,
            "total": self.total,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Status:
        return _parse(
            lambda: cls(
                bool(data["indexed"]),
                int(data["files"]),
                int(data["families"]),
                bool(data["indexing"]),
                int(data["done"]),
                int(data["total"]),
            )
        )


@dataclass(frozen=True)
class ApiError:
    code: str
    message: str

    def to_dict(self) -> dict:
        return {"error": self.code, "message": self.message}

    @classmethod
    def from_dict(cls, data: dict) -> ApiError:
        return _parse(lambda: cls(str(data["error"]), str(data["message"])))
