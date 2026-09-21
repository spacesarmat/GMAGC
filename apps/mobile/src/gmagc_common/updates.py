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
                url = str(item["browser_download_url"])
                assets.append(Asset(str(item["name"]), url, size if isinstance(size, int) else 0))
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
