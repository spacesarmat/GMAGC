"""Заглушки для тестов экрана: страница, диалог выбора файла, буфер обмена, сервер телефона."""

from types import SimpleNamespace

import flet as ft

from gmagc_desktop.server.runner import ServerStartError


class FakeView:
    """Замена корневого ft.View: запоминает решения confirm_pop."""

    def __init__(self):
        self.can_pop = True
        self.on_confirm_pop = None
        self.decisions = []

    async def confirm_pop(self, should_pop):
        self.decisions.append(should_pop)


class StubPage:
    """Минимальная замена ft.Page: запоминает добавленное, поток выполняет сразу."""

    def __init__(self):
        self.title = ""
        self.added = []
        self.services = []
        self.updates = 0
        self.views = [FakeView()]  # корневой вид: сюда Android-приложение вешает обработчик кнопки «Назад»

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
        return [SimpleNamespace(path=path, bytes=None) for path in self.files]


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
