"""Заглушки для тестов Android-приложения: камера, разрешение, хранилище, сетевой клиент."""

from types import SimpleNamespace

import flet_camera as fc
import flet_permission_handler as ph

from gmagc_common.protocol import Health, MatchResponse, ResultItem, Status


def cam(direction: str):
    return SimpleNamespace(name=direction, lens_direction=fc.CameraLensDirection(direction))


class FakeCameraApi:
    """Замена fc.Camera: записывает вызовы в calls."""

    def __init__(self, cameras=None, min_zoom=1.0, max_zoom=6.0, picture=b"JPEG-shot", fail=None, picture_failures=0):
        self.cameras = list(cameras) if cameras is not None else [cam("front"), cam("back")]
        self.min_zoom = min_zoom
        self.max_zoom = max_zoom
        self.picture = picture
        self.fail = fail  # имя метода, который должен упасть
        self.picture_failures = picture_failures  # сколько первых снимков упадёт, как при потерянном контроллере
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
        if self.picture_failures > 0:
            self.picture_failures -= 1
            raise RuntimeError("Exception: Camera is not initialized. Call initialize() first.")
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
