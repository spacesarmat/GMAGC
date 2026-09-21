# GMAGC: автообновление (0.6.0). План реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** приложения сами узнают о новой версии на GitHub Releases и предлагают обновиться: ПК ставит обновление по кнопке (загрузка, проверка суммы, замена файлов помощником, перезапуск), Android открывает загрузку APK.

**Architecture:** Общая логика (разбор релиза, версии, выбор файла, безопасное открытие адреса) в `gmagc_common/updates.py` на стандартной библиотеке. ПК: `gmagc_desktop/update/` (`installer.py` загрузка/распаковка/скрипт-помощник, `manager.py` проверка и установка без Flet) и полоса обновления в экране. Android: `gmagc_mobile/updates.py` и полоса со ссылкой на загрузку. Источник подменяется `GMAGC_UPDATE_URL` (только адрес на локальный хост) для тестов и живой проверки.

**Tech Stack:** Python 3.12, стандартная библиотека (`urllib`, `zipfile`, `hashlib`, `subprocess`), Flet 1.0.0, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-09-21-gmagc-auto-update-design.md`

## Global Constraints

- Новых зависимостей нет. `gmagc_common` остаётся на стандартной библиотеке, копии в `apps/*/src/gmagc_common` синхронизируются `python scripts/sync_common.py`.
- Только HTTPS и хосты `github.com`, `*.github.com`, `*.githubusercontent.com` (проверяется каждый переход); исключение: адрес из `GMAGC_UPDATE_URL`, если его хост `127.0.0.1`, `localhost` или `::1`.
- Обновление ПК ставится только по нажатию «Обновить»; контрольная сумма SHA-256 берётся из `.sha256` того же релиза; без суммы или при несовпадении файл не ставится.
- Сеть только для проверки и загрузки; ошибка или отсутствие сети при фоновой проверке ничего не показывает; приложение остаётся полностью офлайн.
- Данные пользователя (настройки, индекс) лежат вне папки приложения и обновлением не трогаются. Прежняя версия остаётся рядом как `<папка>.previous`.
- Тесты не ходят в интернет: только локальный поддельный сервер (`tests/updates_stub.py`) и заглушки.
- Слои `service/`, `update/`, `server/` не импортируют Flet; строки интерфейса и комментарии на русском; автор `@ANDY_BUM` остаётся на экранах.
- Коммиты: `git commit -m "<тип>: <описание>" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"`. Работа на ветке `feat/auto-update`, в `main` только через Pull Request с зелёными проверками.
- Запуск тестов: `.venv\Scripts\python.exe -m pytest -q`, линтер: `.venv\Scripts\python.exe -m ruff check .`.
- Имена тестовых модулей уникальны на весь `tests/` (нет `__init__.py`).

---

### Task 1: Общая логика обновлений `gmagc_common/updates.py`

**Files:**
- Create: `packages/common/gmagc_common/updates.py`, `tests/updates_stub.py`, `apps/desktop/src/gmagc_common/updates.py` и `apps/mobile/src/gmagc_common/updates.py` (копии скриптом)
- Test: `tests/common/test_updates.py`

**Interfaces:**
- Produces (`gmagc_common.updates`): `REPO`, `RELEASES_API`, `RELEASES_PAGE`, `CHECK_INTERVAL_SECONDS`, `UPDATE_URL_ENV`; `UpdateCheckError(Exception)` (текст для показа); `parse_version(text) -> tuple[int, int, int] | None`; `is_newer(candidate, current) -> bool`; `Asset(name, url, size)`; `ReleaseInfo(version, tag, notes, page_url, assets)` c `from_api(dict) -> ReleaseInfo | None`; `pick_assets(release, platform) -> tuple[Asset, Asset | None] | None` (`platform` из `windows`, `macos`, `android`); `parse_sha256(text) -> str | None`; `is_allowed_url(url, allow_local=False) -> bool`; `update_source() -> tuple[str, bool]` (адрес и «локальный ли»); `open_url(url, *, allow_local=False, timeout=8.0, user_agent="GMAGC")` (ответ `urllib`, переходы проверяются); `fetch_latest(current_version, timeout=8.0, url=None, allow_local=False) -> ReleaseInfo | None` (`None`, если новой версии нет); `check_due(last_check, now, interval=CHECK_INTERVAL_SECONDS) -> bool`.
- Produces (`tests/updates_stub.py`): `stub_server(routes) -> контекст с базовым адресом`, `release_json(version, base, platforms=("windows", "macos", "android"), **flags) -> dict`.

- [ ] **Step 1: Write the failing tests and the stub server**

```python
# path: tests/updates_stub.py
"""Поддельный «GitHub» для тестов обновлений: локальный HTTP-сервер с заданными ответами."""

import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ASSET_NAMES = {
    "windows": "GMAGC-desktop-windows-{v}.zip",
    "macos": "GMAGC-desktop-macos-{v}.zip",
    "android": "GMAGC-android-{v}.apk",
}


def release_json(version, base, platforms=("windows", "macos", "android"), **flags):
    """Ответ GitHub API /releases/latest; файлы лежат по адресам base/<имя>, рядом .sha256."""
    assets = []
    for platform in platforms:
        name = ASSET_NAMES[platform].format(v=version)
        assets.append({"name": name, "browser_download_url": f"{base}/{name}", "size": 1000})
        assets.append({"name": name + ".sha256", "browser_download_url": f"{base}/{name}.sha256", "size": 100})
    return {
        "tag_name": f"v{version}",
        "name": f"GMAGC {version}",
        "html_url": f"{base}/releases/tag/v{version}",
        "body": f"Что нового в {version}",
        "draft": flags.get("draft", False),
        "prerelease": flags.get("prerelease", False),
        "assets": assets,
    }


@contextmanager
def stub_server(routes):
    """routes: путь -> {"body": bytes, "status": 200, "headers": {}, "declared_length": int, "delay": float}."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            route = routes.get(self.path)
            if route is None:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            time.sleep(route.get("delay", 0))
            body = route.get("body", b"")
            self.send_response(route.get("status", 200))
            self.send_header("Content-Length", str(route.get("declared_length", len(body))))
            for name, value in route.get("headers", {}).items():
                self.send_header(name, value)
            self.end_headers()
            try:
                self.wfile.write(body)
            except OSError:
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
```

```python
# path: tests/common/test_updates.py
import json
import socket

import pytest

from gmagc_common import updates
from gmagc_common.updates import (
    Asset,
    ReleaseInfo,
    UpdateCheckError,
    check_due,
    fetch_latest,
    is_allowed_url,
    is_newer,
    open_url,
    parse_sha256,
    parse_version,
    pick_assets,
    update_source,
)
from tests.updates_stub import release_json, stub_server

SHA = "a" * 64


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("v0.5.1", (0, 5, 1)),
        ("0.10.0", (0, 10, 0)),
        (" v1.2.3 ", (1, 2, 3)),
        ("1.2", None),
        ("1.2.3.4", None),
        ("v1.2.3-rc1", None),
        ("latest", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_version(text, expected):
    assert parse_version(text) == expected


def test_versions_compare_numerically_not_as_text():
    assert is_newer("0.10.0", "0.9.9") and is_newer("v1.0.0", "0.99.99")
    assert not is_newer("0.5.1", "0.5.1") and not is_newer("0.5.0", "0.5.1")
    assert not is_newer("garbage", "0.5.1") and not is_newer("0.6.0", "garbage")


def test_a_release_is_read_from_the_api_reply():
    release = ReleaseInfo.from_api(release_json("0.6.0", "https://example.invalid"))

    assert release.version == "0.6.0" and release.tag == "v0.6.0"
    assert release.notes == "Что нового в 0.6.0" and release.page_url.endswith("/releases/tag/v0.6.0")
    assert len(release.assets) == 6 and release.assets[0] == Asset(
        "GMAGC-desktop-windows-0.6.0.zip", "https://example.invalid/GMAGC-desktop-windows-0.6.0.zip", 1000
    )


@pytest.mark.parametrize(
    "broken",
    [
        {**release_json("0.6.0", "x"), "draft": True},
        {**release_json("0.6.0", "x"), "prerelease": True},
        {**release_json("0.6.0", "x"), "tag_name": "nightly"},
        {"assets": []},
        [],
        None,
    ],
)
def test_drafts_prereleases_and_foreign_replies_are_not_releases(broken):
    assert ReleaseInfo.from_api(broken) is None


def test_broken_assets_are_skipped_and_a_missing_body_is_empty():
    data = release_json("0.6.0", "https://example.invalid")
    data["assets"] = [{"name": "no-url"}, "junk", {"name": "ok.zip", "browser_download_url": "https://x/ok.zip"}]
    data["body"] = None

    release = ReleaseInfo.from_api(data)

    assert [a.name for a in release.assets] == ["ok.zip"] and release.assets[0].size == 0 and release.notes == ""


@pytest.mark.parametrize(
    ("platform", "name"),
    [
        ("windows", "GMAGC-desktop-windows-0.6.0.zip"),
        ("macos", "GMAGC-desktop-macos-0.6.0.zip"),
        ("android", "GMAGC-android-0.6.0.apk"),
    ],
)
def test_the_file_and_its_checksum_are_picked_by_platform(platform, name):
    release = ReleaseInfo.from_api(release_json("0.6.0", "https://example.invalid"))

    asset, checksum = pick_assets(release, platform)

    assert asset.name == name and checksum.name == name + ".sha256"


def test_a_missing_file_checksum_or_platform_is_reported_as_none():
    release = ReleaseInfo.from_api(release_json("0.6.0", "https://example.invalid", platforms=("windows",)))
    assert pick_assets(release, "macos") is None and pick_assets(release, "linux") is None

    release = ReleaseInfo.from_api(release_json("0.6.0", "https://example.invalid"))
    kept = tuple(a for a in release.assets if not a.name.endswith(".sha256"))
    without_sum = ReleaseInfo(release.version, release.tag, release.notes, release.page_url, kept)
    asset, checksum = pick_assets(without_sum, "android")
    assert asset.name.endswith(".apk") and checksum is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (f"{SHA}  GMAGC-android-0.6.0.apk\n", SHA),
        (f"{SHA.upper()} *file.zip", SHA),
        (f"\n  {SHA}\n", SHA),
        ("not a hash  file.zip", None),
        ("abc123  file.zip", None),
        ("", None),
    ],
)
def test_parse_sha256(text, expected):
    assert parse_sha256(text) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://api.github.com/repos/spacesarmat/GMAGC/releases/latest",
        "https://github.com/spacesarmat/GMAGC/releases/download/v0.6.0/GMAGC-android-0.6.0.apk",
        "https://objects.githubusercontent.com/github-production-release-asset/abc",
        "https://release-assets.githubusercontent.com/x",
    ],
)
def test_github_addresses_are_allowed(url):
    assert is_allowed_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/x",
        "https://evil.example/x",
        "https://github.com.evil.example/x",
        "https://evilgithub.com/x",
        "https://githubusercontent.com.evil.example/x",
        "https://notgithubusercontent.com/x",
        "ftp://github.com/x",
        "file:///C:/x",
        "http://127.0.0.1:8000/x",
        "",
        "not a url",
    ],
)
def test_other_addresses_are_refused(url):
    assert not is_allowed_url(url)


def test_a_local_address_is_allowed_only_on_request_and_only_over_loopback():
    assert is_allowed_url("http://127.0.0.1:8000/x", allow_local=True)
    assert is_allowed_url("http://localhost:8000/x", allow_local=True)
    assert not is_allowed_url("http://192.168.1.5:8000/x", allow_local=True)
    assert not is_allowed_url("http://example.com/x", allow_local=True)


def test_the_update_source_is_github_unless_a_loopback_override_is_set(monkeypatch):
    monkeypatch.delenv(updates.UPDATE_URL_ENV, raising=False)
    assert update_source() == (updates.RELEASES_API, False)

    monkeypatch.setenv(updates.UPDATE_URL_ENV, "http://127.0.0.1:9999/latest")
    assert update_source() == ("http://127.0.0.1:9999/latest", True)

    monkeypatch.setenv(updates.UPDATE_URL_ENV, "https://evil.example/latest")
    assert update_source() == (updates.RELEASES_API, False)
    monkeypatch.setenv(updates.UPDATE_URL_ENV, "http://192.168.1.5/latest")
    assert update_source() == (updates.RELEASES_API, False)


def test_the_check_is_due_once_a_day_and_when_the_clock_went_back():
    day = updates.CHECK_INTERVAL_SECONDS
    assert check_due(0, 1_000_000) and check_due(1_000_000 - day, 1_000_000)
    assert not check_due(1_000_000 - day + 1, 1_000_000)
    assert check_due(2_000_000, 1_000_000)


def test_a_newer_release_is_returned_and_an_equal_or_older_one_is_not():
    routes = {}
    with stub_server(routes) as base:
        routes["/latest"] = {"body": json.dumps(release_json("0.6.0", base)).encode()}
        newer = fetch_latest("0.5.1", url=f"{base}/latest", allow_local=True)
        same = fetch_latest("0.6.0", url=f"{base}/latest", allow_local=True)
        older = fetch_latest("0.7.0", url=f"{base}/latest", allow_local=True)

    assert newer.version == "0.6.0" and same is None and older is None


@pytest.mark.parametrize(
    ("status", "fragment"),
    [(404, "не найдены"), (403, "ограничил"), (429, "ограничил"), (500, "ошибкой 500")],
)
def test_http_errors_are_reported_in_words(status, fragment):
    with stub_server({"/latest": {"status": status, "body": b"{}"}}) as base:
        with pytest.raises(UpdateCheckError) as error:
            fetch_latest("0.5.1", url=f"{base}/latest", allow_local=True)

    assert fragment in str(error.value)


def test_replies_that_are_not_a_release_are_errors():
    cases = [b"<html>captive portal</html>", b'{"hello": "world"}', b"[1, 2]", b'{"tag_name": "v1.0.0", "draft": true}']
    for body in cases:
        with stub_server({"/latest": {"body": body}}) as base:
            with pytest.raises(UpdateCheckError):
                fetch_latest("0.5.1", url=f"{base}/latest", allow_local=True)


def test_an_oversized_reply_is_refused(monkeypatch):
    monkeypatch.setattr(updates, "MAX_RESPONSE_BYTES", 100)
    with stub_server({"/latest": {"body": b"x" * 500}}) as base:
        with pytest.raises(UpdateCheckError) as error:
            fetch_latest("0.5.1", url=f"{base}/latest", allow_local=True)

    assert "большой" in str(error.value)


def test_no_connection_and_a_slow_server_are_reported_as_no_connection():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]
    with pytest.raises(UpdateCheckError) as error:
        fetch_latest("0.5.1", url=f"http://127.0.0.1:{closed_port}/latest", allow_local=True)
    assert "Нет связи" in str(error.value)

    with stub_server({"/latest": {"body": b"{}", "delay": 1.5}}) as base:
        with pytest.raises(UpdateCheckError) as error:
            fetch_latest("0.5.1", timeout=0.3, url=f"{base}/latest", allow_local=True)
    assert "Нет связи" in str(error.value)


def test_a_redirect_to_a_foreign_host_is_refused():
    routes = {"/latest": {"status": 302, "headers": {"Location": "https://evil.example/latest"}}}
    with stub_server(routes) as base:
        with pytest.raises(UpdateCheckError) as error:
            fetch_latest("0.5.1", url=f"{base}/latest", allow_local=True)

    assert "недопустим" in str(error.value)


def test_a_redirect_within_the_allowed_scope_is_followed():
    routes = {}
    with stub_server(routes) as base:
        routes["/old"] = {"status": 302, "headers": {"Location": f"{base}/latest"}}
        routes["/latest"] = {"body": json.dumps(release_json("0.6.0", base)).encode()}

        release = fetch_latest("0.5.1", url=f"{base}/old", allow_local=True)

    assert release.version == "0.6.0"


def test_open_url_refuses_a_disallowed_address_before_connecting():
    with pytest.raises(UpdateCheckError):
        open_url("https://evil.example/x")
    with pytest.raises(UpdateCheckError):
        open_url("http://127.0.0.1:1/x")  # локальный адрес без allow_local
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/common/test_updates.py -q`
Expected: FAIL (`ModuleNotFoundError: gmagc_common.updates`).

- [ ] **Step 3: Write the implementation**

```python
# path: packages/common/gmagc_common/updates.py
"""Проверка обновлений на GitHub Releases: версии, разбор релиза, выбор файла, безопасное открытие адреса.

Только стандартная библиотека: пакет без изменений копируется в оба приложения (scripts/sync_common.py).
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit

REPO = "spacesarmat/GMAGC"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
CHECK_INTERVAL_SECONDS = 24 * 60 * 60
MAX_RESPONSE_BYTES = 1024 * 1024
UPDATE_URL_ENV = "GMAGC_UPDATE_URL"  # только для тестов и отладки: адрес на локальный хост подменяет GitHub
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")

_VERSION = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")
_SHA256 = re.compile(r"[0-9a-fA-F]{64}")
_ASSET_NAMES = {
    "windows": "GMAGC-desktop-windows-{v}.zip",
    "macos": "GMAGC-desktop-macos-{v}.zip",
    "android": "GMAGC-android-{v}.apk",
}


class UpdateCheckError(Exception):
    """Проверка обновления не удалась; текст можно показывать пользователю."""


def parse_version(text: str) -> tuple[int, int, int] | None:
    """`v0.5.1` или `0.5.1` -> (0, 5, 1); всё остальное (в том числе `1.2`, `1.2.3-rc1`) даёт None."""
    if not isinstance(text, str):
        return None
    match = _VERSION.fullmatch(text.strip())
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


def is_newer(candidate: str, current: str) -> bool:
    new, old = parse_version(candidate), parse_version(current)
    return new is not None and old is not None and new > old


@dataclass(frozen=True)
class Asset:
    name: str
    url: str
    size: int


@dataclass(frozen=True)
class ReleaseInfo:
    version: str  # `0.6.0`
    tag: str  # `v0.6.0`
    notes: str
    page_url: str
    assets: tuple[Asset, ...]

    @classmethod
    def from_api(cls, data: object) -> ReleaseInfo | None:
        """Релиз из ответа GitHub API; черновики, предрелизы и чужие ответы дают None."""
        if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
            return None
        tag = data.get("tag_name")
        parsed = parse_version(tag)
        if parsed is None:
            return None
        assets = []
        for item in data.get("assets") or []:
            if isinstance(item, dict) and "name" in item and "browser_download_url" in item:
                size = item.get("size")
                assets.append(Asset(str(item["name"]), str(item["browser_download_url"]), size if isinstance(size, int) else 0))
        return cls(
            ".".join(str(part) for part in parsed),
            tag.strip(),
            str(data.get("body") or ""),
            str(data.get("html_url") or RELEASES_PAGE),
            tuple(assets),
        )


def pick_assets(release: ReleaseInfo, platform: str) -> tuple[Asset, Asset | None] | None:
    """Файл релиза для платформы (`windows`, `macos`, `android`) и его `.sha256` (или None, если суммы нет)."""
    pattern = _ASSET_NAMES.get(platform)
    if pattern is None:
        return None
    name = pattern.format(v=release.version)
    by_name = {asset.name: asset for asset in release.assets}
    main = by_name.get(name)
    return None if main is None else (main, by_name.get(name + ".sha256"))


def parse_sha256(text: str) -> str | None:
    """Контрольная сумма из файла формата `sha256sum` (`<хеш>  <имя>`) или None."""
    for line in text.splitlines():
        token = line.strip().split(" ")[0] if line.strip() else ""
        if token:
            return token.lower() if _SHA256.fullmatch(token) else None
    return None


def is_allowed_url(url: str, allow_local: bool = False) -> bool:
    """HTTPS и хосты GitHub (`github.com`, `*.github.com`, `*.githubusercontent.com`); локальный адрес только по запросу."""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
    except ValueError:
        return False
    if allow_local and parts.scheme == "http" and host in LOCAL_HOSTS:
        return True
    if parts.scheme != "https":
        return False
    return host in ("github.com", "api.github.com") or host.endswith((".github.com", ".githubusercontent.com"))


def update_source() -> tuple[str, bool]:
    """Адрес проверки и признак «локальный»: `GMAGC_UPDATE_URL` действует, только если ведёт на loopback."""
    override = os.environ.get(UPDATE_URL_ENV, "").strip()
    if override and is_allowed_url(override, allow_local=True) and urlsplit(override).hostname in LOCAL_HOSTS:
        return override, True
    return RELEASES_API, False


class _CheckedRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, allow_local: bool):
        self._allow_local = allow_local

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not is_allowed_url(newurl, self._allow_local):
            raise UpdateCheckError("Переход на недопустимый адрес: обновление отменено")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_url(url: str, *, allow_local: bool = False, timeout: float = 8.0, user_agent: str = "GMAGC"):
    """Открывает адрес через urllib, проверяя его и каждый переход; ошибки сети остаются исключениями urllib."""
    if not is_allowed_url(url, allow_local):
        raise UpdateCheckError("Недопустимый адрес обновления")
    opener = urllib.request.build_opener(_CheckedRedirect(allow_local))
    request = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "application/vnd.github+json"})
    return opener.open(request, timeout=timeout)


def fetch_latest(
    current_version: str, timeout: float = 8.0, url: str | None = None, allow_local: bool = False
) -> ReleaseInfo | None:
    """Последний релиз, если он новее current_version, иначе None; сбои дают UpdateCheckError."""
    source, local = (url, allow_local) if url else update_source()
    try:
        with open_url(source, allow_local=local, timeout=timeout, user_agent=f"GMAGC/{current_version}") as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
        if error.code in (403, 429):
            raise UpdateCheckError("GitHub временно ограничил число запросов: попробуйте позже") from error
        if error.code == 404:
            raise UpdateCheckError("Релизы не найдены") from error
        raise UpdateCheckError(f"GitHub ответил ошибкой {error.code}") from error
    except OSError as error:  # нет сети, отказ в соединении, таймаут
        raise UpdateCheckError("Нет связи с GitHub") from error
    if len(raw) > MAX_RESPONSE_BYTES:
        raise UpdateCheckError("Слишком большой ответ GitHub")
    try:
        data = json.loads(raw)
    except ValueError as error:
        raise UpdateCheckError("Ответ GitHub не удалось разобрать") from error
    release = ReleaseInfo.from_api(data)
    if release is None:
        raise UpdateCheckError("Ответ GitHub не похож на релиз")
    return release if is_newer(release.version, current_version) else None


def check_due(last_check: float, now: float, interval: float = CHECK_INTERVAL_SECONDS) -> bool:
    """Пора ли проверять: раз в interval секунд; если часы ушли назад, тоже пора."""
    return last_check <= 0 or last_check > now or now - last_check >= interval
```

- [ ] **Step 4: Sync the copies and run the tests**

Run: `.venv\Scripts\python.exe scripts\sync_common.py`, затем `.venv\Scripts\python.exe -m pytest tests/common -q`
Expected: PASS (включая тест на совпадение копий).

- [ ] **Step 5: Lint and commit**

```bash
.venv/Scripts/python.exe -m ruff check --fix . && .venv/Scripts/python.exe scripts/sync_common.py && .venv/Scripts/python.exe -m pytest -q
git add packages apps/desktop/src/gmagc_common apps/mobile/src/gmagc_common tests
git commit -m "feat: shared release lookup and safe URL handling for updates" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: Настройки обновлений и методы `SearchService`

**Files:**
- Modify: `apps/desktop/src/gmagc_desktop/service/settings.py`, `apps/desktop/src/gmagc_desktop/service/search_service.py`
- Test: `tests/desktop/test_settings_updates.py`

**Interfaces:**
- Consumes: `gmagc_common.updates.parse_version`.
- Produces: `Settings.check_updates: bool = True`, `Settings.skipped_version: str = ""`, `Settings.last_update_check: float = 0.0`; `SearchService.set_check_updates(enabled: bool)`, `mark_update_checked(when: float)`, `skip_update(version: str)`.

- [ ] **Step 1: Write the failing tests**

```python
# path: tests/desktop/test_settings_updates.py
import json

import pytest

from gmagc_desktop.service.search_service import SearchService
from gmagc_desktop.service.settings import Settings, load_settings, save_settings


def test_update_defaults_check_on_start_and_nothing_skipped():
    settings = Settings()

    assert settings.check_updates is True and settings.skipped_version == "" and settings.last_update_check == 0.0


def test_update_settings_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    save_settings(Settings(check_updates=False, skipped_version="0.6.0", last_update_check=1_700_000_000.5), path)

    loaded = load_settings(path)

    assert (loaded.check_updates, loaded.skipped_version, loaded.last_update_check) == (False, "0.6.0", 1_700_000_000.5)


@pytest.mark.parametrize(
    "raw",
    [
        {"check_updates": "yes", "skipped_version": 5, "last_update_check": "today"},
        {"skipped_version": "latest", "last_update_check": -1},
        {"skipped_version": "1.2", "last_update_check": True},
        {"last_update_check": float("inf")},
        {"last_update_check": None},
    ],
)
def test_bad_update_values_fall_back_to_defaults(tmp_path, raw):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    loaded = load_settings(path)

    assert loaded.check_updates is True and loaded.skipped_version == "" and loaded.last_update_check == 0.0


def test_the_service_persists_update_choices(tmp_path):
    service = SearchService(tmp_path / "data")
    service.load()

    service.set_check_updates(False)
    service.mark_update_checked(1_700_000_123.0)
    service.skip_update("0.7.1")

    other = SearchService(tmp_path / "data")
    other.load()
    assert other.settings.check_updates is False
    assert other.settings.last_update_check == 1_700_000_123.0 and other.settings.skipped_version == "0.7.1"


def test_a_malformed_version_is_not_stored_as_skipped(tmp_path):
    service = SearchService(tmp_path / "data")
    service.load()

    service.skip_update("not-a-version")

    assert service.settings.skipped_version == ""
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/desktop/test_settings_updates.py -q`
Expected: FAIL (нет полей и методов).

- [ ] **Step 3: Write the implementation**

В `apps/desktop/src/gmagc_desktop/service/settings.py`:

1. Импорты: после `import json` добавить `import math`; после `from gmagc_common.protocol import DEFAULT_PORT, is_valid_code, normalize_code` добавить `from gmagc_common.updates import parse_version`.
2. В `Settings` после `access_code: str = ""` добавить:

```python
    check_updates: bool = True
    skipped_version: str = ""
    last_update_check: float = 0.0
```

3. В `load_settings` после строки `access_code = raw.get("access_code", "")` добавить:

```python
    check_updates = raw.get("check_updates", True)
    skipped_version = raw.get("skipped_version", "")
    last_update_check = raw.get("last_update_check", 0.0)
```

и в вызов `Settings(...)` добавить аргументы:

```python
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
```

В `apps/desktop/src/gmagc_desktop/service/search_service.py` после метода `set_server_enabled` добавить:

```python
    def set_check_updates(self, enabled: bool) -> None:
        self._update_settings(check_updates=enabled)

    def mark_update_checked(self, when: float) -> None:
        self._update_settings(last_update_check=float(when))

    def skip_update(self, version: str) -> None:
        """Запоминает версию, о которой больше не напоминать (неверный формат сбрасывает пропуск)."""
        self._update_settings(skipped_version=version if parse_version(version) else "")
```

и в импорты этого файла добавить `from gmagc_common.updates import parse_version` (рядом с `from gmagc_common.protocol import is_valid_code`).

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest tests/desktop -q`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
.venv/Scripts/python.exe -m ruff check --fix . && .venv/Scripts/python.exe -m pytest -q
git add apps/desktop/src/gmagc_desktop/service tests/desktop
git commit -m "feat: update preferences in settings and the search service" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---
### Task 3: Установщик обновления ПК (`gmagc_desktop/update/installer.py`)

**Files:**
- Create: `apps/desktop/src/gmagc_desktop/update/__init__.py`, `apps/desktop/src/gmagc_desktop/update/installer.py`
- Test: `tests/desktop/test_update_installer.py`

**Interfaces:**
- Consumes: `gmagc_common.updates` (`Asset`, `UpdateCheckError`, `open_url`, `parse_sha256`), `tests/updates_stub.py`.
- Produces: `InstallError(Exception)`, `InstallCancelled(Exception)`; `platform_key() -> "windows" | "macos" | None`; `current_executable() -> Path | None`; `install_target(executable, platform) -> Path | None`; `is_writable(path) -> bool`; `sha256_of(path) -> str`; `download(asset, checksum_asset, dest_dir, *, progress=None, cancel=None, allow_local=False, timeout=30.0) -> Path`; `stage(zip_path, staging_dir, platform) -> Path`; `backup_dir(target) -> Path`; `windows_script(...)`, `macos_script(...)`, `write_helper(platform, work_dir, *, pid, staged, target, exe, backup, log) -> Path`, `launch_helper(script, platform)`; константы `MAX_DOWNLOAD_BYTES`, `MAX_UNPACKED_BYTES`.

- [ ] **Step 1: Write the failing tests**

```python
# path: tests/desktop/test_update_installer.py
import hashlib
import io
import shlex
import sys
import zipfile
from pathlib import Path, PurePosixPath

import pytest

from gmagc_common.updates import Asset
from gmagc_desktop.update import installer
from gmagc_desktop.update.installer import (
    InstallCancelled,
    InstallError,
    backup_dir,
    current_executable,
    download,
    install_target,
    is_writable,
    launch_helper,
    macos_script,
    platform_key,
    sha256_of,
    stage,
    windows_script,
    write_helper,
)
from tests.updates_stub import stub_server


def make_zip(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def serve(body, sha=None, name="GMAGC-desktop-windows-0.6.0.zip", **route):
    """Сервер с файлом и его .sha256; возвращает (контекст, asset, checksum_asset-фабрика)."""
    digest = sha or hashlib.sha256(body).hexdigest()
    routes = {
        f"/{name}": {"body": body, **route},
        f"/{name}.sha256": {"body": f"{digest}  {name}\n".encode()},
    }
    return routes, name


def assets(base, name, size=0):
    return Asset(name, f"{base}/{name}", size), Asset(name + ".sha256", f"{base}/{name}.sha256", 100)


# ---- определение папки приложения ---------------------------------------------------------
def test_the_windows_install_target_is_the_folder_of_the_app_exe():
    exe = Path("C:/Apps/GMAGC/gmagc-desktop.exe")

    assert install_target(exe, "windows") == exe.parent
    assert install_target(Path("C:/Apps/GMAGC/GMAGC-desktop.EXE"), "windows") == exe.parent


def test_a_foreign_executable_is_not_an_install_target():
    assert install_target(Path("C:/Python312/python.exe"), "windows") is None
    assert install_target(None, "windows") is None
    assert install_target(Path("/usr/bin/python3"), "linux") is None


def test_the_macos_install_target_is_the_app_bundle():
    exe = Path("/Applications/GMAGC.app/Contents/MacOS/gmagc-desktop")

    assert install_target(exe, "macos") == Path("/Applications/GMAGC.app")
    assert install_target(Path("/usr/local/bin/python3"), "macos") is None


def test_the_platform_key_and_current_executable_are_sane_here():
    assert platform_key() in {"windows", "macos", None}
    if sys.platform == "win32":
        assert platform_key() == "windows"
        executable = current_executable()
        assert executable is not None and executable.is_file()


def test_writability_is_tested_by_creating_a_file(tmp_path):
    assert is_writable(tmp_path)
    assert not is_writable(tmp_path / "missing" / "deeper")


def test_the_backup_folder_sits_next_to_the_app():
    assert backup_dir(Path("C:/Apps/GMAGC")) == Path("C:/Apps/GMAGC.previous")


def test_sha256_of_a_file(tmp_path):
    path = tmp_path / "f.bin"
    path.write_bytes(b"hello")

    assert sha256_of(path) == hashlib.sha256(b"hello").hexdigest()


# ---- загрузка ---------------------------------------------------------------------------------
def test_a_verified_download_is_saved_and_reports_progress(tmp_path):
    body = b"x" * 600_000
    routes, name = serve(body)
    steps = []
    with stub_server(routes) as base:
        asset, checksum = assets(base, name, size=len(body))

        path = download(asset, checksum, tmp_path / "dl", progress=lambda done, total: steps.append((done, total)), allow_local=True)

    assert path == tmp_path / "dl" / name and path.read_bytes() == body
    assert steps[-1] == (600_000, 600_000) and steps == sorted(steps) and len(steps) >= 3
    assert not list((tmp_path / "dl").glob("*.part"))


def test_a_wrong_checksum_removes_the_file_and_refuses_the_update(tmp_path):
    routes, name = serve(b"payload", sha="0" * 64)
    with stub_server(routes) as base:
        asset, checksum = assets(base, name)
        with pytest.raises(InstallError) as error:
            download(asset, checksum, tmp_path / "dl", allow_local=True)

    assert "Контрольная сумма не совпала" in str(error.value)
    assert list((tmp_path / "dl").glob("*")) == []


def test_a_release_without_a_checksum_is_refused(tmp_path):
    routes, name = serve(b"payload")
    with stub_server(routes) as base:
        asset, _ = assets(base, name)
        with pytest.raises(InstallError) as error:
            download(asset, None, tmp_path / "dl", allow_local=True)

    assert "нет контрольной суммы" in str(error.value)


def test_a_broken_checksum_file_is_refused(tmp_path):
    routes, name = serve(b"payload")
    routes[f"/{name}.sha256"] = {"body": b"this is not a hash\n"}
    with stub_server(routes) as base:
        asset, checksum = assets(base, name)
        with pytest.raises(InstallError) as error:
            download(asset, checksum, tmp_path / "dl", allow_local=True)

    assert "повреждена" in str(error.value)


def test_a_truncated_download_is_refused(tmp_path):
    routes, name = serve(b"short", declared_length=5000)
    with stub_server(routes) as base:
        asset, checksum = assets(base, name)
        with pytest.raises(InstallError):
            download(asset, checksum, tmp_path / "dl", allow_local=True)

    assert list((tmp_path / "dl").glob("*")) == []


def test_cancelling_stops_the_download_and_leaves_nothing(tmp_path):
    routes, name = serve(b"x" * 600_000)
    with stub_server(routes) as base:
        asset, checksum = assets(base, name)
        with pytest.raises(InstallCancelled):
            download(asset, checksum, tmp_path / "dl", cancel=lambda: True, allow_local=True)

    assert list((tmp_path / "dl").glob("*")) == []


def test_a_file_over_the_size_limit_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "MAX_DOWNLOAD_BYTES", 1000)
    routes, name = serve(b"x" * 5000)
    with stub_server(routes) as base:
        asset, checksum = assets(base, name)
        with pytest.raises(InstallError) as error:
            download(asset, checksum, tmp_path / "dl", allow_local=True)

    assert "слишком большой" in str(error.value)


def test_a_redirect_to_a_foreign_host_is_refused(tmp_path):
    routes, name = serve(b"payload")
    routes[f"/{name}"] = {"status": 302, "headers": {"Location": "https://evil.example/x.zip"}}
    with stub_server(routes) as base:
        asset, checksum = assets(base, name)
        with pytest.raises(InstallError) as error:
            download(asset, checksum, tmp_path / "dl", allow_local=True)

    assert "недопустим" in str(error.value)


def test_a_local_address_is_refused_unless_allowed(tmp_path):
    routes, name = serve(b"payload")
    with stub_server(routes) as base:
        asset, checksum = assets(base, name)
        with pytest.raises(InstallError):
            download(asset, checksum, tmp_path / "dl")


# ---- распаковка -----------------------------------------------------------------------------------
def write_archive(tmp_path, files):
    path = tmp_path / "update.zip"
    path.write_bytes(make_zip(files))
    return path


def test_a_windows_archive_is_unpacked_with_its_folders(tmp_path):
    archive = write_archive(tmp_path, {"gmagc-desktop.exe": b"MZ", "data/app.bin": b"1", "Lib/x/y.pyc": b"2"})

    root = stage(archive, tmp_path / "staged", "windows")

    assert root == (tmp_path / "staged").resolve() and (root / "gmagc-desktop.exe").read_bytes() == b"MZ"
    assert (root / "data" / "app.bin").read_bytes() == b"1" and (root / "Lib" / "x" / "y.pyc").read_bytes() == b"2"


@pytest.mark.parametrize("evil", ["../evil.txt", "a/../../evil.txt", "/abs/evil.txt", "C:/evil.txt", "..\\evil.txt"])
def test_an_unsafe_path_in_the_archive_stops_the_installation(tmp_path, evil):
    archive = write_archive(tmp_path, {"gmagc-desktop.exe": b"MZ", evil: b"x"})

    with pytest.raises(InstallError) as error:
        stage(archive, tmp_path / "staged", "windows")

    assert "небезопасный путь" in str(error.value)
    assert not (tmp_path / "evil.txt").exists() and not Path("/abs/evil.txt").exists()


def test_an_archive_without_the_app_is_refused(tmp_path):
    with pytest.raises(InstallError) as error:
        stage(write_archive(tmp_path, {"readme.txt": b"hi"}), tmp_path / "staged", "windows")

    assert "нет приложения" in str(error.value)


def test_a_file_that_is_not_an_archive_is_refused(tmp_path):
    path = tmp_path / "update.zip"
    path.write_bytes(b"not a zip")

    with pytest.raises(InstallError) as error:
        stage(path, tmp_path / "staged", "windows")

    assert "не архив" in str(error.value)


def test_an_archive_that_unpacks_to_too_much_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "MAX_UNPACKED_BYTES", 100)
    archive = write_archive(tmp_path, {"gmagc-desktop.exe": b"x" * 1000})

    with pytest.raises(InstallError) as error:
        stage(archive, tmp_path / "staged", "windows")

    assert "слишком велик" in str(error.value)


# ---- скрипты-помощники ----------------------------------------------------------------------------
WIN = {
    "pid": 4242,
    "staged": r"C:\Users\Иван Петров\AppData\Local\@ANDY_BUM\GMAGC\updates\0.6.0\staged",
    "target": r"C:\Apps\GMAGC гобо 100%",
    "backup": r"C:\Apps\GMAGC гобо 100%.previous",
    "exe": r"C:\Apps\GMAGC гобо 100%\gmagc-desktop.exe",
    "log": r"C:\Users\Иван Петров\AppData\Local\@ANDY_BUM\GMAGC\update.log",
}


def test_the_windows_script_waits_backs_up_copies_restores_and_restarts():
    script = windows_script(**WIN)

    assert 'set "PID=4242"' in script and "tasklist" in script and "goto wait" in script
    assert script.count("robocopy") == 3 and "if errorlevel 8 goto restore" in script and ":restore" in script
    assert 'start "" "%EXE%"' in script and "chcp 65001" in script
    assert script.endswith("\r\n") and "\n" not in script.replace("\r\n", "")


def test_the_windows_script_keeps_cyrillic_and_spaces_and_doubles_percent_signs():
    script = windows_script(**WIN)

    assert r'set "DST=C:\Apps\GMAGC гобо 100%%"' in script
    assert r'set "SRC=C:\Users\Иван Петров\AppData\Local\@ANDY_BUM\GMAGC\updates\0.6.0\staged"' in script
    assert "100%%.previous" in script and "100%.previous" not in script.replace("100%%.previous", "")


def test_the_macos_script_quotes_every_path():
    target = "/Applications/My App's/GMAGC.app"
    script = macos_script(pid=77, staged="/tmp/up date/GMAGC.app", target=target, backup=target + ".previous", log="/tmp/u.log")

    assert script.startswith("#!/bin/sh") and "PID=77" in script and "ditto" in script and "kill -0" in script
    assert f"DST={shlex.quote(target)}" in script and f"SRC={shlex.quote('/tmp/up date/GMAGC.app')}" in script
    assert 'open "$DST"' in script and script.endswith("\n") and "\r" not in script


def test_the_helper_is_written_next_to_the_staged_files(tmp_path):
    fields = {**WIN, "staged": tmp_path / "staged", "target": tmp_path / "app", "backup": tmp_path / "app.previous",
              "exe": tmp_path / "app" / "gmagc-desktop.exe", "log": tmp_path / "update.log"}

    script = write_helper("windows", tmp_path / "work", **fields)

    assert script == tmp_path / "work" / "apply-update.cmd"
    data = script.read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf") and b'set "PID=4242"' in data and str(tmp_path).encode() in data


def test_the_macos_helper_is_executable(tmp_path):
    script = write_helper("macos", tmp_path / "work", pid=5, staged=tmp_path / "s", target=tmp_path / "GMAGC.app",
                          exe=tmp_path / "x", backup=tmp_path / "GMAGC.app.previous", log=tmp_path / "l")

    assert script.name == "apply-update.sh" and script.read_text(encoding="utf-8").startswith("#!/bin/sh")
    if sys.platform != "win32":
        assert script.stat().st_mode & 0o111


def test_an_unsupported_platform_has_no_helper(tmp_path):
    with pytest.raises(InstallError):
        write_helper("linux", tmp_path, pid=1, staged=tmp_path, target=tmp_path, exe=tmp_path, backup=tmp_path, log=tmp_path)


def test_the_helper_is_launched_detached_without_a_window(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(installer.subprocess, "Popen", lambda *args, **kwargs: calls.append((args, kwargs)))
    script = tmp_path / "apply-update.cmd"

    launch_helper(script, "windows")
    launch_helper(tmp_path / "apply-update.sh", "macos")

    (win_args, win_kwargs), (mac_args, mac_kwargs) = calls
    assert win_args[0][:4] == ["cmd.exe", "/d", "/c", "call"] and win_args[0][4] == str(script)
    assert win_kwargs["close_fds"] is True and "creationflags" in win_kwargs
    assert mac_args[0][0] == "/bin/sh" and mac_kwargs["start_new_session"] is True


def test_a_failing_launch_is_reported(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("нет доступа")

    monkeypatch.setattr(installer.subprocess, "Popen", boom)

    with pytest.raises(InstallError) as error:
        launch_helper(tmp_path / "apply-update.cmd", "windows")

    assert "Не удалось запустить" in str(error.value)


def test_posix_style_paths_are_pure_and_do_not_need_a_disk():
    assert PurePosixPath("/Applications/GMAGC.app").suffix == ".app"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/desktop/test_update_installer.py -q`
Expected: FAIL (`ModuleNotFoundError: gmagc_desktop.update`).

- [ ] **Step 3: Write the implementation**

```python
# path: apps/desktop/src/gmagc_desktop/update/__init__.py
"""Обновление ПК-приложения с GitHub Releases (без Flet)."""
```

```python
# path: apps/desktop/src/gmagc_desktop/update/installer.py
"""Загрузка, проверка и установка обновления ПК-приложения (без Flet)."""

from __future__ import annotations

import ctypes
import hashlib
import http.client
import os
import shlex
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path

from gmagc_common.updates import Asset, UpdateCheckError, open_url, parse_sha256

MAX_DOWNLOAD_BYTES = 400 * 1024 * 1024
MAX_UNPACKED_BYTES = 1024 * 1024 * 1024
CHUNK_BYTES = 256 * 1024
WINDOWS_EXE = "gmagc-desktop.exe"


class InstallError(Exception):
    """Обновление не установлено; текст можно показывать пользователю."""


class InstallCancelled(Exception):
    """Пользователь отменил загрузку."""


def platform_key() -> str | None:
    return {"win32": "windows", "darwin": "macos"}.get(sys.platform)


def current_executable() -> Path | None:
    """Путь к исполняемому файлу процесса (у собранного приложения это gmagc-desktop)."""
    try:
        if sys.platform == "win32":
            buffer = ctypes.create_unicode_buffer(32768)
            length = ctypes.windll.kernel32.GetModuleFileNameW(None, buffer, len(buffer))
            return Path(buffer.value) if length else None
        if sys.platform == "darwin":
            size = ctypes.c_uint32(4096)
            buffer = ctypes.create_string_buffer(4096)
            if ctypes.CDLL(None)._NSGetExecutablePath(buffer, ctypes.byref(size)) == 0:
                return Path(os.fsdecode(buffer.value)).resolve()
    except (OSError, AttributeError):
        return None
    return None


def install_target(executable: Path | None, platform: str | None) -> Path | None:
    """Что заменять: папка приложения (Windows) или пакет .app (macOS); None, если запуск не из сборки."""
    if executable is None:
        return None
    if platform == "windows":
        return executable.parent if executable.name.lower() == WINDOWS_EXE else None
    if platform == "macos":
        for parent in executable.parents:
            if parent.suffix == ".app":
                return parent
    return None


def is_writable(path: Path) -> bool:
    """Можно ли создать файл в папке (проверка реальным созданием: права Windows не видны через os.access)."""
    try:
        with tempfile.TemporaryFile(dir=path):
            return True
    except OSError:
        return False


def backup_dir(target: Path) -> Path:
    return target.with_name(target.name + ".previous")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expected_checksum(asset: Asset | None, allow_local: bool, timeout: float) -> str:
    if asset is None:
        raise InstallError("В релизе нет контрольной суммы: обновление не установлено, скачайте его вручную")
    try:
        with open_url(asset.url, allow_local=allow_local, timeout=timeout) as response:
            text = response.read(4096).decode("utf-8", "replace")
    except UpdateCheckError as error:
        raise InstallError(str(error)) from error
    except (OSError, http.client.HTTPException) as error:
        raise InstallError(f"Не удалось получить контрольную сумму: {error}") from error
    checksum = parse_sha256(text)
    if checksum is None:
        raise InstallError("Контрольная сумма в релизе повреждена: обновление не установлено")
    return checksum


def download(
    asset: Asset,
    checksum_asset: Asset | None,
    dest_dir: Path,
    *,
    progress: Callable[[int, int], None] | None = None,
    cancel: Callable[[], bool] | None = None,
    allow_local: bool = False,
    timeout: float = 30.0,
) -> Path:
    """Скачивает файл релиза, сверяет SHA-256 с файлом .sha256 и возвращает путь; при любом сбое ничего не остаётся."""
    expected = _expected_checksum(checksum_asset, allow_local, timeout)
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / asset.name
    part = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    done = 0
    total = 0
    try:
        with open_url(asset.url, allow_local=allow_local, timeout=timeout) as response, part.open("wb") as out:
            total = int(response.headers.get("Content-Length") or asset.size or 0)
            if total > MAX_DOWNLOAD_BYTES:
                raise InstallError("Файл обновления слишком большой")
            while True:
                if cancel is not None and cancel():
                    raise InstallCancelled()
                chunk = response.read(CHUNK_BYTES)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if done > MAX_DOWNLOAD_BYTES:
                    raise InstallError("Файл обновления слишком большой")
                if progress is not None:
                    progress(done, total)
        if total and done != total:
            raise InstallError("Загрузка оборвалась: файл получен не полностью")
        if digest.hexdigest() != expected:
            raise InstallError("Контрольная сумма не совпала: файл повреждён, обновление не установлено")
        part.replace(target)
        return target
    except UpdateCheckError as error:
        raise InstallError(str(error)) from error
    except (OSError, http.client.HTTPException) as error:
        raise InstallError(f"Не удалось скачать обновление: {error}") from error
    finally:
        part.unlink(missing_ok=True)


def _ditto(zip_path: Path, dest: Path) -> None:
    """macOS: распаковка с сохранением прав и ссылок (zipfile теряет бит исполнения)."""
    try:
        subprocess.run(["ditto", "-x", "-k", str(zip_path), str(dest)], check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as error:
        raise InstallError(f"Не удалось распаковать обновление: {error}") from error


def stage(zip_path: Path, staging_dir: Path, platform: str) -> Path:
    """Распаковывает архив во временную папку (без выхода за её пределы) и возвращает распакованное приложение."""
    root = staging_dir.resolve()
    try:
        archive = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError) as error:
        raise InstallError("Файл обновления повреждён: это не архив") from error
    with archive:
        infos = archive.infolist()
        if sum(info.file_size for info in infos) > MAX_UNPACKED_BYTES:
            raise InstallError("Архив обновления слишком велик после распаковки")
        for info in infos:
            destination = (root / info.filename).resolve()
            if destination != root and root not in destination.parents:
                raise InstallError("Архив обновления содержит небезопасный путь: установка отменена")
        root.mkdir(parents=True, exist_ok=True)
        if platform == "macos":
            _ditto(zip_path, root)
        else:
            archive.extractall(root)
    if platform == "windows":
        if not (root / WINDOWS_EXE).is_file():
            raise InstallError("В архиве нет приложения GMAGC")
        return root
    apps = [item for item in root.iterdir() if item.suffix == ".app"]
    if len(apps) != 1:
        raise InstallError("В архиве нет приложения GMAGC")
    return apps[0]


def windows_script(*, pid: int, staged: str, target: str, backup: str, exe: str, log: str) -> str:
    """Пакетный файл: ждёт выхода приложения, копирует прежнюю версию в резерв, ставит новую, при сбое возвращает резерв."""

    def value(text: str) -> str:
        return text.replace("%", "%%")  # процент в пути иначе разворачивается cmd

    lines = [
        "@echo off",
        "chcp 65001 >nul",
        f'set "PID={int(pid)}"',
        f'set "SRC={value(staged)}"',
        f'set "DST={value(target)}"',
        f'set "BAK={value(backup)}"',
        f'set "EXE={value(exe)}"',
        f'set "LOG={value(log)}"',
        'echo waiting for the application to exit > "%LOG%"',
        ":wait",
        'tasklist /FI "PID eq %PID%" /NH 2>nul | findstr /C:" %PID% " >nul',
        "if not errorlevel 1 (",
        "  ping -n 2 127.0.0.1 >nul",
        "  goto wait",
        ")",
        'if exist "%BAK%" rmdir /s /q "%BAK%"',
        'robocopy "%DST%" "%BAK%" /E /R:2 /W:1 /NFL /NDL /NJH /NJS /NP >> "%LOG%" 2>&1',
        "if errorlevel 8 goto restore",
        'robocopy "%SRC%" "%DST%" /E /R:3 /W:2 /NFL /NDL /NJH /NJS /NP >> "%LOG%" 2>&1',
        "if errorlevel 8 goto restore",
        'echo updated >> "%LOG%"',
        "goto launch",
        ":restore",
        'echo update failed, restoring the previous version >> "%LOG%"',
        'robocopy "%BAK%" "%DST%" /E /R:3 /W:2 /NFL /NDL /NJH /NJS /NP >> "%LOG%" 2>&1',
        ":launch",
        'start "" "%EXE%"',
        'rmdir /s /q "%SRC%" 2>nul',
        '(goto) 2>nul & del "%~f0"',
    ]
    return "\r\n".join(lines) + "\r\n"


def macos_script(*, pid: int, staged: str, target: str, backup: str, log: str) -> str:
    quote = shlex.quote
    lines = [
        "#!/bin/sh",
        f"PID={int(pid)}",
        f"SRC={quote(staged)}",
        f"DST={quote(target)}",
        f"BAK={quote(backup)}",
        f"LOG={quote(log)}",
        'while kill -0 "$PID" 2>/dev/null; do sleep 1; done',
        'rm -rf "$BAK"',
        'if ! mv "$DST" "$BAK"; then echo "cannot move the old version" >> "$LOG"; open "$DST"; exit 1; fi',
        'if ! ditto "$SRC" "$DST" >> "$LOG" 2>&1; then',
        '  echo "update failed, restoring the previous version" >> "$LOG"',
        '  rm -rf "$DST"; mv "$BAK" "$DST"',
        "fi",
        'open "$DST"',
        'rm -rf "$SRC"',
        'rm -f -- "$0"',
    ]
    return "\n".join(lines) + "\n"


def write_helper(
    platform: str, work_dir: Path, *, pid: int, staged: Path, target: Path, exe: Path, backup: Path, log: Path
) -> Path:
    work_dir.mkdir(parents=True, exist_ok=True)
    if platform == "windows":
        script = work_dir / "apply-update.cmd"
        text = windows_script(pid=pid, staged=str(staged), target=str(target), backup=str(backup), exe=str(exe), log=str(log))
        script.write_bytes(text.encode("utf-8"))  # UTF-8 без BOM: cmd читает его после chcp 65001
        return script
    if platform == "macos":
        script = work_dir / "apply-update.sh"
        script.write_text(
            macos_script(pid=pid, staged=str(staged), target=str(target), backup=str(backup), log=str(log)),
            encoding="utf-8",
            newline="\n",
        )
        script.chmod(0o755)
        return script
    raise InstallError("Обновление из приложения на этой платформе не поддерживается")


def launch_helper(script: Path, platform: str) -> None:
    """Запускает помощника отдельным процессом без окна: он переживёт закрытие приложения."""
    quiet = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    try:
        if platform == "windows":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            subprocess.Popen(
                ["cmd.exe", "/d", "/c", "call", str(script)],
                creationflags=flags,
                close_fds=True,
                cwd=tempfile.gettempdir(),
                **quiet,
            )
        else:
            subprocess.Popen(
                ["/bin/sh", str(script)], start_new_session=True, close_fds=True, cwd=tempfile.gettempdir(), **quiet
            )
    except OSError as error:
        raise InstallError(f"Не удалось запустить установщик обновления: {error}") from error
```

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest tests/desktop/test_update_installer.py -q`
Expected: PASS. Если тест на `..\\evil.txt` не проходит на Linux (обратный слэш там обычный символ имени), оставить в параметрах только пути с `/`.

- [ ] **Step 5: Lint and commit**

```bash
.venv/Scripts/python.exe -m ruff check --fix . && .venv/Scripts/python.exe -m pytest -q
git add apps/desktop/src/gmagc_desktop/update tests/desktop
git commit -m "feat: download, verify, stage and apply an update of the desktop app" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: Менеджер обновлений (`gmagc_desktop/update/manager.py`)

**Files:**
- Create: `apps/desktop/src/gmagc_desktop/update/manager.py`
- Test: `tests/desktop/test_update_manager.py`

**Interfaces:**
- Consumes: `installer` (Task 3), `gmagc_common.updates` (Task 1), `SearchService.set_check_updates`, `mark_update_checked`, `skip_update`, `settings` (Task 2).
- Produces: `UpdateOffer(release, can_install, reason="")`; `UpdateManager(service, data_dir, current_version=VERSION, platform=None, executable=None, fetch=fetch_latest, now=time.time, launch=launch_helper, pid=None)` с методами `check(*, force=False) -> UpdateOffer | None` (`UpdateCheckError` пробрасывается), `install(offer, progress=None, cancel=None) -> Path` (путь скрипта; `InstallError`, `InstallCancelled`), `skip(version)`, `cleanup()`.

- [ ] **Step 1: Write the failing tests**

```python
# path: tests/desktop/test_update_manager.py
import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from gmagc_common.updates import ReleaseInfo, UpdateCheckError, fetch_latest
from gmagc_desktop.service.search_service import SearchService
from gmagc_desktop.update import manager as manager_module
from gmagc_desktop.update.installer import InstallCancelled, InstallError
from gmagc_desktop.update.manager import UpdateManager
from tests.updates_stub import release_json, stub_server

NOW = 1_800_000_000.0
DAY = 24 * 3600


def app_zip():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("gmagc-desktop.exe", b"MZ-new")
        archive.writestr("data/app.bin", b"new data")
    return buffer.getvalue()


@pytest.fixture()
def service(tmp_path):
    instance = SearchService(tmp_path / "data")
    instance.load()
    return instance


@pytest.fixture()
def install_dir(tmp_path):
    folder = tmp_path / "Apps" / "GMAGC"
    folder.mkdir(parents=True)
    (folder / "gmagc-desktop.exe").write_bytes(b"MZ-old")
    return folder


def release(version="0.6.0", platforms=("windows", "macos", "android")):
    return ReleaseInfo.from_api(release_json(version, "https://example.invalid", platforms=platforms))


def make_manager(service, tmp_path, install_dir, *, fetch=None, launched=None, **options):
    return UpdateManager(
        service,
        tmp_path / "data",
        current_version=options.pop("current_version", "0.5.1"),
        platform=options.pop("platform", "windows"),
        executable=options.pop("executable", install_dir / "gmagc-desktop.exe"),
        fetch=fetch or (lambda version: release()),
        now=lambda: NOW,
        launch=(lambda script, platform: launched.append((script, platform))) if launched is not None else (lambda s, p: None),
        pid=4242,
        **options,
    )


def test_a_recent_check_and_a_disabled_check_do_not_touch_the_network(service, tmp_path, install_dir):
    def forbidden(version):
        raise AssertionError("сеть не должна вызываться")

    manager = make_manager(service, tmp_path, install_dir, fetch=forbidden)
    service.mark_update_checked(NOW - 3600)
    assert manager.check() is None

    service.mark_update_checked(0)
    service.set_check_updates(False)
    assert manager.check() is None


def test_a_forced_check_ignores_the_schedule_and_the_switch(service, tmp_path, install_dir):
    service.set_check_updates(False)
    service.mark_update_checked(NOW - 60)
    manager = make_manager(service, tmp_path, install_dir)

    offer = manager.check(force=True)

    assert offer.release.version == "0.6.0" and offer.can_install is True and offer.reason == ""


def test_a_due_check_offers_a_newer_version_and_records_the_time(service, tmp_path, install_dir):
    manager = make_manager(service, tmp_path, install_dir)

    offer = manager.check()

    assert offer.release.version == "0.6.0" and service.settings.last_update_check == NOW


def test_no_newer_version_gives_none_but_still_records_the_check(service, tmp_path, install_dir):
    manager = make_manager(service, tmp_path, install_dir, fetch=lambda version: None)

    assert manager.check() is None
    assert service.settings.last_update_check == NOW


def test_a_failed_check_propagates_and_is_not_recorded(service, tmp_path, install_dir):
    def broken(version):
        raise UpdateCheckError("Нет связи с GitHub")

    manager = make_manager(service, tmp_path, install_dir, fetch=broken)

    with pytest.raises(UpdateCheckError):
        manager.check()

    assert service.settings.last_update_check == 0.0


def test_a_skipped_version_is_hidden_from_the_background_check_but_shown_on_demand(service, tmp_path, install_dir):
    manager = make_manager(service, tmp_path, install_dir)
    manager.skip("0.6.0")

    assert manager.check() is None
    assert manager.check(force=True).release.version == "0.6.0"
    assert service.settings.skipped_version == "0.6.0"

    manager = make_manager(service, tmp_path, install_dir, fetch=lambda version: release("0.7.0"))
    service.mark_update_checked(0)
    assert manager.check().release.version == "0.7.0"


def test_a_platform_without_a_file_cannot_install_from_the_app(service, tmp_path, install_dir):
    manager = make_manager(service, tmp_path, install_dir, fetch=lambda version: release(platforms=("android",)))

    offer = manager.check(force=True)

    assert offer.can_install is False and "нет готового файла" in offer.reason


def test_a_run_from_source_cannot_install_from_the_app(service, tmp_path, install_dir):
    manager = make_manager(service, tmp_path, install_dir, executable=Path("C:/Python312/python.exe"))

    offer = manager.check(force=True)

    assert offer.can_install is False and "не из собранной папки" in offer.reason


def test_a_release_without_a_checksum_cannot_install_from_the_app(service, tmp_path, install_dir):
    def without_sum(version):
        base = release()
        kept = tuple(a for a in base.assets if not a.name.endswith(".sha256"))
        return ReleaseInfo(base.version, base.tag, base.notes, base.page_url, kept)

    manager = make_manager(service, tmp_path, install_dir, fetch=without_sum)

    offer = manager.check(force=True)

    assert offer.can_install is False and "контрольной суммы" in offer.reason


def test_a_read_only_install_folder_cannot_install_from_the_app(service, tmp_path, install_dir, monkeypatch):
    monkeypatch.setattr(manager_module, "is_writable", lambda path: False)
    manager = make_manager(service, tmp_path, install_dir)

    offer = manager.check(force=True)

    assert offer.can_install is False and "нет прав на запись" in offer.reason.lower()


def serve_release(monkeypatch, zip_bytes, sha=None):
    """Поддельный GitHub с релизом 0.6.0 для Windows; GMAGC_UPDATE_URL разрешает локальные адреса."""
    routes = {}
    name = "GMAGC-desktop-windows-0.6.0.zip"
    server = stub_server(routes)
    base = server.__enter__()
    routes["/latest"] = {"body": json.dumps(release_json("0.6.0", base, platforms=("windows",))).encode()}
    routes[f"/{name}"] = {"body": zip_bytes}
    routes[f"/{name}.sha256"] = {"body": f"{sha or hashlib.sha256(zip_bytes).hexdigest()}  {name}\n".encode()}
    monkeypatch.setenv("GMAGC_UPDATE_URL", f"{base}/latest")
    return base, server


def test_install_downloads_verifies_stages_writes_the_helper_and_launches_it(service, tmp_path, install_dir, monkeypatch):
    base, server = serve_release(monkeypatch, app_zip())
    launched, steps = [], []
    try:
        manager = make_manager(
            service, tmp_path, install_dir, launched=launched,
            fetch=lambda version: fetch_latest(version, url=f"{base}/latest", allow_local=True),
        )
        offer = manager.check(force=True)
        assert offer.can_install

        script = manager.install(offer, progress=lambda done, total: steps.append((done, total)))
    finally:
        server.__exit__(None, None, None)

    work = tmp_path / "data" / "updates" / "0.6.0"
    assert script == work / "apply-update.cmd" and launched == [(script, "windows")]
    assert (work / "staged" / "gmagc-desktop.exe").read_bytes() == b"MZ-new"
    assert (work / "staged" / "data" / "app.bin").read_bytes() == b"new data"
    assert not list(work.glob("*.zip")) and steps
    text = script.read_text(encoding="utf-8")
    assert 'set "PID=4242"' in text and str(install_dir) in text and str(install_dir) + ".previous" in text
    assert str(tmp_path / "data" / "update.log") in text
    assert (install_dir / "gmagc-desktop.exe").read_bytes() == b"MZ-old"  # до перезапуска ничего не тронуто


def test_a_wrong_checksum_stops_the_installation_before_anything_is_launched(service, tmp_path, install_dir, monkeypatch):
    base, server = serve_release(monkeypatch, app_zip(), sha="0" * 64)
    launched = []
    try:
        manager = make_manager(
            service, tmp_path, install_dir, launched=launched,
            fetch=lambda version: fetch_latest(version, url=f"{base}/latest", allow_local=True),
        )
        offer = manager.check(force=True)
        with pytest.raises(InstallError):
            manager.install(offer)
    finally:
        server.__exit__(None, None, None)

    assert launched == [] and (install_dir / "gmagc-desktop.exe").read_bytes() == b"MZ-old"


def test_cancelling_the_installation_launches_nothing(service, tmp_path, install_dir, monkeypatch):
    base, server = serve_release(monkeypatch, app_zip())
    launched = []
    try:
        manager = make_manager(
            service, tmp_path, install_dir, launched=launched,
            fetch=lambda version: fetch_latest(version, url=f"{base}/latest", allow_local=True),
        )
        offer = manager.check(force=True)
        with pytest.raises(InstallCancelled):
            manager.install(offer, cancel=lambda: True)
    finally:
        server.__exit__(None, None, None)

    assert launched == []


def test_installing_an_offer_that_cannot_be_installed_is_refused(service, tmp_path, install_dir):
    manager = make_manager(service, tmp_path, install_dir, fetch=lambda version: release(platforms=("android",)))
    offer = manager.check(force=True)

    with pytest.raises(InstallError) as error:
        manager.install(offer)

    assert "нет готового файла" in str(error.value)


def test_cleanup_removes_leftovers_of_earlier_updates(service, tmp_path, install_dir):
    leftovers = tmp_path / "data" / "updates" / "0.5.9" / "staged"
    leftovers.mkdir(parents=True)
    (leftovers / "x.bin").write_bytes(b"1")
    manager = make_manager(service, tmp_path, install_dir)

    manager.cleanup()

    assert not (tmp_path / "data" / "updates").exists()
    manager.cleanup()  # повторный вызов безопасен
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/desktop/test_update_manager.py -q`
Expected: FAIL (`ModuleNotFoundError: gmagc_desktop.update.manager`).

- [ ] **Step 3: Write the implementation**

```python
# path: apps/desktop/src/gmagc_desktop/update/manager.py
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
            return UpdateOffer(release, False, f"Нет прав на запись в папку приложения ({target}): скачайте обновление вручную.")
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
```

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest tests/desktop/test_update_manager.py -q`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
.venv/Scripts/python.exe -m ruff check --fix . && .venv/Scripts/python.exe -m pytest -q
git add apps/desktop/src/gmagc_desktop/update tests/desktop
git commit -m "feat: update manager that checks, offers and installs desktop updates" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---
### Task 5: Полоса обновления в ПК-приложении

**Files:**
- Create: `apps/desktop/src/gmagc_desktop/ui/update_bar.py`, `tests/desktop/test_update_bar.py`
- Modify: `apps/desktop/src/gmagc_desktop/ui/app.py`, `tests/fakes.py` (`FakeUpdates`), `tests/desktop/test_desktop_ui.py` и `tests/desktop/test_phone_ui.py` (в `make_app`: `services.setdefault("updates", None)`)

**Interfaces:**
- Consumes: `UpdateManager` (`check`, `install`, `skip`, `cleanup`), `UpdateOffer`, `InstallError`, `InstallCancelled`, `UpdateCheckError`, `SearchService.set_check_updates`, `settings.check_updates`.
- Produces: `UpdateBar(page, service, updates, *, open_url=webbrowser.open, quit_app=None, delay=5.0)` c контролами `container`, `switch`, `check_button`, `status` и методами `start()`, `on_check(_event)`, `on_update_now(_event)`, `on_skip(_event)`, `on_release_page(_event)`, `on_cancel(_event)`, `on_toggle(_event)`; `DesktopApp(..., updates=None, open_url=webbrowser.open, quit_app=None, update_delay=5.0)`; `build_page` создаёт `UpdateManager` сам, если `updates` не передан (`updates=None` отключает обновления).

- [ ] **Step 1: Write the failing tests and the fake**

В `tests/fakes.py` добавить (импорты `Path` из `pathlib` и `InstallCancelled` из `gmagc_desktop.update.installer`):

```python
class FakeUpdates:
    """Замена UpdateManager: запоминает вызовы, ответы задаются в тесте."""

    def __init__(self, offer=None, check_error=None, install_error=None):
        self.offer = offer
        self.check_error = check_error
        self.install_error = install_error
        self.checks = []
        self.skipped = []
        self.installs = []
        self.cleaned = 0
        self.progress_steps = ((5_000_000, 10_000_000), (10_000_000, 10_000_000))
        self.during_install = None  # вызывается между шагами загрузки (например, нажатие «Отмена»)

    def cleanup(self):
        self.cleaned += 1

    def check(self, *, force=False):
        self.checks.append(force)
        if self.check_error:
            raise self.check_error
        return self.offer

    def skip(self, version):
        self.skipped.append(version)

    def install(self, offer, progress=None, cancel=None):
        self.installs.append(offer)
        if self.install_error:
            raise self.install_error
        for done, total in self.progress_steps:
            if progress:
                progress(done, total)
            if self.during_install:
                self.during_install()
            if cancel and cancel():
                raise InstallCancelled()
        return Path("apply-update.cmd")
```

```python
# path: tests/desktop/test_update_bar.py
import threading
from types import SimpleNamespace

import pytest

from gmagc_common.updates import ReleaseInfo, UpdateCheckError
from gmagc_desktop.about import VERSION
from gmagc_desktop.service.search_service import SearchService
from gmagc_desktop.ui import update_bar as update_bar_module
from gmagc_desktop.ui.update_bar import UpdateBar
from gmagc_desktop.update.installer import InstallError
from gmagc_desktop.update.manager import UpdateOffer
from tests.fakes import FakeUpdates, StubPage
from tests.updates_stub import release_json


def offer(can_install=True, reason="", version="0.9.0"):
    release = ReleaseInfo.from_api(release_json(version, "https://example.invalid"))
    return UpdateOffer(release, can_install, reason)


def make(tmp_path, updates, **options):
    service = SearchService(tmp_path / "data")
    service.load()
    opened, quits = [], []
    page = StubPage()
    bar = UpdateBar(
        page,
        service,
        updates,
        open_url=opened.append,
        quit_app=lambda: quits.append(1),
        delay=0,
        **options,
    )
    return bar, service, page, opened, quits


def test_the_startup_check_cleans_up_and_shows_a_newer_version(tmp_path):
    updates = FakeUpdates(offer())
    bar, _, _, _, _ = make(tmp_path, updates)

    bar.start()

    assert updates.cleaned == 1 and updates.checks == [False]
    assert bar.container.visible and bar.text.value == f"Доступна версия 0.9.0 (у вас {VERSION})"
    assert bar.now_button.visible and bar.skip_button.visible and bar.page_button.visible
    assert not bar.note.visible and not bar.progress.visible and not bar.cancel_button.visible


def test_a_disabled_check_does_nothing_at_startup(tmp_path):
    updates = FakeUpdates(offer())
    bar, service, _, _, _ = make(tmp_path, updates)
    service.set_check_updates(False)

    bar.start()

    assert updates.checks == [] and updates.cleaned == 0 and not bar.container.visible


def test_no_newer_version_keeps_the_bar_hidden_and_a_failed_background_check_is_silent(tmp_path):
    bar, _, _, _, _ = make(tmp_path, FakeUpdates(offer=None))
    bar.start()
    assert not bar.container.visible and bar.status.value == ""

    bar, _, _, _, _ = make(tmp_path, FakeUpdates(check_error=UpdateCheckError("Нет связи с GitHub")))
    bar.start()
    assert not bar.container.visible and bar.status.value == ""

    bar, _, _, _, _ = make(tmp_path, FakeUpdates(check_error=RuntimeError("неожиданно")))
    bar.start()
    assert not bar.container.visible and bar.status.value == ""


def test_a_manual_check_reports_every_outcome(tmp_path):
    bar, _, _, _, _ = make(tmp_path, FakeUpdates(offer=None))
    bar.on_check(None)
    assert bar.status.value == f"Установлена последняя версия ({VERSION})"

    bar, _, _, _, _ = make(tmp_path, FakeUpdates(check_error=UpdateCheckError("Нет связи с GitHub")))
    bar.on_check(None)
    assert bar.status.value == "Нет связи с GitHub"

    bar, _, _, _, _ = make(tmp_path, FakeUpdates(check_error=RuntimeError("сбой")))
    bar.on_check(None)
    assert "Ошибка проверки обновлений: сбой" in bar.status.value

    updates = FakeUpdates(offer())
    bar, _, _, _, _ = make(tmp_path, updates)
    bar.on_check(None)
    assert updates.checks == [True] and bar.container.visible and bar.status.value == ""


def test_an_offer_that_cannot_be_installed_shows_why_and_only_offers_the_release_page(tmp_path):
    bar, _, _, opened, _ = make(tmp_path, FakeUpdates(offer(False, "Нет прав на запись в папку приложения")))

    bar.start()

    assert bar.note.visible and "Нет прав на запись" in bar.note.value
    assert not bar.now_button.visible and bar.page_button.content.value == "Открыть страницу релиза"
    bar.on_release_page(None)
    assert opened == ["https://example.invalid/releases/tag/v0.9.0"]


def test_the_release_notes_button_opens_the_release_page(tmp_path):
    bar, _, _, opened, _ = make(tmp_path, FakeUpdates(offer()))
    bar.start()

    assert bar.page_button.content.value == "Что нового"
    bar.on_release_page(None)

    assert opened == ["https://example.invalid/releases/tag/v0.9.0"]


def test_skipping_remembers_the_version_and_hides_the_bar(tmp_path):
    updates = FakeUpdates(offer())
    bar, _, _, _, _ = make(tmp_path, updates)
    bar.start()

    bar.on_skip(None)

    assert updates.skipped == ["0.9.0"] and not bar.container.visible


def test_installing_shows_progress_and_quits_the_app_when_done(tmp_path):
    updates = FakeUpdates(offer())
    bar, _, _, _, quits = make(tmp_path, updates)
    bar.start()
    seen = []
    original = updates.install

    def spy(offer_, progress=None, cancel=None):
        seen.append((bar.now_button.disabled, bar.progress.visible, bar.cancel_button.visible))
        return original(offer_, progress=progress, cancel=cancel)

    updates.install = spy

    bar.on_update_now(None)

    assert seen == [(True, True, True)] and len(updates.installs) == 1
    assert bar.progress.value == 1.0 and "перезапуск" in bar.text.value.lower() and quits == [1]


def test_a_progress_message_shows_megabytes(tmp_path):
    updates = FakeUpdates(offer())
    updates.progress_steps = ((5_000_000, 10_000_000),)
    bar, _, _, _, _ = make(tmp_path, updates)
    bar.start()
    texts = []
    updates.during_install = lambda: texts.append(bar.note.value)

    bar.on_update_now(None)

    assert texts == ["Скачивание: 5 из 10 МБ"]


def test_a_failed_installation_shows_the_reason_and_the_fallback_and_keeps_running(tmp_path):
    updates = FakeUpdates(offer(), install_error=InstallError("Контрольная сумма не совпала"))
    bar, _, _, _, quits = make(tmp_path, updates)
    bar.start()

    bar.on_update_now(None)

    assert quits == [] and bar.note.visible and "Контрольная сумма не совпала" in bar.note.value
    assert "странице релиза" in bar.note.value
    assert bar.now_button.visible and not bar.now_button.disabled and not bar.progress.visible and not bar.cancel_button.visible


def test_cancelling_the_download_stops_it_without_quitting(tmp_path):
    updates = FakeUpdates(offer())
    bar, _, _, _, quits = make(tmp_path, updates)
    bar.start()
    updates.during_install = lambda: bar.on_cancel(None)

    bar.on_update_now(None)

    assert quits == [] and "Загрузка отменена" in bar.note.value and not bar.cancel_button.visible


def test_a_second_click_while_installing_is_ignored(tmp_path):
    updates = FakeUpdates(offer())
    bar, _, _, _, _ = make(tmp_path, updates)
    bar.start()
    updates.during_install = lambda: bar.on_update_now(None)

    bar.on_update_now(None)

    assert len(updates.installs) == 1


def test_the_switch_persists_the_choice(tmp_path):
    bar, service, _, _, _ = make(tmp_path, FakeUpdates())
    assert bar.switch.value is True

    bar.switch.value = False
    bar.on_toggle(None)

    assert service.settings.check_updates is False


def test_the_switch_starts_from_the_saved_setting(tmp_path):
    service = SearchService(tmp_path / "data")
    service.load()
    service.set_check_updates(False)
    bar = UpdateBar(StubPage(), service, FakeUpdates(), delay=0)

    assert bar.switch.value is False


def test_the_default_quit_closes_the_window_and_arms_a_fallback_exit(tmp_path, monkeypatch):
    timers = []

    class FakeTimer:
        def __init__(self, seconds, function, args):
            timers.append((seconds, function, args))

        def start(self):
            timers[-1] += ("started",)

    monkeypatch.setattr(update_bar_module.threading, "Timer", FakeTimer)
    service = SearchService(tmp_path / "data")
    service.load()
    page = StubPage()
    page.window = SimpleNamespace(destroy=lambda: None)
    tasks = []
    page.run_task = lambda handler, *args: tasks.append(handler)
    bar = UpdateBar(page, service, FakeUpdates(), delay=0)

    bar.quit_app()

    assert tasks == [page.window.destroy]
    assert timers and timers[0][0] > 0 and timers[0][-1] == "started"
    assert threading.active_count() >= 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/desktop/test_update_bar.py -q`
Expected: FAIL (`ModuleNotFoundError: gmagc_desktop.ui.update_bar`).

- [ ] **Step 3: Write the implementation**

```python
# path: apps/desktop/src/gmagc_desktop/ui/update_bar.py
"""Полоса обновления ПК-приложения: предложение новой версии, загрузка, «Пропустить», ручная проверка."""

from __future__ import annotations

import os
import threading
import time
import webbrowser
from collections.abc import Callable

import flet as ft

from gmagc_common.updates import UpdateCheckError
from gmagc_desktop.about import VERSION
from gmagc_desktop.service.search_service import SearchService
from gmagc_desktop.update.installer import InstallCancelled, InstallError
from gmagc_desktop.update.manager import UpdateOffer

MANUAL_FALLBACK = " Можно скачать обновление вручную на странице релиза."
EXIT_FALLBACK_SECONDS = 4.0  # если окно не закрылось само, процесс завершается: помощнику нужно, чтобы приложение вышло


class UpdateBar:
    def __init__(
        self,
        page: ft.Page,
        service: SearchService,
        updates,
        *,
        open_url: Callable[[str], object] = webbrowser.open,
        quit_app: Callable[[], None] | None = None,
        delay: float = 5.0,
    ):
        self.page = page
        self.service = service
        self.updates = updates
        self.open_url = open_url
        self.quit_app = quit_app or self._default_quit
        self.delay = delay
        self.offer: UpdateOffer | None = None
        self._cancel = False
        self._installing = False

        self.text = ft.Text("", weight=ft.FontWeight.BOLD)
        self.note = ft.Text("", size=12, visible=False, selectable=True)
        self.progress = ft.ProgressBar(value=0, visible=False)
        self.now_button = ft.Button("Обновить", on_click=self.on_update_now)
        self.page_button = ft.TextButton(content=ft.Text("Что нового"), on_click=self.on_release_page)
        self.skip_button = ft.TextButton(content=ft.Text("Пропустить"), on_click=self.on_skip)
        self.cancel_button = ft.Button("Отмена", on_click=self.on_cancel, visible=False)
        self.container = ft.Container(
            ft.Column(
                [
                    self.text,
                    self.note,
                    self.progress,
                    ft.Row(
                        [self.now_button, self.page_button, self.skip_button, self.cancel_button], spacing=8, wrap=True
                    ),
                ],
                spacing=6,
            ),
            padding=10,
            border_radius=6,
            bgcolor=ft.Colors.BLUE_100,
            visible=False,
        )
        self.status = ft.Text("", size=12)
        self.switch = ft.Switch(
            label="Проверять обновления при запуске", value=service.settings.check_updates, on_change=self.on_toggle
        )
        self.check_button = ft.TextButton(content=ft.Text("Проверить обновления", size=12), on_click=self.on_check)

    # ---- проверка ----------------------------------------------------------------
    def start(self) -> None:
        """Фоновая проверка через delay секунд после запуска (если она включена в настройках)."""
        if self.updates is not None and self.service.settings.check_updates:
            self.page.run_thread(self._startup_check)

    def _startup_check(self) -> None:
        self.updates.cleanup()
        time.sleep(self.delay)
        self._run_check(force=False)

    def on_check(self, _event) -> None:
        if self.updates is None:
            return
        self._set_status("Проверяю обновления…")
        self.page.run_thread(lambda: self._run_check(force=True))

    def _run_check(self, *, force: bool) -> None:
        try:
            offer = self.updates.check(force=force)
        except UpdateCheckError as error:
            if force:
                self._set_status(str(error))
            return
        except Exception as error:  # noqa: BLE001 - проверка не должна ни ронять приложение, ни шуметь
            if force:
                self._set_status(f"Ошибка проверки обновлений: {error}")
            return
        if offer is None:
            self._set_status(f"Установлена последняя версия ({VERSION})" if force else "")
            return
        self._show_offer(offer)

    def _set_status(self, text: str) -> None:
        self.status.value = text
        self.page.update()

    def _show_offer(self, offer: UpdateOffer) -> None:
        self.offer = offer
        self.text.value = f"Доступна версия {offer.release.version} (у вас {VERSION})"
        self.note.value = offer.reason
        self.note.visible = bool(offer.reason)
        self.now_button.visible = offer.can_install
        self.page_button.content.value = "Что нового" if offer.can_install else "Открыть страницу релиза"
        self.container.visible = True
        self.status.value = ""
        self.page.update()

    # ---- кнопки полосы ------------------------------------------------------------------
    def on_release_page(self, _event) -> None:
        if self.offer is not None:
            self.open_url(self.offer.release.page_url)

    def on_skip(self, _event) -> None:
        if self.offer is not None:
            self.updates.skip(self.offer.release.version)
        self.container.visible = False
        self.page.update()

    def on_cancel(self, _event) -> None:
        self._cancel = True

    def on_toggle(self, _event) -> None:
        self.service.set_check_updates(bool(self.switch.value))

    def on_update_now(self, _event) -> None:
        if self.offer is None or not self.offer.can_install or self._installing:
            return
        self._installing = True
        self._cancel = False
        self.now_button.disabled = self.skip_button.disabled = self.page_button.disabled = True
        self.cancel_button.visible = True
        self.progress.value = 0
        self.progress.visible = True
        self.note.value = "Скачивание…"
        self.note.visible = True
        self.page.update()
        self.page.run_thread(self._install_worker)

    def _install_worker(self) -> None:
        try:
            self.updates.install(self.offer, progress=self._on_progress, cancel=lambda: self._cancel)
        except InstallCancelled:
            self._install_failed("Загрузка отменена.")
        except (InstallError, UpdateCheckError) as error:
            self._install_failed(f"{error}.{MANUAL_FALLBACK}".replace("..", "."))
        except Exception as error:  # noqa: BLE001 - рабочий поток обязан показать причину, а не пропасть
            self._install_failed(f"Ошибка обновления: {error}.{MANUAL_FALLBACK}")
        else:
            self.progress.value = 1.0
            self.text.value = "Обновление скачано, приложение перезапускается…"
            self.note.visible = False
            self.cancel_button.visible = False
            self.page.update()
            self.quit_app()

    def _on_progress(self, done: int, total: int) -> None:
        self.progress.value = done / total if total else 0
        self.note.value = f"Скачивание: {done // 1_000_000} из {total // 1_000_000} МБ" if total else "Скачивание…"
        self.page.update()

    def _install_failed(self, text: str) -> None:
        self._installing = False
        self.now_button.disabled = self.skip_button.disabled = self.page_button.disabled = False
        self.cancel_button.visible = False
        self.progress.visible = False
        self.note.value = text
        self.note.visible = True
        self.page.update()

    def _default_quit(self) -> None:
        """Закрывает окно; если оно не закрылось, процесс завершается через несколько секунд."""
        timer = threading.Timer(EXIT_FALLBACK_SECONDS, os._exit, [0])
        timer.daemon = True
        timer.start()
        self.page.run_task(self.page.window.destroy)
```

Правки `apps/desktop/src/gmagc_desktop/ui/app.py` (Edit-ами):

1. Импорты: `import webbrowser` (после `import os`); `from gmagc_desktop.ui.update_bar import UpdateBar` и `from gmagc_desktop.update.manager import UpdateManager` (в общий блок `gmagc_desktop`).
2. В `DesktopApp.__init__` в параметры после `qr: Callable[[str], bytes] = qr_png,` добавить:

```python
        updates=None,
        open_url: Callable[[str], object] = webbrowser.open,
        quit_app: Callable[[], None] | None = None,
        update_delay: float = 5.0,
```

а после `self.history: list[RequestRecord] = []` (или рядом с другими полями) добавить:

```python
        self.update_bar = (
            UpdateBar(page, service, updates, open_url=open_url, quit_app=quit_app, delay=update_delay)
            if updates is not None
            else None
        )
```

3. В `build()` после строки `self.status_label.value = status_text(status)` добавить (значение выключателя берётся из загруженных настроек):

```python
        if self.update_bar is not None:
            self.update_bar.switch.value = self.service.settings.check_updates
```

в левую колонку `left = ft.Column([...])` после `self.history_column,` добавить `*([self.update_bar.switch] if self.update_bar else []),`; в `footer = ft.Row([...])` после `self.check_label,` добавить `*([self.update_bar.check_button, self.update_bar.status] if self.update_bar else []),`; в основную колонку `ft.Column([ft.Row([left, ft.VerticalDivider(), right], ...), footer], expand=True)` перед `ft.Row([left, ...` вставить `*([self.update_bar.container] if self.update_bar else []),`; после `self.page.add(...)` (перед блоком `demo_photo`) добавить:

```python
        if self.update_bar is not None:
            self.update_bar.start()
```

4. В `build_page` перед `app = DesktopApp(...)` заменить создание на:

```python
    service = service or SearchService(data_dir())
    if "updates" not in services:  # updates=None в тестах отключает обновления
        services["updates"] = UpdateManager(service, data_dir())
    app = DesktopApp(page, service, **services)
```

В `tests/desktop/test_desktop_ui.py` и `tests/desktop/test_phone_ui.py` в `make_app` добавить `services.setdefault("updates", None)` перед созданием страницы.

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest tests/desktop -q`
Expected: PASS (новые тесты полосы и прежние тесты экрана).

- [ ] **Step 5: Lint and commit**

```bash
.venv/Scripts/python.exe -m ruff check --fix . && .venv/Scripts/python.exe -m pytest -q
git add apps/desktop/src/gmagc_desktop/ui tests
git commit -m "feat: update bar in the desktop app with install, skip and manual check" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6: Обновление в Android-приложении

**Files:**
- Create: `apps/mobile/src/gmagc_mobile/updates.py`, `apps/mobile/src/gmagc_mobile/update_bar.py`, `tests/mobile/test_mobile_updates.py`
- Modify: `apps/mobile/src/gmagc_mobile/app.py`, `tests/fakes_mobile.py`, `tests/mobile/test_mobile_app.py`

**Interfaces:**
- Consumes: `gmagc_common.updates` (`fetch_latest`, `pick_assets`, `check_due`, `UpdateCheckError`), `gmagc_mobile.about.VERSION`.
- Produces: `UpdateNotice(version, url, page_url)`; `UpdateTracker(prefs, current_version=VERSION, fetch=fetch_latest, now=time.time)` с async `enabled()`, `set_enabled(bool)`, `check(*, force=False) -> UpdateNotice | None`, `skip(version)`; `UpdateBar(tracker, launcher, page, delay=3.0)` с контролами `container`, `switch`, `check_button`, `status` и async `startup()`, `check(force)`, `on_download`, `on_skip`, `on_toggle`, `on_check_now`; `MobileApp(..., tracker=None, launcher=None, check_on_start=True, update_delay=3.0)`.

- [ ] **Step 1: Write the failing tests**

В `tests/fakes_mobile.py` добавить заглушку загрузчика ссылок:

```python
class FakeLauncher:
    """Замена ft.UrlLauncher."""

    def __init__(self):
        self.opened = []

    async def launch_url(self, url, **kwargs):
        self.opened.append(url)
```

```python
# path: tests/mobile/test_mobile_updates.py
import asyncio

import flet as ft
import pytest

from gmagc_common.updates import ReleaseInfo, UpdateCheckError
from gmagc_mobile.about import VERSION
from gmagc_mobile.app import MobileApp
from gmagc_mobile.camera import CameraController
from gmagc_mobile.store import ConnectionStore
from gmagc_mobile.update_bar import UpdateBar
from gmagc_mobile.updates import KEY_ENABLED, KEY_LAST, KEY_SKIPPED, UpdateTracker
from tests.fakes import FakeClipboard, FakePicker, StubPage
from tests.fakes_mobile import FakeCameraApi, FakeLauncher, FakePermission, FakePrefs, Script
from tests.updates_stub import release_json

NOW = 1_800_000_000.0


def release(version="0.9.0", platforms=("windows", "macos", "android")):
    return ReleaseInfo.from_api(release_json(version, "https://example.invalid", platforms=platforms))


def tracker(prefs=None, fetch=None, now=NOW):
    return UpdateTracker(prefs if prefs is not None else FakePrefs(), current_version="0.5.2", fetch=fetch or (lambda v: release()), now=lambda: now)


def run(coroutine):
    return asyncio.run(coroutine)


def test_a_newer_release_gives_a_notice_with_the_apk_link_and_records_the_check():
    prefs = FakePrefs()

    notice = run(tracker(prefs).check())

    assert notice.version == "0.9.0" and notice.url == "https://example.invalid/GMAGC-android-0.9.0.apk"
    assert notice.page_url.endswith("/releases/tag/v0.9.0") and prefs.data[KEY_LAST] == NOW


def test_a_recent_check_or_a_disabled_check_does_not_touch_the_network():
    def forbidden(version):
        raise AssertionError("сеть не должна вызываться")

    assert run(tracker(FakePrefs({KEY_LAST: NOW - 3600}), fetch=forbidden).check()) is None
    assert run(tracker(FakePrefs({KEY_ENABLED: False}), fetch=forbidden).check()) is None


def test_a_forced_check_ignores_the_schedule_and_the_switch():
    prefs = FakePrefs({KEY_ENABLED: False, KEY_LAST: NOW - 60})

    assert run(tracker(prefs).check(force=True)).version == "0.9.0"


def test_no_newer_release_gives_none_but_records_the_check_and_errors_are_not_recorded():
    prefs = FakePrefs()
    assert run(tracker(prefs, fetch=lambda v: None).check()) is None and prefs.data[KEY_LAST] == NOW

    def broken(version):
        raise UpdateCheckError("Нет связи с GitHub")

    prefs = FakePrefs()
    with pytest.raises(UpdateCheckError):
        run(tracker(prefs, fetch=broken).check())
    assert KEY_LAST not in prefs.data


def test_a_skipped_version_is_hidden_from_the_background_check_only():
    prefs = FakePrefs()
    update = tracker(prefs)
    run(update.skip("0.9.0"))

    assert prefs.data[KEY_SKIPPED] == "0.9.0"
    assert run(update.check()) is None
    assert run(update.check(force=True)).version == "0.9.0"


def test_a_release_without_an_apk_falls_back_to_the_release_page():
    notice = run(tracker(fetch=lambda v: release(platforms=("windows",))).check())

    assert notice.url == notice.page_url


def test_the_switch_defaults_to_on_and_ignores_garbage():
    assert run(tracker(FakePrefs()).enabled()) is True
    assert run(tracker(FakePrefs({KEY_ENABLED: "yes"})).enabled()) is True
    update = tracker(FakePrefs())
    run(update.set_enabled(False))
    assert run(update.enabled()) is False


def test_broken_stored_values_and_a_failing_storage_are_tolerated():
    assert run(tracker(FakePrefs({KEY_LAST: "yesterday", KEY_SKIPPED: 5})).check()).version == "0.9.0"
    assert run(tracker(FakePrefs(fail=True)).enabled()) is True


# ---- полоса на экране -------------------------------------------------------------------------------
def make_bar(update=None, launcher=None):
    page = StubPage()
    launcher = launcher or FakeLauncher()
    bar = UpdateBar(update or tracker(), launcher, page, delay=0)
    return bar, launcher, page


def test_the_startup_check_shows_the_bar():
    bar, _, _ = make_bar()

    run(bar.startup())

    assert bar.container.visible and bar.text.value == f"Доступна версия 0.9.0 (у вас {VERSION})"


def test_a_failed_background_check_is_silent_and_a_manual_one_reports():
    def broken(version):
        raise UpdateCheckError("Нет связи с GitHub")

    bar, _, _ = make_bar(tracker(fetch=broken))
    run(bar.startup())
    assert not bar.container.visible and bar.status.value == ""

    run(bar.on_check_now(None))
    assert bar.status.value == "Нет связи с GitHub"


def test_a_manual_check_without_news_says_so():
    bar, _, _ = make_bar(tracker(fetch=lambda v: None))

    run(bar.on_check_now(None))

    assert bar.status.value == f"Установлена последняя версия ({VERSION})" and not bar.container.visible


def test_download_opens_the_apk_link_and_skip_hides_the_bar():
    bar, launcher, _ = make_bar()
    run(bar.startup())

    run(bar.on_download(None))
    run(bar.on_skip(None))

    assert launcher.opened == ["https://example.invalid/GMAGC-android-0.9.0.apk"] and not bar.container.visible


def test_a_failing_launcher_is_reported_not_raised():
    class Broken:
        async def launch_url(self, url, **kwargs):
            raise RuntimeError("нет браузера")

    bar, _, _ = make_bar(launcher=Broken())
    run(bar.startup())

    run(bar.on_download(None))

    assert "нет браузера" in bar.status.value


def test_the_switch_persists_and_starts_from_the_saved_state():
    prefs = FakePrefs({KEY_ENABLED: False})
    bar, _, _ = make_bar(tracker(prefs))
    run(bar.load())
    assert bar.switch.value is False

    bar.switch.value = True
    run(bar.on_toggle(None))

    assert prefs.data[KEY_ENABLED] is True


# ---- встроено в экран ---------------------------------------------------------------------------------
def make_app(update, launcher=None, check_on_start=True):
    page = StubPage()
    app = MobileApp(
        page,
        ConnectionStore(FakePrefs()),
        CameraController(FakeCameraApi(), FakePermission(), settle_seconds=0, retry_seconds=0),
        preview=ft.Container(),
        picker=FakePicker(),
        clipboard=FakeClipboard(),
        client_factory=Script().factory,
        marker_seconds=0,
        mount_seconds=0,
        tracker=update,
        launcher=launcher or FakeLauncher(),
        check_on_start=check_on_start,
        update_delay=0,
    )
    app.build()
    return app, page


def test_the_screen_checks_for_updates_after_start_and_shows_the_bar():
    async def scenario():
        app, _ = make_app(tracker())
        await app.start()
        await app.update_task
        return app

    app = run(scenario())

    assert app.update_bar.container.visible and "0.9.0" in app.update_bar.text.value


def test_the_screen_does_not_check_when_switched_off_or_when_no_tracker_is_given():
    app, _ = make_app(tracker(FakePrefs({KEY_ENABLED: False}), fetch=lambda v: pytest.fail("сеть")))
    run(app.start())
    assert app.update_task is None or run(_finish(app)) is None

    app, _ = make_app(None)
    run(app.start())
    assert app.update_bar is None


async def _finish(app):
    return await app.update_task


def test_the_connect_screen_has_the_switch_and_the_manual_check():
    app, _ = make_app(tracker(), check_on_start=False)

    controls = list(_walk(app.connect_view))

    assert app.update_bar.switch in controls and app.update_bar.check_button in controls
    assert app.update_bar.container in list(_walk(_root(app)))


def _root(app):
    return app.page.added[0]


def _walk(control):
    yield control
    for attribute in ("content", "controls"):
        value = getattr(control, attribute, None)
        for child in value if isinstance(value, list) else [value] if value is not None else []:
            if isinstance(child, ft.Control):
                yield from _walk(child)
```

В `tests/mobile/test_mobile_app.py`: в `test_build_page_wires_services_and_starts` заменить проверку `len(page.services) == 4` на `== 5` (добавился загрузчик ссылок) и передать `tracker=None`; в `build_on` тоже передать `tracker=None`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/mobile/test_mobile_updates.py -q`
Expected: FAIL (`ModuleNotFoundError: gmagc_mobile.updates`).

- [ ] **Step 3: Write the implementation**

```python
# path: apps/mobile/src/gmagc_mobile/updates.py
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
```

```python
# path: apps/mobile/src/gmagc_mobile/update_bar.py
"""Полоса обновления Android-приложения: «Доступна версия…», «Скачать», «Пропустить», ручная проверка."""

from __future__ import annotations

import asyncio

import flet as ft

from gmagc_common.updates import UpdateCheckError
from gmagc_mobile.about import VERSION
from gmagc_mobile.updates import UpdateNotice, UpdateTracker


class UpdateBar:
    def __init__(self, tracker: UpdateTracker, launcher, page: ft.Page, delay: float = 3.0):
        self.tracker = tracker
        self.launcher = launcher
        self.page = page
        self.delay = delay
        self.notice: UpdateNotice | None = None

        self.text = ft.Text("", weight=ft.FontWeight.BOLD)
        self.download_button = ft.Button("Скачать", on_click=self.on_download)
        self.skip_button = ft.TextButton(content=ft.Text("Пропустить"), on_click=self.on_skip)
        self.container = ft.Container(
            ft.Column([self.text, ft.Row([self.download_button, self.skip_button], spacing=8, wrap=True)], spacing=6),
            padding=10,
            border_radius=6,
            bgcolor=ft.Colors.BLUE_100,
            visible=False,
        )
        self.status = ft.Text("", size=12)
        self.switch = ft.Switch(label="Проверять обновления", value=True, on_change=self.on_toggle)
        self.check_button = ft.TextButton(content=ft.Text("Проверить обновления", size=12), on_click=self.on_check_now)

    async def load(self) -> None:
        self.switch.value = await self.tracker.enabled()

    async def startup(self) -> None:
        """Фоновая проверка через delay секунд после запуска; сбой сети ничего не показывает."""
        await asyncio.sleep(self.delay)
        await self.check(force=False)

    async def check(self, *, force: bool) -> None:
        try:
            notice = await self.tracker.check(force=force)
        except UpdateCheckError as error:
            if force:
                self._status(str(error))
            return
        except Exception as error:  # noqa: BLE001
            if force:
                self._status(f"Ошибка проверки обновлений: {error}")
            return
        if notice is None:
            self._status(f"Установлена последняя версия ({VERSION})" if force else "")
            return
        self.notice = notice
        self.text.value = f"Доступна версия {notice.version} (у вас {VERSION})"
        self.container.visible = True
        self._status("")

    def _status(self, text: str) -> None:
        self.status.value = text
        self.page.update()

    async def on_check_now(self, _event) -> None:
        self._status("Проверяю обновления…")
        await self.check(force=True)

    async def on_download(self, _event) -> None:
        if self.notice is None:
            return
        try:
            await self.launcher.launch_url(self.notice.url)
        except Exception as error:  # noqa: BLE001
            self._status(f"Не удалось открыть ссылку на загрузку: {error}")

    async def on_skip(self, _event) -> None:
        if self.notice is not None:
            await self.tracker.skip(self.notice.version)
        self.container.visible = False
        self.page.update()

    async def on_toggle(self, _event) -> None:
        await self.tracker.set_enabled(bool(self.switch.value))
```

Правки `apps/mobile/src/gmagc_mobile/app.py`:

1. Импорт: `from gmagc_mobile.update_bar import UpdateBar` и `from gmagc_mobile.updates import UpdateTracker`.
2. В `MobileApp.__init__` в параметры после `hint_seconds: float | None = None,` добавить `tracker=None, launcher=None, check_on_start: bool = True, update_delay: float = 3.0,`; в тело после `self.back_hint = ...` добавить:

```python
        self.launcher = launcher
        self.check_on_start = check_on_start
        self.update_task: asyncio.Task | None = None
        self.update_bar = UpdateBar(tracker, launcher, page, delay=update_delay) if tracker is not None else None
```

3. Экран подключения: перед `ft.Text(f"Версия {VERSION}. Автор: {AUTHOR}", size=12),` в `connect_view` вставить `*self._update_controls(),` и добавить метод:

```python
    def _update_controls(self) -> list[ft.Control]:
        if self.update_bar is None:
            return []
        return [self.update_bar.switch, ft.Row([self.update_bar.check_button, self.update_bar.status], wrap=True)]
```

(метод должен вызываться после создания `self.update_bar`, поэтому блок `connect_view` в `__init__` идёт после присвоения `self.update_bar`; при необходимости перенести присвоение выше по коду.)

4. В `build()` в корневую колонку первым элементом добавить `*([self.update_bar.container] if self.update_bar else []),`.
5. В конец `start()` (после ветвей подключения) добавить вызов `await self._begin_update_check()`, а перед ними в начале метода `if demo_link:` ветку оставить как есть; метод:

```python
    async def _begin_update_check(self) -> None:
        if self.update_bar is None:
            return
        await self.update_bar.load()
        if self.check_on_start and self.update_bar.switch.value:
            self.update_task = asyncio.create_task(self.update_bar.startup())
```

(вызывать в каждом выходе из `start()`: после показа экрана подключения, после `_connect(stored)` и после `_demo`.)

6. В `build_page`: `tracker = services.pop("tracker", "default")`, `launcher = services.pop("launcher", None) or ft.UrlLauncher()`; если `tracker == "default"`, то `tracker = UpdateTracker(prefs)`; передать `tracker=tracker, launcher=launcher` в `MobileApp(...)`, добавить `launcher` в `page.services.extend([...])`.

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest tests/mobile -q`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
.venv/Scripts/python.exe -m ruff check --fix . && .venv/Scripts/python.exe -m pytest -q
git add apps/mobile/src/gmagc_mobile tests
git commit -m "feat: update notice in the Android app with a download link" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 7: Постоянный ключ подписи Android (нужно разрешение пользователя)

Обновление APK поверх установленного возможно только при одинаковой подписи, а сейчас каждая сборка на GitHub подписывается новым временным ключом.

**Files:**
- Modify: `.github/workflows/build-android.yml`, `README.md`

- [ ] **Step 1: Ask the user for permission**

Создание ключа и запись его в секреты репозитория меняют постоянную настройку репозитория; спросить разрешение. Ключ нужно сохранить и у пользователя: потеря ключа означает, что обновить установленные приложения уже нельзя.

- [ ] **Step 2: Generate the keystore once**

Разовый запуск workflow `Make Android key` (`workflow_dispatch`, `ubuntu-latest`): `keytool -genkeypair -v -keystore gmagc-upload.jks -alias gmagc -keyalg RSA -keysize 2048 -validity 10000` со случайными паролями (`openssl rand -hex 16`), результат загружается артефактом (хранение 1 день). Скачать артефакт, положить копию в безопасное место пользователя, записать секреты `gh secret set ANDROID_KEYSTORE_B64`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_PASSWORD`, `ANDROID_KEY_ALIAS`; артефакт и workflow удалить.

- [ ] **Step 3: Use the key in the Android build**

В `build-android.yml` перед шагом сборки добавить шаг: декодировать `ANDROID_KEYSTORE_B64` в `$RUNNER_TEMP/gmagc-upload.jks`; в шаг `flet build apk` добавить `--android-signing-key-store "$RUNNER_TEMP/gmagc-upload.jks" --android-signing-key-alias "$ANDROID_KEY_ALIAS"` и переменные `FLET_ANDROID_SIGNING_KEY_STORE_PASSWORD`, `FLET_ANDROID_SIGNING_KEY_PASSWORD` из секретов. Для запусков из форков секретов нет: шаг подписи пропускается (`if: env.ANDROID_KEYSTORE_B64 != ''`), сборка остаётся отладочной.

- [ ] **Step 4: Verify the signature**

Скачать APK из сборки на PR и проверить подпись (`apksigner verify --print-certs` или разбор `META-INF/*.RSA` через Python): отпечаток сертификата должен совпадать в двух разных сборках подряд.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/build-android.yml README.md
git commit -m "build: sign the Android APK with a persistent key so updates install over the old version" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 8: Окно с просьбой поддержать автора

Решения (пользователь дал ссылку и попросил всплывающее окно; частоту выбрал я, чтобы окно не раздражало): первое окно на 5-м запуске, дальше не чаще раза в 30 дней; кнопки «Поддержать» (открывает ссылку в браузере и больше не напоминает), «Позже» (напомнит через 30 дней), «Больше не показывать»; окно не показывается, пока идёт индексация, поиск или отправка; постоянные ссылки «Поддержать автора» и «Telegram автора» (`https://t.me/Andy_bum`) внизу экрана (ПК) и на экране подключения (Android) работают всегда и не меняют расписание; ссылки на донаты и Telegram также вносятся в README и заметки релиза.

**Files:**
- Create: `packages/common/gmagc_common/support.py` (+ копии скриптом), `apps/desktop/src/gmagc_desktop/ui/support.py`, `apps/mobile/src/gmagc_mobile/support.py`
- Modify: `apps/desktop/src/gmagc_desktop/service/settings.py`, `apps/desktop/src/gmagc_desktop/service/search_service.py`, `apps/desktop/src/gmagc_desktop/ui/app.py`, `apps/mobile/src/gmagc_mobile/app.py`, `tests/fakes.py` (`StubPage.show_dialog`/`pop_dialog`), `tests/desktop/test_desktop_ui.py`, `tests/desktop/test_phone_ui.py` (в `make_app`: `services.setdefault("support", False)`), `tests/mobile/*` (в `make_app`/`build_on`: `support` не передаётся, по умолчанию выключено)
- Test: `tests/common/test_support.py`, `tests/desktop/test_support_prompt.py`, `tests/mobile/test_mobile_support.py`

**Interfaces:**
- Produces (`gmagc_common.support`): `SUPPORT_URL` (`https://boosty.to/djmaker/donate`), `FIRST_ASK_LAUNCH = 5`, `REMIND_AFTER_SECONDS = 30 суток`, ответы `SUPPORT`, `LATER`, `NEVER`; `SupportState(launches=0, last_ask=0.0, muted=False)`; `register_launch(state)`, `should_ask(state, now) -> bool`, `after_answer(state, now, answer) -> SupportState`.
- Produces (ПК): `Settings.launches`, `Settings.support_last_ask`, `Settings.support_muted`; `SearchService.support_state()`, `save_support_state(state)`; `ui.support.SupportPrompt(page, service, *, open_url=webbrowser.open, now=time.time, delay=8.0, busy=lambda: False)` с `link`, `start()`, `show()`, `on_support`, `on_later`, `on_never`, `on_open_link`; `DesktopApp(..., support=True, support_delay=8.0)`.
- Produces (Android): `gmagc_mobile.support.SupportPrompt(prefs, launcher, page, *, now=time.time, delay=8.0, busy=lambda: False)` c `link`, async `startup()`, `show()`, `on_support`, `on_later`, `on_never`, `on_open_link`; `MobileApp(..., support=False, support_delay=8.0)`.

- [ ] **Step 1: Write the failing tests**

```python
# path: tests/common/test_support.py
import pytest

from gmagc_common.support import (
    AUTHOR_TELEGRAM_URL,
    FIRST_ASK_LAUNCH,
    LATER,
    NEVER,
    REMIND_AFTER_SECONDS,
    SUPPORT,
    SUPPORT_URL,
    SupportState,
    after_answer,
    register_launch,
    should_ask,
)

NOW = 1_800_000_000.0


def launched(times):
    state = SupportState()
    for _ in range(times):
        state = register_launch(state)
    return state


def test_the_links_are_the_authors_donation_page_and_telegram():
    assert SUPPORT_URL == "https://boosty.to/djmaker/donate"
    assert AUTHOR_TELEGRAM_URL == "https://t.me/Andy_bum"


def test_launches_are_counted_and_the_first_ask_waits_for_the_fifth_launch():
    assert register_launch(SupportState()).launches == 1
    assert not should_ask(launched(FIRST_ASK_LAUNCH - 1), NOW)
    assert should_ask(launched(FIRST_ASK_LAUNCH), NOW)
    assert should_ask(launched(FIRST_ASK_LAUNCH + 10), NOW)


def test_later_postpones_the_next_ask_by_thirty_days():
    state = after_answer(launched(5), NOW, LATER)

    assert state.last_ask == NOW and state.muted is False
    assert not should_ask(state, NOW + REMIND_AFTER_SECONDS - 1)
    assert should_ask(state, NOW + REMIND_AFTER_SECONDS)


@pytest.mark.parametrize("answer", [SUPPORT, NEVER])
def test_support_and_never_stop_the_asking_for_good(answer):
    state = after_answer(launched(5), NOW, answer)

    assert state.muted is True and state.last_ask == NOW
    assert not should_ask(state, NOW + 10 * REMIND_AFTER_SECONDS)


def test_a_clock_that_went_back_asks_again_and_an_unknown_answer_is_an_error():
    state = after_answer(launched(5), NOW, LATER)
    assert should_ask(state, NOW - 100)
    with pytest.raises(ValueError):
        after_answer(state, NOW, "maybe")
```

```python
# path: tests/desktop/test_support_prompt.py
from gmagc_common.support import AUTHOR_TELEGRAM_URL, FIRST_ASK_LAUNCH, REMIND_AFTER_SECONDS, SUPPORT_URL
from gmagc_desktop.service.search_service import SearchService
from gmagc_desktop.service.settings import Settings, load_settings, save_settings
from gmagc_desktop.ui.support import SupportPrompt
from tests.fakes import StubPage

NOW = 1_800_000_000.0


def make(tmp_path, launches=0, busy=False, last_ask=0.0, muted=False):
    if launches or last_ask or muted:
        save_settings(Settings(launches=launches, support_last_ask=last_ask, support_muted=muted), tmp_path / "data" / "settings.json")
    service = SearchService(tmp_path / "data")
    service.load()
    opened = []
    page = StubPage()
    prompt = SupportPrompt(page, service, open_url=opened.append, now=lambda: NOW, delay=0, busy=lambda: busy)
    return prompt, service, page, opened


def test_the_settings_keep_the_support_state(tmp_path):
    save_settings(Settings(launches=7, support_last_ask=12.5, support_muted=True), tmp_path / "s.json")

    loaded = load_settings(tmp_path / "s.json")

    assert (loaded.launches, loaded.support_last_ask, loaded.support_muted) == (7, 12.5, True)
    assert load_settings(tmp_path / "missing.json").launches == 0


def test_every_start_counts_a_launch_and_the_dialog_waits_for_the_fifth(tmp_path):
    for launch in range(1, FIRST_ASK_LAUNCH):
        prompt, service, page, _ = make(tmp_path, launches=launch - 1)
        prompt.start()
        assert service.settings.launches == launch and page.dialogs == []

    prompt, service, page, _ = make(tmp_path, launches=FIRST_ASK_LAUNCH - 1)
    prompt.start()

    assert service.settings.launches == FIRST_ASK_LAUNCH and len(page.dialogs) == 1


def test_the_dialog_explains_and_offers_three_choices(tmp_path):
    prompt, _, page, _ = make(tmp_path, launches=5)
    prompt.start()

    dialog = page.dialogs[0]

    assert dialog.title.value == "Поддержать автора"
    assert [b.content.value if hasattr(b.content, "value") else b.content for b in dialog.actions] == [
        "Поддержать",
        "Позже",
        "Больше не показывать",
    ]


def test_support_opens_the_link_records_it_and_closes_the_dialog(tmp_path):
    prompt, service, page, opened = make(tmp_path, launches=5)
    prompt.start()

    prompt.on_support(None)

    assert opened == [SUPPORT_URL] and page.dialogs == [] and service.settings.support_muted is True
    assert service.settings.support_last_ask == NOW


def test_later_postpones_and_never_mutes(tmp_path):
    prompt, service, page, opened = make(tmp_path, launches=5)
    prompt.start()
    prompt.on_later(None)
    assert page.dialogs == [] and opened == [] and service.settings.support_muted is False
    assert service.settings.support_last_ask == NOW

    prompt, service, page, _ = make(tmp_path, launches=6, last_ask=NOW - REMIND_AFTER_SECONDS)
    prompt.start()
    assert len(page.dialogs) == 1
    prompt.on_never(None)
    assert service.settings.support_muted is True and page.dialogs == []


def test_a_muted_or_recently_asked_user_is_left_alone(tmp_path):
    prompt, _, page, _ = make(tmp_path, launches=50, muted=True)
    prompt.start()
    assert page.dialogs == []

    prompt, _, page, _ = make(tmp_path, launches=50, last_ask=NOW - 3600)
    prompt.start()
    assert page.dialogs == []


def test_a_busy_app_skips_the_dialog_without_recording_an_ask(tmp_path):
    prompt, service, page, _ = make(tmp_path, launches=9, busy=True)

    prompt.start()

    assert page.dialogs == [] and service.settings.support_last_ask == 0.0 and service.settings.launches == 10


def test_the_permanent_link_opens_the_page_and_never_changes_the_schedule(tmp_path):
    prompt, service, _, opened = make(tmp_path, launches=1)

    prompt.on_open_link(None)

    assert opened == [SUPPORT_URL] and service.settings.support_last_ask == 0.0 and service.settings.support_muted is False


def test_the_telegram_link_opens_the_authors_account(tmp_path):
    prompt, _, _, opened = make(tmp_path, launches=1)

    prompt.on_open_telegram(None)

    assert opened == [AUTHOR_TELEGRAM_URL] and AUTHOR_TELEGRAM_URL == "https://t.me/Andy_bum"
```

```python
# path: tests/mobile/test_mobile_support.py
import asyncio

from gmagc_common.support import AUTHOR_TELEGRAM_URL, REMIND_AFTER_SECONDS, SUPPORT_URL
from gmagc_mobile.support import KEY_LAST, KEY_LAUNCHES, KEY_MUTED, SupportPrompt
from tests.fakes import StubPage
from tests.fakes_mobile import FakeLauncher, FakePrefs

NOW = 1_800_000_000.0


def run(coroutine):
    return asyncio.run(coroutine)


def make(prefs=None, busy=False):
    prefs = prefs if prefs is not None else FakePrefs()
    launcher, page = FakeLauncher(), StubPage()
    prompt = SupportPrompt(prefs, launcher, page, now=lambda: NOW, delay=0, busy=lambda: busy)
    return prompt, prefs, launcher, page


def test_the_dialog_appears_on_the_fifth_launch_only():
    for launch in range(1, 5):
        prompt, prefs, _, page = make(FakePrefs({KEY_LAUNCHES: launch - 1}))
        run(prompt.startup())
        assert prefs.data[KEY_LAUNCHES] == launch and page.dialogs == []

    prompt, prefs, _, page = make(FakePrefs({KEY_LAUNCHES: 4}))
    run(prompt.startup())

    assert prefs.data[KEY_LAUNCHES] == 5 and len(page.dialogs) == 1
    assert page.dialogs[0].title.value == "Поддержать автора"


def test_support_opens_the_link_and_mutes():
    prompt, prefs, launcher, page = make(FakePrefs({KEY_LAUNCHES: 4}))
    run(prompt.startup())

    run(prompt.on_support(None))

    assert launcher.opened == [SUPPORT_URL] and page.dialogs == [] and prefs.data[KEY_MUTED] is True and prefs.data[KEY_LAST] == NOW


def test_later_and_never():
    prompt, prefs, _, page = make(FakePrefs({KEY_LAUNCHES: 4}))
    run(prompt.startup())
    run(prompt.on_later(None))
    assert page.dialogs == [] and prefs.data[KEY_LAST] == NOW and prefs.data.get(KEY_MUTED) is not True

    prompt, prefs, _, page = make(FakePrefs({KEY_LAUNCHES: 5, KEY_LAST: NOW - REMIND_AFTER_SECONDS}))
    run(prompt.startup())
    assert len(page.dialogs) == 1
    run(prompt.on_never(None))
    assert prefs.data[KEY_MUTED] is True


def test_a_muted_recent_or_busy_user_is_left_alone_and_a_broken_storage_is_tolerated():
    for prefs, busy in ((FakePrefs({KEY_LAUNCHES: 50, KEY_MUTED: True}), False), (FakePrefs({KEY_LAUNCHES: 50, KEY_LAST: NOW - 60}), False), (FakePrefs({KEY_LAUNCHES: 9}), True)):
        prompt, _, _, page = make(prefs, busy=busy)
        run(prompt.startup())
        assert page.dialogs == []

    prompt, _, _, page = make(FakePrefs(fail=True))
    run(prompt.startup())
    assert page.dialogs == []


def test_the_permanent_link_opens_the_page_without_touching_the_schedule():
    prompt, prefs, launcher, _ = make(FakePrefs({KEY_LAUNCHES: 1}))

    run(prompt.on_open_link(None))

    assert launcher.opened == [SUPPORT_URL] and KEY_LAST not in prefs.data and KEY_MUTED not in prefs.data


def test_the_telegram_link_opens_the_authors_account():
    prompt, _, launcher, _ = make()

    run(prompt.on_open_telegram(None))

    assert launcher.opened == [AUTHOR_TELEGRAM_URL]
```

В `tests/fakes.py` в `StubPage.__init__` добавить `self.dialogs = []`, а в класс методы:

```python
    def show_dialog(self, dialog):
        self.dialogs.append(dialog)

    def pop_dialog(self):
        return self.dialogs.pop() if self.dialogs else None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/common/test_support.py tests/desktop/test_support_prompt.py tests/mobile/test_mobile_support.py -q`
Expected: FAIL (нет модулей и полей).

- [ ] **Step 3: Write the implementation**

```python
# path: packages/common/gmagc_common/support.py
"""Просьба поддержать автора: адрес и расписание показа окна (только стандартная библиотека)."""

from __future__ import annotations

from dataclasses import dataclass, replace

SUPPORT_URL = "https://boosty.to/djmaker/donate"
AUTHOR_TELEGRAM_URL = "https://t.me/Andy_bum"  # Telegram автора: постоянная ссылка на экранах
FIRST_ASK_LAUNCH = 5  # первое окно не раньше пятого запуска
REMIND_AFTER_SECONDS = 30 * 24 * 60 * 60  # «Позже» напоминает через 30 суток

SUPPORT = "support"
LATER = "later"
NEVER = "never"

DIALOG_TITLE = "Поддержать автора"
DIALOG_TEXT = (
    "GMAGC бесплатна, её делает один человек. Если программа помогает вам в работе, "
    "вы можете поддержать автора добровольным взносом. Спасибо!"
)


@dataclass(frozen=True)
class SupportState:
    launches: int = 0
    last_ask: float = 0.0
    muted: bool = False


def register_launch(state: SupportState) -> SupportState:
    return replace(state, launches=state.launches + 1)


def should_ask(state: SupportState, now: float) -> bool:
    if state.muted or state.launches < FIRST_ASK_LAUNCH:
        return False
    return state.last_ask <= 0 or state.last_ask > now or now - state.last_ask >= REMIND_AFTER_SECONDS


def after_answer(state: SupportState, now: float, answer: str) -> SupportState:
    if answer in (SUPPORT, NEVER):
        return replace(state, last_ask=now, muted=True)
    if answer == LATER:
        return replace(state, last_ask=now)
    raise ValueError(f"неизвестный ответ: {answer}")
```

Настройки ПК (`settings.py`): в `Settings` добавить `launches: int = 0`, `support_last_ask: float = 0.0`, `support_muted: bool = False`; в `load_settings` прочитать их с проверкой (`launches` неотрицательное целое, `support_last_ask` неотрицательное конечное число, `support_muted` bool, иначе значения по умолчанию). В `SearchService` добавить (с импортом `SupportState` из `gmagc_common.support`):

```python
    def support_state(self) -> SupportState:
        s = self.settings
        return SupportState(s.launches, s.support_last_ask, s.support_muted)

    def save_support_state(self, state: SupportState) -> None:
        self._update_settings(launches=state.launches, support_last_ask=state.last_ask, support_muted=state.muted)
```

```python
# path: apps/desktop/src/gmagc_desktop/ui/support.py
"""Окно с просьбой поддержать автора (ПК): расписание, кнопки, постоянная ссылка."""

from __future__ import annotations

import time
import webbrowser
from collections.abc import Callable

import flet as ft

from gmagc_common.support import (
    AUTHOR_TELEGRAM_URL,
    DIALOG_TEXT,
    DIALOG_TITLE,
    LATER,
    NEVER,
    SUPPORT,
    SUPPORT_URL,
    after_answer,
    register_launch,
    should_ask,
)
from gmagc_desktop.service.search_service import SearchService


class SupportPrompt:
    def __init__(
        self,
        page: ft.Page,
        service: SearchService,
        *,
        open_url: Callable[[str], object] = webbrowser.open,
        now: Callable[[], float] = time.time,
        delay: float = 8.0,
        busy: Callable[[], bool] = lambda: False,
    ):
        self.page = page
        self.service = service
        self.open_url = open_url
        self.now = now
        self.delay = delay
        self.busy = busy
        self.link = ft.TextButton(content=ft.Text("Поддержать автора", size=12), on_click=self.on_open_link)
        self.telegram_link = ft.TextButton(content=ft.Text("Telegram автора", size=12), on_click=self.on_open_telegram)
        self._dialog: ft.AlertDialog | None = None

    def start(self) -> None:
        """Считает запуск и, если пора, показывает окно через delay секунд (если приложение не занято)."""
        state = register_launch(self.service.support_state())
        self.service.save_support_state(state)
        if should_ask(state, self.now()):
            self.page.run_thread(self._show_later)

    def _show_later(self) -> None:
        time.sleep(self.delay)
        if not self.busy():
            self.show()

    def show(self) -> None:
        self._dialog = ft.AlertDialog(
            title=ft.Text(DIALOG_TITLE),
            content=ft.Text(DIALOG_TEXT),
            actions=[
                ft.Button("Поддержать", on_click=self.on_support),
                ft.TextButton(content=ft.Text("Позже"), on_click=self.on_later),
                ft.TextButton(content=ft.Text("Больше не показывать"), on_click=self.on_never),
            ],
        )
        self.page.show_dialog(self._dialog)

    def _answer(self, answer: str) -> None:
        state = after_answer(self.service.support_state(), self.now(), answer)
        self.service.save_support_state(state)
        self.page.pop_dialog()
        self._dialog = None

    def on_support(self, _event) -> None:
        self.open_url(SUPPORT_URL)
        self._answer(SUPPORT)

    def on_later(self, _event) -> None:
        self._answer(LATER)

    def on_never(self, _event) -> None:
        self._answer(NEVER)

    def on_open_link(self, _event) -> None:
        self.open_url(SUPPORT_URL)

    def on_open_telegram(self, _event) -> None:
        self.open_url(AUTHOR_TELEGRAM_URL)
```

Правки `apps/desktop/src/gmagc_desktop/ui/app.py`: параметры `support: bool = True, support_delay: float = 8.0` в `DesktopApp.__init__`; `self.support = SupportPrompt(page, service, open_url=open_url, delay=support_delay, busy=lambda: self._busy) if support else None`; в `footer` после `self.check_label,` добавить `*([self.support.link, self.support.telegram_link] if self.support else []),`; после `self.page.add(...)` добавить `if self.support is not None: self.support.start()`. В `make_app` тестов ПК `services.setdefault("support", False)`.

```python
# path: apps/mobile/src/gmagc_mobile/support.py
"""Окно с просьбой поддержать автора (Android): расписание в SharedPreferences, кнопки, постоянная ссылка."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

import flet as ft

from gmagc_common.support import (
    AUTHOR_TELEGRAM_URL,
    DIALOG_TEXT,
    DIALOG_TITLE,
    LATER,
    NEVER,
    SUPPORT,
    SUPPORT_URL,
    SupportState,
    after_answer,
    register_launch,
    should_ask,
)

KEY_LAUNCHES = "gmagc.support.launches"
KEY_LAST = "gmagc.support.last_ask"
KEY_MUTED = "gmagc.support.muted"


class SupportPrompt:
    def __init__(
        self,
        prefs,
        launcher,
        page: ft.Page,
        *,
        now: Callable[[], float] = time.time,
        delay: float = 8.0,
        busy: Callable[[], bool] = lambda: False,
    ):
        self.prefs = prefs
        self.launcher = launcher
        self.page = page
        self.now = now
        self.delay = delay
        self.busy = busy
        self.link = ft.TextButton(content=ft.Text("Поддержать автора", size=12), on_click=self.on_open_link)
        self.telegram_link = ft.TextButton(content=ft.Text("Telegram автора", size=12), on_click=self.on_open_telegram)

    async def _load(self) -> SupportState:
        try:
            launches = await self.prefs.get(KEY_LAUNCHES)
            last = await self.prefs.get(KEY_LAST)
            muted = await self.prefs.get(KEY_MUTED)
        except Exception:  # noqa: BLE001 - недоступное хранилище: просьбу не показываем
            return SupportState(0, 0.0, True)
        return SupportState(
            launches if isinstance(launches, int) and not isinstance(launches, bool) and launches >= 0 else 0,
            float(last) if isinstance(last, int | float) and not isinstance(last, bool) and last >= 0 else 0.0,
            muted is True,
        )

    async def _save(self, state: SupportState) -> None:
        await self.prefs.set(KEY_LAUNCHES, state.launches)
        await self.prefs.set(KEY_LAST, state.last_ask)
        await self.prefs.set(KEY_MUTED, state.muted)

    async def startup(self) -> None:
        """Считает запуск и, если пора, показывает окно через delay секунд (если приложение не занято)."""
        state = await self._load()
        if state.muted and state.launches == 0:  # хранилище недоступно
            return
        state = register_launch(state)
        await self._save(state)
        if not should_ask(state, self.now()):
            return
        await asyncio.sleep(self.delay)
        if not self.busy():
            self.show()

    def show(self) -> None:
        self.page.show_dialog(
            ft.AlertDialog(
                title=ft.Text(DIALOG_TITLE),
                content=ft.Text(DIALOG_TEXT),
                actions=[
                    ft.Button("Поддержать", on_click=self.on_support),
                    ft.TextButton(content=ft.Text("Позже"), on_click=self.on_later),
                    ft.TextButton(content=ft.Text("Больше не показывать"), on_click=self.on_never),
                ],
            )
        )

    async def _answer(self, answer: str) -> None:
        await self._save(after_answer(await self._load(), self.now(), answer))
        self.page.pop_dialog()

    async def on_support(self, _event) -> None:
        await self._open()
        await self._answer(SUPPORT)

    async def on_later(self, _event) -> None:
        await self._answer(LATER)

    async def on_never(self, _event) -> None:
        await self._answer(NEVER)

    async def on_open_link(self, _event) -> None:
        await self._open()

    async def on_open_telegram(self, _event) -> None:
        await self._open(AUTHOR_TELEGRAM_URL)

    async def _open(self, url: str = SUPPORT_URL) -> None:
        try:
            await self.launcher.launch_url(url)
        except Exception:  # noqa: BLE001 - нет браузера: окно всё равно закрываем
            pass
```

Правки `apps/mobile/src/gmagc_mobile/app.py`: параметры `support: bool = False, support_delay: float = 8.0` в `MobileApp.__init__` (в тестах ничего не меняется: по умолчанию выключено); `self.support = SupportPrompt(prefs, launcher, page, delay=support_delay, busy=lambda: self._busy) if support and launcher is not None else None` (для этого `MobileApp` получает `prefs`: либо параметром, либо через `ConnectionStore`; проще передать `prefs` отдельным необязательным параметром `prefs=None`); в `connect_view` перед строкой версии добавить `*([self.support.link, self.support.telegram_link] if self.support else []),`; в конец `start()` (после `_begin_update_check`) добавить `if self.support is not None: self.support_task = asyncio.create_task(self.support.startup())`. В `build_page`: `support=True`, `prefs=prefs` передаются в `MobileApp` (в тестах `build_page` передают `support=False`).

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: PASS (все новые и прежние тесты).

- [ ] **Step 5: Lint and commit**

```bash
.venv/Scripts/python.exe scripts/sync_common.py
.venv/Scripts/python.exe -m ruff check --fix . && .venv/Scripts/python.exe -m pytest -q
git add packages apps tests
git commit -m "feat: dialog asking to support the author with a donation link" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---
### Task 9: Сквозная проверка на Windows, README, версия 0.6.0, PR и релиз

**Files:**
- Modify: `apps/desktop/src/gmagc_desktop/about.py`, `apps/mobile/src/gmagc_mobile/about.py`, `apps/desktop/pyproject.toml`, `apps/mobile/pyproject.toml` (версия `0.6.0`), `README.md`

- [ ] **Step 1: Bump the version and run everything**

`VERSION` и `version` в четырёх местах `0.6.0`. Run: `.venv\Scripts\python.exe -m pytest -q` и `.venv\Scripts\python.exe -m ruff check .`. Expected: всё зелёное.

- [ ] **Step 2: Build the Windows app and prepare a fake GitHub**

`.\scripts\build_windows.ps1`. Затем: скопировать `apps\desktop\build\windows` в `C:\Users\ANDYBUM\Тест GMAGC\GMAGC` (кириллица и пробел в пути); собрать zip той же сборки с добавленным файлом `UPDATED.txt` под именем `GMAGC-desktop-windows-9.9.9.zip`, посчитать SHA-256, положить `.sha256`; поднять локальный сервер (`python -m http.server`-подобный скрипт из `scratchpad`), отдающий `/latest` (JSON релиза `9.9.9` с адресами на этот сервер).

- [ ] **Step 3: Run the update end to end**

Запустить установленную копию с `GMAGC_UPDATE_URL=http://127.0.0.1:<порт>/latest`, `GMAGC_DATA_DIR=<временная папка>`. Через 5 секунд в окне должна появиться полоса «Доступна версия 9.9.9 (у вас 0.6.0)»; снимок окна `scripts\capture_window.ps1`; клик по «Обновить» (скрипт `user32`); дождаться перезапуска. Проверить: в папке установки есть `UPDATED.txt`, рядом папка `GMAGC.previous` со старой версией, процесс `gmagc-desktop` запущен заново (другой PID), `update.log` без ошибок, скрипт-помощник удалил сам себя; настройки и индекс на месте.

- [ ] **Step 4: Check the failure paths live**

Неверная контрольная сумма (подменить `.sha256`): полоса показывает «Контрольная сумма не совпала…», файлы не тронуты. Отмена загрузки. Проверка без сети (сервер остановлен): фоновая проверка молчит, ручная показывает «Нет связи с GitHub».

- [ ] **Step 5: Android bar check on Windows**

Запустить мобильное приложение (`flet run`) с `GMAGC_UPDATE_URL` на тот же локальный сервер (в JSON есть APK): видна полоса «Доступна версия…», «Скачать» открывает адрес APK.

- [ ] **Step 6: README, commit, PR, CI, release**

README: раздел «Обновления» (как работает проверка, «Обновить» по кнопке, что сумма проверяется, выключатель, резервная папка `.previous`, Android ведёт на загрузку APK, `GMAGC_UPDATE_URL` для отладки). Затем:

```bash
git add -A
git commit -m "docs: README and version 0.6.0 for the auto-update" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
git push -u origin feat/auto-update
gh pr create --title "Автообновление (0.6.0)" --body-file <файл описания> --base main
```

Дождаться зелёных проверок, `gh pr merge --squash --delete-branch`, тег `v0.6.0`, релизные сборки, проверка контрольных сумм и запуска Windows-архива, замена заметок релиза, обновление памяти проекта.
