"""Клиент сервера GMAGC на ПК (стандартная библиотека): проверка подключения и поиск по фото."""

from __future__ import annotations

import http.client
import json

from gmagc_common.i18n import t
from gmagc_common.protocol import (
    API_VERSION,
    APP_NAME,
    ApiError,
    Connection,
    FixtureUploadResult,
    Health,
    MatchResponse,
    ProtocolError,
    Status,
)
from gmagc_common.scan_draft import ScanDraft

UNREACHABLE = "unreachable"
UNAUTHORIZED = "unauthorized"
RATE_LIMITED = "rate_limited"
NO_INDEX = "no_index"
BAD_IMAGE = "bad_image"
TOO_LARGE = "too_large"
BAD_PROFILE = "bad_profile"
NO_TARGET = "no_target"
BAD_SCAN = "bad_scan"
SCAN_UNAVAILABLE = "scan_unavailable"
SERVER = "server"
PROTOCOL = "protocol"

_KIND_BY_CODE = {
    "unauthorized": UNAUTHORIZED,
    "rate_limited": RATE_LIMITED,
    "no_index": NO_INDEX,
    "bad_image": BAD_IMAGE,
    "bad_request": BAD_IMAGE,
    "too_large": TOO_LARGE,
    "bad_profile": BAD_PROFILE,
    "no_target": NO_TARGET,
    "bad_scan": BAD_SCAN,
    "scan_unavailable": SCAN_UNAVAILABLE,
}


def _not_gmagc() -> str:
    return t("Это не сервер GMAGC: проверьте адрес и порт.")


class ClientError(Exception):
    """Ошибка обращения к ПК; kind говорит экрану, что показать."""

    def __init__(self, kind: str, message: str, retry_after: int = 0):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.retry_after = retry_after


class GmagcClient:
    def __init__(
        self, connection: Connection, timeout: float = 10.0, match_timeout: float = 15.0, scan_timeout: float = 240.0
    ):
        self.connection = connection
        self._timeout = timeout
        self._match_timeout = match_timeout
        self._scan_timeout = scan_timeout  # распознавание многостраничного PDF на ПК идёт минуты

    def health(self) -> Health:
        data = self._request("GET", "/api/health", auth=False)
        try:
            health = Health.from_dict(data)
        except ProtocolError as error:
            raise ClientError(PROTOCOL, _not_gmagc()) from error
        if health.app != APP_NAME:
            raise ClientError(PROTOCOL, _not_gmagc())
        if health.api != API_VERSION:
            raise ClientError(
                PROTOCOL,
                t(
                    "Версия приложения на ПК (API {api}) не подходит к этому телефону (API {phone_api}): "
                    "обновите оба приложения.",
                    api=health.api,
                    phone_api=API_VERSION,
                ),
            )
        return health

    def status(self) -> Status:
        data = self._request("GET", "/api/status")
        try:
            return Status.from_dict(data)
        except ProtocolError as error:
            raise ClientError(PROTOCOL, t("Неожиданный ответ ПК на запрос состояния.")) from error

    def verify(self) -> tuple[Health, Status]:
        """Проверяет адрес (health без кода) и код доступа (status с кодом)."""
        return self.health(), self.status()

    def match(self, image: bytes, top: int | None = None) -> MatchResponse:
        path = "/api/match" + (f"?top={top}" if top else "")
        data = self._request("POST", path, body=image, timeout=self._match_timeout)
        try:
            return MatchResponse.from_dict(data)
        except ProtocolError as error:
            raise ClientError(PROTOCOL, t("Неожиданный ответ ПК на поиск.")) from error

    def send_fixture(self, profile: dict) -> FixtureUploadResult:
        """Отправляет профиль прибора (словарь `profile_to_dict`) на ПК: тот сам запишет типы для grandMA3 и grandMA2."""
        body = json.dumps(profile, ensure_ascii=False).encode("utf-8")
        data = self._request(
            "POST", "/api/fixtures", body=body, timeout=self._match_timeout, content_type="application/json"
        )
        try:
            return FixtureUploadResult.from_dict(data)
        except ProtocolError as error:
            raise ClientError(PROTOCOL, t("Неожиданный ответ ПК на отправку профиля.")) from error

    def scan_fixture(self, data: bytes, content_type: str = "image/jpeg") -> ScanDraft:
        """Отправляет фото или PDF инструкции на ПК и возвращает черновик каналов (распознавание — на ПК)."""
        reply = self._request(
            "POST", "/api/fixture-scan?engine=local", body=data, timeout=self._scan_timeout, content_type=content_type
        )
        try:
            return ScanDraft.from_dict(reply)
        except ValueError as error:
            raise ClientError(PROTOCOL, t("Неожиданный ответ ПК на распознавание.")) from error

    def _request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        auth: bool = True,
        timeout: float | None = None,
        content_type: str = "image/jpeg",
    ) -> dict:
        headers: dict[str, str] = {}
        if auth:
            headers["Authorization"] = f"Bearer {self.connection.code}"
        if body is not None:
            headers["Content-Type"] = content_type
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
            raise ClientError(PROTOCOL, _not_gmagc()) from error
        if not isinstance(data, dict):
            raise ClientError(PROTOCOL, _not_gmagc())
        if status == 200:
            return data
        try:
            api_error = ApiError.from_dict(data)
        except ProtocolError as error:
            raise ClientError(SERVER, t("Ответ ПК: HTTP {status}", status=status)) from error
        retry_after = int(retry_header) if retry_header and retry_header.isdigit() else 0
        raise ClientError(_KIND_BY_CODE.get(api_error.code, SERVER), api_error.message, retry_after)
