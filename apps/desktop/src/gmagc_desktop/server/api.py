"""HTTP-API для телефона: /api/health, /api/status, /api/match, /api/fixtures."""

from __future__ import annotations

import json
import logging
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlsplit

from gmagc_common.fixtures import ProfileError, profile_from_dict
from gmagc_common.ma3_export import ExportError
from gmagc_common.protocol import (
    API_VERSION,
    APP_NAME,
    ERROR_STATUS,
    MAX_IMAGE_BYTES,
    MAX_PROFILE_BYTES,
    ApiError,
    Health,
    MatchResponse,
    ResultItem,
    Status,
)
from gmagc_desktop.about import VERSION
from gmagc_desktop.service.access import RateLimiter, codes_equal
from gmagc_desktop.service.fixture_export import FixtureExporter, NoTargetError
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
    fixtures: FixtureExporter | None = None


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
            path = urlsplit(self.path).path
            if path == "/api/match":
                self._authorized(self._match)
            elif path == "/api/fixtures":
                self._authorized(self._fixtures)
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

    def _fixtures(self) -> None:
        """Принимает профиль прибора (JSON) и записывает типы grandMA3 и grandMA2 в папки пультов на этом ПК."""
        length = self._content_length()
        if length is None:
            self._error("bad_request", "нужен заголовок Content-Length")
            return
        if length > MAX_PROFILE_BYTES:
            self._error("too_large", f"профиль больше {MAX_PROFILE_BYTES // 1024} КБ")
            return
        self._unread = 0
        try:
            data = self.rfile.read(length)
        except OSError:
            self._error("bad_request", "не удалось получить профиль")
            return
        if len(data) != length:
            self._error("bad_request", "тело запроса получено не полностью")
            return
        try:
            profile = profile_from_dict(json.loads(data.decode("utf-8")))
        except (ValueError, ProfileError):  # UnicodeDecodeError и ошибка разбора JSON тоже ValueError
            self._error("bad_profile", "это не профиль прибора GMAGC")
            return
        exporter = self.context.fixtures
        if exporter is None:
            self._error("server_error", "запись типов приборов не настроена")
            return
        try:
            result = exporter.store(profile)
        except ExportError as error:
            self._error("bad_profile", str(error))
            return
        except NoTargetError as error:
            self._error("no_target", f"некуда записать типы приборов: {error}")
            return
        except OSError as error:
            log.exception("не удалось записать тип прибора")
            self._error("server_error", f"не удалось записать файл: {error}")
            return
        log.info("получен профиль «%s»: записано файлов %d", profile.name, len(result.written))
        self._send_json(200, result.to_dict())

    def _notify(self, record: RequestRecord) -> None:
        callback = self.context.on_request
        if callback is None:
            return
        try:
            callback(record)
        except Exception:  # noqa: BLE001 - сбой экрана не должен ломать сервер
            log.exception("обработчик запроса завершился ошибкой")
