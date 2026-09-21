# GMAGC: сервер для телефона (этап 4). План реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ПК-приложение принимает фото по Wi-Fi (HTTP-сервер стартует автоматически), возвращает результаты поиска, показывает QR/код подключения и историю запросов; клик по найденному файлу копирует его абсолютный путь в буфер обмена.

**Architecture:** Общий протокол `gmagc_common` (стандартная библиотека, копии в приложениях, тест на совпадение). Сервер на `http.server` в `gmagc_desktop/server/` поверх `SearchService` (замок вокруг поиска и подмены индекса); блок «Телефон» и история в экране Flet; `scripts/phone_sim.py` заменяет телефон при проверке.

**Tech Stack:** Python 3.12, Flet 1.0.0, стандартная библиотека (`http.server`, `hmac`, `secrets`), `segno` (QR), pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-09-21-gmagc-phone-server-design.md`

## Global Constraints

- Flet закреплён на 1.0.0; `requires-python = ">=3.12,<3.13"`; `[tool.flet.compile] packages = false` остаётся. Новые зависимости только `segno` (в `apps/desktop/pyproject.toml` и `requirements-dev.txt`); FastAPI/uvicorn/pydantic не используются.
- Слой `service/` и `server/` не импортируют Flet; `ui/` без бизнес-логики.
- API: `API_VERSION = 1`, порт по умолчанию 8765 (до 10 попыток подряд), код 8 символов из `ABCDEFGHJKMNPQRSTUVWXYZ23456789`, тело фото до 10 МБ, все методы кроме `/api/health` требуют `Authorization: Bearer <код>`, после 5 неверных кодов с одного адреса 429 на 30 с.
- Сервер включён по умолчанию (`server_enabled = True`), код постоянный (в `settings.json`), «Новый код» создаёт другой.
- Клик по карточке результата копирует `os.path.abspath(full_path)` (путь вместе с именем файла) через `Clipboard.set`; открытие папки только по кнопке значка папки.
- `packages/common/gmagc_common` каноничен; копия `apps/desktop/src/gmagc_common` обновляется `python scripts/sync_common.py` и коммитится.
- Тесты используют только синтетические данные (`tests/fixtures.py`); `gobos/`, `photo/`, `models/` не читаются и не коммитятся.
- Автор `@ANDY_BUM` остаётся на экране. Комментарии и строки интерфейса на русском.
- Коммиты: `git commit -m "<тип>: <описание>" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"`. Работа на ветке `feat/phone-server`, в `main` только через Pull Request с зелёными проверками.
- Запуск тестов: `.venv\Scripts\python.exe -m pytest -q`, линтер: `.venv\Scripts\python.exe -m ruff check .`.

---

### Task 1: Общий протокол `gmagc_common`

**Files:**
- Create: `packages/common/gmagc_common/__init__.py`, `packages/common/gmagc_common/protocol.py`, `scripts/sync_common.py`, `apps/desktop/src/gmagc_common/` (копия скриптом)
- Test: `tests/common/test_protocol.py`, `tests/common/test_common_sync.py`

**Interfaces:**
- Produces (`gmagc_common.protocol`): константы `API_VERSION`, `APP_NAME`, `DEFAULT_PORT`, `CODE_LENGTH`, `CODE_ALPHABET`, `MAX_IMAGE_BYTES`, `LINK_SCHEME`, `ERROR_STATUS: dict[str, int]`; `normalize_code(text) -> str`, `is_valid_code(text) -> bool`, `format_code(text) -> str`; `Connection(host, port, code)`; `build_link(host, port, code) -> str`, `parse_link(text) -> Connection | None`, `parse_address(text) -> tuple[str, int] | None`; `ProtocolError(ValueError)`; dataclasses `ResultItem`, `MatchResponse`, `Health`, `Status`, `ApiError` с `to_dict()` / `from_dict(dict)`.

- [ ] **Step 1: Write the failing tests**

```python
# path: tests/common/test_protocol.py
import pytest

from gmagc_common import protocol
from gmagc_common.protocol import (
    ApiError,
    Connection,
    Health,
    MatchResponse,
    ProtocolError,
    ResultItem,
    Status,
    build_link,
    format_code,
    is_valid_code,
    normalize_code,
    parse_address,
    parse_link,
)


def test_code_helpers_ignore_case_spaces_and_dashes():
    assert normalize_code(" abcd-2345 ") == "ABCD2345"
    assert format_code("abcd2345") == "ABCD-2345"
    assert is_valid_code("ABCD-2345") and is_valid_code("abcd2345")


@pytest.mark.parametrize("bad", ["", "ABCD234", "ABCD23456", "ABCD-234O", "ABCD-2341", "ABCD-23L5", "ЖЖЖЖ2345"])
def test_invalid_codes_are_rejected(bad):
    assert not is_valid_code(bad)


def test_the_alphabet_has_no_lookalikes_and_matches_the_code_length():
    assert not set("0O1IL") & set(protocol.CODE_ALPHABET)
    assert len(set(protocol.CODE_ALPHABET)) == len(protocol.CODE_ALPHABET) == 31
    assert protocol.CODE_LENGTH == 8


def test_link_round_trip():
    link = build_link("192.168.1.5", 8765, "abcd-2345")
    assert link == "gmagc://connect?host=192.168.1.5&port=8765&code=ABCD2345"
    assert parse_link(link) == Connection("192.168.1.5", 8765, "ABCD2345")
    assert parse_link("  " + link + "\n") == Connection("192.168.1.5", 8765, "ABCD2345")


@pytest.mark.parametrize(
    "bad",
    [
        "http://connect?host=1.2.3.4&port=8765&code=ABCD2345",
        "gmagc://other?host=1.2.3.4&port=8765&code=ABCD2345",
        "gmagc://connect?port=8765&code=ABCD2345",
        "gmagc://connect?host=1.2.3.4&port=0&code=ABCD2345",
        "gmagc://connect?host=1.2.3.4&port=70000&code=ABCD2345",
        "gmagc://connect?host=1.2.3.4&port=abc&code=ABCD2345",
        "gmagc://connect?host=1.2.3.4&port=8765&code=BAD",
        "gmagc://connect?host=a/b&port=8765&code=ABCD2345",
        "",
        "мусор",
    ],
)
def test_bad_links_give_none(bad):
    assert parse_link(bad) is None


def test_parse_link_tolerates_non_strings():
    assert parse_link(None) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("192.168.1.5", ("192.168.1.5", 8765)),
        ("192.168.1.5:9000", ("192.168.1.5", 9000)),
        (" http://pc-name.local:8766/ ", ("pc-name.local", 8766)),
        ("192.168.1.5:", None),
        ("192.168.1.5:99999", None),
        ("a:b:c", None),
        ("", None),
        ("bad host", None),
    ],
)
def test_parse_address(text, expected):
    assert parse_address(text) == expected


def sample_response():
    item = ResultItem(1, "a.png", "C:\\lib\\a.png", 0.875, ("C:\\lib2\\a.png",), b"\x89PNGthumb")
    return MatchResponse("abc123", "found", 12.5, (item,), b"\x89PNGproj")


def test_match_response_round_trip_keeps_bytes_and_tuples():
    response = sample_response()
    restored = MatchResponse.from_dict(response.to_dict())
    assert restored == response
    assert isinstance(restored.results[0].copies, tuple)
    assert MatchResponse.from_dict(MatchResponse("x", "no_projection", 1.0, (), None).to_dict()).projection_png is None


def test_health_status_and_error_round_trip():
    health = Health("GMAGC", 1, "0.4.0", True, 11178)
    status = Status(True, 11178, 9396, False, 0, 0)
    error = ApiError("unauthorized", "неверный код доступа")
    assert Health.from_dict(health.to_dict()) == health
    assert Status.from_dict(status.to_dict()) == status
    assert ApiError.from_dict(error.to_dict()) == error


@pytest.mark.parametrize(
    "broken",
    [
        {},
        {"request_id": "x"},
        {"request_id": "x", "outcome": "found", "took_ms": "не число", "results": []},
        {"request_id": "x", "outcome": "found", "took_ms": 1, "results": [{"rank": 1}]},
        {"request_id": "x", "outcome": "found", "took_ms": 1, "results": [], "projection_png": "!!not base64!!"},
        None,
    ],
)
def test_broken_responses_raise_protocol_error(broken):
    with pytest.raises(ProtocolError):
        MatchResponse.from_dict(broken)


def test_every_error_code_has_an_http_status():
    codes = {"unauthorized", "bad_request", "bad_image", "not_found", "too_large", "rate_limited", "no_index", "server_error"}
    assert set(protocol.ERROR_STATUS) == codes
    assert protocol.ERROR_STATUS["unauthorized"] == 401 and protocol.ERROR_STATUS["rate_limited"] == 429
    assert protocol.ERROR_STATUS["too_large"] == 413 and protocol.ERROR_STATUS["no_index"] == 409
```

```python
# path: tests/common/test_common_sync.py
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "packages" / "common" / "gmagc_common"
TARGETS = [ROOT / "apps" / "desktop" / "src" / "gmagc_common"]


def test_app_copies_match_the_canonical_package():
    names = sorted(path.name for path in SOURCE.glob("*.py"))
    assert "protocol.py" in names
    for target in TARGETS:
        assert sorted(path.name for path in target.glob("*.py")) == names, f"{target}: набор файлов отличается"
        for name in names:
            assert (target / name).read_bytes() == (SOURCE / name).read_bytes(), (
                f"{target / name} расходится с оригиналом: запустите python scripts/sync_common.py"
            )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/common -q`
Expected: FAIL (`ModuleNotFoundError: gmagc_common`).

- [ ] **Step 3: Write the implementation**

```python
# path: packages/common/gmagc_common/__init__.py
"""Общий для ПК и телефона протокол GMAGC (только стандартная библиотека)."""
```

```python
# path: packages/common/gmagc_common/protocol.py
"""Протокол связи телефона и ПК: константы, код доступа, ссылка подключения, ответы API.

Только стандартная библиотека: пакет без изменений копируется в приложения (scripts/sync_common.py).
"""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import NamedTuple, TypeVar
from urllib.parse import parse_qs, urlencode, urlsplit

API_VERSION = 1
APP_NAME = "GMAGC"
DEFAULT_PORT = 8765
CODE_LENGTH = 8
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # без похожих 0/O и 1/I/L
MAX_IMAGE_BYTES = 10 * 1024 * 1024
LINK_SCHEME = "gmagc"

ERROR_STATUS = {
    "unauthorized": 401,
    "bad_request": 400,
    "bad_image": 400,
    "not_found": 404,
    "too_large": 413,
    "rate_limited": 429,
    "no_index": 409,
    "server_error": 500,
}

_HOST = re.compile(r"[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?")
_T = TypeVar("_T")


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
        raise ProtocolError("повреждённое изображение в ответе") from error


def _parse(build: Callable[[], _T]) -> _T:
    """Вызывает build() и превращает любые ошибки разбора в ProtocolError."""
    try:
        return build()
    except ProtocolError:
        raise
    except (KeyError, TypeError, AttributeError, ValueError) as error:
        raise ProtocolError(f"неверный ответ сервера: {error!r}") from error


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
```

```python
# path: scripts/sync_common.py
"""Копирует packages/common/gmagc_common в приложения: python scripts/sync_common.py"""

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "packages" / "common" / "gmagc_common"
TARGETS = [ROOT / "apps" / "desktop" / "src" / "gmagc_common"]


def sync() -> list[Path]:
    written = []
    for target in TARGETS:
        target.mkdir(parents=True, exist_ok=True)
        for source in sorted(SOURCE.glob("*.py")):
            shutil.copyfile(source, target / source.name)
            written.append(target / source.name)
    return written


if __name__ == "__main__":
    for path in sync():
        print(path.relative_to(ROOT))
```

- [ ] **Step 4: Sync the copy and run the tests**

Run: `.venv\Scripts\python.exe scripts\sync_common.py`, затем `.venv\Scripts\python.exe -m pytest tests/common -q`
Expected: PASS (оба файла тестов).

- [ ] **Step 5: Lint and commit**

```bash
.venv/Scripts/python.exe -m ruff check --fix . && .venv/Scripts/python.exe scripts/sync_common.py && .venv/Scripts/python.exe -m pytest tests/common -q
git add packages scripts/sync_common.py apps/desktop/src/gmagc_common tests/common
git commit -m "feat: shared phone protocol package with synced app copy" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: Настройки сервера и потокобезопасный `SearchService`

**Files:**
- Modify: `apps/desktop/src/gmagc_desktop/service/settings.py`, `apps/desktop/src/gmagc_desktop/service/search_service.py`
- Create: `apps/desktop/src/gmagc_desktop/service/access.py`
- Test: `tests/desktop/test_settings_server.py`, `tests/desktop/test_service_access.py`, `tests/server/test_access.py`

**Interfaces:**
- Consumes: `gmagc_common.protocol` (`DEFAULT_PORT`, `CODE_ALPHABET`, `CODE_LENGTH`, `is_valid_code`, `normalize_code`).
- Produces: `Settings(library_dir, top_n, server_enabled=True, port=8765, access_code="")`; `service.access.generate_code() -> str`, `codes_equal(expected, given) -> bool`, `RateLimiter(max_failures=5, block_seconds=30.0, clock=time.monotonic)` с `retry_after(client) -> int`, `failure(client)`, `success(client)`; `SearchService.ensure_access_code() -> str`, `reset_access_code() -> str`, `set_server_enabled(bool)`, `indexing_state() -> tuple[bool, int, int]`, `search_image_bytes(data, top_n=None)`; поиск и подмена индекса идут под общим `RLock`.

- [ ] **Step 1: Write the failing tests**

```python
# path: tests/desktop/test_settings_server.py
import json

import pytest

from gmagc_common.protocol import DEFAULT_PORT
from gmagc_desktop.service.settings import Settings, load_settings, save_settings


def test_server_defaults_enable_the_server_on_the_default_port():
    settings = Settings()
    assert settings.server_enabled is True and settings.port == DEFAULT_PORT and settings.access_code == ""


def test_server_settings_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    save_settings(Settings(server_enabled=False, port=9000, access_code="ABCD2345"), path)

    loaded = load_settings(path)

    assert (loaded.server_enabled, loaded.port, loaded.access_code) == (False, 9000, "ABCD2345")


def test_access_code_is_normalized_on_load(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"access_code": "abcd-2345"}), encoding="utf-8")

    assert load_settings(path).access_code == "ABCD2345"


@pytest.mark.parametrize(
    "raw",
    [
        {"server_enabled": "no", "port": "9000", "access_code": 123},
        {"port": 80, "access_code": "short"},
        {"port": True},
        {"port": 70000},
        {"access_code": "ABCD0O1I"},
    ],
)
def test_bad_server_values_fall_back_to_defaults(tmp_path, raw):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    loaded = load_settings(path)

    assert loaded.server_enabled is True and loaded.port == DEFAULT_PORT and loaded.access_code == ""
```

```python
# path: tests/server/test_access.py
import string

import pytest

from gmagc_common.protocol import CODE_ALPHABET, CODE_LENGTH, is_valid_code
from gmagc_desktop.service.access import RateLimiter, codes_equal, generate_code


def test_generated_codes_are_valid_and_differ():
    codes = {generate_code() for _ in range(20)}
    assert len(codes) == 20
    assert all(len(code) == CODE_LENGTH and set(code) <= set(CODE_ALPHABET) and is_valid_code(code) for code in codes)
    assert not set(string.ascii_lowercase) & set("".join(codes))


def test_codes_equal_ignores_case_and_dashes_but_never_matches_an_empty_code():
    assert codes_equal("ABCD2345", "abcd-2345")
    assert not codes_equal("ABCD2345", "ABCD2346")
    assert not codes_equal("", "")
    assert not codes_equal("", "ABCD2345")
    assert not codes_equal("ABCD2345", "")
    assert not codes_equal("ABCD2345", "ЖЖЖЖ2345")


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_rate_limiter_blocks_after_five_failures_and_recovers():
    clock = FakeClock()
    limiter = RateLimiter(max_failures=5, block_seconds=30.0, clock=clock)

    for _ in range(4):
        limiter.failure("1.1.1.1")
        assert limiter.retry_after("1.1.1.1") == 0
    limiter.failure("1.1.1.1")

    assert limiter.retry_after("1.1.1.1") == 30
    assert limiter.retry_after("2.2.2.2") == 0
    clock.now += 10.2
    assert limiter.retry_after("1.1.1.1") == 20
    clock.now += 20
    assert limiter.retry_after("1.1.1.1") == 0
    limiter.failure("1.1.1.1")
    assert limiter.retry_after("1.1.1.1") == 0  # счётчик начат заново


def test_success_resets_the_failure_counter():
    limiter = RateLimiter(max_failures=3, block_seconds=30.0, clock=FakeClock())
    limiter.failure("a")
    limiter.failure("a")
    limiter.success("a")
    limiter.failure("a")
    limiter.failure("a")
    assert limiter.retry_after("a") == 0


@pytest.mark.parametrize("bad", [0, -1])
def test_rate_limiter_rejects_a_non_positive_limit(bad):
    with pytest.raises(ValueError):
        RateLimiter(max_failures=bad)
```

```python
# path: tests/desktop/test_service_access.py
import threading

import cv2
import numpy as np
import pytest

from gmagc_common.protocol import is_valid_code
from gmagc_desktop.matcher.synthetic import simulate_photo
from gmagc_desktop.service.search_service import SearchService
from tests.fixtures import shape_images, write_library


@pytest.fixture()
def library(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    write_library(root)
    return root


@pytest.fixture()
def service(tmp_path, library):
    instance = SearchService(tmp_path / "data")
    instance.load()
    instance.set_library(library)
    instance.build_index()
    return instance


def photo_png(seed=5):
    photo = simulate_photo(shape_images()["ell"], np.random.default_rng(seed))
    ok, buffer = cv2.imencode(".png", photo)
    assert ok
    return buffer.tobytes()


def test_access_code_is_generated_once_and_persisted(tmp_path):
    service = SearchService(tmp_path / "data")
    service.load()

    code = service.ensure_access_code()

    assert is_valid_code(code) and service.ensure_access_code() == code
    other = SearchService(tmp_path / "data")
    other.load()
    assert other.settings.access_code == code


def test_reset_access_code_changes_and_persists_it(tmp_path):
    service = SearchService(tmp_path / "data")
    service.load()
    old = service.ensure_access_code()

    new = service.reset_access_code()

    assert new != old and is_valid_code(new)
    other = SearchService(tmp_path / "data")
    other.load()
    assert other.settings.access_code == new


def test_set_server_enabled_is_persisted(tmp_path):
    service = SearchService(tmp_path / "data")
    service.load()

    service.set_server_enabled(False)

    other = SearchService(tmp_path / "data")
    other.load()
    assert other.settings.server_enabled is False


def test_indexing_state_follows_the_build(tmp_path, library):
    service = SearchService(tmp_path / "data")
    service.load()
    service.set_library(library)
    assert service.indexing_state() == (False, 0, 0)
    seen = []

    service.build_index(progress=lambda done, total: seen.append(service.indexing_state()))

    assert seen and all(state[0] for state in seen)
    assert seen[-1][1] == seen[-1][2] > 0
    assert service.indexing_state()[0] is False


def test_indexing_flag_is_cleared_when_the_build_fails(tmp_path):
    service = SearchService(tmp_path / "data")
    service.load()
    service.set_library(tmp_path / "missing")

    with pytest.raises(Exception):  # noqa: B017 - тип ошибки проверяют тесты индекса
        service.build_index()

    assert service.indexing_state()[0] is False


def test_search_image_bytes_honors_top_n(service):
    assert len(service.search_image_bytes(photo_png(), top_n=2).results) == 2


def test_search_waits_while_the_index_is_being_swapped(service):
    finished = threading.Event()

    def search():
        service.search_image_bytes(photo_png())
        finished.set()

    with service._lock:  # noqa: SLF001 - проверяем, что поиск держит общий замок
        thread = threading.Thread(target=search)
        thread.start()
        assert not finished.wait(0.4)
    assert finished.wait(15)
    thread.join()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/desktop/test_settings_server.py tests/desktop/test_service_access.py tests/server/test_access.py -q`
Expected: FAIL (нет `service.access`, полей `Settings`, методов сервиса).

- [ ] **Step 3: Write the implementation**

```python
# path: apps/desktop/src/gmagc_desktop/service/access.py
"""Код доступа телефона и защита от его подбора."""

from __future__ import annotations

import hmac
import math
import secrets
import threading
import time
from collections.abc import Callable

from gmagc_common.protocol import CODE_ALPHABET, CODE_LENGTH, normalize_code


def generate_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def codes_equal(expected: str, given: str) -> bool:
    """Сравнение за постоянное время; пустой код на ПК не совпадает ни с чем."""
    if not expected:
        return False
    return hmac.compare_digest(normalize_code(expected).encode("utf-8"), normalize_code(given).encode("utf-8"))


class RateLimiter:
    """После max_failures неверных кодов подряд адрес блокируется на block_seconds."""

    def __init__(
        self, max_failures: int = 5, block_seconds: float = 30.0, clock: Callable[[], float] = time.monotonic
    ):
        if max_failures < 1:
            raise ValueError("max_failures должен быть положительным")
        self._max_failures = max_failures
        self._block_seconds = block_seconds
        self._clock = clock
        self._failures: dict[str, int] = {}
        self._blocked_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def retry_after(self, client: str) -> int:
        """Сколько секунд адрес ещё заблокирован (0: можно пробовать)."""
        with self._lock:
            until = self._blocked_until.get(client)
            if until is None:
                return 0
            left = until - self._clock()
            if left <= 0:
                del self._blocked_until[client]
                return 0
            return math.ceil(left)

    def failure(self, client: str) -> None:
        with self._lock:
            count = self._failures.get(client, 0) + 1
            if count >= self._max_failures:
                self._blocked_until[client] = self._clock() + self._block_seconds
                count = 0
            self._failures[client] = count

    def success(self, client: str) -> None:
        with self._lock:
            self._failures.pop(client, None)
```

```python
# path: apps/desktop/src/gmagc_desktop/service/settings.py
"""Настройки приложения и каталог данных пользователя."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from gmagc_common.protocol import DEFAULT_PORT, is_valid_code, normalize_code

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


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


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
    server_enabled = raw.get("server_enabled", True)
    port = raw.get("port", DEFAULT_PORT)
    access_code = raw.get("access_code", "")
    return Settings(
        library_dir=library_dir if isinstance(library_dir, str) else "",
        top_n=top_n if _is_int(top_n) and 1 <= top_n <= MAX_TOP_N else 10,
        server_enabled=server_enabled if isinstance(server_enabled, bool) else True,
        port=port if _is_int(port) and 1024 <= port <= MAX_PORT else DEFAULT_PORT,
        access_code=normalize_code(access_code) if isinstance(access_code, str) and is_valid_code(access_code) else "",
    )


def save_settings(settings: Settings, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")
```

Правки `apps/desktop/src/gmagc_desktop/service/search_service.py` (Edit-ами):

1. Импорты: после `import time` добавить `import threading`; в блок первой стороны после `import numpy as np` (после пустой строки) добавить `from gmagc_common.protocol import is_valid_code` перед `from gmagc_desktop.library.cache import update_index`, и `from gmagc_desktop.service.access import generate_code` перед `from gmagc_desktop.service.results import ...`.
2. В `__init__` после `self._searcher: Searcher | None = None` добавить:

```python
        self._lock = threading.RLock()  # поиск и подмена индекса не пересекаются: UI и сервер работают из разных потоков
        self._indexing = False
        self._done = 0
        self._total = 0
```

3. `_use`, `set_library`, `build_index`, `search_photo`, `search_image_bytes` заменить на:

```python
    def _use(self, index: LibraryIndex | None) -> None:
        with self._lock:
            self._index = index
            self._searcher = (
                None if index is None else Searcher(index.search_data(), self._embedder, w_embed=DEFAULT_W_EMBED)
            )

    def _update_settings(self, **changes) -> None:
        with self._lock:
            self.settings = replace(self.settings, **changes)
            save_settings(self.settings, self._settings_path)

    def set_library(self, path: str | Path) -> None:
        """Запоминает папку библиотеки; индекс другой папки сбрасывается вместе с кэшем."""
        path = str(path)
        with self._lock:
            if path != self.settings.library_dir:
                self._use(None)
                self._index_path.unlink(missing_ok=True)
            self._update_settings(library_dir=path)

    def build_index(
        self, progress: ProgressCallback | None = None, cancel: Callable[[], bool] | None = None
    ) -> IndexStatus:
        """Строит или дособирает индекс. LibraryNotFound, LibraryScanError, IndexCancelled пробрасываются."""
        if not self.settings.library_dir:
            raise NoIndexError("папка библиотеки не выбрана")
        self._indexing, self._done, self._total = True, 0, 0
        try:
            self._use(
                update_index(self.settings.library_dir, self._embedder, self._index_path, self._track(progress), cancel)
            )
        finally:
            self._indexing = False
        return self.status()

    def _track(self, progress: ProgressCallback | None) -> ProgressCallback:
        def report(done: int, total: int) -> None:
            self._done, self._total = done, total
            if progress is not None:
                progress(done, total)

        return report

    def indexing_state(self) -> tuple[bool, int, int]:
        """(идёт ли индексация, готово, всего) для /api/status."""
        return self._indexing, self._done, self._total

    def ensure_access_code(self) -> str:
        """Код доступа телефона: создаётся один раз и хранится в настройках."""
        with self._lock:
            if not is_valid_code(self.settings.access_code):
                self._update_settings(access_code=generate_code())
            return self.settings.access_code

    def reset_access_code(self) -> str:
        with self._lock:
            self._update_settings(access_code=generate_code())
            return self.settings.access_code

    def set_server_enabled(self, enabled: bool) -> None:
        self._update_settings(server_enabled=enabled)

    def search_photo(self, photo_bgr: np.ndarray, top_n: int | None = None) -> SearchOutcome:
        with self._lock:  # индекс и папка библиотеки не меняются, пока идёт поиск
            return self._search(photo_bgr, top_n)

    def _search(self, photo_bgr: np.ndarray, top_n: int | None) -> SearchOutcome:
        searcher, index = self._searcher, self._index
        if searcher is None or index is None:
            raise NoIndexError("индекс не построен")
        started = time.perf_counter()
        normalized = normalize_photo(photo_bgr)
        if normalized is None:
            return SearchOutcome(Outcome.NO_PROJECTION, took_ms=_elapsed_ms(started))
        matches = searcher.search(normalized, top_n=top_n or self.settings.top_n)
        results = tuple(self._result(index, rank, match) for rank, match in enumerate(matches, start=1))
        confident = bool(results) and results[0].score >= LOW_CONFIDENCE_SCORE
        return SearchOutcome(
            Outcome.FOUND if confident else Outcome.LOW_CONFIDENCE,
            results,
            thumbnail_png(normalized, PROJECTION_SIZE),
            _elapsed_ms(started),
        )
```

и `search_image_bytes`:

```python
    def search_image_bytes(self, data: bytes, top_n: int | None = None) -> SearchOutcome:
        photo = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR) if data else None
        if photo is None:
            raise PhotoError("не удалось прочитать изображение")
        return self.search_photo(photo, top_n)
```

(старые тела `_use`, `set_library`, `build_index`, `search_photo` удаляются; `search_file`, `status`, `load`, `_result`, `_full_path`, `_thumbnail` остаются как есть.)

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest tests/desktop tests/server/test_access.py -q`
Expected: PASS (включая прежние тесты сервиса и настроек).

- [ ] **Step 5: Lint and commit**

```bash
.venv/Scripts/python.exe -m ruff check --fix . && .venv/Scripts/python.exe -m pytest -q
git add apps/desktop/src/gmagc_desktop/service tests/desktop tests/server
git commit -m "feat: server settings, access code and a thread-safe search service" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---
### Task 3: Адреса ПК и QR

**Files:**
- Create: `apps/desktop/src/gmagc_desktop/server/__init__.py`, `apps/desktop/src/gmagc_desktop/server/network.py`, `apps/desktop/src/gmagc_desktop/server/qr.py`
- Modify: `apps/desktop/pyproject.toml` (зависимость `segno`), `requirements-dev.txt`
- Test: `tests/server/test_network.py`, `tests/server/test_qr.py`

**Interfaces:**
- Produces: `server.network.lan_addresses() -> list[str]` (основной адрес маршрута первым, без loopback и link-local; без интернета); `server.qr.qr_png(text, scale=5) -> bytes` (PNG).

- [ ] **Step 1: Write the failing tests**

```python
# path: tests/server/test_network.py
from gmagc_desktop.server import network


def test_primary_address_goes_first_and_duplicates_and_unusable_ones_are_dropped(monkeypatch):
    monkeypatch.setattr(network, "_primary_address", lambda: "192.168.1.5")
    monkeypatch.setattr(
        network, "_all_addresses", lambda: ["127.0.0.1", "169.254.10.3", "10.0.0.7", "192.168.1.5", "0.0.0.0"]
    )

    assert network.lan_addresses() == ["192.168.1.5", "10.0.0.7"]


def test_without_a_route_the_hostname_addresses_are_used(monkeypatch):
    monkeypatch.setattr(network, "_primary_address", lambda: None)
    monkeypatch.setattr(network, "_all_addresses", lambda: ["10.0.0.7"])

    assert network.lan_addresses() == ["10.0.0.7"]


def test_no_network_gives_an_empty_list(monkeypatch):
    monkeypatch.setattr(network, "_primary_address", lambda: None)
    monkeypatch.setattr(network, "_all_addresses", lambda: [])

    assert network.lan_addresses() == []


def test_real_lookup_returns_only_ipv4_strings():
    for address in network.lan_addresses():
        parts = address.split(".")
        assert len(parts) == 4 and all(part.isdigit() and 0 <= int(part) <= 255 for part in parts)
        assert not address.startswith(("127.", "169.254."))
```

```python
# path: tests/server/test_qr.py
from gmagc_common.protocol import build_link
from gmagc_desktop.server.qr import qr_png


def test_qr_is_a_png_and_grows_with_the_scale():
    link = build_link("192.168.1.5", 8765, "ABCD2345")

    small, large = qr_png(link, scale=3), qr_png(link, scale=8)

    assert small.startswith(b"\x89PNG\r\n\x1a\n") and large.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(large) > len(small)


def test_different_links_give_different_images():
    assert qr_png(build_link("192.168.1.5", 8765, "ABCD2345")) != qr_png(build_link("192.168.1.5", 8765, "ABCD2346"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/server/test_network.py tests/server/test_qr.py -q`
Expected: FAIL (нет модулей `gmagc_desktop.server`).

- [ ] **Step 3: Write the implementation**

```python
# path: apps/desktop/src/gmagc_desktop/server/__init__.py
"""HTTP-сервер для телефона (без Flet)."""
```

```python
# path: apps/desktop/src/gmagc_desktop/server/network.py
"""Адреса ПК в локальной сети (работает без интернета)."""

from __future__ import annotations

import socket


def _usable(address: str) -> bool:
    return not address.startswith(("127.", "169.254.", "0."))


def _primary_address() -> str | None:
    """Адрес интерфейса, через который ушёл бы трафик в сеть. Пакеты не отправляются: UDP connect лишь выбирает маршрут."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))  # 192.0.2.0/24 зарезервирован для документации
            return probe.getsockname()[0]
    except OSError:
        return None


def _all_addresses() -> list[str]:
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return []
    return [str(info[4][0]) for info in infos]


def lan_addresses() -> list[str]:
    """IPv4 ПК: основной адрес маршрута первым, затем остальные (без loopback и link-local)."""
    found: list[str] = []
    primary = _primary_address()
    for address in ([primary] if primary else []) + _all_addresses():
        if address and _usable(address) and address not in found:
            found.append(address)
    return found
```

```python
# path: apps/desktop/src/gmagc_desktop/server/qr.py
"""QR-код подключения (segno: чистый Python, PNG без Pillow)."""

from __future__ import annotations

import io

import segno


def qr_png(text: str, scale: int = 5) -> bytes:
    buffer = io.BytesIO()
    segno.make(text, error="m").save(buffer, kind="png", scale=scale, border=2)
    return buffer.getvalue()
```

В `apps/desktop/pyproject.toml` в `dependencies` добавить строку `"segno",` после `"Pillow",`; в `requirements-dev.txt` добавить строку `segno` после `Pillow`.

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest tests/server/test_network.py tests/server/test_qr.py -q`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
.venv/Scripts/python.exe -m ruff check --fix . && .venv/Scripts/python.exe -m pytest -q
git add apps/desktop tests/server requirements-dev.txt
git commit -m "feat: LAN address lookup and QR image for phone pairing" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: HTTP-API и `PhoneServer`

**Files:**
- Create: `apps/desktop/src/gmagc_desktop/server/api.py`, `apps/desktop/src/gmagc_desktop/server/runner.py`
- Test: `tests/server/conftest.py`, `tests/server/test_api.py`, `tests/server/test_runner.py`

**Interfaces:**
- Consumes: `SearchService` (`search_image_bytes(data, top_n)`, `status()`, `indexing_state()`, `settings.access_code`, `settings.top_n`), `service.access` (`RateLimiter`, `codes_equal`), `gmagc_common.protocol`.
- Produces: `server.api.RequestRecord(request_id, time, client, photo, outcome)`, `server.api.ApiContext(service, limiter, on_request)`, `server.api.ApiHandler`, `server.api.match_response(request_id, outcome) -> MatchResponse`; `server.runner.PhoneServer(service, on_request=None, host="0.0.0.0", limiter=None)` со свойством `on_request` (читается и присваивается), `start(port=8765) -> int` (фактический порт; `ServerStartError`), `stop()`, `running`, `port`; `server.runner.ServerStartError(RuntimeError)`, `PORT_TRIES = 10`.

- [ ] **Step 1: Write the failing tests**

```python
# path: tests/server/conftest.py
import http.client
import json
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from gmagc_desktop.matcher.synthetic import simulate_photo
from gmagc_desktop.server.runner import PhoneServer
from gmagc_desktop.service.search_service import SearchService
from tests.fixtures import shape_images, write_library


@pytest.fixture()
def service(tmp_path):
    library = tmp_path / "lib"
    library.mkdir()
    write_library(library)
    instance = SearchService(tmp_path / "data")
    instance.load()
    instance.set_library(library)
    instance.build_index()
    instance.ensure_access_code()
    return instance


@pytest.fixture()
def photo_jpeg():
    photo = simulate_photo(shape_images()["ell"], np.random.default_rng(5))
    ok, buffer = cv2.imencode(".jpg", photo)
    assert ok
    return buffer.tobytes()


@pytest.fixture()
def running(service):
    """Сервер на 127.0.0.1 со свободным портом; records собирает вызовы on_request."""
    records = []
    server = PhoneServer(service, on_request=records.append, host="127.0.0.1")
    port = server.start(0)
    yield SimpleNamespace(server=server, port=port, code=service.settings.access_code, records=records)
    server.stop()


@pytest.fixture()
def call(running):
    """call(метод, путь, body=None, code=<верный>) -> (статус, ответ http.client, JSON или None)."""

    def _call(method, path, body=None, code="valid", headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", running.port, timeout=20)
        head = dict(headers or {})
        token = running.code if code == "valid" else code
        if token is not None:
            head["Authorization"] = f"Bearer {token}"
        try:
            connection.request(method, path, body=body, headers=head)
            response = connection.getresponse()
            raw = response.read()
            return response.status, response, (json.loads(raw) if raw else None)
        finally:
            connection.close()

    return _call
```

```python
# path: tests/server/test_api.py
import http.client
import json
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np

from gmagc_common.protocol import MAX_IMAGE_BYTES, ApiError, Health, MatchResponse, Status
from gmagc_desktop.server.api import RequestRecord
from gmagc_desktop.server.runner import PhoneServer
from gmagc_desktop.service.results import Outcome
from gmagc_desktop.service.search_service import SearchService


def test_health_needs_no_code_and_reports_the_index(call):
    status, _, body = call("GET", "/api/health", code=None)

    health = Health.from_dict(body)
    assert status == 200 and health.app == "GMAGC" and health.api == 1
    assert health.indexed is True and health.files == 6


def test_status_requires_the_code_and_reports_progress_fields(call):
    status, _, body = call("GET", "/api/status", code=None)
    assert status == 401 and ApiError.from_dict(body).code == "unauthorized"

    status, _, body = call("GET", "/api/status")
    result = Status.from_dict(body)
    assert status == 200 and result.indexed and result.files == 6 and result.families == 5
    assert result.indexing is False


def test_match_returns_results_with_thumbnails_and_the_projection(call, photo_jpeg, service):
    status, _, body = call("POST", "/api/match", photo_jpeg, headers={"Content-Type": "image/jpeg"})

    response = MatchResponse.from_dict(body)
    assert status == 200 and response.outcome in {"found", "low_confidence"}
    assert len(response.results) == 5 and [item.rank for item in response.results] == [1, 2, 3, 4, 5]
    top = response.results[0]
    assert top.name in {"ell.png", "ell_small.png"} and top.path.startswith(service.settings.library_dir)
    assert top.thumbnail_png.startswith(b"\x89PNG") and response.projection_png.startswith(b"\x89PNG")
    assert 0 < top.score <= 1 and len(response.request_id) == 8


def test_match_honors_the_top_parameter_and_clamps_it(call, photo_jpeg):
    _, _, body = call("POST", "/api/match?top=2", photo_jpeg)
    assert len(MatchResponse.from_dict(body).results) == 2
    _, _, body = call("POST", "/api/match?top=999", photo_jpeg)
    assert len(MatchResponse.from_dict(body).results) == 5  # в библиотеке всего 5 семейств
    _, _, body = call("POST", "/api/match?top=abc", photo_jpeg)
    assert len(MatchResponse.from_dict(body).results) == 5


def test_a_flat_photo_reports_no_projection(call):
    ok, buffer = cv2.imencode(".png", np.full((480, 640, 3), 90, np.uint8))
    status, _, body = call("POST", "/api/match", buffer.tobytes())

    response = MatchResponse.from_dict(body)
    assert status == 200 and response.outcome == "no_projection" and response.results == ()
    assert response.projection_png is None


def test_wrong_or_missing_code_is_401_even_with_a_big_body(call, photo_jpeg):
    for code in ("ABCD2346", "", None):
        status, _, body = call("POST", "/api/match", photo_jpeg * 5, code=code)
        assert status == 401 and ApiError.from_dict(body).code == "unauthorized"


def test_five_wrong_codes_block_the_client_for_a_while(call):
    for _ in range(5):
        assert call("GET", "/api/status", code="ABCD2346")[0] == 401

    status, response, body = call("GET", "/api/status", code="ABCD2346")
    assert status == 429 and ApiError.from_dict(body).code == "rate_limited"
    assert 1 <= int(response.getheader("Retry-After")) <= 30
    assert call("GET", "/api/status")[0] == 429  # верный код тоже ждёт конца блокировки


def test_bad_bodies_are_reported_with_json_errors(call, running):
    status, _, body = call("POST", "/api/match", b"not an image")
    assert status == 400 and ApiError.from_dict(body).code == "bad_image"

    status, _, body = call("POST", "/api/match", b"")
    assert status == 400 and ApiError.from_dict(body).code == "bad_image"

    connection = http.client.HTTPConnection("127.0.0.1", running.port, timeout=20)
    connection.putrequest("POST", "/api/match")
    connection.putheader("Authorization", f"Bearer {running.code}")
    connection.endheaders()  # без Content-Length
    response = connection.getresponse()
    assert response.status == 400 and ApiError.from_dict(json.loads(response.read())).code == "bad_request"
    connection.close()


def test_a_body_over_the_limit_is_413(call):
    status, _, body = call("POST", "/api/match", b"\0" * (MAX_IMAGE_BYTES + 1))

    assert status == 413 and ApiError.from_dict(body).code == "too_large"


def test_unknown_paths_and_methods_answer_json(call):
    status, _, body = call("GET", "/nope")
    assert status == 404 and ApiError.from_dict(body).code == "not_found"

    status, _, body = call("POST", "/api/health", b"x")
    assert status == 404 and body["error"] == "not_found"

    status, response, body = call("PUT", "/api/match", b"x")
    assert status == 501 and body["error"] == "bad_request"
    assert response.getheader("Content-Type").startswith("application/json")


def test_no_index_is_409(tmp_path, photo_jpeg):
    empty = SearchService(tmp_path / "empty")
    empty.load()
    code = empty.ensure_access_code()
    server = PhoneServer(empty, host="127.0.0.1")
    port = server.start(0)
    try:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
        connection.request("POST", "/api/match", body=photo_jpeg, headers={"Authorization": f"Bearer {code}"})
        response = connection.getresponse()
        assert response.status == 409 and ApiError.from_dict(json.loads(response.read())).code == "no_index"
        connection.close()
    finally:
        server.stop()


def test_the_request_callback_gets_the_photo_client_and_outcome(call, running, photo_jpeg):
    status, _, body = call("POST", "/api/match", photo_jpeg)

    assert status == 200 and len(running.records) == 1
    record = running.records[0]
    assert isinstance(record, RequestRecord) and record.request_id == body["request_id"]
    assert record.client == "127.0.0.1" and record.photo == photo_jpeg
    assert record.outcome.kind in {Outcome.FOUND, Outcome.LOW_CONFIDENCE} and record.time > 0


def test_a_failing_callback_does_not_break_the_response(service, photo_jpeg):
    def boom(_record):
        raise RuntimeError("UI упал")

    server = PhoneServer(service, on_request=boom, host="127.0.0.1")
    port = server.start(0)
    try:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
        connection.request(
            "POST", "/api/match", body=photo_jpeg, headers={"Authorization": f"Bearer {service.settings.access_code}"}
        )
        assert connection.getresponse().status == 200
        connection.close()
    finally:
        server.stop()


def test_parallel_requests_all_succeed(call, photo_jpeg):
    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses = list(pool.map(lambda _: call("POST", "/api/match", photo_jpeg)[0], range(6)))

    assert statuses == [200] * 6


def test_the_code_is_read_live_so_a_new_code_takes_effect_at_once(call, service):
    assert call("GET", "/api/status")[0] == 200
    new_code = service.reset_access_code()

    assert call("GET", "/api/status", code=new_code)[0] == 200
    assert call("GET", "/api/status", code="ABCD2346")[0] == 401
```

```python
# path: tests/server/test_runner.py
import socket

import pytest

from gmagc_desktop.server import runner
from gmagc_desktop.server.runner import PORT_TRIES, PhoneServer, ServerStartError


def test_start_serves_and_stop_frees_the_port(service):
    server = PhoneServer(service, host="127.0.0.1")
    assert not server.running and server.port == 0

    port = server.start(0)

    assert server.running and server.port == port > 0
    assert server.start(0) == port  # повторный запуск ничего не меняет
    with socket.create_connection(("127.0.0.1", port), timeout=5):
        pass
    server.stop()
    assert not server.running and server.port == 0
    with pytest.raises(OSError), socket.create_connection(("127.0.0.1", port), timeout=2):
        pass
    server.stop()  # повторная остановка безопасна


def test_a_busy_port_moves_to_the_next_one(service):
    first = PhoneServer(service, host="127.0.0.1")
    second = PhoneServer(service, host="127.0.0.1")
    port = first.start(0)
    try:
        actual = second.start(port)

        assert port < actual < port + PORT_TRIES and second.running
    finally:
        second.stop()
        first.stop()


def test_no_free_port_raises_a_clear_error(service, monkeypatch):
    monkeypatch.setattr(runner, "PORT_TRIES", 1)
    first = PhoneServer(service, host="127.0.0.1")
    second = PhoneServer(service, host="127.0.0.1")
    port = first.start(0)
    try:
        with pytest.raises(ServerStartError) as error:
            second.start(port)

        assert str(port) in str(error.value) and not second.running
    finally:
        first.stop()


def test_on_request_can_be_replaced_after_creation(service):
    server = PhoneServer(service, host="127.0.0.1")
    assert server.on_request is None
    marker = lambda _record: None  # noqa: E731
    server.on_request = marker
    assert server.on_request is marker
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/server/test_api.py tests/server/test_runner.py -q`
Expected: FAIL (нет `server.api`, `server.runner`).

- [ ] **Step 3: Write the implementation**

```python
# path: apps/desktop/src/gmagc_desktop/server/api.py
"""HTTP-API для телефона: /api/health, /api/status, /api/match."""

from __future__ import annotations

import json
import logging
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlsplit

from gmagc_common.protocol import (
    API_VERSION,
    APP_NAME,
    ERROR_STATUS,
    MAX_IMAGE_BYTES,
    ApiError,
    Health,
    MatchResponse,
    ResultItem,
    Status,
)
from gmagc_desktop.about import VERSION
from gmagc_desktop.service.access import RateLimiter, codes_equal
from gmagc_desktop.service.results import SearchOutcome
from gmagc_desktop.service.search_service import NoIndexError, PhotoError, SearchService
from gmagc_desktop.service.settings import MAX_TOP_N

log = logging.getLogger("gmagc.server")
DRAIN_LIMIT = 2 * MAX_IMAGE_BYTES  # столько лишнего тела дочитываем, чтобы клиент увидел ответ, а не обрыв соединения


@dataclass(frozen=True)
class RequestRecord:
    """Один запрос телефона: для истории и показа в окне ПК."""

    request_id: str
    time: float
    client: str
    photo: bytes
    outcome: SearchOutcome


@dataclass
class ApiContext:
    service: SearchService
    limiter: RateLimiter
    on_request: Callable[[RequestRecord], None] | None = None


def match_response(request_id: str, outcome: SearchOutcome) -> MatchResponse:
    items = tuple(
        ResultItem(r.rank, r.name, r.full_path, r.score, r.copies, r.thumbnail_png) for r in outcome.results
    )
    return MatchResponse(request_id, outcome.kind.value, outcome.took_ms, items, outcome.projection_png)


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "GMAGC"
    timeout = 15  # секунд на чтение из сокета: зависший клиент не держит поток
    _unread = 0

    @property
    def context(self) -> ApiContext:
        return self.server.context  # type: ignore[attr-defined]

    # ---- ответы ------------------------------------------------------------
    def log_message(self, format, *args):  # noqa: A002 - сигнатура базового класса
        log.debug("%s %s", self.client_address[0], format % args)

    def send_error(self, code, message=None, explain=None):
        """Ошибки разбора запроса (400, 501...) базовый класс отдаёт HTML; у нас всегда JSON."""
        self._error("bad_request", message or "некорректный запрос", status=int(code))

    def _send_json(self, status: int, payload: dict, headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _error(self, code: str, message: str, *, status: int | None = None, headers: dict[str, str] | None = None):
        self._send_json(status or ERROR_STATUS[code], ApiError(code, message).to_dict(), headers)

    # ---- маршруты ----------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 - имя задаёт BaseHTTPRequestHandler
        path = urlsplit(self.path).path
        if path == "/api/health":
            self._health()
        elif path == "/api/status":
            self._authorized(self._status)
        else:
            self._error("not_found", "нет такого метода")

    def do_POST(self) -> None:  # noqa: N802
        self._unread = self._content_length() or 0
        try:
            if urlsplit(self.path).path == "/api/match":
                self._authorized(self._match)
            else:
                self._error("not_found", "нет такого метода")
        finally:
            self._drain()

    def _content_length(self) -> int | None:
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return None
        return length if length >= 0 else None

    def _drain(self) -> None:
        """Дочитывает непрочитанное тело запроса (в пределах лимита): закрытие сокета с непрочитанными данными рвёт ответ."""
        remaining = min(self._unread, DRAIN_LIMIT)
        self._unread = 0
        try:
            while remaining > 0:
                chunk = self.rfile.read(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
        except OSError:
            pass

    def _authorized(self, handler: Callable[[], None]) -> None:
        client = self.client_address[0]
        limiter = self.context.limiter
        wait = limiter.retry_after(client)
        if wait:
            self._error(
                "rate_limited", f"слишком много неверных кодов, повторите через {wait} с", headers={"Retry-After": str(wait)}
            )
            return
        scheme, _, given = self.headers.get("Authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not codes_equal(self.context.service.settings.access_code, given.strip()):
            limiter.failure(client)
            self._error("unauthorized", "неверный код доступа")
            return
        limiter.success(client)
        handler()

    def _health(self) -> None:
        status = self.context.service.status()
        health = Health(APP_NAME, API_VERSION, VERSION, status is not None, status.files if status else 0)
        self._send_json(200, health.to_dict())

    def _status(self) -> None:
        service = self.context.service
        status = service.status()
        indexing, done, total = service.indexing_state()
        result = Status(
            status is not None,
            status.files if status else 0,
            status.families if status else 0,
            indexing,
            done,
            total,
        )
        self._send_json(200, result.to_dict())

    def _top(self) -> int | None:
        try:
            top = int(parse_qs(urlsplit(self.path).query)["top"][0])
        except (KeyError, IndexError, ValueError):
            return None
        return min(max(top, 1), MAX_TOP_N)

    def _match(self) -> None:
        length = self._content_length()
        if length is None:
            self._error("bad_request", "нужен заголовок Content-Length")
            return
        if length == 0:
            self._error("bad_image", "пустое изображение")
            return
        if length > MAX_IMAGE_BYTES:
            self._error("too_large", f"изображение больше {MAX_IMAGE_BYTES // (1024 * 1024)} МБ")
            return
        self._unread = 0
        try:
            data = self.rfile.read(length)
        except OSError:
            self._error("bad_request", "не удалось получить изображение")
            return
        if len(data) != length:
            self._error("bad_request", "тело запроса получено не полностью")
            return
        try:
            outcome = self.context.service.search_image_bytes(data, top_n=self._top())
        except PhotoError:
            self._error("bad_image", "не удалось прочитать изображение")
            return
        except NoIndexError:
            self._error("no_index", "на ПК не выбрана библиотека или индекс ещё не построен")
            return
        except Exception:  # noqa: BLE001 - сервер обязан ответить, а не оборвать соединение
            log.exception("ошибка поиска")
            self._error("server_error", "ошибка поиска на ПК")
            return
        request_id = secrets.token_hex(4)
        self._send_json(200, match_response(request_id, outcome).to_dict())
        self._notify(RequestRecord(request_id, time.time(), self.client_address[0], data, outcome))

    def _notify(self, record: RequestRecord) -> None:
        callback = self.context.on_request
        if callback is None:
            return
        try:
            callback(record)
        except Exception:  # noqa: BLE001 - сбой экрана не должен ломать сервер
            log.exception("обработчик запроса завершился ошибкой")
```

```python
# path: apps/desktop/src/gmagc_desktop/server/runner.py
"""Запуск и остановка HTTP-сервера в фоновом потоке."""

from __future__ import annotations

import logging
import socketserver
import sys
import threading
from collections.abc import Callable
from http.server import ThreadingHTTPServer

from gmagc_common.protocol import DEFAULT_PORT
from gmagc_desktop.server.api import ApiContext, ApiHandler, RequestRecord
from gmagc_desktop.service.access import RateLimiter
from gmagc_desktop.service.search_service import SearchService

log = logging.getLogger("gmagc.server")
PORT_TRIES = 10  # сколько портов подряд пробовать, если основной занят


class ServerStartError(RuntimeError):
    """Не нашлось свободного порта для сервера."""


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    # На Windows SO_REUSEADDR позволяет двум серверам сесть на один порт; там он не нужен.
    allow_reuse_address = sys.platform != "win32"

    def __init__(self, address: tuple[str, int], context: ApiContext):
        super().__init__(address, ApiHandler)
        self.context = context

    def server_bind(self) -> None:
        # HTTPServer.server_bind вызывает getfqdn(): на ПК без DNS это секунды. Имя сервера нам не нужно.
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name, self.server_port = str(host), port

    def handle_error(self, request, client_address) -> None:
        error = sys.exc_info()[1]
        if isinstance(error, (ConnectionError, TimeoutError)):
            log.debug("клиент %s оборвал соединение: %r", client_address[0], error)
        else:
            log.exception("необработанная ошибка запроса от %s", client_address[0])


class PhoneServer:
    def __init__(
        self,
        service: SearchService,
        on_request: Callable[[RequestRecord], None] | None = None,
        host: str = "0.0.0.0",
        limiter: RateLimiter | None = None,
    ):
        self._context = ApiContext(service, limiter or RateLimiter(), on_request)
        self._host = host
        self._httpd: _Server | None = None
        self._thread: threading.Thread | None = None

    @property
    def on_request(self) -> Callable[[RequestRecord], None] | None:
        return self._context.on_request

    @on_request.setter
    def on_request(self, callback: Callable[[RequestRecord], None] | None) -> None:
        self._context.on_request = callback

    @property
    def running(self) -> bool:
        return self._httpd is not None

    @property
    def port(self) -> int:
        return self._httpd.server_address[1] if self._httpd else 0

    def start(self, port: int = DEFAULT_PORT) -> int:
        """Запускает сервер на первом свободном порту из PORT_TRIES подряд; возвращает фактический порт."""
        if self._httpd is not None:
            return self.port
        candidates = [0] if port == 0 else list(range(port, min(port + PORT_TRIES, 65536)))
        last_error: OSError | None = None
        httpd: _Server | None = None
        for candidate in candidates:
            try:
                httpd = _Server((self._host, candidate), self._context)
                break
            except OSError as error:
                last_error = error
        if httpd is None:
            raise ServerStartError(f"порт {port} занят (проверено портов: {len(candidates)}): {last_error}")
        self._httpd = httpd
        self._thread = threading.Thread(
            target=httpd.serve_forever, kwargs={"poll_interval": 0.2}, name="gmagc-phone-server", daemon=True
        )
        self._thread.start()
        return self.port

    def stop(self) -> None:
        httpd, thread = self._httpd, self._thread
        if httpd is None:
            return
        self._httpd = self._thread = None
        httpd.shutdown()
        httpd.server_close()
        if thread is not None:
            thread.join(timeout=5)
```

Замечание: `PORT_TRIES` читается в `start()` как глобал модуля, поэтому `monkeypatch.setattr(runner, "PORT_TRIES", 1)` в тесте действует.

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest tests/server -q`
Expected: PASS. Если `test_a_body_over_the_limit_is_413` падает обрывом соединения, проверить `_drain` и `DRAIN_LIMIT`.

- [ ] **Step 5: Lint and commit**

```bash
.venv/Scripts/python.exe -m ruff check --fix . && .venv/Scripts/python.exe -m pytest -q
git add apps/desktop/src/gmagc_desktop/server tests/server
git commit -m "feat: HTTP API and background server for the phone" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---
### Task 5: Скрипт `phone_sim.py` (имитация телефона)

**Files:**
- Create: `scripts/phone_sim.py`
- Test: `tests/server/test_phone_sim.py`

**Interfaces:**
- Consumes: `gmagc_common.protocol` (`parse_link`, `parse_address`, `is_valid_code`, `normalize_code`, `Connection`, `MatchResponse`, `ProtocolError`, `DEFAULT_PORT`); сервер из Task 4 (фикстуры `running`, `photo_jpeg`).
- Produces: `phone_sim.prepare_jpeg(path, max_side=1280, quality=85) -> bytes`, `phone_sim.send_match(connection, jpeg, top=None, timeout=30.0) -> (status, dict)`, `phone_sim.main(argv=None) -> int` (0 успех, 1 ответ сервера с ошибкой, 2 нет соединения, 3 неверные аргументы или нечитаемое фото).

- [ ] **Step 1: Write the failing tests**

```python
# path: tests/server/test_phone_sim.py
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import phone_sim  # noqa: E402

from gmagc_common.protocol import build_link  # noqa: E402


def save_bytes(tmp_path, data, name="photo.jpg"):
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_prepare_jpeg_shrinks_big_photos_and_keeps_small_ones(tmp_path):
    big = tmp_path / "big.png"
    cv2.imwrite(str(big), np.full((2000, 3000, 3), 120, np.uint8))
    small = tmp_path / "small.png"
    cv2.imwrite(str(small), np.full((300, 400, 3), 120, np.uint8))

    big_jpeg = cv2.imdecode(np.frombuffer(phone_sim.prepare_jpeg(big), np.uint8), cv2.IMREAD_COLOR)
    small_jpeg = cv2.imdecode(np.frombuffer(phone_sim.prepare_jpeg(small), np.uint8), cv2.IMREAD_COLOR)

    assert max(big_jpeg.shape[:2]) == 1280 and big_jpeg.shape[:2] == (853, 1280)
    assert small_jpeg.shape[:2] == (300, 400)


def test_prepare_jpeg_reads_paths_with_non_ascii_names(tmp_path):
    path = tmp_path / "фото проекции.png"
    ok, buffer = cv2.imencode(".png", np.full((100, 100, 3), 50, np.uint8))
    path.write_bytes(buffer.tobytes())

    assert phone_sim.prepare_jpeg(path).startswith(b"\xff\xd8")


def test_prepare_jpeg_rejects_a_non_image(tmp_path):
    with pytest.raises(ValueError):
        phone_sim.prepare_jpeg(save_bytes(tmp_path, b"not an image", "x.jpg"))


def test_main_with_a_link_prints_the_outcome_and_the_results(tmp_path, running, photo_jpeg, capsys):
    photo = save_bytes(tmp_path, photo_jpeg)
    link = build_link("127.0.0.1", running.port, running.code)

    code = phone_sim.main(["--link", link, str(photo)])

    out = capsys.readouterr().out
    assert code == 0 and "исход:" in out and " 1. " in out and ".png" in out
    assert len(running.records) == 1


def test_main_with_host_port_code_and_top(tmp_path, running, photo_jpeg, capsys):
    photo = save_bytes(tmp_path, photo_jpeg)

    code = phone_sim.main(
        ["--host", "127.0.0.1", "--port", str(running.port), "--code", running.code.lower(), "--top", "2", str(photo)]
    )

    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()[:2] in {"1.", "2.", "3."}]
    assert code == 0 and len(lines) == 2


def test_wrong_code_exits_with_1_and_names_the_error(tmp_path, running, photo_jpeg, capsys):
    photo = save_bytes(tmp_path, photo_jpeg)

    code = phone_sim.main(["--host", "127.0.0.1", "--port", str(running.port), "--code", "ABCD2346", str(photo)])

    assert code == 1 and "unauthorized" in capsys.readouterr().err


def test_a_closed_port_exits_with_2(tmp_path, running, photo_jpeg, capsys):
    photo = save_bytes(tmp_path, photo_jpeg)
    running.server.stop()

    code = phone_sim.main(["--host", "127.0.0.1", "--port", str(running.port), "--code", running.code, str(photo)])

    assert code == 2 and "нет соединения" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        ["photo.jpg"],
        ["--host", "127.0.0.1", "photo.jpg"],
        ["--link", "мусор", "photo.jpg"],
        ["--host", "bad host", "--code", "ABCD2345", "photo.jpg"],
        ["--host", "127.0.0.1", "--code", "BAD", "photo.jpg"],
    ],
)
def test_bad_arguments_exit_with_3(argv, capsys):
    assert phone_sim.main(argv) == 3
    assert capsys.readouterr().err


def test_a_missing_photo_exits_with_3(tmp_path, running, capsys):
    link = build_link("127.0.0.1", running.port, running.code)

    assert phone_sim.main(["--link", link, str(tmp_path / "нет.jpg")]) == 3
    assert "не удалось прочитать фото" in capsys.readouterr().err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/server/test_phone_sim.py -q`
Expected: FAIL (`ModuleNotFoundError: phone_sim`).

- [ ] **Step 3: Write the implementation**

```python
# path: scripts/phone_sim.py
"""Имитация телефона: отправляет фото на сервер GMAGC и печатает результаты.

  phone_sim.py --link "gmagc://connect?host=192.168.1.5&port=8765&code=ABCD2345" photo.jpg
  phone_sim.py --host 192.168.1.5 --port 8765 --code ABCD-2345 photo.jpg --top 5

Как телефон, уменьшает фото до 1280 px по длинной стороне и отправляет JPEG.
Коды выхода: 0 успех, 1 сервер ответил ошибкой, 2 нет соединения, 3 неверные аргументы или нечитаемое фото.
"""

from __future__ import annotations

import argparse
import http.client
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "desktop" / "src"))

from gmagc_common.protocol import (  # noqa: E402
    DEFAULT_PORT,
    Connection,
    MatchResponse,
    ProtocolError,
    is_valid_code,
    normalize_code,
    parse_address,
    parse_link,
)

MAX_SIDE = 1280
JPEG_QUALITY = 85


def prepare_jpeg(path: str | Path, max_side: int = MAX_SIDE, quality: int = JPEG_QUALITY) -> bytes:
    """Читает фото (в том числе с не-ASCII именем), уменьшает до max_side по длинной стороне, кодирует в JPEG."""
    image = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"не изображение: {path}")
    height, width = image.shape[:2]
    scale = max_side / max(height, width)
    if scale < 1:
        image = cv2.resize(image, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
    ok, buffer = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError("не удалось закодировать JPEG")
    return buffer.tobytes()


def send_match(connection: Connection, jpeg: bytes, top: int | None = None, timeout: float = 30.0) -> tuple[int, dict]:
    path = "/api/match" + (f"?top={top}" if top else "")
    client = http.client.HTTPConnection(connection.host, connection.port, timeout=timeout)
    try:
        client.request(
            "POST", path, body=jpeg, headers={"Authorization": f"Bearer {connection.code}", "Content-Type": "image/jpeg"}
        )
        response = client.getresponse()
        return response.status, json.loads(response.read() or b"{}")
    finally:
        client.close()


def resolve_connection(args: argparse.Namespace) -> Connection | None:
    if args.link:
        return parse_link(args.link)
    if not args.host or not args.code or not is_valid_code(args.code):
        return None
    address = parse_address(f"{args.host}:{args.port}")
    return Connection(address[0], address[1], normalize_code(args.code)) if address else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Отправляет фото на сервер GMAGC как телефон.")
    parser.add_argument("photo", help="файл с фото проекции")
    parser.add_argument("--link", help="ссылка из QR: gmagc://connect?host=…&port=…&code=…")
    parser.add_argument("--host", help="адрес ПК (вместо --link)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--code", help="код доступа (вместе с --host)")
    parser.add_argument("--top", type=int, help="сколько результатов вернуть")
    parser.add_argument("--max-side", type=int, default=MAX_SIDE, help="длинная сторона фото, px")
    args = parser.parse_args(argv)

    connection = resolve_connection(args)
    if connection is None:
        print("нужны верная --link или --host с --code (8 символов)", file=sys.stderr)
        return 3
    try:
        jpeg = prepare_jpeg(args.photo, args.max_side)
    except (OSError, ValueError) as error:
        print(f"не удалось прочитать фото: {error}", file=sys.stderr)
        return 3

    started = time.perf_counter()
    try:
        status, body = send_match(connection, jpeg, args.top)
    except (OSError, http.client.HTTPException) as error:
        print(f"нет соединения с {connection.host}:{connection.port}: {error}", file=sys.stderr)
        return 2
    except ValueError as error:  # ответ не JSON: это не сервер GMAGC
        print(f"сервер ответил не по протоколу: {error}", file=sys.stderr)
        return 1
    elapsed_ms = (time.perf_counter() - started) * 1000

    if status != 200:
        print(f"ошибка {status}: {body.get('error')}: {body.get('message')}", file=sys.stderr)
        return 1
    try:
        response = MatchResponse.from_dict(body)
    except ProtocolError as error:
        print(f"сервер ответил не по протоколу: {error}", file=sys.stderr)
        return 1
    print(
        f"исход: {response.outcome}, на ПК {response.took_ms:.0f} мс, всего {elapsed_ms:.0f} мс, "
        f"запрос {response.request_id}, отправлено {len(jpeg) // 1024} КБ"
    )
    for item in response.results:
        copies = f"  (+{len(item.copies)} копий)" if item.copies else ""
        print(f"{item.rank:>2}. {item.score * 100:5.1f}%  {item.path}{copies}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest tests/server -q`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
.venv/Scripts/python.exe -m ruff check --fix . && .venv/Scripts/python.exe -m pytest -q
git add scripts/phone_sim.py tests/server/test_phone_sim.py
git commit -m "feat: phone simulator script for testing the server without a phone" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6: Экран: блок «Телефон», история запросов, копирование пути по клику

**Files:**
- Modify: `apps/desktop/src/gmagc_desktop/ui/app.py`, `apps/desktop/src/gmagc_desktop/ui/texts.py`, `tests/desktop/test_desktop_ui.py`
- Create: `tests/fakes.py`
- Test: `tests/desktop/test_phone_ui.py`, `tests/desktop/test_history_texts.py`

**Interfaces:**
- Consumes: `PhoneServer` (`start(port) -> int`, `stop()`, `running`, `port`, `on_request`), `ServerStartError`, `RequestRecord`, `lan_addresses`, `qr_png`, `SearchService` (`ensure_access_code`, `reset_access_code`, `set_server_enabled`, `settings`), `gmagc_common.protocol` (`build_link`, `format_code`).
- Produces: `DesktopApp(page, service, picker=None, clipboard=None, reveal=..., check=..., server=None, addresses=lan_addresses, qr=qr_png)`; публичные для тестов: `server_switch`, `server_status`, `qr_holder`, `code_text`, `code_row`, `addresses_text`, `phone_note`, `history_column`, `history_title`, `source_label`, `copy_label`, методы `on_toggle_server`, `on_copy_code` (async), `on_new_code`, `on_phone_request`, `on_history_click`, `on_card_click` (async), `copy_path(path)` (async); `HISTORY_LIMIT = 10`; `texts.history_text(when, client, outcome)`, `texts.source_text(when, client)`.

- [ ] **Step 1: Move the shared test doubles and write the failing tests**

```python
# path: tests/fakes.py
"""Заглушки для тестов экрана: страница, диалог выбора файла, буфер обмена, сервер телефона."""

from types import SimpleNamespace

import flet as ft

from gmagc_desktop.server.runner import ServerStartError


class StubPage:
    """Минимальная замена ft.Page: запоминает добавленное, поток выполняет сразу."""

    def __init__(self):
        self.title = ""
        self.added = []
        self.services = []
        self.updates = 0

    def add(self, *controls):
        self.added.extend(controls)

    def update(self):
        self.updates += 1

    def run_thread(self, handler, *args, **kwargs):
        handler(*args, **kwargs)


class FakePicker:
    def __init__(self, folder=None, files=()):
        self.folder = folder
        self.files = list(files)

    async def get_directory_path(self, dialog_title=None, initial_directory=None):
        return self.folder

    async def pick_files(self, **kwargs):
        return [SimpleNamespace(path=path) for path in self.files]


class FakeClipboard:
    def __init__(self, image=None, files=()):
        self.image = image
        self.files = list(files)
        self.copied = []

    async def get_image(self):
        return self.image

    async def get_files(self):
        return list(self.files)

    async def set(self, value):
        self.copied.append(value)


class FakeServer:
    """Замена PhoneServer: запоминает вызовы, порт не занимает."""

    def __init__(self, port=8765, error=None):
        self.port_result = port
        self.error = error
        self.starts = []
        self.stops = 0
        self.running = False
        self.port = 0
        self.on_request = None

    def start(self, port):
        self.starts.append(port)
        if self.error:
            raise ServerStartError(self.error)
        self.running = True
        self.port = self.port_result
        return self.port

    def stop(self):
        self.stops += 1
        self.running = False
        self.port = 0


def walk(control):
    yield control
    for attribute in ("content", "controls"):
        value = getattr(control, attribute, None)
        for child in value if isinstance(value, list) else [value] if value is not None else []:
            if isinstance(child, ft.Control):
                yield from walk(child)


def texts(control):
    return [c.value for c in walk(control) if isinstance(c, ft.Text)]
```

В `tests/desktop/test_desktop_ui.py`: удалить локальные определения `StubPage`, `FakePicker`, `FakeClipboard`, `walk`, `texts` и импорт `SimpleNamespace`, добавить `from tests.fakes import FakeClipboard, FakePicker, FakeServer, StubPage, texts, walk`; `make_app` заменить на

```python
def make_app(tmp_path, **services):
    services.setdefault("server", FakeServer())  # настоящий сервер в тестах экрана не запускаем
    page = StubPage()
    app = build_page(page, service=SearchService(tmp_path / "data"), **services)
    return app, page
```

и тест `test_clicking_a_result_path_reveals_the_file` заменить на:

```python
def test_the_folder_button_of_a_result_reveals_the_file(tmp_path, library):
    revealed = []
    photo = save_photo(tmp_path / "p.png", ell_photo())
    app, _ = indexed_app(tmp_path, library, reveal=revealed.append)
    app.picker.files = [str(photo)]
    asyncio.run(app.on_pick_photo(None))

    button = next(c for c in walk(app.results_column.controls[0]) if isinstance(c, ft.IconButton))
    button.on_click(None)

    assert len(revealed) == 1 and revealed[0].startswith(str(library)) and revealed[0].endswith(".png")
```

```python
# path: tests/desktop/test_history_texts.py
import time

from gmagc_desktop.service.results import Outcome, Result, SearchOutcome
from gmagc_desktop.ui.texts import history_text, source_text


def outcome(kind=Outcome.FOUND, results=True):
    items = (Result(1, "a.png", "v/a.png", "/lib/v/a.png", 0.812, (), b"x"),) if results else ()
    return SearchOutcome(kind, items, b"p", 3.0)


def stamp(when):
    return time.strftime("%H:%M:%S", time.localtime(when))


def test_source_text_names_the_client_and_the_time():
    assert source_text(1_700_000_000.0, "192.168.1.23") == f"Запрос с телефона 192.168.1.23, {stamp(1_700_000_000.0)}"


def test_history_text_shows_the_best_match_or_the_missing_projection():
    when = 1_700_000_000.0
    assert history_text(when, "192.168.1.23", outcome()) == f"{stamp(when)} · 192.168.1.23 · a.png 81.2%"
    assert history_text(when, "10.0.0.7", outcome(Outcome.NO_PROJECTION, results=False)).endswith("проекция не найдена")
    assert history_text(when, "10.0.0.7", outcome(Outcome.LOW_CONFIDENCE, results=False)).endswith("проекция не найдена")
```

```python
# path: tests/desktop/test_phone_ui.py
import asyncio
import os
from types import SimpleNamespace

import cv2
import flet as ft
import numpy as np
import pytest

from gmagc_common.protocol import Connection, format_code, parse_link
from gmagc_desktop.matcher.synthetic import simulate_photo
from gmagc_desktop.server.api import RequestRecord
from gmagc_desktop.service.results import Outcome, Result, SearchOutcome
from gmagc_desktop.service.search_service import SearchService
from gmagc_desktop.service.settings import Settings, load_settings, save_settings
from gmagc_desktop.ui.app import HISTORY_LIMIT, build_page
from tests.fakes import FakeClipboard, FakePicker, FakeServer, StubPage, texts, walk
from tests.fixtures import shape_images, write_library


def make_app(tmp_path, *, enabled=True, addresses=("192.168.1.5",), server=None, **services):
    data = tmp_path / "data"
    if not enabled:
        save_settings(Settings(server_enabled=False), data / "settings.json")
    links = []
    services.setdefault("qr", lambda link: links.append(link) or b"PNG:" + link.encode())
    services.setdefault("clipboard", FakeClipboard())
    page = StubPage()
    app = build_page(
        page, service=SearchService(data), server=server or FakeServer(), addresses=lambda: list(addresses), **services
    )
    return app, page, links


def record(number=1, client="192.168.1.23", outcome=None):
    full_path = os.path.join(os.sep, "lib", "v", f"g{number}.png")
    result = Result(1, f"g{number}.png", f"v/g{number}.png", full_path, 0.9, (), b"PNG")
    default = SearchOutcome(Outcome.FOUND, (result,), b"\x89PNG", 5.0)
    return RequestRecord(f"r{number}", 1_700_000_000.0 + number, client, b"\x89PNG-photo", outcome or default)


def test_the_server_starts_automatically_and_shows_the_address_code_and_qr(tmp_path):
    server = FakeServer(port=8765)

    app, _, links = make_app(tmp_path, server=server)

    code = app.service.settings.access_code
    assert server.starts == [8765] and app.server_switch.value is True
    assert app.server_status.value == "Работает: 192.168.1.5:8765"
    assert app.code_text.value == f"Код: {format_code(code)}" and app.code_text.visible and app.code_row.visible
    assert parse_link(links[-1]) == Connection("192.168.1.5", 8765, code)
    assert app.qr_holder.visible and app.qr_holder.controls[0].src.startswith(b"PNG:")
    assert server.on_request == app.on_phone_request


def test_the_code_survives_a_restart(tmp_path):
    first, _, _ = make_app(tmp_path)
    second, _, _ = make_app(tmp_path)

    assert second.service.settings.access_code == first.service.settings.access_code != ""


def test_a_disabled_server_is_not_started(tmp_path):
    server = FakeServer()

    app, _, _ = make_app(tmp_path, enabled=False, server=server)

    assert server.starts == [] and app.server_switch.value is False
    assert app.server_status.value == "Выключен" and not app.qr_holder.visible and not app.code_text.visible


def test_the_switch_stops_and_restarts_the_server_and_remembers_the_choice(tmp_path):
    server = FakeServer()
    app, _, _ = make_app(tmp_path, server=server)

    app.server_switch.value = False
    app.on_toggle_server(None)

    assert server.stops == 1 and app.server_status.value == "Выключен" and not app.qr_holder.visible
    assert load_settings(tmp_path / "data" / "settings.json").server_enabled is False

    app.server_switch.value = True
    app.on_toggle_server(None)

    assert server.starts == [8765, 8765] and app.server_status.value == "Работает: 192.168.1.5:8765"
    assert load_settings(tmp_path / "data" / "settings.json").server_enabled is True


def test_a_start_failure_is_shown_instead_of_the_qr(tmp_path):
    app, _, _ = make_app(tmp_path, server=FakeServer(error="порт 8765 занят"))

    assert app.server_status.value == "Не удалось запустить: порт 8765 занят"
    assert not app.qr_holder.visible and not app.code_text.visible


def test_without_a_network_address_the_qr_is_hidden_with_a_hint(tmp_path):
    app, _, _ = make_app(tmp_path, addresses=())

    assert "адрес ПК в сети не найден" in app.server_status.value and not app.qr_holder.visible


def test_other_addresses_are_listed_and_the_first_one_goes_into_the_qr(tmp_path):
    app, _, links = make_app(tmp_path, addresses=("192.168.1.5", "10.0.0.7", "172.16.0.2"))

    assert app.addresses_text.visible and "10.0.0.7, 172.16.0.2" in app.addresses_text.value
    assert parse_link(links[-1]).host == "192.168.1.5"


def test_a_new_code_replaces_the_code_everywhere(tmp_path):
    app, _, links = make_app(tmp_path)
    old = app.service.settings.access_code

    app.on_new_code(None)

    new = app.service.settings.access_code
    assert new != old and app.code_text.value == f"Код: {format_code(new)}"
    assert parse_link(links[-1]).code == new
    assert load_settings(tmp_path / "data" / "settings.json").access_code == new


def test_copy_code_puts_the_formatted_code_on_the_clipboard(tmp_path):
    app, _, _ = make_app(tmp_path)

    asyncio.run(app.on_copy_code(None))

    assert app.clipboard.copied == [format_code(app.service.settings.access_code)]
    assert app.phone_note.visible and "скопирован" in app.phone_note.value


def test_a_phone_request_is_shown_in_the_main_window_and_the_history(tmp_path):
    app, _, _ = make_app(tmp_path)

    app.on_phone_request(record(1))

    assert app.source_label.visible and "192.168.1.23" in app.source_label.value
    assert app.photo_holder.visible and app.projection_holder.visible and len(app.results_column.controls) == 1
    assert app.history_title.visible and len(app.history_column.controls) == 1
    row = texts(app.history_column.controls[0])[0]
    assert "192.168.1.23" in row and "g1.png" in row and "90.0%" in row


def test_the_history_keeps_the_latest_requests_newest_first(tmp_path):
    app, _, _ = make_app(tmp_path)

    for number in range(1, HISTORY_LIMIT + 3):
        app.on_phone_request(record(number))

    assert len(app.history_column.controls) == HISTORY_LIMIT
    assert f"g{HISTORY_LIMIT + 2}.png" in texts(app.history_column.controls[0])[0]
    assert "g3.png" in texts(app.history_column.controls[-1])[0]


def test_clicking_a_history_row_shows_that_request_again(tmp_path):
    app, _, _ = make_app(tmp_path)
    app.on_phone_request(record(1))
    app.on_phone_request(record(2))
    assert "g2.png" in " ".join(texts(app.results_column.controls[0]))

    older = app.history_column.controls[1]
    older.on_click(SimpleNamespace(control=older))

    assert "g1.png" in " ".join(texts(app.results_column.controls[0]))


def test_a_phone_request_without_a_projection_shows_the_message(tmp_path):
    app, _, _ = make_app(tmp_path)

    app.on_phone_request(record(1, outcome=SearchOutcome(Outcome.NO_PROJECTION, (), None, 2.0)))

    assert "Проекция на фото не найдена" in app.banner_text.value and app.results_column.controls == []
    assert "проекция не найдена" in texts(app.history_column.controls[0])[0]


def result_container(app):
    return next(c for c in walk(app.results_column.controls[0]) if isinstance(c, ft.Container) and c.data)


def test_clicking_a_result_copies_its_absolute_path_with_the_file_name(tmp_path):
    app, _, _ = make_app(tmp_path)
    rec = record(1)
    app.on_phone_request(rec)
    container = result_container(app)

    asyncio.run(container.on_click(SimpleNamespace(control=container)))

    expected = os.path.abspath(rec.outcome.results[0].full_path)
    assert app.clipboard.copied == [expected] and expected.endswith("g1.png")
    assert app.copy_label.visible and expected in app.copy_label.value


def test_a_relative_path_is_copied_as_an_absolute_one(tmp_path):
    app, _, _ = make_app(tmp_path)

    asyncio.run(app.copy_path(os.path.join("rel", "x.png")))

    assert app.clipboard.copied == [os.path.abspath(os.path.join("rel", "x.png"))]


def test_the_folder_button_reveals_the_file_and_does_not_copy(tmp_path):
    revealed = []
    app, _, _ = make_app(tmp_path, reveal=revealed.append)
    rec = record(1)
    app.on_phone_request(rec)

    button = next(c for c in walk(app.results_column.controls[0]) if isinstance(c, ft.IconButton))
    button.on_click(None)

    assert revealed == [rec.outcome.results[0].full_path] and app.clipboard.copied == []


def test_a_file_search_hides_the_phone_caption_and_the_copy_notice(tmp_path):
    library = tmp_path / "lib"
    library.mkdir()
    write_library(library)
    ok, buffer = cv2.imencode(".png", simulate_photo(shape_images()["ell"], np.random.default_rng(5)))
    photo = tmp_path / "p.png"
    photo.write_bytes(buffer.tobytes())
    app, _, _ = make_app(tmp_path, picker=FakePicker(files=[str(photo)]))
    app.service.set_library(library)
    app.service.build_index()
    app.on_phone_request(record(1))
    asyncio.run(app.copy_path("x.png"))
    assert app.source_label.visible and app.copy_label.visible

    asyncio.run(app.on_pick_photo(None))

    assert not app.source_label.visible and not app.copy_label.visible
    assert len(app.results_column.controls) == 5


@pytest.mark.parametrize("name", ["server_switch", "server_status", "qr_holder", "history_column"])
def test_the_phone_block_is_part_of_the_screen(tmp_path, name):
    app, page, _ = make_app(tmp_path)

    assert getattr(app, name) in list(walk(page.added[0]))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/desktop -q`
Expected: FAIL (в `DesktopApp` нет параметров `server`, `addresses`, `qr`, нет блока «Телефон»).

- [ ] **Step 3: Write the implementation**

Добавить в `apps/desktop/src/gmagc_desktop/ui/texts.py` (импорт `import time` после `from __future__ import annotations`, а `from gmagc_desktop.service.results import LOW_CONFIDENCE_SCORE, IndexStatus, Outcome` дополнить `SearchOutcome`):

```python
def _stamp(when: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(when))


def source_text(when: float, client: str) -> str:
    return f"Запрос с телефона {client}, {_stamp(when)}"


def history_text(when: float, client: str, outcome: SearchOutcome) -> str:
    if outcome.kind is Outcome.NO_PROJECTION or not outcome.results:
        return f"{_stamp(when)} · {client} · проекция не найдена"
    top = outcome.results[0]
    return f"{_stamp(when)} · {client} · {top.name} {score_text(top.score)}"
```

```python
# path: apps/desktop/src/gmagc_desktop/ui/app.py
"""Экран ПК-приложения: библиотека, индекс, поиск по фото, сервер для телефона."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import flet as ft

from gmagc_common.protocol import build_link, format_code
from gmagc_desktop.about import AUTHOR, NAME, VERSION
from gmagc_desktop.library.index import IndexCancelled, LibraryNotFound, LibraryScanError
from gmagc_desktop.selfcheck import run_core_check
from gmagc_desktop.server.api import RequestRecord
from gmagc_desktop.server.network import lan_addresses
from gmagc_desktop.server.qr import qr_png
from gmagc_desktop.server.runner import PhoneServer, ServerStartError
from gmagc_desktop.service.results import Outcome, Result, SearchOutcome
from gmagc_desktop.service.reveal import reveal_in_file_manager
from gmagc_desktop.service.search_service import NoIndexError, PhotoError, SearchService
from gmagc_desktop.service.settings import data_dir
from gmagc_desktop.ui.texts import history_text, outcome_message, score_text, source_text, status_text

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
NO_LIBRARY_HINT = "Сначала выберите папку библиотеки и постройте индекс"
PHONE_HINT = "Телефон и ПК должны быть в одной сети Wi-Fi. При первом запуске разрешите доступ в брандмауэре Windows."
HISTORY_LIMIT = 10


class DesktopApp:
    def __init__(
        self,
        page: ft.Page,
        service: SearchService,
        picker=None,
        clipboard=None,
        reveal: Callable[[str], bool] = reveal_in_file_manager,
        check: Callable[[], dict] = run_core_check,
        server=None,
        addresses: Callable[[], list[str]] = lan_addresses,
        qr: Callable[[str], bytes] = qr_png,
    ):
        self.page = page
        self.service = service
        self.picker = picker or ft.FilePicker()
        self.clipboard = clipboard or ft.Clipboard()
        self.reveal = reveal
        self.check = check
        self.server = server or PhoneServer(service)
        self.server.on_request = self.on_phone_request
        self.addresses = addresses
        self.qr = qr
        self.history: list[RequestRecord] = []
        self._busy = False
        self._cancel = False

        self.library_text = ft.Text("не выбрана", selectable=True)
        self.status_label = ft.Text("Индекс не построен")
        self.progress = ft.ProgressBar(value=0, visible=False)
        self.progress_label = ft.Text(visible=False)
        self.choose_folder_button = ft.Button("Выбрать папку…", on_click=self.on_choose_folder)
        self.rebuild_button = ft.Button("Обновить индекс", on_click=self.on_rebuild)
        self.cancel_button = ft.Button("Отмена", on_click=self.on_cancel, visible=False)
        self.pick_photo_button = ft.Button("Выбрать фото…", on_click=self.on_pick_photo)
        self.paste_button = ft.Button("Вставить из буфера", on_click=self.on_paste)
        self.banner_text = ft.Text(color=ft.Colors.BLACK)
        self.banner = ft.Container(self.banner_text, padding=10, border_radius=6, visible=False)
        self.source_label = ft.Text("", visible=False)
        self.photo_holder = ft.Column(visible=False, spacing=4)
        self.projection_holder = ft.Column(visible=False, spacing=4)
        self.results_column = ft.Column(spacing=8)
        self.copy_label = ft.Text("", size=12, visible=False, selectable=True)
        self.check_label = ft.Text("")

        self.server_switch = ft.Switch(label="Сервер для телефона", value=False, on_change=self.on_toggle_server)
        self.server_status = ft.Text("Выключен")
        self.qr_holder = ft.Column(visible=False)
        self.code_text = ft.Text("", size=16, weight=ft.FontWeight.BOLD, selectable=True, visible=False)
        self.code_row = ft.Row(
            [
                ft.TextButton(content=ft.Text("Копировать код"), on_click=self.on_copy_code),
                ft.TextButton(content=ft.Text("Новый код"), on_click=self.on_new_code),
            ],
            spacing=4,
            visible=False,
        )
        self.phone_note = ft.Text("", size=12, visible=False)
        self.addresses_text = ft.Text("", size=12, visible=False, selectable=True)
        self.history_title = ft.Text("Запросы с телефона", size=14, weight=ft.FontWeight.BOLD, visible=False)
        self.history_column = ft.Column(spacing=0)

    # ---- построение экрана -------------------------------------------------
    def build(self) -> None:
        status = self.service.load()
        self.library_text.value = self.service.settings.library_dir or "не выбрана"
        self.status_label.value = status_text(status)
        self.page.services.extend([self.picker, self.clipboard])
        if self.service.settings.server_enabled:
            self.server_switch.value = True
            self._start_server()

        left = ft.Column(
            [
                ft.Text("Библиотека", size=18, weight=ft.FontWeight.BOLD),
                self.library_text,
                self.choose_folder_button,
                self.rebuild_button,
                self.status_label,
                self.progress,
                self.progress_label,
                self.cancel_button,
                ft.Divider(),
                ft.Text("Телефон", size=18, weight=ft.FontWeight.BOLD),
                self.server_switch,
                self.server_status,
                self.qr_holder,
                self.code_text,
                self.code_row,
                self.phone_note,
                self.addresses_text,
                ft.Text(PHONE_HINT, size=12),
                self.history_title,
                self.history_column,
            ],
            spacing=8,
            width=320,
            scroll=ft.ScrollMode.AUTO,
        )
        right = ft.Column(
            [
                ft.Row([self.pick_photo_button, self.paste_button], spacing=8),
                self.source_label,
                self.banner,
                ft.Row(
                    [self.photo_holder, self.projection_holder],
                    spacing=16,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                ft.Text("Результаты", size=18, weight=ft.FontWeight.BOLD),
                self.copy_label,
                self.results_column,
            ],
            spacing=10,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        )
        footer = ft.Row(
            [
                ft.Text(f"{NAME} {VERSION} · Автор: {AUTHOR}", size=12),
                ft.TextButton(content=ft.Text("Проверить ядро", size=12), on_click=self.on_check),
                self.check_label,
            ],
            spacing=12,
        )
        self.page.add(
            ft.SafeArea(
                ft.Column(
                    [
                        ft.Row(
                            [left, ft.VerticalDivider(), right],
                            expand=True,
                            vertical_alignment=ft.CrossAxisAlignment.START,
                        ),
                        footer,
                    ],
                    expand=True,
                ),
                expand=True,
            )
        )
        demo_photo = os.environ.get("GMAGC_DEMO_PHOTO")
        if demo_photo:
            self.page.run_thread(lambda: self._run_demo(os.environ.get("GMAGC_DEMO_LIBRARY", ""), demo_photo))

    # ---- состояние ---------------------------------------------------------
    def _set_busy(self, busy: bool, *, indexing: bool = False) -> None:
        self._busy = busy
        for button in (self.choose_folder_button, self.rebuild_button, self.pick_photo_button, self.paste_button):
            button.disabled = busy
        self.progress.visible = busy and indexing
        self.progress_label.visible = busy and indexing
        self.cancel_button.visible = busy and indexing
        if not busy or not indexing:
            self.progress.value = 0
        self.page.update()

    def _show_banner(self, text: str, *, error: bool) -> None:
        self.banner_text.value = text
        self.banner.bgcolor = ft.Colors.RED_100 if error else ft.Colors.AMBER_100
        self.banner.visible = True
        self.page.update()

    def _hide_banner(self) -> None:
        self.banner.visible = False

    # ---- сервер для телефона -----------------------------------------------
    def _start_server(self) -> None:
        try:
            self.server.start(self.service.settings.port)
        except ServerStartError as error:
            self._show_server(error=str(error))
        else:
            self._show_server()

    def _show_server(self, error: str | None = None) -> None:
        """Отражает состояние сервера в блоке «Телефон» (экран обновляет вызывающий)."""
        running = self.server.running and error is None
        addresses = self.addresses() if running else []
        for control in (self.qr_holder, self.code_text, self.code_row, self.addresses_text, self.phone_note):
            control.visible = False
        if error:
            self.server_status.value = f"Не удалось запустить: {error}"
        elif not running:
            self.server_status.value = "Выключен"
        elif not addresses:
            self.server_status.value = (
                f"Работает на порту {self.server.port}, но адрес ПК в сети не найден: подключите ПК к Wi-Fi"
            )
        else:
            host, port = addresses[0], self.server.port
            code = self.service.ensure_access_code()
            self.server_status.value = f"Работает: {host}:{port}"
            self.qr_holder.controls = [
                ft.Image(src=self.qr(build_link(host, port, code)), width=180, height=180, fit=ft.BoxFit.CONTAIN)
            ]
            self.code_text.value = f"Код: {format_code(code)}"
            self.addresses_text.value = "Другие адреса ПК: " + ", ".join(addresses[1:])
            self.qr_holder.visible = self.code_text.visible = self.code_row.visible = True
            self.addresses_text.visible = len(addresses) > 1

    def on_toggle_server(self, _event) -> None:
        enabled = bool(self.server_switch.value)
        self.service.set_server_enabled(enabled)
        if enabled:
            self._start_server()
        else:
            self.server.stop()
            self._show_server()
        self.page.update()

    async def on_copy_code(self, _event) -> None:
        await self.clipboard.set(format_code(self.service.ensure_access_code()))
        self.phone_note.value = "Код скопирован"
        self.phone_note.visible = True
        self.page.update()

    def on_new_code(self, _event) -> None:
        self.service.reset_access_code()
        self._show_server()
        self.page.update()

    def on_phone_request(self, record: RequestRecord) -> None:
        """Вызывается из потока сервера: запись в историю и показ результата в основном окне."""
        self.history.insert(0, record)
        del self.history[HISTORY_LIMIT:]
        self.history_column.controls = [self._history_row(item) for item in self.history]
        self.history_title.visible = True
        self._show_record(record)

    def _history_row(self, record: RequestRecord) -> ft.TextButton:
        return ft.TextButton(
            content=ft.Text(history_text(record.time, record.client, record.outcome), size=12),
            data=record,
            on_click=self.on_history_click,
        )

    def on_history_click(self, event) -> None:
        self._show_record(event.control.data)

    def _show_record(self, record: RequestRecord) -> None:
        self._hide_banner()
        self.source_label.value = source_text(record.time, record.client)
        self.source_label.visible = True
        self._show_photo(record.photo)
        self._show_outcome(record.outcome)

    # ---- индексация --------------------------------------------------------
    async def on_choose_folder(self, _event) -> None:
        folder = await self.picker.get_directory_path(dialog_title="Папка библиотеки гобо")
        if not folder:
            return
        self.service.set_library(folder)
        self.library_text.value = folder
        self.status_label.value = status_text(self.service.status())
        self._start_index()

    async def on_rebuild(self, _event) -> None:
        self._start_index()

    def on_cancel(self, _event) -> None:
        self._cancel = True

    def _start_index(self) -> None:
        if self._busy:
            return
        if not self.service.settings.library_dir:
            self._show_banner(NO_LIBRARY_HINT, error=True)
            return
        self._cancel = False
        self._hide_banner()
        self._set_busy(True, indexing=True)
        self.page.run_thread(self._index_worker)

    def _index_worker(self) -> None:
        try:
            self.service.build_index(progress=self._on_progress, cancel=lambda: self._cancel)
        except IndexCancelled:
            self._show_banner("Индексация отменена", error=False)
        except (LibraryNotFound, LibraryScanError) as error:
            self._show_banner(str(error), error=True)
        except Exception as error:  # noqa: BLE001 - рабочий поток обязан показать причину, а не пропасть
            self._show_banner(f"Ошибка индексации: {error}", error=True)
        finally:
            self.status_label.value = status_text(self.service.status())
            self._set_busy(False)

    def _on_progress(self, done: int, total: int) -> None:
        self.progress.value = done / total if total else 0
        self.progress_label.value = f"Индексация: {done} из {total}"
        self.page.update()

    # ---- поиск -------------------------------------------------------------
    async def on_pick_photo(self, _event) -> None:
        files = await self.picker.pick_files(dialog_title="Фото проекции", file_type=ft.FilePickerFileType.IMAGE)
        if files and files[0].path:
            self._search_bytes_from(Path(files[0].path))

    async def on_paste(self, _event) -> None:
        data = await self.clipboard.get_image()
        if data:
            self._start_search(data)
            return
        for name in await self.clipboard.get_files():
            if Path(name).suffix.lower() in IMAGE_SUFFIXES:
                self._search_bytes_from(Path(name))
                return
        self._show_banner("В буфере обмена нет картинки или файла-изображения", error=True)

    def _search_bytes_from(self, path: Path) -> None:
        try:
            data = path.read_bytes()
        except OSError as error:
            self._show_banner(f"Не удалось прочитать файл: {error}", error=True)
            return
        self._start_search(data)

    def _start_search(self, data: bytes) -> None:
        if self._busy:
            return
        if self.service.status() is None:
            self._show_banner(NO_LIBRARY_HINT, error=True)
            return
        self._hide_banner()
        self.source_label.visible = False
        self._show_photo(data)
        self._set_busy(True)
        self.page.run_thread(lambda: self._search_worker(data))

    def _search_worker(self, data: bytes) -> None:
        try:
            outcome = self.service.search_image_bytes(data)
        except NoIndexError:
            self._show_banner(NO_LIBRARY_HINT, error=True)
        except PhotoError as error:
            self._show_banner(f"Не удалось прочитать фото: {error}", error=True)
        except Exception as error:  # noqa: BLE001 - рабочий поток обязан показать причину, а не пропасть
            self._show_banner(f"Ошибка поиска: {error}", error=True)
        else:
            self._show_outcome(outcome)
        finally:
            self._set_busy(False)

    def _show_photo(self, data: bytes) -> None:
        self.photo_holder.controls = [
            ft.Text("Фото"),
            ft.Image(src=data, width=260, height=200, fit=ft.BoxFit.CONTAIN),
        ]
        self.photo_holder.visible = True
        self.projection_holder.visible = False
        self.results_column.controls = []
        self.copy_label.visible = False
        self.page.update()

    def _show_outcome(self, outcome: SearchOutcome) -> None:
        message = outcome_message(outcome.kind)
        if message:
            self._show_banner(message, error=outcome.kind is Outcome.NO_PROJECTION)
        if outcome.projection_png:
            self.projection_holder.controls = [
                ft.Text("Найденная проекция"),
                ft.Image(src=outcome.projection_png, width=160, height=160, fit=ft.BoxFit.CONTAIN),
            ]
        self.projection_holder.visible = bool(outcome.projection_png)
        self.results_column.controls = [self._result_card(result) for result in outcome.results]
        self.page.update()

    def _result_card(self, result: Result) -> ft.Card:
        details: list[ft.Control] = [
            ft.Text(result.name, weight=ft.FontWeight.BOLD),
            ft.Text(result.full_path, size=12),
            ft.Text(score_text(result.score)),
        ]
        if result.copies:
            details.append(ft.Text(f"ещё {len(result.copies)} файлов", tooltip="\n".join(result.copies)))
        return ft.Card(
            ft.Container(
                ft.Row(
                    [
                        ft.Image(src=result.thumbnail_png, width=96, height=96, fit=ft.BoxFit.CONTAIN),
                        ft.Column(details, spacing=2, expand=True),
                        ft.IconButton(
                            icon=ft.Icons.FOLDER_OPEN,
                            tooltip="Показать в папке",
                            on_click=lambda _event, path=result.full_path: self.reveal(path),
                        ),
                    ],
                    spacing=12,
                ),
                padding=10,
                ink=True,
                data=result.full_path,
                tooltip="Нажмите, чтобы скопировать путь к файлу",
                on_click=self.on_card_click,
            )
        )

    async def on_card_click(self, event) -> None:
        await self.copy_path(event.control.data)

    async def copy_path(self, path: str) -> None:
        """Копирует абсолютный путь файла (вместе с именем) в буфер обмена."""
        absolute = os.path.abspath(path)
        await self.clipboard.set(absolute)
        self.copy_label.value = f"Путь скопирован: {absolute}"
        self.copy_label.visible = True
        self.page.update()

    # ---- прочее ------------------------------------------------------------
    def on_check(self, _event) -> None:
        info = self.check()
        head = "ОК: ядро работает" if info["ok"] else "ОШИБКА: ядро не сработало"
        self.check_label.value = head + ", " + ", ".join(f"{name}: {value}" for name, value in info["versions"].items())
        self.page.update()

    def _run_demo(self, library: str, photo: str) -> None:
        """Отладка: GMAGC_DEMO_LIBRARY / GMAGC_DEMO_PHOTO запускают индексацию и поиск при старте."""
        self._set_busy(True, indexing=True)
        if library:
            self.service.set_library(library)
            self.library_text.value = library
        self._index_worker()
        self._set_busy(True)
        data = Path(photo).read_bytes()
        self._show_photo(data)
        self._search_worker(data)


def build_page(page: ft.Page, service: SearchService | None = None, **services) -> DesktopApp:
    page.title = f"{NAME} {VERSION}"
    window = getattr(page, "window", None)
    if window is not None:
        window.width, window.height = 1100, 760
    app = DesktopApp(page, service or SearchService(data_dir()), **services)
    app.build()
    return app
```

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest tests/desktop -q`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
.venv/Scripts/python.exe -m ruff check --fix . && .venv/Scripts/python.exe -m pytest -q
git add apps/desktop/src/gmagc_desktop/ui tests/fakes.py tests/desktop
git commit -m "feat: phone block, request history and copy-path-on-click in the desktop screen" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 7: Сборка, живая проверка, README, версия 0.4.0, PR и релиз

**Files:**
- Modify: `apps/desktop/src/gmagc_desktop/about.py`, `apps/mobile/src/gmagc_mobile/about.py` (VERSION `0.4.0`), `apps/desktop/pyproject.toml`, `apps/mobile/pyproject.toml` (version `0.4.0`), `README.md`, `docs/superpowers/specs/2026-09-21-gmagc-phone-server-design.md` (коды выхода `phone_sim`)

- [ ] **Step 1: Bump the version**

Во всех четырёх местах `0.3.0` -> `0.4.0` (`VERSION` в двух `about.py`, `version` в двух `pyproject.toml`). В спецификации (раздел 7) коды выхода скрипта: `0 успех, 1 ответ сервера с ошибкой, 2 нет соединения, 3 неверные аргументы или нечитаемое фото`.

Run: `.venv\Scripts\python.exe -m pytest -q` и `.venv\Scripts\python.exe -m ruff check .`
Expected: все тесты проходят, линтер чист.

- [ ] **Step 2: Local Windows build with the smoke launch**

Run: `.\scripts\build_windows.ps1` (нужна ветка со всеми коммитами). Ожидается «Готово: приложение запущено, ошибок Python нет».

- [ ] **Step 3: Live check on real data**

1. Запустить `apps/desktop/build/windows/gmagc-desktop.exe` с `GMAGC_DATA_DIR=$env:TEMP\gmagc_live`, `GMAGC_DEMO_LIBRARY=C:\Users\ANDYBUM\GMAGC\gobos`, `GMAGC_DEMO_PHOTO=<photo_13>`. Дождаться индекса (файл `index.npz` в каталоге данных).
2. Прочитать `access_code` из `$env:TEMP\gmagc_live\settings.json`, адрес ПК (`python -c "from gmagc_desktop.server.network import lan_addresses; print(lan_addresses())"`).
3. По LAN-адресу: `.venv\Scripts\python.exe scripts\phone_sim.py --host <адрес> --port 8765 --code <код> photo\photo_13_*.jpg` (ожидается код выхода 0, верное гобо в первых результатах), затем с неверным кодом (код выхода 1).
4. Снимок окна `scripts\capture_window.ps1`: виден блок «Телефон» (переключатель, «Работает: адрес:порт», QR, код), запрос в истории, результат в основном окне с подписью «Запрос с телефона …».
5. Клик по карточке результата (скриптом через `user32`: `SetCursorPos` и `mouse_event`) и проверка `Get-Clipboard`: в буфере абсолютный путь файла с именем.
6. Закрыть приложение, завершить процесс `gmagc-desktop`.

Если что-то не так, исправить в `ui/app.py` или сервере, добавить тест, повторить шаги 2–5.

- [ ] **Step 4: README**

Обновить README: статус (v0.4.0, сервер для телефона), раздел «Сервер для телефона» (автозапуск, QR/код, брандмауэр, API кратко, `phone_sim.py`), клик по карточке копирует путь (кнопка значка папки открывает папку), число тестов, структура (`packages/common`, `server/`, `scripts/phone_sim.py`, `sync_common.py`), правило «менять протокол в `packages/common`, затем `scripts/sync_common.py`».

- [ ] **Step 5: Commit, push, PR, CI, merge, tag, release**

```bash
git add -A
git commit -m "docs: README and version 0.4.0 for the phone server" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
git push -u origin feat/phone-server
gh pr create --title "Сервер для телефона (этап 4)" --body-file <файл описания> --base main
```

Дождаться зелёных проверок (тесты на трёх ОС, сборки Windows/macOS/Android), `gh pr merge --squash --delete-branch`, `git checkout main && git pull`, тег `git tag -a v0.4.0 -m "GMAGC 0.4.0: сервер для телефона" && git push origin v0.4.0`, дождаться релизных сборок, проверить контрольную сумму и запуск Windows-архива, заменить заметки релиза (`gh release edit v0.4.0 --title … --notes-file …`), обновить память проекта.
