"""Заглушки для тестов ПК-приложения: сервер телефона и менеджер обновлений."""

from pathlib import Path

from gmagc_desktop.server.runner import ServerStartError
from gmagc_desktop.update.installer import InstallCancelled


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
