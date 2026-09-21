# GMAGC: Android-клиент (этап 5). План реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Android-приложение подключается к ПК (QR или адрес и код), снимает проекцию камерой с приближением и фокусом либо берёт фото из галереи, показывает результаты и копирует абсолютный путь найденного файла.

**Architecture:** Клиент на `http.client` поверх общего протокола `gmagc_common`; отдельные небольшие модули (`client`, `store`, `qr`, `imaging`, `camera`, `texts`) без Flet там, где это возможно, и один экран `MobileApp` (подключение, камера, результаты), тестируемый на заглушках. Сборка Android получает разрешение камеры и HTTP без шифрования через `pyproject.toml`.

**Tech Stack:** Python 3.12, Flet 1.0.0, flet-camera, flet-permission-handler, `pyzbar` и `Pillow` (колёса для Android есть на pypi.flet.dev), pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-09-21-gmagc-android-client-design.md`

## Global Constraints

- Flet закреплён на 1.0.0 (в `apps/mobile/pyproject.toml`, `requirements-dev.txt`, `FLET_VERSION` трёх workflow); `requires-python = ">=3.12,<3.13"`. Новые зависимости мобильного приложения только `pyzbar` и `Pillow`; сетевой клиент на стандартной библиотеке.
- Мобильное приложение не импортирует `gmagc_desktop`; общее только `gmagc_common` (копия `apps/mobile/src/gmagc_common`, оригинал `packages/common/gmagc_common`, синхронизация `python scripts/sync_common.py`).
- Камера: задняя, `ResolutionPreset.HIGH`; приближение (ползунок, «+»/«−», щипок), фокус (касание по кадру, блокировка); нет фото в галерее без `FilePicker`.
- Клик по карточке результата и кнопка «Копировать путь» кладут в буфер `path` из ответа сервера как есть (абсолютный путь на ПК вместе с именем файла).
- Импорты `pyzbar` и `PIL` выполняются внутри функций и не ломают приложение, если их нет.
- Тесты используют только синтетические данные; `gobos/`, `photo/`, `models/` не читаются. Комментарии и строки интерфейса на русском; автор `@ANDY_BUM` виден на экране.
- Коммиты: `git commit -m "<тип>: <описание>" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"`. Работа на ветке `feat/android-client`, в `main` только через Pull Request с зелёными проверками.
- Запуск тестов: `.venv\Scripts\python.exe -m pytest -q`, линтер: `.venv\Scripts\python.exe -m ruff check .`.

---

### Task 1: Общие константы исходов, копия протокола в мобильном приложении, общие фикстуры

**Files:**
- Modify: `packages/common/gmagc_common/protocol.py`, `scripts/sync_common.py`, `tests/common/test_common_sync.py`, `tests/server/conftest.py`
- Create: `tests/conftest.py`, `tests/common/test_outcomes.py`, `apps/mobile/src/gmagc_common/` (копия скриптом)

**Interfaces:**
- Produces: `gmagc_common.protocol.OUTCOME_FOUND = "found"`, `OUTCOME_LOW_CONFIDENCE = "low_confidence"`, `OUTCOME_NO_PROJECTION = "no_projection"`; `apps/mobile/src/gmagc_common` рядом с копией в десктопе; фикстуры `service`, `photo_jpeg`, `running` доступны всем тестам (`tests/conftest.py`), фикстура `call` остаётся в `tests/server/conftest.py`.

- [ ] **Step 1: Write the failing tests**

```python
# path: tests/common/test_outcomes.py
from gmagc_common import protocol
from gmagc_desktop.service.results import Outcome


def test_outcome_constants_match_the_server_enum():
    assert {outcome.value for outcome in Outcome} == {
        protocol.OUTCOME_FOUND,
        protocol.OUTCOME_LOW_CONFIDENCE,
        protocol.OUTCOME_NO_PROJECTION,
    }
```

В `tests/common/test_common_sync.py` список `TARGETS` заменить на:

```python
TARGETS = [
    ROOT / "apps" / "desktop" / "src" / "gmagc_common",
    ROOT / "apps" / "mobile" / "src" / "gmagc_common",
]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/common -q`
Expected: FAIL (нет констант `OUTCOME_*`, нет копии в `apps/mobile/src`).

- [ ] **Step 3: Write the implementation**

В `packages/common/gmagc_common/protocol.py` после строки `LINK_SCHEME = "gmagc"` добавить:

```python
OUTCOME_FOUND = "found"
OUTCOME_LOW_CONFIDENCE = "low_confidence"
OUTCOME_NO_PROJECTION = "no_projection"
```

В `scripts/sync_common.py` список целей заменить на:

```python
TARGETS = [ROOT / "apps" / "desktop" / "src" / "gmagc_common", ROOT / "apps" / "mobile" / "src" / "gmagc_common"]
```

Общие фикстуры:

```python
# path: tests/conftest.py
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
    """Сервис с построенным индексом синтетической библиотеки и кодом доступа."""
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
```

```python
# path: tests/server/conftest.py
import http.client
import json

import pytest


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

- [ ] **Step 4: Sync the copies and run the tests**

Run: `.venv\Scripts\python.exe scripts\sync_common.py`, затем `.venv\Scripts\python.exe -m pytest -q`
Expected: PASS (все прежние тесты, включая сервер, и новые).

- [ ] **Step 5: Lint and commit**

```bash
.venv/Scripts/python.exe -m ruff check --fix . && .venv/Scripts/python.exe -m pytest -q
git add packages scripts/sync_common.py apps/desktop/src/gmagc_common apps/mobile/src/gmagc_common tests
git commit -m "feat: outcome constants, protocol copy for the mobile app, shared test fixtures" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: Сетевой клиент `gmagc_mobile/client.py`

**Files:**
- Create: `apps/mobile/src/gmagc_mobile/client.py`
- Test: `tests/mobile/test_client.py`

**Interfaces:**
- Consumes: `gmagc_common.protocol` (`Connection`, `Health`, `Status`, `MatchResponse`, `ApiError`, `ProtocolError`, `API_VERSION`, `APP_NAME`); сервер и фикстуры `running`, `photo_jpeg` из `tests/conftest.py`.
- Produces: виды ошибок `UNREACHABLE`, `UNAUTHORIZED`, `RATE_LIMITED`, `NO_INDEX`, `BAD_IMAGE`, `TOO_LARGE`, `SERVER`, `PROTOCOL` (строки); `ClientError(kind, message, retry_after=0)`; `GmagcClient(connection, timeout=10.0, match_timeout=60.0)` с методами `health() -> Health`, `status() -> Status`, `verify() -> tuple[Health, Status]`, `match(image: bytes, top: int | None = None) -> MatchResponse`.

- [ ] **Step 1: Write the failing tests**

```python
# path: tests/mobile/test_client.py
import json
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from gmagc_common.protocol import MAX_IMAGE_BYTES, Connection, MatchResponse
from gmagc_desktop.server.runner import PhoneServer
from gmagc_desktop.service.search_service import SearchService
from gmagc_mobile.client import (
    BAD_IMAGE,
    NO_INDEX,
    PROTOCOL,
    RATE_LIMITED,
    SERVER,
    TOO_LARGE,
    UNAUTHORIZED,
    UNREACHABLE,
    ClientError,
    GmagcClient,
)


def make_client(running, code=None, **options):
    return GmagcClient(Connection("127.0.0.1", running.port, code or running.code), **options)


@contextmanager
def stub_server(status=200, body=b"{}", content_type="application/json", delay=0.0):
    """Поддельный сервер: на любой запрос отвечает заданным телом."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            time.sleep(delay)
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_POST = do_GET

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield Connection("127.0.0.1", server.server_address[1], "ABCD2345")
    finally:
        server.shutdown()
        server.server_close()


def test_verify_returns_the_health_and_the_status(running):
    health, status = make_client(running).verify()

    assert health.app == "GMAGC" and health.indexed and health.files == 6
    assert status.indexed and status.families == 5 and status.indexing is False


def test_a_wrong_code_is_unauthorized(running):
    with pytest.raises(ClientError) as error:
        make_client(running, "ABCD2346").verify()

    assert error.value.kind == UNAUTHORIZED


def test_five_wrong_codes_lead_to_the_rate_limit_with_a_wait_time(running):
    client = make_client(running, "ABCD2346")
    for _ in range(5):
        with pytest.raises(ClientError) as error:
            client.status()
        assert error.value.kind == UNAUTHORIZED

    with pytest.raises(ClientError) as error:
        client.status()

    assert error.value.kind == RATE_LIMITED and 1 <= error.value.retry_after <= 30


def test_match_returns_the_parsed_response(running, photo_jpeg):
    response = make_client(running).match(photo_jpeg)

    assert isinstance(response, MatchResponse) and response.outcome in {"found", "low_confidence"}
    assert len(response.results) == 5 and response.results[0].path.endswith(".png")
    assert response.results[0].thumbnail_png.startswith(b"\x89PNG")


def test_match_honors_top(running, photo_jpeg):
    assert len(make_client(running).match(photo_jpeg, top=2).results) == 2


def test_a_closed_port_is_unreachable(running):
    running.server.stop()

    with pytest.raises(ClientError) as error:
        make_client(running).verify()

    assert error.value.kind == UNREACHABLE


def test_a_slow_server_times_out_as_unreachable():
    with stub_server(delay=1.5) as connection, pytest.raises(ClientError) as error:
        GmagcClient(connection, timeout=0.3).health()

    assert error.value.kind == UNREACHABLE


def test_junk_and_empty_images_are_bad_image(running):
    with pytest.raises(ClientError) as error:
        make_client(running).match(b"not an image")
    assert error.value.kind == BAD_IMAGE

    with pytest.raises(ClientError) as error:
        make_client(running).match(b"")
    assert error.value.kind == BAD_IMAGE


def test_an_oversized_image_is_too_large(running):
    with pytest.raises(ClientError) as error:
        make_client(running).match(b"\0" * (MAX_IMAGE_BYTES + 1))

    assert error.value.kind == TOO_LARGE


def test_a_pc_without_an_index_is_no_index(tmp_path, photo_jpeg):
    empty = SearchService(tmp_path / "empty")
    empty.load()
    code = empty.ensure_access_code()
    server = PhoneServer(empty, host="127.0.0.1")
    port = server.start(0)
    try:
        with pytest.raises(ClientError) as error:
            GmagcClient(Connection("127.0.0.1", port, code)).match(photo_jpeg)
        assert error.value.kind == NO_INDEX
        health, status = GmagcClient(Connection("127.0.0.1", port, code)).verify()
        assert health.indexed is False and status.indexed is False
    finally:
        server.stop()


def test_a_foreign_json_server_is_a_protocol_error():
    with stub_server(body=b'{"hello": "world"}') as connection, pytest.raises(ClientError) as error:
        GmagcClient(connection).health()

    assert error.value.kind == PROTOCOL and "не сервер GMAGC" in error.value.message


def test_a_non_json_server_is_a_protocol_error():
    with stub_server(body=b"<html>router</html>", content_type="text/html") as connection:
        with pytest.raises(ClientError) as error:
            GmagcClient(connection).health()

    assert error.value.kind == PROTOCOL


def test_an_incompatible_api_version_is_reported():
    body = json.dumps({"app": "GMAGC", "api": 99, "version": "9.0.0", "indexed": True, "files": 1}).encode()
    with stub_server(body=body) as connection, pytest.raises(ClientError) as error:
        GmagcClient(connection).health()

    assert error.value.kind == PROTOCOL and "API 99" in error.value.message


def test_an_unknown_error_reply_is_a_server_error():
    with stub_server(status=503, body=b'{"oops": 1}') as connection, pytest.raises(ClientError) as error:
        GmagcClient(connection).health()

    assert error.value.kind == SERVER and "503" in error.value.message


def test_a_known_error_code_keeps_the_server_message():
    body = json.dumps({"error": "server_error", "message": "ошибка поиска на ПК"}).encode()
    with stub_server(status=500, body=body) as connection, pytest.raises(ClientError) as error:
        GmagcClient(connection).match(b"x")

    assert error.value.kind == SERVER and error.value.message == "ошибка поиска на ПК"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/mobile/test_client.py -q`
Expected: FAIL (`ModuleNotFoundError: gmagc_mobile.client`).

- [ ] **Step 3: Write the implementation**

```python
# path: apps/mobile/src/gmagc_mobile/client.py
"""Клиент сервера GMAGC на ПК (стандартная библиотека): проверка подключения и поиск по фото."""

from __future__ import annotations

import http.client
import json

from gmagc_common.protocol import (
    API_VERSION,
    APP_NAME,
    ApiError,
    Connection,
    Health,
    MatchResponse,
    ProtocolError,
    Status,
)

UNREACHABLE = "unreachable"
UNAUTHORIZED = "unauthorized"
RATE_LIMITED = "rate_limited"
NO_INDEX = "no_index"
BAD_IMAGE = "bad_image"
TOO_LARGE = "too_large"
SERVER = "server"
PROTOCOL = "protocol"

_KIND_BY_CODE = {
    "unauthorized": UNAUTHORIZED,
    "rate_limited": RATE_LIMITED,
    "no_index": NO_INDEX,
    "bad_image": BAD_IMAGE,
    "bad_request": BAD_IMAGE,
    "too_large": TOO_LARGE,
}
_NOT_GMAGC = "Это не сервер GMAGC: проверьте адрес и порт."


class ClientError(Exception):
    """Ошибка обращения к ПК; kind говорит экрану, что показать."""

    def __init__(self, kind: str, message: str, retry_after: int = 0):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.retry_after = retry_after


class GmagcClient:
    def __init__(self, connection: Connection, timeout: float = 10.0, match_timeout: float = 60.0):
        self.connection = connection
        self._timeout = timeout
        self._match_timeout = match_timeout

    def health(self) -> Health:
        data = self._request("GET", "/api/health", auth=False)
        try:
            health = Health.from_dict(data)
        except ProtocolError as error:
            raise ClientError(PROTOCOL, _NOT_GMAGC) from error
        if health.app != APP_NAME:
            raise ClientError(PROTOCOL, _NOT_GMAGC)
        if health.api != API_VERSION:
            raise ClientError(
                PROTOCOL,
                f"Версия приложения на ПК (API {health.api}) не подходит к этому телефону (API {API_VERSION}): "
                "обновите оба приложения.",
            )
        return health

    def status(self) -> Status:
        data = self._request("GET", "/api/status")
        try:
            return Status.from_dict(data)
        except ProtocolError as error:
            raise ClientError(PROTOCOL, "Неожиданный ответ ПК на запрос состояния.") from error

    def verify(self) -> tuple[Health, Status]:
        """Проверяет адрес (health без кода) и код доступа (status с кодом)."""
        return self.health(), self.status()

    def match(self, image: bytes, top: int | None = None) -> MatchResponse:
        path = "/api/match" + (f"?top={top}" if top else "")
        data = self._request("POST", path, body=image, timeout=self._match_timeout)
        try:
            return MatchResponse.from_dict(data)
        except ProtocolError as error:
            raise ClientError(PROTOCOL, "Неожиданный ответ ПК на поиск.") from error

    def _request(
        self, method: str, path: str, body: bytes | None = None, auth: bool = True, timeout: float | None = None
    ) -> dict:
        headers: dict[str, str] = {}
        if auth:
            headers["Authorization"] = f"Bearer {self.connection.code}"
        if body is not None:
            headers["Content-Type"] = "image/jpeg"
        client = http.client.HTTPConnection(self.connection.host, self.connection.port, timeout=timeout or self._timeout)
        try:
            client.request(method, path, body=body, headers=headers)
            response = client.getresponse()
            raw = response.read()
            status = response.status
            retry_header = response.getheader("Retry-After")
        except (OSError, http.client.HTTPException) as error:  # в том числе отказ в соединении и таймаут
            raise ClientError(UNREACHABLE, f"{type(error).__name__}: {error}") from error
        finally:
            client.close()
        try:
            data = json.loads(raw) if raw else {}
        except ValueError as error:
            raise ClientError(PROTOCOL, _NOT_GMAGC) from error
        if not isinstance(data, dict):
            raise ClientError(PROTOCOL, _NOT_GMAGC)
        if status == 200:
            return data
        try:
            api_error = ApiError.from_dict(data)
        except ProtocolError as error:
            raise ClientError(SERVER, f"Ответ ПК: HTTP {status}") from error
        retry_after = int(retry_header) if retry_header and retry_header.isdigit() else 0
        raise ClientError(_KIND_BY_CODE.get(api_error.code, SERVER), api_error.message, retry_after)
```

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest tests/mobile/test_client.py -q`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
.venv/Scripts/python.exe -m ruff check --fix . && .venv/Scripts/python.exe -m pytest -q
git add apps/mobile/src/gmagc_mobile/client.py tests/mobile/test_client.py
git commit -m "feat: typed network client of the Android app" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: Хранилище подключения, подготовка фото и чтение QR

**Files:**
- Create: `apps/mobile/src/gmagc_mobile/store.py`, `apps/mobile/src/gmagc_mobile/imaging.py`, `apps/mobile/src/gmagc_mobile/qr.py`
- Modify: `requirements-dev.txt` (строка `pyzbar`), `.github/workflows/ci.yml` (библиотека zbar в CI)
- Test: `tests/mobile/test_store.py`, `tests/mobile/test_imaging.py`, `tests/mobile/test_qr.py`

**Interfaces:**
- Produces: `store.ConnectionStore(prefs)` c async `load() -> Connection | None`, `save(connection)`, `clear()`; `imaging.prepare_upload(data: bytes, limit: int = 8 МБ) -> bytes` (`ValueError`, если файл не изображение или не уменьшается до лимита); `qr.decode_qr(image: bytes) -> str | None`, `qr.connection_from_qr(image: bytes) -> Connection | None`, `qr.QrUnavailable(RuntimeError)`.

- [ ] **Step 1: Write the failing tests**

```python
# path: tests/mobile/test_store.py
import asyncio

from gmagc_common.protocol import Connection
from gmagc_mobile.store import KEY_CODE, KEY_HOST, KEY_PORT, ConnectionStore


class FakePrefs:
    """Замена ft.SharedPreferences: словарь с асинхронными методами."""

    def __init__(self, data=None, fail=False):
        self.data = dict(data or {})
        self.fail = fail

    async def get(self, key):
        if self.fail:
            raise RuntimeError("хранилище недоступно")
        return self.data.get(key)

    async def set(self, key, value):
        self.data[key] = value
        return True

    async def remove(self, key):
        return self.data.pop(key, None) is not None


def test_a_saved_connection_is_loaded_back():
    store = ConnectionStore(FakePrefs())
    connection = Connection("192.168.1.5", 8765, "ABCD2345")

    asyncio.run(store.save(connection))

    assert asyncio.run(store.load()) == connection


def test_nothing_saved_gives_none():
    assert asyncio.run(ConnectionStore(FakePrefs()).load()) is None


def test_clear_forgets_the_connection():
    prefs = FakePrefs()
    store = ConnectionStore(prefs)
    asyncio.run(store.save(Connection("192.168.1.5", 8765, "ABCD2345")))

    asyncio.run(store.clear())

    assert asyncio.run(store.load()) is None and prefs.data == {}


def test_a_whole_number_float_port_is_accepted():
    prefs = FakePrefs({KEY_HOST: "10.0.0.7", KEY_PORT: 8766.0, KEY_CODE: "abcd-2345"})

    assert asyncio.run(ConnectionStore(prefs).load()) == Connection("10.0.0.7", 8766, "ABCD2345")


def test_broken_stored_values_give_none():
    bad = [
        {KEY_HOST: "10.0.0.7", KEY_PORT: "8765", KEY_CODE: "ABCD2345"},
        {KEY_HOST: "10.0.0.7", KEY_PORT: True, KEY_CODE: "ABCD2345"},
        {KEY_HOST: "10.0.0.7", KEY_PORT: 8765.5, KEY_CODE: "ABCD2345"},
        {KEY_HOST: "10.0.0.7", KEY_PORT: 70000, KEY_CODE: "ABCD2345"},
        {KEY_HOST: "bad host", KEY_PORT: 8765, KEY_CODE: "ABCD2345"},
        {KEY_HOST: "10.0.0.7", KEY_PORT: 8765, KEY_CODE: "BAD"},
        {KEY_HOST: 5, KEY_PORT: 8765, KEY_CODE: "ABCD2345"},
    ]
    for data in bad:
        assert asyncio.run(ConnectionStore(FakePrefs(data)).load()) is None, data


def test_a_failing_storage_gives_none():
    assert asyncio.run(ConnectionStore(FakePrefs(fail=True)).load()) is None
```

```python
# path: tests/mobile/test_imaging.py
import io

import numpy as np
import pytest
from PIL import Image

from gmagc_mobile.imaging import UPLOAD_LIMIT, prepare_upload


def png_bytes(width, height):
    x = np.linspace(0, 255, width, dtype=np.uint8)
    y = np.linspace(0, 255, height, dtype=np.uint8)
    pixels = np.stack([np.tile(x, (height, 1)), np.tile(y[:, None], (1, width)), np.full((height, width), 90, np.uint8)], -1)
    buffer = io.BytesIO()
    Image.fromarray(pixels).save(buffer, "PNG")
    return buffer.getvalue()


def test_small_files_are_sent_as_is():
    data = png_bytes(64, 48)

    assert prepare_upload(data) is data and len(data) < UPLOAD_LIMIT


def test_a_file_over_the_limit_is_shrunk_to_a_jpeg_under_the_limit():
    data = png_bytes(3000, 2000)

    result = prepare_upload(data, limit=len(data) - 1)

    assert result.startswith(b"\xff\xd8") and len(result) <= len(data) - 1
    with Image.open(io.BytesIO(result)) as picture:
        assert max(picture.size) <= 2560


def test_an_image_that_cannot_fit_raises():
    with pytest.raises(ValueError):
        prepare_upload(png_bytes(400, 300), limit=10)


def test_a_big_non_image_raises():
    with pytest.raises(ValueError):
        prepare_upload(b"x" * 2000, limit=1000)
```

```python
# path: tests/mobile/test_qr.py
import io

import pytest
from PIL import Image, ImageFilter

from gmagc_common.protocol import Connection, build_link
from gmagc_desktop.server.qr import qr_png
from gmagc_mobile import qr

LINK = build_link("192.168.1.121", 8765, "ZBZ36YNK")

try:
    from pyzbar import pyzbar as _pyzbar  # noqa: F401

    HAVE_ZBAR = True
except Exception:  # noqa: BLE001 - нет колеса или разделяемой библиотеки zbar
    HAVE_ZBAR = False
needs_zbar = pytest.mark.skipif(not HAVE_ZBAR, reason="нет библиотеки zbar")


def camera_shot(link=LINK, size=(1280, 720), qr_side=360):
    """Похоже на снимок экрана камерой: QR на сером фоне, слегка размытый."""
    code = Image.open(io.BytesIO(qr_png(link))).convert("RGB").resize((qr_side, qr_side), Image.NEAREST)
    canvas = Image.new("RGB", size, (70, 70, 80))
    canvas.paste(code, ((size[0] - qr_side) // 2, (size[1] - qr_side) // 2))
    buffer = io.BytesIO()
    canvas.filter(ImageFilter.GaussianBlur(1.2)).save(buffer, "JPEG", quality=80)
    return buffer.getvalue()


def test_a_missing_decoder_is_reported_as_unavailable(monkeypatch):
    def unavailable():
        raise qr.QrUnavailable("нет zbar")

    monkeypatch.setattr(qr, "_load", unavailable)

    with pytest.raises(qr.QrUnavailable):
        qr.connection_from_qr(b"anything")


@needs_zbar
def test_the_qr_of_the_pc_screen_is_read_from_a_photo():
    assert qr.decode_qr(camera_shot()) == LINK
    assert qr.connection_from_qr(camera_shot()) == Connection("192.168.1.121", 8765, "ZBZ36YNK")


@needs_zbar
def test_the_plain_qr_image_is_read():
    assert qr.decode_qr(qr_png(LINK)) == LINK


@needs_zbar
def test_a_photo_without_a_qr_gives_none():
    buffer = io.BytesIO()
    Image.new("RGB", (640, 480), (120, 120, 120)).save(buffer, "PNG")

    assert qr.decode_qr(buffer.getvalue()) is None
    assert qr.connection_from_qr(buffer.getvalue()) is None


@needs_zbar
def test_bytes_that_are_not_an_image_give_none():
    assert qr.decode_qr(b"definitely not an image") is None


@needs_zbar
def test_a_qr_with_foreign_text_is_not_a_connection():
    assert qr.decode_qr(camera_shot("https://example.com/")) == "https://example.com/"
    assert qr.connection_from_qr(camera_shot("https://example.com/")) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/mobile/test_store.py tests/mobile/test_imaging.py tests/mobile/test_qr.py -q`
Expected: FAIL (нет модулей `store`, `imaging`, `qr`).

- [ ] **Step 3: Write the implementation**

```python
# path: apps/mobile/src/gmagc_mobile/store.py
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
```

```python
# path: apps/mobile/src/gmagc_mobile/imaging.py
"""Подготовка фото из галереи к отправке на ПК (лимит сервера 10 МБ)."""

from __future__ import annotations

import io

UPLOAD_LIMIT = 8 * 1024 * 1024  # запас до лимита сервера
MAX_SIDE = 2560


def prepare_upload(data: bytes, limit: int = UPLOAD_LIMIT) -> bytes:
    """Файл до limit уходит как есть; больший уменьшается Pillow до JPEG не больше limit (иначе ValueError)."""
    if len(data) <= limit:
        return data
    try:
        from PIL import Image, ImageOps

        with Image.open(io.BytesIO(data)) as opened:
            picture = ImageOps.exif_transpose(opened).convert("RGB")
    except Exception as error:  # noqa: BLE001 - нет Pillow или файл не изображение
        raise ValueError("файл не удалось прочитать как изображение") from error
    picture.thumbnail((MAX_SIDE, MAX_SIDE))
    for quality in (85, 70, 55):
        buffer = io.BytesIO()
        picture.save(buffer, "JPEG", quality=quality)
        if len(buffer.getvalue()) <= limit:
            return buffer.getvalue()
    raise ValueError("изображение слишком большое даже после уменьшения")
```

```python
# path: apps/mobile/src/gmagc_mobile/qr.py
"""Чтение QR-кода подключения из снимка камеры (pyzbar + Pillow)."""

from __future__ import annotations

import io

from gmagc_common.protocol import Connection, parse_link

MAX_SIDE = 1600


class QrUnavailable(RuntimeError):
    """Библиотека чтения QR (pyzbar/zbar) или Pillow недоступна на этом устройстве."""


def _load():
    try:
        from PIL import Image
        from pyzbar import pyzbar
    except Exception as error:  # noqa: BLE001 - нет колеса или нет разделяемой библиотеки zbar
        raise QrUnavailable(str(error)) from error
    return Image, pyzbar


def decode_qr(image: bytes) -> str | None:
    """Текст первого QR-кода на снимке или None, если кода не видно."""
    Image, pyzbar = _load()
    try:
        with Image.open(io.BytesIO(image)) as opened:
            picture = opened.convert("L")
    except Exception:  # noqa: BLE001 - не изображение
        return None
    picture.thumbnail((MAX_SIDE, MAX_SIDE))
    for symbol in pyzbar.decode(picture, symbols=[pyzbar.ZBarSymbol.QRCODE]):
        try:
            return symbol.data.decode("utf-8")
        except UnicodeDecodeError:
            continue
    return None


def connection_from_qr(image: bytes) -> Connection | None:
    text = decode_qr(image)
    return parse_link(text) if text else None
```

В `requirements-dev.txt` добавить строку `pyzbar` (с CRLF, как остальные). В `.github/workflows/ci.yml` перед шагом `python -m pip install -r requirements-dev.txt` вставить:

```yaml
      - name: Библиотека zbar для тестов чтения QR
        if: runner.os == 'Linux'
        run: sudo apt-get update && sudo apt-get install -y libzbar0
      - name: Библиотека zbar для тестов чтения QR (macOS)
        if: runner.os == 'macOS'
        run: brew install zbar
```

- [ ] **Step 4: Install and run the tests**

Run: `.venv\Scripts\python.exe -m pip install pyzbar`, затем `.venv\Scripts\python.exe -m pytest tests/mobile -q`
Expected: PASS; тесты `test_qr` могут быть пропущены, если zbar не загрузился (в CI на Linux и macOS они выполняются).

- [ ] **Step 5: Lint and commit**

```bash
.venv/Scripts/python.exe -m ruff check --fix . && .venv/Scripts/python.exe -m pytest -q
git add apps/mobile/src/gmagc_mobile tests/mobile requirements-dev.txt .github/workflows/ci.yml
git commit -m "feat: connection store, photo preparation and QR reader for the Android app" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---
### Task 4: Управление камерой (приближение, фокус) и тексты

**Files:**
- Create: `apps/mobile/src/gmagc_mobile/camera.py`, `apps/mobile/src/gmagc_mobile/texts.py`, `tests/fakes_mobile.py`
- Test: `tests/mobile/test_camera.py`, `tests/mobile/test_mobile_texts.py`

**Interfaces:**
- Consumes: `flet_camera` (`Camera` API: `get_available_cameras`, `initialize`, `get_min_zoom_level`, `get_max_zoom_level`, `set_zoom_level`, `set_focus_mode`, `set_focus_point`, `set_exposure_point`, `take_picture`, `pause_preview`, `resume_preview`), `flet_permission_handler` (`PermissionHandler.request`), `client.ClientError` и виды ошибок из Task 2.
- Produces: `camera.CameraController(camera, permission, settle_seconds=0.8)`: атрибуты `ready`, `error`, `zoom`, `min_zoom`, `max_zoom`, `focus_locked`; async `start() -> bool`, `set_zoom(value) -> float`, `zoom_by(delta) -> float`, `focus_at(x, y, width, height) -> bool`, `toggle_focus_lock() -> bool` (новое состояние «зафиксирован»), `take_picture() -> bytes`, `pause()`, `resume()`; `texts.error_text(ClientError) -> str`, `texts.outcome_message(outcome: str) -> str | None`, `texts.score_text(score) -> str`, `texts.status_line(connection, status) -> str`, `texts.zoom_text(zoom) -> str`, `texts.NO_INDEX_NOTE`; заглушки `tests/fakes_mobile.py`: `FakeCameraApi`, `FakePermission`, `FakePrefs`, `Script`.

- [ ] **Step 1: Write the failing tests**

```python
# path: tests/fakes_mobile.py
"""Заглушки для тестов Android-приложения: камера, разрешение, хранилище, сетевой клиент."""

from types import SimpleNamespace

import flet_camera as fc
import flet_permission_handler as ph

from gmagc_common.protocol import Health, MatchResponse, ResultItem, Status


def cam(direction: str):
    return SimpleNamespace(name=direction, lens_direction=fc.CameraLensDirection(direction))


class FakeCameraApi:
    """Замена fc.Camera: записывает вызовы в calls."""

    def __init__(self, cameras=None, min_zoom=1.0, max_zoom=6.0, picture=b"JPEG-shot", fail=None):
        self.cameras = list(cameras) if cameras is not None else [cam("front"), cam("back")]
        self.min_zoom = min_zoom
        self.max_zoom = max_zoom
        self.picture = picture
        self.fail = fail  # имя метода, который должен упасть
        self.calls = []

    def _maybe_fail(self, name):
        if self.fail == name:
            raise RuntimeError(f"сбой {name}")

    async def get_available_cameras(self):
        self._maybe_fail("get_available_cameras")
        return self.cameras

    async def initialize(self, description, preset, enable_audio=True):
        self._maybe_fail("initialize")
        self.calls.append(("initialize", description.lens_direction, preset, enable_audio))

    async def get_min_zoom_level(self):
        self._maybe_fail("get_min_zoom_level")
        return self.min_zoom

    async def get_max_zoom_level(self):
        self._maybe_fail("get_max_zoom_level")
        return self.max_zoom

    async def set_zoom_level(self, zoom):
        self._maybe_fail("set_zoom_level")
        self.calls.append(("zoom", zoom))

    async def set_focus_mode(self, mode):
        self._maybe_fail("set_focus_mode")
        self.calls.append(("focus_mode", mode))

    async def set_focus_point(self, point):
        self._maybe_fail("set_focus_point")
        self.calls.append(("focus_point", tuple(point)))

    async def set_exposure_point(self, point):
        self._maybe_fail("set_exposure_point")
        self.calls.append(("exposure_point", tuple(point)))

    async def take_picture(self):
        self._maybe_fail("take_picture")
        self.calls.append(("take_picture",))
        return self.picture

    async def pause_preview(self):
        self.calls.append(("pause",))

    async def resume_preview(self):
        self.calls.append(("resume",))


class FakePermission:
    def __init__(self, status=ph.PermissionStatus.GRANTED):
        self.status = status
        self.requested = []

    async def request(self, permission):
        self.requested.append(permission)
        return self.status


class FakePrefs:
    """Замена ft.SharedPreferences: словарь с асинхронными методами."""

    def __init__(self, data=None, fail=False):
        self.data = dict(data or {})
        self.fail = fail

    async def get(self, key):
        if self.fail:
            raise RuntimeError("хранилище недоступно")
        return self.data.get(key)

    async def set(self, key, value):
        self.data[key] = value
        return True

    async def remove(self, key):
        return self.data.pop(key, None) is not None


def item(rank, name, path, score, copies=()):
    return ResultItem(rank, name, path, score, tuple(copies), b"\x89PNG-thumb")


def sample_response(outcome="found", results=None):
    items = (
        results
        if results is not None
        else (
            item(1, "a.png", "C:\\gobos\\vendor\\a.png", 0.912, copies=("C:\\gobos\\other\\a.png",)),
            item(2, "b.png", "C:\\gobos\\vendor\\b.png", 0.803),
        )
    )
    return MatchResponse("r1", outcome, 12.5, tuple(items), b"\x89PNG-proj")


class Script:
    """Управляет поведением подставного сетевого клиента: результат или исключение для verify и match."""

    def __init__(self):
        self.verify_result = (Health("GMAGC", 1, "0.5.0", True, 11178), Status(True, 11178, 9396, False, 0, 0))
        self.match_result = sample_response()
        self.connections = []
        self.matches = []

    def factory(self, connection):
        self.connections.append(connection)
        return ScriptedClient(self)


class ScriptedClient:
    def __init__(self, script):
        self.script = script

    def verify(self):
        result = self.script.verify_result
        if isinstance(result, Exception):
            raise result
        return result

    def match(self, image, top=None):
        self.script.matches.append(image)
        result = self.script.match_result
        if isinstance(result, Exception):
            raise result
        return result
```

```python
# path: tests/mobile/test_camera.py
import asyncio

import flet_camera as fc
import flet_permission_handler as ph
import pytest

from gmagc_mobile.camera import CameraController
from tests.fakes_mobile import FakeCameraApi, FakePermission, cam


def make(api=None, permission=None):
    api = api or FakeCameraApi()
    return CameraController(api, permission or FakePermission(), settle_seconds=0), api


def started(api=None):
    controller, api = make(api)
    assert asyncio.run(controller.start())
    return controller, api


def test_start_asks_for_the_camera_permission_and_picks_the_back_camera():
    permission = FakePermission()
    controller, api = make(permission=permission)

    assert asyncio.run(controller.start()) is True

    assert permission.requested == [ph.Permission.CAMERA]
    assert api.calls[0] == ("initialize", fc.CameraLensDirection.BACK, fc.ResolutionPreset.HIGH, False)
    assert controller.ready and controller.error == ""
    assert (controller.min_zoom, controller.max_zoom, controller.zoom) == (1.0, 6.0, 1.0)


def test_without_a_back_camera_the_first_one_is_used():
    api = FakeCameraApi(cameras=[cam("front")])
    controller, _ = make(api)

    assert asyncio.run(controller.start()) is True
    assert api.calls[0][1] == fc.CameraLensDirection.FRONT


def test_a_denied_permission_is_reported_and_the_camera_stays_off():
    controller, api = make(permission=FakePermission(ph.PermissionStatus.DENIED))

    assert asyncio.run(controller.start()) is False

    assert not controller.ready and "разрешите" in controller.error and api.calls == []


def test_no_cameras_is_reported():
    controller, _ = make(FakeCameraApi(cameras=[]))

    assert asyncio.run(controller.start()) is False
    assert controller.error == "Камера не найдена"


@pytest.mark.parametrize("method", ["get_available_cameras", "initialize"])
def test_plugin_failures_become_a_message_not_an_exception(method):
    controller, _ = make(FakeCameraApi(fail=method))

    assert asyncio.run(controller.start()) is False
    assert controller.error.startswith("Ошибка камеры:") and method in controller.error


def test_an_unreadable_zoom_range_keeps_the_camera_usable_without_zoom():
    controller, _ = make(FakeCameraApi(fail="get_max_zoom_level"))

    assert asyncio.run(controller.start()) is True
    assert (controller.min_zoom, controller.max_zoom) == (1.0, 1.0)


def test_zoom_is_clamped_to_the_supported_range_and_sent_to_the_camera():
    controller, api = started(FakeCameraApi(min_zoom=1.0, max_zoom=4.0))

    assert asyncio.run(controller.set_zoom(2.5)) == 2.5
    assert asyncio.run(controller.set_zoom(99)) == 4.0
    assert asyncio.run(controller.set_zoom(0.2)) == 1.0

    assert [call for call in api.calls if call[0] == "zoom"] == [("zoom", 2.5), ("zoom", 4.0), ("zoom", 1.0)]
    assert controller.zoom == 1.0


def test_zoom_by_steps_up_and_down():
    controller, _ = started()

    assert asyncio.run(controller.zoom_by(0.5)) == 1.5
    assert asyncio.run(controller.zoom_by(0.5)) == 2.0
    assert asyncio.run(controller.zoom_by(-1.5)) == 1.0


def test_zoom_does_nothing_when_the_camera_has_no_zoom_range():
    controller, api = started(FakeCameraApi(min_zoom=1.0, max_zoom=1.0))

    assert asyncio.run(controller.set_zoom(3)) == 1.0
    assert not [call for call in api.calls if call[0] == "zoom"]


def test_a_failing_zoom_call_is_reported_and_keeps_the_old_zoom():
    controller, api = started()
    api.fail = "set_zoom_level"

    assert asyncio.run(controller.set_zoom(3)) == 1.0
    assert "сбой set_zoom_level" in controller.error


def test_a_tap_focuses_and_meters_at_the_normalized_point():
    controller, api = started()

    assert asyncio.run(controller.focus_at(200, 100, 400, 800)) is True

    assert ("focus_point", (0.5, 0.125)) in api.calls and ("exposure_point", (0.5, 0.125)) in api.calls
    assert not [call for call in api.calls if call[0] == "focus_mode"]


def test_points_outside_the_preview_are_clamped_and_an_unknown_size_is_ignored():
    controller, api = started()

    assert asyncio.run(controller.focus_at(-50, 900, 400, 800)) is True
    assert ("focus_point", (0.0, 1.0)) in api.calls
    api.calls.clear()
    assert asyncio.run(controller.focus_at(10, 10, 0, 0)) is False
    assert api.calls == []


def test_focus_is_ignored_while_the_camera_is_not_ready():
    controller, api = make()

    assert asyncio.run(controller.focus_at(10, 10, 100, 100)) is False
    assert api.calls == []


def test_a_camera_without_point_focus_reports_it():
    controller, api = started()
    api.fail = "set_focus_point"

    assert asyncio.run(controller.focus_at(10, 10, 100, 100)) is False
    assert controller.error.startswith("Фокус по точке недоступен")


def test_the_focus_lock_toggles_between_locked_and_auto():
    controller, api = started()

    assert asyncio.run(controller.toggle_focus_lock()) is True
    assert asyncio.run(controller.toggle_focus_lock()) is False

    assert [call for call in api.calls if call[0] == "focus_mode"] == [
        ("focus_mode", fc.FocusMode.LOCKED),
        ("focus_mode", fc.FocusMode.AUTO),
    ]


def test_a_tap_with_the_lock_on_refocuses_and_locks_again():
    controller, api = started()
    asyncio.run(controller.toggle_focus_lock())
    api.calls.clear()

    asyncio.run(controller.focus_at(100, 100, 200, 200))

    assert [call[0] for call in api.calls] == ["focus_mode", "focus_point", "exposure_point", "focus_mode"]
    assert api.calls[0] == ("focus_mode", fc.FocusMode.AUTO) and api.calls[-1] == ("focus_mode", fc.FocusMode.LOCKED)


def test_take_picture_returns_the_bytes_and_requires_a_ready_camera():
    controller, _ = started(FakeCameraApi(picture=b"\xff\xd8jpeg"))
    assert asyncio.run(controller.take_picture()) == b"\xff\xd8jpeg"

    idle, _ = make()
    with pytest.raises(RuntimeError):
        asyncio.run(idle.take_picture())


def test_pause_and_resume_only_touch_a_ready_camera_and_never_raise():
    idle, idle_api = make()
    asyncio.run(idle.pause())
    asyncio.run(idle.resume())
    assert idle_api.calls == []

    controller, api = started()
    asyncio.run(controller.pause())
    asyncio.run(controller.resume())
    assert api.calls[-2:] == [("pause",), ("resume",)]
```

```python
# path: tests/mobile/test_mobile_texts.py
from gmagc_common.protocol import Connection, Status
from gmagc_mobile import client
from gmagc_mobile.client import ClientError
from gmagc_mobile.texts import NO_INDEX_NOTE, error_text, outcome_message, score_text, status_line, zoom_text


def test_each_error_kind_has_a_clear_text():
    assert "одной сети Wi-Fi" in error_text(ClientError(client.UNREACHABLE, "ConnectionRefusedError: x"))
    assert "ConnectionRefusedError" in error_text(ClientError(client.UNREACHABLE, "ConnectionRefusedError: x"))
    assert "Неверный код" in error_text(ClientError(client.UNAUTHORIZED, "неверный код доступа"))
    assert "12 с" in error_text(ClientError(client.RATE_LIMITED, "x", retry_after=12))
    assert "30 с" in error_text(ClientError(client.RATE_LIMITED, "x"))
    assert "индекс" in error_text(ClientError(client.NO_INDEX, "x"))
    assert "прочитать изображение" in error_text(ClientError(client.BAD_IMAGE, "x"))
    assert "слишком большое" in error_text(ClientError(client.TOO_LARGE, "x"))
    assert error_text(ClientError(client.PROTOCOL, "Это не сервер GMAGC")) == "Это не сервер GMAGC"
    assert error_text(ClientError(client.SERVER, "ошибка поиска на ПК")) == "Ошибка на ПК: ошибка поиска на ПК"


def test_outcome_messages():
    assert outcome_message("found") is None
    assert "ненадёжно" in outcome_message("low_confidence")
    assert "переснимите" in outcome_message("no_projection")
    assert outcome_message("something_new") is None


def test_score_is_a_percentage_capped_at_100():
    assert score_text(0.8123) == "81.2%"
    assert score_text(1.7) == "100.0%" and score_text(-1) == "0.0%"


def test_status_line_shows_the_pc_and_the_library_size():
    line = status_line(Connection("192.168.1.5", 8765, "ABCD2345"), Status(True, 11178, 9396, False, 0, 0))

    assert line == "Подключено: 192.168.1.5:8765 · 11\u00a0178 файлов"
    assert "не построен" in status_line(Connection("10.0.0.7", 8766, "ABCD2345"), Status(False, 0, 0, False, 0, 0))
    assert "индексация" in status_line(Connection("10.0.0.7", 8766, "ABCD2345"), Status(True, 5, 5, True, 2, 5))
    assert "индекс" in NO_INDEX_NOTE


def test_zoom_text():
    assert zoom_text(1) == "×1.0" and zoom_text(2.0) == "×2.0" and zoom_text(3.25) == "×3.2"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/mobile/test_camera.py tests/mobile/test_mobile_texts.py -q`
Expected: FAIL (нет модулей `camera`, `texts`).

- [ ] **Step 3: Write the implementation**

```python
# path: apps/mobile/src/gmagc_mobile/camera.py
"""Камера телефона: разрешение, задняя камера, приближение, фокус, снимок."""

from __future__ import annotations

import asyncio

import flet_camera as fc
import flet_permission_handler as ph

FOCUS_SETTLE_SECONDS = 0.8  # сколько ждать наведения, прежде чем зафиксировать фокус после касания


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class CameraController:
    def __init__(self, camera, permission, settle_seconds: float = FOCUS_SETTLE_SECONDS):
        self.camera = camera
        self.permission = permission
        self.settle_seconds = settle_seconds
        self.ready = False
        self.error = ""
        self.min_zoom = 1.0
        self.max_zoom = 1.0
        self.zoom = 1.0
        self.focus_locked = False

    async def start(self) -> bool:
        """Просит разрешение и включает заднюю камеру; причину неудачи кладёт в error."""
        try:
            if await self.permission.request(ph.Permission.CAMERA) != ph.PermissionStatus.GRANTED:
                self.error = "Нет доступа к камере: разрешите его в настройках телефона"
                return False
            cameras = await self.camera.get_available_cameras()
            if not cameras:
                self.error = "Камера не найдена"
                return False
            chosen = next((c for c in cameras if c.lens_direction == fc.CameraLensDirection.BACK), cameras[0])
            await self.camera.initialize(chosen, fc.ResolutionPreset.HIGH, enable_audio=False)
        except Exception as error:  # noqa: BLE001 - экран должен показать причину, а не закрыться
            self.error = f"Ошибка камеры: {error}"
            return False
        await self._read_zoom_range()
        self.ready = True
        self.error = ""
        return True

    async def _read_zoom_range(self) -> None:
        try:
            self.min_zoom = float(await self.camera.get_min_zoom_level())
            self.max_zoom = float(await self.camera.get_max_zoom_level())
        except Exception:  # noqa: BLE001 - без диапазона камера работает, но без приближения
            self.min_zoom = self.max_zoom = 1.0
        self.zoom = self.min_zoom

    async def set_zoom(self, value: float) -> float:
        """Устанавливает приближение в пределах диапазона камеры; возвращает фактическое значение."""
        if self.max_zoom <= self.min_zoom:
            return self.zoom
        target = _clamp(value, self.min_zoom, self.max_zoom)
        try:
            await self.camera.set_zoom_level(target)
        except Exception as error:  # noqa: BLE001
            self.error = f"Приближение недоступно: {error}"
            return self.zoom
        self.zoom = target
        return target

    async def zoom_by(self, delta: float) -> float:
        return await self.set_zoom(self.zoom + delta)

    async def focus_at(self, x: float, y: float, width: float, height: float) -> bool:
        """Наводит фокус и замер экспозиции в точку касания (x, y) на превью размера width×height."""
        if not self.ready or width <= 0 or height <= 0:
            return False
        point = (_clamp(x / width, 0.0, 1.0), _clamp(y / height, 0.0, 1.0))
        try:
            if self.focus_locked:
                await self.camera.set_focus_mode(fc.FocusMode.AUTO)
            await self.camera.set_focus_point(point)
            await self.camera.set_exposure_point(point)
            if self.focus_locked:
                await asyncio.sleep(self.settle_seconds)
                await self.camera.set_focus_mode(fc.FocusMode.LOCKED)
        except Exception as error:  # noqa: BLE001 - не все камеры умеют наводить по точке
            self.error = f"Фокус по точке недоступен: {error}"
            return False
        return True

    async def toggle_focus_lock(self) -> bool:
        """Переключает автофокус и фиксацию фокуса; возвращает True, если фокус теперь зафиксирован."""
        target = not self.focus_locked
        try:
            await self.camera.set_focus_mode(fc.FocusMode.LOCKED if target else fc.FocusMode.AUTO)
        except Exception as error:  # noqa: BLE001
            self.error = f"Фокус недоступен: {error}"
            return self.focus_locked
        self.focus_locked = target
        return target

    async def take_picture(self) -> bytes:
        if not self.ready:
            raise RuntimeError(self.error or "камера не готова")
        return await self.camera.take_picture()

    async def pause(self) -> None:
        if self.ready:
            try:
                await self.camera.pause_preview()
            except Exception:  # noqa: BLE001 - пауза превью лишь экономит батарею
                pass

    async def resume(self) -> None:
        if self.ready:
            try:
                await self.camera.resume_preview()
            except Exception:  # noqa: BLE001
                pass
```

```python
# path: apps/mobile/src/gmagc_mobile/texts.py
"""Тексты Android-приложения, которые можно проверить без окна."""

from __future__ import annotations

from gmagc_common.protocol import OUTCOME_LOW_CONFIDENCE, OUTCOME_NO_PROJECTION, Connection, Status
from gmagc_mobile import client
from gmagc_mobile.client import ClientError

NO_INDEX_NOTE = "На ПК ещё не построен индекс: выберите папку библиотеки в приложении на ПК."


def _number(value: int) -> str:
    return f"{value:,}".replace(",", "\u00a0")


def error_text(error: ClientError) -> str:
    kind = error.kind
    if kind == client.UNREACHABLE:
        return (
            "Нет связи с ПК. Телефон и ПК должны быть в одной сети Wi-Fi, GMAGC должен быть запущен на ПК, "
            f"а брандмауэр Windows должен разрешать доступ. ({error.message})"
        )
    if kind == client.UNAUTHORIZED:
        return "Неверный код доступа. Код показан в приложении на ПК; если его сменили, введите новый."
    if kind == client.RATE_LIMITED:
        return f"Слишком много неверных кодов. Подождите {error.retry_after or 30} с."
    if kind == client.NO_INDEX:
        return "На ПК не выбрана библиотека или индекс ещё не построен. Постройте индекс в приложении на ПК."
    if kind == client.BAD_IMAGE:
        return "ПК не смог прочитать изображение. Попробуйте снять ещё раз."
    if kind == client.TOO_LARGE:
        return "Изображение слишком большое для отправки."
    if kind == client.PROTOCOL:
        return error.message
    return f"Ошибка на ПК: {error.message}"


def outcome_message(outcome: str) -> str | None:
    if outcome == OUTCOME_LOW_CONFIDENCE:
        return "Совпадение ненадёжно: похоже, такого гобо в библиотеке нет. Ниже самые близкие."
    if outcome == OUTCOME_NO_PROJECTION:
        return "Проекция на фото не найдена: переснимите ближе, затемните фон."
    return None


def score_text(score: float) -> str:
    return f"{min(max(score, 0.0), 1.0) * 100:.1f}%"


def status_line(connection: Connection, status: Status) -> str:
    line = f"Подключено: {connection.host}:{connection.port}"
    if not status.indexed:
        return line + " · индекс на ПК не построен"
    line += f" · {_number(status.files)} файлов"
    if status.indexing:
        line += " (идёт индексация)"
    return line


def zoom_text(zoom: float) -> str:
    return f"×{zoom:.1f}"
```

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest tests/mobile/test_camera.py tests/mobile/test_mobile_texts.py -q`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
.venv/Scripts/python.exe -m ruff check --fix . && .venv/Scripts/python.exe -m pytest -q
git add apps/mobile/src/gmagc_mobile tests
git commit -m "feat: camera controller with zoom and focus, and texts for the Android app" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: Экран Android-приложения

**Files:**
- Create: `apps/mobile/src/gmagc_mobile/app.py` (полная замена каркаса)
- Modify: `tests/fakes.py` (`FakePicker` отдаёт `bytes=None`), `tests/mobile/test_mobile_app.py` (полная замена)
- Test: `tests/mobile/test_mobile_app.py`, `tests/mobile/test_mobile_camera_ui.py`

**Interfaces:**
- Consumes: всё из Task 2-4; `tests.fakes` (`StubPage`, `FakePicker`, `FakeClipboard`, `texts`, `walk`), `tests.fakes_mobile`.
- Produces: `MobileApp(page, store, camera, preview=None, picker=None, clipboard=None, client_factory=GmagcClient, qr_reader=connection_from_qr, marker_seconds=1.5)`; async `start()`, `on_connect`, `on_scan_qr`, `on_scan_now`, `on_cancel_scan`, `on_capture`, `on_gallery`, `on_again`, `on_change_pc`, `on_card_click`, `on_copy_click`, `copy_path(path)`, `on_zoom_slider`, `on_zoom_in`, `on_zoom_out`, `on_focus_lock`, `on_preview_tap`, `on_scale_update`; sync `on_scale_start`, `on_preview_size`; поля-контролы для тестов; `async build_page(page, **services) -> MobileApp`.

- [ ] **Step 1: Write the failing tests**

В `tests/fakes.py` в `FakePicker.pick_files` вернуть `SimpleNamespace(path=path, bytes=None)`.

```python
# path: tests/mobile/test_mobile_app.py
import asyncio
from pathlib import Path
from types import SimpleNamespace

import flet as ft
import flet_permission_handler as ph
import pytest

from gmagc_common.protocol import Connection, Health, Status
from gmagc_mobile import client
from gmagc_mobile.about import AUTHOR, NAME, VERSION
from gmagc_mobile.app import MobileApp, build_page
from gmagc_mobile.camera import CameraController
from gmagc_mobile.client import ClientError
from gmagc_mobile.qr import QrUnavailable
from gmagc_mobile.store import KEY_CODE, KEY_HOST, KEY_PORT, ConnectionStore
from tests.fakes import FakeClipboard, FakePicker, StubPage, texts, walk
from tests.fakes_mobile import FakeCameraApi, FakePermission, FakePrefs, Script, sample_response

PC = Connection("192.168.1.121", 8765, "ZBZ36YNK")
STORED = {KEY_HOST: "192.168.1.121", KEY_PORT: 8765, KEY_CODE: "ZBZ36YNK"}


def make_app(prefs=None, script=None, camera_api=None, permission=None, qr_reader=None, picker=None, clipboard=None):
    script = script or Script()
    prefs = prefs if prefs is not None else FakePrefs()
    camera_api = camera_api or FakeCameraApi()
    controller = CameraController(camera_api, permission or FakePermission(), settle_seconds=0)
    page = StubPage()
    app = MobileApp(
        page,
        ConnectionStore(prefs),
        controller,
        preview=ft.Container(),
        picker=picker or FakePicker(),
        clipboard=clipboard or FakeClipboard(),
        client_factory=script.factory,
        qr_reader=qr_reader or (lambda data: None),
        marker_seconds=0,
    )
    app.build()
    return app, page, script, prefs, camera_api


def run(coroutine):
    return asyncio.run(coroutine)


def start(**kwargs):
    app, page, script, prefs, camera_api = make_app(**kwargs)
    run(app.start())
    return app, page, script, prefs, camera_api


def connect_manually(app, address="192.168.1.121:8765", code="zbz3-6ynk"):
    app.address_field.value = address
    app.code_field.value = code
    run(app.on_connect(None))


def views(app):
    return [name for name in ("connect", "camera", "results") if getattr(app, f"{name}_view").visible]


def shoot(app):
    run(app.on_capture(None))


def test_the_first_start_shows_the_connect_screen_and_leaves_the_camera_off():
    app, page, script, _, camera_api = start()

    assert views(app) == ["connect"] and camera_api.calls == [] and script.connections == []
    shown = " ".join(t for t in texts(page.added[0]) if t)
    assert NAME in shown and VERSION in shown and AUTHOR in shown


def test_a_stored_connection_is_restored_and_opens_the_camera():
    app, _, script, _, camera_api = start(prefs=FakePrefs(STORED))

    assert script.connections == [PC] and views(app) == ["camera"]
    assert app.address_field.value == "192.168.1.121:8765" and app.camera.ready
    assert app.camera_title.value == "Подключено: 192.168.1.121:8765 · 11\u00a0178 файлов"
    assert camera_api.calls[0][0] == "initialize"


def test_a_stored_connection_to_an_unreachable_pc_shows_the_error_and_keeps_the_data():
    script = Script()
    script.verify_result = ClientError(client.UNREACHABLE, "ConnectionRefusedError: x")
    app, _, _, prefs, _ = start(prefs=FakePrefs(STORED), script=script)

    assert views(app) == ["connect"] and app.connect_error.visible
    assert "Нет связи с ПК" in app.connect_error.value and prefs.data == STORED
    assert app.address_field.value == "192.168.1.121:8765" and app.code_field.value == "ZBZ36YNK"


def test_manual_connect_verifies_saves_and_opens_the_camera():
    app, _, script, prefs, _ = start()

    connect_manually(app)

    assert script.connections == [PC] and views(app) == ["camera"] and not app.connect_error.visible
    assert prefs.data == STORED


def test_manual_connect_without_a_port_uses_the_default_one():
    app, _, script, _, _ = start()

    connect_manually(app, address="192.168.1.121")

    assert script.connections == [PC]


@pytest.mark.parametrize(
    ("address", "code", "fragment"),
    [("", "ZBZ36YNK", "Введите адрес ПК"), ("bad host", "ZBZ36YNK", "Введите адрес ПК"), ("192.168.1.5", "BAD", "8 символов")],
)
def test_invalid_input_is_reported_without_calling_the_pc(address, code, fragment):
    app, _, script, _, _ = start()

    connect_manually(app, address, code)

    assert fragment in app.connect_error.value and app.connect_error.visible
    assert script.connections == [] and views(app) == ["connect"]


def test_a_wrong_code_stays_on_the_connect_screen_and_saves_nothing():
    script = Script()
    script.verify_result = ClientError(client.UNAUTHORIZED, "неверный код доступа")
    app, _, _, prefs, _ = start(script=script)

    connect_manually(app)

    assert views(app) == ["connect"] and "Неверный код" in app.connect_error.value and prefs.data == {}
    assert "Неверный код" in app.diag_text.value


def test_a_pc_without_an_index_connects_with_a_note():
    script = Script()
    script.verify_result = (Health("GMAGC", 1, "0.5.0", False, 0), Status(False, 0, 0, False, 0, 0))
    app, _, _, _, _ = start(script=script)

    connect_manually(app)

    assert views(app) == ["camera"] and "не построен" in app.camera_title.value
    assert app.camera_message.visible and "индекс" in app.camera_message.value


def test_the_qr_scan_reads_the_link_and_connects():
    seen = []

    def reader(data):
        seen.append(data)
        return PC

    app, _, script, prefs, camera_api = start(qr_reader=reader)

    run(app.on_scan_qr(None))
    assert views(app) == ["camera"] and app.mode == "scan" and app.scan_now_button.visible
    assert not app.capture_button.visible and "QR" in app.camera_title.value
    run(app.on_scan_now(None))

    assert seen == [b"JPEG-shot"] and script.connections == [PC] and prefs.data == STORED
    assert app.mode == "shoot" and app.capture_button.visible and not app.scan_now_button.visible


def test_a_qr_scan_without_a_code_asks_to_move_closer():
    app, _, script, _, _ = start()
    run(app.on_scan_qr(None))

    run(app.on_scan_now(None))

    assert script.connections == [] and views(app) == ["camera"] and app.mode == "scan"
    assert "QR-код не найден" in app.camera_message.value and not app.scan_now_button.disabled


def test_an_unavailable_qr_reader_asks_for_manual_entry():
    def reader(data):
        raise QrUnavailable("нет zbar")

    app, _, _, _, _ = start(qr_reader=reader)
    run(app.on_scan_qr(None))

    run(app.on_scan_now(None))

    assert "вручную" in app.camera_message.value


def test_cancelling_the_scan_returns_to_the_connect_screen():
    app, _, _, _, _ = start()
    run(app.on_scan_qr(None))

    run(app.on_cancel_scan(None))

    assert views(app) == ["connect"]


def test_a_denied_camera_permission_is_shown_and_manual_entry_still_works():
    app, _, _, _, _ = start(permission=FakePermission(ph.PermissionStatus.DENIED))
    run(app.on_scan_qr(None))

    assert "разрешите" in app.camera_message.value and app.scan_now_button.disabled
    run(app.on_cancel_scan(None))
    connect_manually(app)
    assert views(app) == ["camera"] and app.capture_button.disabled and not app.gallery_button.disabled


def test_capture_sends_the_shot_and_shows_the_results():
    app, _, script, _, camera_api = start(prefs=FakePrefs(STORED))

    shoot(app)

    assert script.matches == [b"JPEG-shot"] and views(app) == ["results"]
    assert len(app.results_column.controls) == 2 and app.results_photo.visible and app.results_projection.visible
    first = texts(app.results_column.controls[0])
    assert "a.png" in first and "C:\\gobos\\vendor\\a.png" in first and "91.2%" in first and "ещё 1 файлов" in first
    assert not app.results_banner.visible and ("pause",) in camera_api.calls
    assert not app.capture_button.disabled


def test_low_confidence_and_no_projection_show_banners():
    script = Script()
    script.match_result = sample_response("low_confidence")
    app, _, _, _, _ = start(prefs=FakePrefs(STORED), script=script)
    shoot(app)
    assert app.results_banner.visible and "ненадёжно" in app.results_banner_text.value

    script.match_result = sample_response("no_projection", results=[])
    run(app.on_again(None))
    shoot(app)
    assert "переснимите" in app.results_banner_text.value and app.results_column.controls == []


def test_a_search_error_stays_on_the_camera_with_a_message():
    script = Script()
    script.match_result = ClientError(client.UNREACHABLE, "TimeoutError: timed out")
    app, _, _, _, _ = start(prefs=FakePrefs(STORED), script=script)

    shoot(app)

    assert views(app) == ["camera"] and "Нет связи с ПК" in app.camera_message.value
    assert not app.capture_button.disabled and "Нет связи" in app.diag_text.value


def test_a_changed_code_on_the_pc_sends_the_user_back_to_the_connect_screen():
    script = Script()
    script.match_result = ClientError(client.UNAUTHORIZED, "неверный код доступа")
    app, _, _, _, _ = start(prefs=FakePrefs(STORED), script=script)

    shoot(app)

    assert views(app) == ["connect"] and "Неверный код" in app.connect_error.value


def test_a_camera_failure_while_shooting_is_reported():
    app, _, script, _, camera_api = start(prefs=FakePrefs(STORED))
    camera_api.fail = "take_picture"

    shoot(app)

    assert views(app) == ["camera"] and "Не удалось снять" in app.camera_message.value and script.matches == []
    assert not app.capture_button.disabled


def test_shoot_again_returns_to_the_camera_and_resumes_the_preview():
    app, _, _, _, camera_api = start(prefs=FakePrefs(STORED))
    shoot(app)

    run(app.on_again(None))

    assert views(app) == ["camera"] and camera_api.calls[-1] == ("resume",)


def test_clicking_a_card_and_the_copy_button_copy_the_path_as_is():
    clipboard = FakeClipboard()
    app, _, _, _, _ = start(prefs=FakePrefs(STORED), clipboard=clipboard)
    shoot(app)
    card = next(c for c in walk(app.results_column.controls[0]) if isinstance(c, ft.Container) and c.data)
    button = next(c for c in walk(app.results_column.controls[0]) if isinstance(c, ft.Button))

    run(card.on_click(SimpleNamespace(control=card)))
    run(button.on_click(SimpleNamespace(control=button)))

    assert clipboard.copied == ["C:\\gobos\\vendor\\a.png", "C:\\gobos\\vendor\\a.png"]
    assert app.copy_note.visible and "C:\\gobos\\vendor\\a.png" in app.copy_note.value


def test_the_gallery_photo_is_prepared_and_sent(tmp_path):
    photo = tmp_path / "shot.jpg"
    photo.write_bytes(b"gallery-bytes")
    app, _, script, _, _ = start(prefs=FakePrefs(STORED), picker=FakePicker(files=[str(photo)]))

    run(app.on_gallery(None))

    assert script.matches == [b"gallery-bytes"] and views(app) == ["results"]


def test_an_empty_gallery_choice_does_nothing_and_a_missing_file_is_reported():
    app, _, script, _, _ = start(prefs=FakePrefs(STORED))
    run(app.on_gallery(None))
    assert script.matches == [] and views(app) == ["camera"]

    app.picker.files = [str(Path("no-such-dir") / "missing.jpg")]
    run(app.on_gallery(None))
    assert "Не удалось подготовить фото" in app.camera_message.value and script.matches == []


def test_a_huge_gallery_file_is_shrunk_before_sending(tmp_path, monkeypatch):
    photo = tmp_path / "big.jpg"
    photo.write_bytes(b"huge")
    monkeypatch.setattr("gmagc_mobile.app.prepare_upload", lambda data: b"shrunk")
    app, _, script, _, _ = start(prefs=FakePrefs(STORED), picker=FakePicker(files=[str(photo)]))

    run(app.on_gallery(None))

    assert script.matches == [b"shrunk"]


def test_change_pc_forgets_the_connection():
    app, _, _, prefs, _ = start(prefs=FakePrefs(STORED))

    run(app.on_change_pc(None))

    assert views(app) == ["connect"] and prefs.data == {} and app.client is None and app.connection is None


def test_demo_variables_connect_and_search_at_startup(tmp_path, monkeypatch):
    photo = tmp_path / "demo.jpg"
    photo.write_bytes(b"demo-photo")
    monkeypatch.setenv("GMAGC_MOBILE_DEMO_LINK", "gmagc://connect?host=192.168.1.121&port=8765&code=ZBZ36YNK")
    monkeypatch.setenv("GMAGC_MOBILE_DEMO_PHOTO", str(photo))

    app, _, script, _, _ = start()

    assert script.connections == [PC] and script.matches == [b"demo-photo"] and views(app) == ["results"]


def test_build_page_wires_services_and_starts(monkeypatch):
    page = StubPage()
    script = Script()
    app = asyncio.run(
        build_page(
            page,
            prefs=FakePrefs(STORED),
            permission=FakePermission(),
            camera_control=ft.Container(),
            controller=CameraController(FakeCameraApi(), FakePermission(), settle_seconds=0),
            picker=FakePicker(),
            clipboard=FakeClipboard(),
            client_factory=script.factory,
        )
    )

    assert page.title == f"{NAME} {VERSION}" and script.connections == [PC] and views(app) == ["camera"]
    assert len(page.services) == 4
```

```python
# path: tests/mobile/test_mobile_camera_ui.py
import asyncio
from types import SimpleNamespace

import flet as ft
import flet_camera as fc

from gmagc_mobile.app import MobileApp
from gmagc_mobile.camera import CameraController
from gmagc_mobile.store import ConnectionStore
from tests.fakes import FakeClipboard, FakePicker, StubPage
from tests.fakes_mobile import FakeCameraApi, FakePermission, FakePrefs, Script


def make_running_app(camera_api=None):
    camera_api = camera_api or FakeCameraApi(min_zoom=1.0, max_zoom=5.0)
    controller = CameraController(camera_api, FakePermission(), settle_seconds=0)
    prefs = FakePrefs({"gmagc.host": "192.168.1.121", "gmagc.port": 8765, "gmagc.code": "ZBZ36YNK"})
    app = MobileApp(
        StubPage(),
        ConnectionStore(prefs),
        controller,
        preview=ft.Container(),
        picker=FakePicker(),
        clipboard=FakeClipboard(),
        client_factory=Script().factory,
        marker_seconds=0,
    )
    app.build()
    asyncio.run(app.start())
    return app, camera_api


def run(coroutine):
    return asyncio.run(coroutine)


def zoom_calls(api):
    return [call[1] for call in api.calls if call[0] == "zoom"]


def test_the_slider_range_follows_the_camera_after_start():
    app, _ = make_running_app()

    assert (app.zoom_slider.min, app.zoom_slider.max, app.zoom_slider.value) == (1.0, 5.0, 1.0)
    assert not app.zoom_slider.disabled and app.zoom_label.value == "×1.0"


def test_a_camera_without_zoom_disables_the_zoom_controls():
    app, _ = make_running_app(FakeCameraApi(min_zoom=1.0, max_zoom=1.0))

    assert app.zoom_slider.disabled and app.zoom_in_button.disabled and app.zoom_out_button.disabled


def test_moving_the_slider_zooms_the_camera_and_updates_the_label():
    app, api = make_running_app()

    run(app.on_zoom_slider(SimpleNamespace(control=SimpleNamespace(value=3.25))))

    assert zoom_calls(api) == [3.25] and app.zoom_label.value == "×3.2" and app.zoom_slider.value == 3.25


def test_plus_and_minus_buttons_step_the_zoom_within_the_range():
    app, api = make_running_app()

    run(app.on_zoom_in(None))
    run(app.on_zoom_in(None))
    run(app.on_zoom_out(None))
    for _ in range(20):
        run(app.on_zoom_in(None))

    assert zoom_calls(api)[:3] == [1.5, 2.0, 1.5] and zoom_calls(api)[-1] == 5.0
    assert app.zoom_label.value == "×5.0"


def test_pinching_scales_the_zoom_from_the_value_at_the_start():
    app, api = make_running_app()
    run(app.on_zoom_slider(SimpleNamespace(control=SimpleNamespace(value=2.0))))
    api.calls.clear()

    app.on_scale_start(None)
    run(app.on_scale_update(SimpleNamespace(pointer_count=2, scale=1.5)))
    run(app.on_scale_update(SimpleNamespace(pointer_count=2, scale=2.0)))
    run(app.on_scale_update(SimpleNamespace(pointer_count=2, scale=10.0)))

    assert zoom_calls(api) == [3.0, 4.0, 5.0]


def test_a_one_finger_drag_does_not_change_the_zoom():
    app, api = make_running_app()

    app.on_scale_start(None)
    run(app.on_scale_update(SimpleNamespace(pointer_count=1, scale=3.0)))

    assert zoom_calls(api) == []


def test_tapping_the_preview_focuses_at_the_normalized_point_and_shows_then_hides_the_marker():
    app, api = make_running_app()
    app.on_preview_size(SimpleNamespace(width=400.0, height=800.0))

    run(app.on_preview_tap(SimpleNamespace(local_position=SimpleNamespace(x=100.0, y=400.0))))

    assert ("focus_point", (0.25, 0.5)) in api.calls and ("exposure_point", (0.25, 0.5)) in api.calls
    assert not app.marker.visible and (app.marker.left, app.marker.top) == (100.0 - 32, 400.0 - 32)


def test_the_marker_stays_visible_while_the_focus_call_is_running():
    app, api = make_running_app()
    app.on_preview_size(SimpleNamespace(width=400.0, height=800.0))
    seen = []
    original = api.set_focus_point

    async def spying(point):
        seen.append(app.marker.visible)
        await original(point)

    api.set_focus_point = spying

    run(app.on_preview_tap(SimpleNamespace(local_position=SimpleNamespace(x=10.0, y=10.0))))

    assert seen == [True]


def test_a_tap_before_the_preview_size_is_known_does_not_touch_the_camera():
    app, api = make_running_app()
    api.calls.clear()

    run(app.on_preview_tap(SimpleNamespace(local_position=SimpleNamespace(x=10.0, y=10.0))))

    assert api.calls == []


def test_a_camera_without_point_focus_shows_a_message():
    app, api = make_running_app()
    app.on_preview_size(SimpleNamespace(width=400.0, height=800.0))
    api.fail = "set_focus_point"

    run(app.on_preview_tap(SimpleNamespace(local_position=SimpleNamespace(x=10.0, y=10.0))))

    assert app.camera_message.visible and "Фокус по точке недоступен" in app.camera_message.value


def test_the_focus_button_locks_and_unlocks_the_focus_and_changes_its_label():
    app, api = make_running_app()
    assert app.focus_text.value == "Фокус: авто"

    run(app.on_focus_lock(None))
    assert app.focus_text.value == "Фокус: зафиксирован"
    run(app.on_focus_lock(None))
    assert app.focus_text.value == "Фокус: авто"

    assert [c for c in api.calls if c[0] == "focus_mode"] == [
        ("focus_mode", fc.FocusMode.LOCKED),
        ("focus_mode", fc.FocusMode.AUTO),
    ]


def test_the_preview_is_wrapped_in_a_gesture_detector_with_the_handlers():
    app, _ = make_running_app()

    assert app.gesture.on_tap_down == app.on_preview_tap and app.gesture.on_scale_update == app.on_scale_update
    assert app.gesture.on_scale_start == app.on_scale_start and isinstance(app.gesture, ft.GestureDetector)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/mobile/test_mobile_app.py tests/mobile/test_mobile_camera_ui.py -q`
Expected: FAIL (в `app.py` каркас без `MobileApp`).

- [ ] **Step 3: Write the implementation**

```python
# path: apps/mobile/src/gmagc_mobile/app.py
"""Экран Android-приложения: подключение к ПК, камера с приближением и фокусом, результаты поиска."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from pathlib import Path

import flet as ft
import flet_camera as fc
import flet_permission_handler as ph

from gmagc_common.protocol import (
    Connection,
    MatchResponse,
    ResultItem,
    is_valid_code,
    normalize_code,
    parse_address,
    parse_link,
)
from gmagc_mobile.about import AUTHOR, NAME, VERSION
from gmagc_mobile.camera import CameraController
from gmagc_mobile.client import UNAUTHORIZED, ClientError, GmagcClient
from gmagc_mobile.imaging import prepare_upload
from gmagc_mobile.qr import QrUnavailable, connection_from_qr
from gmagc_mobile.store import ConnectionStore
from gmagc_mobile.texts import NO_INDEX_NOTE, error_text, outcome_message, score_text, status_line, zoom_text

MODE_SHOOT = "shoot"
MODE_SCAN = "scan"
ZOOM_STEP = 0.5
MARKER_SIZE = 64
SCAN_HINT = "Наведите камеру на QR-код в приложении на ПК (приближение и касание для фокуса помогают) и нажмите «Считать QR»"


class MobileApp:
    def __init__(
        self,
        page: ft.Page,
        store: ConnectionStore,
        camera: CameraController,
        preview: ft.Control | None = None,
        picker=None,
        clipboard=None,
        client_factory: Callable[[Connection], GmagcClient] = GmagcClient,
        qr_reader: Callable[[bytes], Connection | None] = connection_from_qr,
        marker_seconds: float = 1.5,
    ):
        self.page = page
        self.store = store
        self.camera = camera
        self.preview = preview if preview is not None else camera.camera
        self.picker = picker or ft.FilePicker()
        self.clipboard = clipboard or ft.Clipboard()
        self.client_factory = client_factory
        self.qr_reader = qr_reader
        self.marker_seconds = marker_seconds
        self.connection: Connection | None = None
        self.client: GmagcClient | None = None
        self.mode = MODE_SHOOT
        self.status_text = ""
        self.last_error = ""
        self._busy = False
        self._preview_size = (0.0, 0.0)
        self._pinch_start = 1.0
        self._zooming = False
        self._marker_token = 0

        # подключение
        self.address_field = ft.TextField(label="Адрес ПК", hint_text="192.168.1.5 или 192.168.1.5:8765")
        self.code_field = ft.TextField(
            label="Код доступа",
            hint_text="ABCD-2345",
            capitalization=ft.TextCapitalization.CHARACTERS,
            max_length=9,
            on_submit=self.on_connect,
        )
        self.scan_button = ft.Button("Считать QR-код с ПК", on_click=self.on_scan_qr)
        self.connect_button = ft.Button("Подключиться", on_click=self.on_connect)
        self.connect_busy = ft.ProgressRing(visible=False, width=24, height=24)
        self.connect_error = ft.Text("", color=ft.Colors.RED_700, visible=False, selectable=True)
        self.connect_view = ft.Column(
            [
                ft.Text(NAME, size=28, weight=ft.FontWeight.BOLD),
                ft.Text("Поиск гобо по фото проекции. Подключитесь к ПК с GMAGC в той же сети Wi-Fi."),
                self.scan_button,
                ft.Text("или введите вручную (адрес и код показаны в приложении на ПК):", size=12),
                self.address_field,
                self.code_field,
                ft.Row([self.connect_button, self.connect_busy], spacing=12),
                self.connect_error,
                ft.Text(f"Версия {VERSION}. Автор: {AUTHOR}", size=12),
            ],
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
            visible=True,
            expand=True,
        )

        # камера
        self.camera_title = ft.Text("", size=14)
        self.marker = ft.Container(
            width=MARKER_SIZE,
            height=MARKER_SIZE,
            border=ft.Border.all(2, ft.Colors.YELLOW_400),
            border_radius=MARKER_SIZE // 2,
            left=0,
            top=0,
            visible=False,
        )
        self.zoom_slider = ft.Slider(min=1, max=2, value=1, disabled=True, on_change=self.on_zoom_slider, expand=True)
        self.zoom_label = ft.Text("×1.0")
        self.zoom_out_button = ft.IconButton(icon=ft.Icons.ZOOM_OUT, disabled=True, on_click=self.on_zoom_out)
        self.zoom_in_button = ft.IconButton(icon=ft.Icons.ZOOM_IN, disabled=True, on_click=self.on_zoom_in)
        self.focus_text = ft.Text("Фокус: авто")
        self.focus_button = ft.TextButton(content=self.focus_text, on_click=self.on_focus_lock)
        self.capture_button = ft.Button("Снять", on_click=self.on_capture)
        self.gallery_button = ft.Button("Из галереи", on_click=self.on_gallery)
        self.scan_now_button = ft.Button("Считать QR", on_click=self.on_scan_now, visible=False)
        self.cancel_scan_button = ft.Button("Отмена", on_click=self.on_cancel_scan, visible=False)
        self.change_pc_button = ft.TextButton(content=ft.Text("Сменить ПК", size=12), on_click=self.on_change_pc)
        self.camera_message = ft.Text("", visible=False, selectable=True)
        self.busy_ring = ft.ProgressRing(visible=False, width=24, height=24)
        self.gesture = ft.GestureDetector(
            content=ft.Stack([self.preview, self.marker], expand=True),
            on_tap_down=self.on_preview_tap,
            on_scale_start=self.on_scale_start,
            on_scale_update=self.on_scale_update,
            expand=True,
        )
        if hasattr(self.preview, "on_size_change"):
            self.preview.on_size_change = self.on_preview_size
        self.camera_view = ft.Column(
            [
                ft.Row([self.camera_title, self.change_pc_button], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                self.gesture,
                ft.Row([self.zoom_out_button, self.zoom_slider, self.zoom_in_button, self.zoom_label]),
                self.focus_button,
                self.camera_message,
                ft.Row(
                    [self.capture_button, self.gallery_button, self.scan_now_button, self.cancel_scan_button, self.busy_ring],
                    spacing=8,
                    wrap=True,
                ),
            ],
            spacing=6,
            visible=False,
            expand=True,
        )

        # результаты
        self.results_banner_text = ft.Text(color=ft.Colors.BLACK)
        self.results_banner = ft.Container(self.results_banner_text, padding=10, border_radius=6, visible=False)
        self.results_photo = ft.Column(visible=False, spacing=4)
        self.results_projection = ft.Column(visible=False, spacing=4)
        self.copy_note = ft.Text("", size=12, visible=False, selectable=True)
        self.results_column = ft.Column(spacing=8)
        self.again_button = ft.Button("Снять ещё", on_click=self.on_again)
        self.results_view = ft.Column(
            [
                self.again_button,
                self.results_banner,
                ft.Row([self.results_photo, self.results_projection], spacing=12, vertical_alignment=ft.CrossAxisAlignment.START),
                ft.Text("Результаты (нажмите на карточку, чтобы скопировать путь)", size=14, weight=ft.FontWeight.BOLD),
                self.copy_note,
                self.results_column,
            ],
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
            visible=False,
            expand=True,
        )

        self.diag_text = ft.Text("", size=10, color=ft.Colors.GREY_600, selectable=True, visible=False)

    # ---- построение и запуск -----------------------------------------------
    def build(self) -> None:
        self.page.add(
            ft.SafeArea(
                ft.Column([self.connect_view, self.camera_view, self.results_view, self.diag_text], expand=True),
                expand=True,
            )
        )

    async def start(self) -> None:
        demo_link = os.environ.get("GMAGC_MOBILE_DEMO_LINK")
        if demo_link:
            await self._demo(demo_link, os.environ.get("GMAGC_MOBILE_DEMO_PHOTO"))
            return
        stored = await self.store.load()
        if stored is None:
            self._show_connect()
            return
        self._fill(stored)
        await self._connect(stored)

    async def _demo(self, link: str, photo: str | None) -> None:
        """Отладка на ПК: GMAGC_MOBILE_DEMO_LINK подключает, GMAGC_MOBILE_DEMO_PHOTO сразу ищет."""
        connection = parse_link(link)
        if connection is None or not await self._connect(connection):
            return
        if photo:
            self._set_busy(True)
            await self._search(Path(photo).read_bytes())

    # ---- вид -----------------------------------------------------------------
    def _show(self, name: str) -> None:
        self.connect_view.visible = name == "connect"
        self.camera_view.visible = name == "camera"
        self.results_view.visible = name == "results"
        self.page.update()

    def _remember(self, text: str) -> None:
        self.last_error = text
        self.diag_text.value = f"Последняя ошибка: {text}"
        self.diag_text.visible = True

    def _show_connect(self, error: str | None = None) -> None:
        self.connect_error.value = error or ""
        self.connect_error.visible = bool(error)
        if error:
            self._remember(error)
        self._show("connect")

    def _show_camera(self, mode: str, note: str | None = None) -> None:
        self.mode = mode
        scanning = mode == MODE_SCAN
        self.camera_title.value = SCAN_HINT if scanning else self.status_text
        self.capture_button.visible = self.gallery_button.visible = not scanning
        self.scan_now_button.visible = self.cancel_scan_button.visible = scanning
        self.change_pc_button.visible = not scanning
        self.camera_message.value = note or ""
        self.camera_message.visible = bool(note)
        self._show("camera")

    def _camera_note(self, text: str) -> None:
        self.camera_message.value = text
        self.camera_message.visible = True
        self._remember(text)
        self.page.update()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for button in (self.capture_button, self.gallery_button, self.scan_now_button, self.connect_button, self.scan_button):
            button.disabled = busy
        if not busy and not self.camera.ready:
            self.capture_button.disabled = self.scan_now_button.disabled = True
        self.busy_ring.visible = self.connect_busy.visible = busy
        self.page.update()

    def _fill(self, connection: Connection) -> None:
        self.address_field.value = f"{connection.host}:{connection.port}"
        self.code_field.value = connection.code

    def _sync_zoom(self) -> None:
        usable = self.camera.ready and self.camera.max_zoom > self.camera.min_zoom
        self.zoom_slider.min = self.camera.min_zoom
        self.zoom_slider.max = self.camera.max_zoom if usable else self.camera.min_zoom + 1
        self.zoom_slider.value = self.camera.zoom
        self.zoom_label.value = zoom_text(self.camera.zoom)
        self.zoom_slider.disabled = self.zoom_in_button.disabled = self.zoom_out_button.disabled = not usable

    # ---- подключение ---------------------------------------------------------
    async def on_connect(self, _event) -> None:
        if self._busy:
            return
        address = parse_address(self.address_field.value or "")
        if address is None:
            self._show_connect("Введите адрес ПК, например 192.168.1.5 или 192.168.1.5:8765")
            return
        code = self.code_field.value or ""
        if not is_valid_code(code):
            self._show_connect("Код доступа состоит из 8 символов (буквы и цифры), он показан в приложении на ПК")
            return
        await self._connect(Connection(address[0], address[1], normalize_code(code)))

    async def _connect(self, connection: Connection) -> bool:
        self._set_busy(True)
        client = self.client_factory(connection)
        try:
            _, status = await asyncio.to_thread(client.verify)
        except ClientError as error:
            self._set_busy(False)
            self._show_connect(error_text(error))
            return False
        except Exception as error:  # noqa: BLE001 - подключение обязано показать причину
            self._set_busy(False)
            self._show_connect(f"Ошибка подключения: {error}")
            return False
        self.connection, self.client = connection, client
        await self.store.save(connection)
        self._fill(connection)
        self.status_text = status_line(connection, status)
        self._set_busy(False)
        self._show_camera(MODE_SHOOT, note=None if status.indexed else NO_INDEX_NOTE)
        await self._ensure_camera()
        return True

    async def _ensure_camera(self) -> None:
        if self.camera.ready:
            await self.camera.resume()
        else:
            await self.camera.start()
            if not self.camera.ready:
                self._camera_note(self.camera.error or "Камера недоступна")
        self._sync_zoom()
        self._set_busy(self._busy)

    async def on_change_pc(self, _event) -> None:
        await self.store.clear()
        self.connection = self.client = None
        self._show_connect()

    # ---- QR ------------------------------------------------------------------
    async def on_scan_qr(self, _event) -> None:
        self._show_camera(MODE_SCAN)
        await self._ensure_camera()

    async def on_cancel_scan(self, _event) -> None:
        self._show_connect()

    async def on_scan_now(self, _event) -> None:
        if self._busy or not self.camera.ready:
            return
        self._set_busy(True)
        connection = None
        failure = ""
        try:
            data = await self.camera.take_picture()
            connection = await asyncio.to_thread(self.qr_reader, data)
        except QrUnavailable:
            failure = "Чтение QR недоступно на этом телефоне: введите адрес и код вручную."
        except Exception as error:  # noqa: BLE001
            failure = f"Ошибка камеры: {error}"
        self._set_busy(False)
        if connection is not None:
            await self._connect(connection)
            return
        self._camera_note(
            failure
            or "QR-код не найден. Поднесите камеру ближе (приближение и касание для фокуса помогают): "
            "код должен быть целиком в кадре и чётким."
        )

    # ---- съёмка и поиск --------------------------------------------------------
    async def on_capture(self, _event) -> None:
        if self._busy or not self.camera.ready:
            return
        self._set_busy(True)
        try:
            data = await self.camera.take_picture()
        except Exception as error:  # noqa: BLE001
            self._set_busy(False)
            self._camera_note(f"Не удалось снять: {error}")
            return
        await self._search(data)

    async def on_gallery(self, _event) -> None:
        if self._busy:
            return
        files = await self.picker.pick_files(dialog_title="Фото проекции", file_type=ft.FilePickerFileType.IMAGE)
        if not files:
            return
        picked = files[0]
        try:
            raw = picked.bytes if picked.bytes else Path(picked.path).read_bytes()
            data = await asyncio.to_thread(prepare_upload, raw)
        except (OSError, ValueError, TypeError) as error:
            self._camera_note(f"Не удалось подготовить фото: {error}")
            return
        self._set_busy(True)
        await self._search(data)

    async def _search(self, data: bytes) -> None:
        """Отправляет фото на ПК (вызывающий уже включил busy) и показывает результат или ошибку."""
        response: MatchResponse | None = None
        failure: ClientError | None = None
        message = ""
        try:
            response = await asyncio.to_thread(self.client.match, data)
        except ClientError as error:
            failure = error
        except Exception as error:  # noqa: BLE001
            message = f"Ошибка: {error}"
        self._set_busy(False)
        if failure is not None:
            if failure.kind == UNAUTHORIZED:
                self._show_connect(error_text(failure))
            else:
                self._camera_note(error_text(failure))
            return
        if response is None:
            self._camera_note(message or "Ошибка поиска")
            return
        await self._show_results(data, response)

    async def _show_results(self, photo: bytes, response: MatchResponse) -> None:
        await self.camera.pause()
        banner = outcome_message(response.outcome)
        self.results_banner_text.value = banner or ""
        self.results_banner.bgcolor = ft.Colors.RED_100 if response.outcome == "no_projection" else ft.Colors.AMBER_100
        self.results_banner.visible = bool(banner)
        self.results_photo.controls = [ft.Text("Фото"), ft.Image(src=photo, width=160, height=120, fit=ft.BoxFit.CONTAIN)]
        self.results_photo.visible = True
        self.results_projection.controls = [
            ft.Text("Найденная проекция"),
            ft.Image(src=response.projection_png or b"", width=120, height=120, fit=ft.BoxFit.CONTAIN),
        ]
        self.results_projection.visible = bool(response.projection_png)
        self.results_column.controls = [self._result_card(item) for item in response.results]
        self.copy_note.visible = False
        self._show("results")

    def _result_card(self, item: ResultItem) -> ft.Card:
        details: list[ft.Control] = [
            ft.Text(item.name, weight=ft.FontWeight.BOLD),
            ft.Text(item.path, size=12, selectable=False),
            ft.Text(score_text(item.score)),
        ]
        if item.copies:
            details.append(ft.Text(f"ещё {len(item.copies)} файлов", tooltip="\n".join(item.copies)))
        details.append(ft.Button("Копировать путь", data=item.path, on_click=self.on_copy_click))
        return ft.Card(
            ft.Container(
                ft.Row(
                    [
                        ft.Image(src=item.thumbnail_png, width=80, height=80, fit=ft.BoxFit.CONTAIN),
                        ft.Column(details, spacing=2, expand=True),
                    ],
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                padding=10,
                ink=True,
                data=item.path,
                on_click=self.on_card_click,
            )
        )

    async def on_again(self, _event) -> None:
        self._show_camera(MODE_SHOOT)
        await self.camera.resume()

    async def on_card_click(self, event) -> None:
        await self.copy_path(event.control.data)

    async def on_copy_click(self, event) -> None:
        await self.copy_path(event.control.data)

    async def copy_path(self, path: str) -> None:
        """Копирует путь файла на ПК (как пришёл в ответе, вместе с именем файла) в буфер обмена."""
        await self.clipboard.set(path)
        self.copy_note.value = f"Путь скопирован: {path}"
        self.copy_note.visible = True
        self.page.update()

    # ---- приближение и фокус -----------------------------------------------------
    async def _zoom_to(self, value: float) -> None:
        zoom = await self.camera.set_zoom(value)
        self.zoom_slider.value = zoom
        self.zoom_label.value = zoom_text(zoom)
        self.page.update()

    async def on_zoom_slider(self, event) -> None:
        await self._zoom_to(float(event.control.value))

    async def on_zoom_in(self, _event) -> None:
        await self._zoom_to(self.camera.zoom + ZOOM_STEP)

    async def on_zoom_out(self, _event) -> None:
        await self._zoom_to(self.camera.zoom - ZOOM_STEP)

    def on_scale_start(self, _event) -> None:
        self._pinch_start = self.camera.zoom

    async def on_scale_update(self, event) -> None:
        if event.pointer_count < 2 or self._zooming:
            return
        self._zooming = True
        try:
            await self._zoom_to(self._pinch_start * event.scale)
        finally:
            self._zooming = False

    def on_preview_size(self, event) -> None:
        self._preview_size = (float(event.width), float(event.height))

    async def on_preview_tap(self, event) -> None:
        """Касание кадра наводит фокус и замер экспозиции в эту точку, на кадре мигает метка."""
        width, height = self._preview_size
        if not self.camera.ready or width <= 0 or height <= 0:
            return
        x, y = float(event.local_position.x), float(event.local_position.y)
        self._marker_token += 1
        token = self._marker_token
        self.marker.left, self.marker.top = x - MARKER_SIZE / 2, y - MARKER_SIZE / 2
        self.marker.visible = True
        self.page.update()
        if not await self.camera.focus_at(x, y, width, height):
            self._camera_note(self.camera.error or "Фокус по точке недоступен")
        await asyncio.sleep(self.marker_seconds)
        if token == self._marker_token:
            self.marker.visible = False
            self.page.update()

    async def on_focus_lock(self, _event) -> None:
        locked = await self.camera.toggle_focus_lock()
        self.focus_text.value = "Фокус: зафиксирован" if locked else "Фокус: авто"
        self.page.update()


async def build_page(page: ft.Page, **services) -> MobileApp:
    """Собирает экран из служб Flet (в тестах их подменяют) и запускает подключение."""
    page.title = f"{NAME} {VERSION}"
    prefs = services.pop("prefs", None) or ft.SharedPreferences()
    permission = services.pop("permission", None) or ph.PermissionHandler()
    camera_control = services.pop("camera_control", None) or fc.Camera(expand=True, preview_enabled=True)
    controller = services.pop("controller", None) or CameraController(camera_control, permission)
    app = MobileApp(page, ConnectionStore(prefs), controller, preview=camera_control, **services)
    page.services.extend([prefs, permission, app.picker, app.clipboard])
    app.build()
    await app.start()
    return app
```

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest tests/mobile -q`
Expected: PASS. Если тест `test_zoom_text` (проверка округления `2.55`) окажется нестабильным из-за округления, оставить только `zoom_text(1) == "×1.0"`.

- [ ] **Step 5: Lint and commit**

```bash
.venv/Scripts/python.exe -m ruff check --fix . && .venv/Scripts/python.exe -m pytest -q
git add apps/mobile/src/gmagc_mobile tests
git commit -m "feat: Android screen with connection, camera zoom and focus, and results" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---
### Task 6: Настройки сборки Android, живая проверка, README, версия 0.5.0, PR и релиз

**Files:**
- Modify: `apps/mobile/pyproject.toml`, `apps/mobile/src/gmagc_mobile/about.py`, `apps/desktop/src/gmagc_desktop/about.py`, `apps/desktop/pyproject.toml`, `README.md`, `tests/mobile/` (тест конфигурации сборки)
- Test: `tests/mobile/test_android_config.py`

- [ ] **Step 1: Write the failing test of the build configuration**

```python
# path: tests/mobile/test_android_config.py
import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[2] / "apps" / "mobile" / "pyproject.toml"


def load():
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def test_the_camera_permission_is_requested_for_the_android_manifest():
    assert "camera" in load()["tool"]["flet"]["permissions"]


def test_cleartext_http_is_allowed_for_the_local_network():
    application = load()["tool"]["flet"]["android"]["manifest_application"]

    assert application["usesCleartextTraffic"] == "true"


def test_the_qr_and_image_libraries_are_dependencies_and_flet_stays_pinned():
    dependencies = " ".join(load()["project"]["dependencies"])

    assert "pyzbar" in dependencies and "Pillow" in dependencies
    assert "flet==1.0.0" in dependencies and "flet-camera==1.0.0" in dependencies
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/mobile/test_android_config.py -q`
Expected: FAIL (нет ключей `permissions`, `manifest_application`, зависимостей).

- [ ] **Step 3: Update the build configuration and the version**

В `apps/mobile/pyproject.toml`: версия `0.5.0`; в `dependencies` добавить `"pyzbar",` и `"Pillow",`; в таблицу `[tool.flet]` добавить `permissions = ["camera"]  # android.permission.CAMERA в манифесте`; после `[tool.flet.app]` добавить:

```toml
[tool.flet.android.manifest_application]
usesCleartextTraffic = "true"  # телефон общается с ПК по HTTP в локальной сети
```

`VERSION = "0.5.0"` в обоих `about.py`, `version = "0.5.0"` в обоих `pyproject.toml`.

- [ ] **Step 4: Run the whole suite**

Run: `.venv\Scripts\python.exe -m pytest -q` и `.venv\Scripts\python.exe -m ruff check .`
Expected: все тесты проходят, линтер чист.

- [ ] **Step 5: Commit the configuration**

```bash
git add apps tests
git commit -m "build: camera permission, cleartext HTTP and QR dependencies for the Android build" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

- [ ] **Step 6: Live check of the mobile app on Windows against the real PC app**

1. Установить в окружение сборки Flet зависимости мобильного приложения: `$env:USERPROFILE\.venv312\Scripts\python.exe -m pip install flet==1.0.0 flet-camera==1.0.0 flet-permission-handler==1.0.0 pyzbar Pillow`.
2. Собрать ПК-приложение (`.\scripts\build_windows.ps1`) и запустить его с `GMAGC_DATA_DIR=$env:TEMP\gmagc_live`, `GMAGC_DEMO_LIBRARY=C:\Users\ANDYBUM\GMAGC\gobos`, `GMAGC_DEMO_PHOTO=<photo_13>`; дождаться `index.npz`; прочитать `access_code` из `settings.json`, адрес ПК из `lan_addresses()`.
3. Запустить мобильное приложение как окно Windows: `$env:GMAGC_MOBILE_DEMO_LINK="gmagc://connect?host=<адрес>&port=8765&code=<код>"; $env:GMAGC_MOBILE_DEMO_PHOTO=<photo_14>; & $env:USERPROFILE\.venv312\Scripts\flet.exe run apps\mobile\src\main.py`. Снять окно `scripts\capture_window.ps1` (процесс `flet`): виден результат поиска с карточками; в окне ПК появился запрос с телефона.
4. Без демо-переменных: экран подключения, ввод адреса и кода вручную (клики через `user32`), неверный код (сообщение), верный (переход к камере), кнопка «Из галереи» не автоматизируется (системный диалог), поэтому проверяется демо-переменной.
5. Клик по карточке, `Get-Clipboard`: в буфере путь файла на ПК с именем.
6. Закрыть оба приложения.

Что не проверяется без телефона: камера, приближение, фокус, чтение QR и сеть на реальном Android.

- [ ] **Step 7: README**

Обновить README: статус (v0.5.0, Android-клиент), раздел «Android-приложение» (подключение по QR или адресу и коду, камера с приближением: ползунок, «+»/«−», щипок; фокус: касание по кадру, «Фокус: авто/зафиксирован»; «Из галереи»; результаты, клик по карточке или «Копировать путь»; что нужно: телефон и ПК в одной Wi-Fi, разрешить камеру и доступ GMAGC в брандмауэре Windows; установка APK: разрешить неизвестные источники), строка про `permissions = ["camera"]` и `usesCleartextTraffic` в разделе про сборки, число тестов, структура (`apps/mobile/src/gmagc_mobile/`, копия `gmagc_common`).

- [ ] **Step 8: Commit, push, PR, CI, APK manifest check, merge, tag, release**

```bash
git add -A
git commit -m "docs: README and version 0.5.0 for the Android client" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
git push -u origin feat/android-client
gh pr create --title "Android-клиент (этап 5)" --body-file <файл описания> --base main
```

Дождаться зелёных проверок (тесты на трёх ОС, сборки Windows/macOS/Android). Скачать APK из артефакта запуска `Build Android` этого PR (`gh run download <id> -n GMAGC-android`) и разобрать бинарный манифест (`pyaxmlparser`): должны быть `android.permission.CAMERA`, `android.permission.INTERNET` и `usesCleartextTraffic="true"`. Затем `gh pr merge --squash --delete-branch`, тег `v0.5.0`, релизные сборки, проверка контрольных сумм и запуска Windows-архива, заметки релиза (`gh release edit`), обновление памяти проекта.
