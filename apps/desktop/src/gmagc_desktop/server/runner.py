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
from gmagc_desktop.service.fixture_export import FixtureExporter
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
        fixtures: FixtureExporter | None = None,
    ):
        exporter = fixtures or FixtureExporter(lambda: service.settings)
        self._context = ApiContext(service, limiter or RateLimiter(), on_request, exporter)
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
