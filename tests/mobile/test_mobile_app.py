import asyncio

import flet_permission_handler as ph

from gmagc_mobile.about import AUTHOR, NAME, VERSION
from gmagc_mobile.app import STUB_TEXT, build_page, start_camera


class StubPage:
    def __init__(self):
        self.title = ""
        self.added = []
        self.services = []
        self.updates = 0

    def add(self, *controls):
        self.added.extend(controls)

    def update(self):
        self.updates += 1


class FakeStatus:
    def __init__(self):
        self.value = ""


class FakePermission:
    def __init__(self, status):
        self.status = status

    async def request(self, permission):
        assert permission == ph.Permission.CAMERA
        return self.status


class FakeCamera:
    def __init__(self, cameras=("back",), fail=False):
        self.cameras = list(cameras)
        self.fail = fail
        self.initialized_with = None

    async def get_available_cameras(self):
        if self.fail:
            raise RuntimeError("нет плагина")
        return self.cameras

    async def initialize(self, description, preset, enable_audio=True):
        self.initialized_with = (description, enable_audio)


def run(page, permission, camera):
    status = FakeStatus()
    asyncio.run(start_camera(page, permission, camera, status))
    return status


def test_granted_permission_initializes_the_first_camera():
    camera = FakeCamera(cameras=("back", "front"))

    status = run(StubPage(), FakePermission(ph.PermissionStatus.GRANTED), camera)

    assert status.value == "Камера готова"
    assert camera.initialized_with == ("back", False)


def test_denied_permission_explains_what_to_do():
    camera = FakeCamera()

    status = run(StubPage(), FakePermission(ph.PermissionStatus.DENIED), camera)

    assert "разрешите" in status.value
    assert camera.initialized_with is None


def test_no_camera_and_plugin_errors_are_shown_not_raised():
    assert run(StubPage(), FakePermission(ph.PermissionStatus.GRANTED), FakeCamera(cameras=())).value == "Камера не найдена"
    assert "Ошибка камеры" in run(StubPage(), FakePermission(ph.PermissionStatus.GRANTED), FakeCamera(fail=True)).value


def test_page_shows_name_version_author_and_the_server_stub():
    page = StubPage()

    async def no_start(page, permission, camera, status):
        status.value = "запуск пропущен"

    status = asyncio.run(build_page(page, starter=no_start))

    assert page.title == f"{NAME} {VERSION}"
    assert len(page.services) == 1
    assert status.value == "запуск пропущен"
    assert page.updates >= 0
    assert STUB_TEXT and AUTHOR
