import asyncio
from types import SimpleNamespace

import flet as ft

from gmagc_mobile.app import MobileApp
from gmagc_mobile.camera import CameraController
from gmagc_mobile.store import ConnectionStore
from tests.fakes import FakeClipboard, FakePicker, StubPage
from tests.fakes_mobile import FakeCameraApi, FakePermission, FakePrefs, Script

STORED = {"gmagc.host": "192.168.1.121", "gmagc.port": 8765, "gmagc.code": "ZBZ36YNK"}


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make(prefs=None, camera_api=None):
    clock = Clock()
    camera_api = camera_api or FakeCameraApi()
    page = StubPage()
    app = MobileApp(
        page,
        ConnectionStore(FakePrefs(prefs)),
        CameraController(camera_api, FakePermission(), settle_seconds=0, retry_seconds=0),
        preview=ft.Container(),
        picker=FakePicker(),
        clipboard=FakeClipboard(),
        client_factory=Script().factory,
        qr_reader=lambda data: None,
        marker_seconds=0,
        mount_seconds=0,
        clock=clock,
        back_seconds=0,
        hint_seconds=0,  # подсказка гасится сразу, тесты не ждут
    )
    app.build()
    asyncio.run(app.start())
    return app, page.views[0], clock, camera_api


def press_back(app, view):
    asyncio.run(app.on_confirm_pop(SimpleNamespace(control=view)))


def views_shown(app):
    return [name for name in ("connect", "camera", "results") if getattr(app, f"{name}_view").visible]


def test_the_root_view_hands_the_back_button_to_the_app():
    app, view, _, _ = make()

    assert view.can_pop is False and view.on_confirm_pop == app.on_confirm_pop


def test_back_from_the_results_returns_to_the_camera_and_does_not_exit():
    app, view, _, camera_api = make(STORED)
    asyncio.run(app.on_capture(None))
    assert views_shown(app) == ["results"]

    press_back(app, view)

    assert views_shown(app) == ["camera"] and view.decisions == [False]
    assert len([c for c in camera_api.calls if c[0] == "initialize"]) == 2 and app.camera.ready


def test_back_while_scanning_returns_to_the_connect_screen():
    app, view, _, _ = make()
    asyncio.run(app.on_scan_qr(None))
    assert views_shown(app) == ["camera"] and app.mode == "scan"

    press_back(app, view)

    assert views_shown(app) == ["connect"] and view.decisions == [False]


def test_the_camera_screen_needs_a_second_back_press_to_exit():
    app, view, clock, _ = make(STORED)
    app.back_seconds = 2.5

    press_back(app, view)
    assert view.decisions == [False] and views_shown(app) == ["camera"]
    clock.now += 1.0
    press_back(app, view)

    assert view.decisions == [False, True]


def test_a_late_second_back_press_only_shows_the_hint_again():
    app, view, clock, _ = make(STORED)
    app.back_seconds = 2.5

    press_back(app, view)
    clock.now += 10.0
    press_back(app, view)

    assert view.decisions == [False, False]


def test_the_first_back_press_shows_the_hint_and_it_disappears_afterwards():
    app, view, _, _ = make(STORED)
    seen = []
    original = view.confirm_pop

    async def spy(should_pop):
        seen.append(app.back_hint.visible)
        await original(should_pop)

    view.confirm_pop = spy

    press_back(app, view)

    assert seen == [True] and app.back_hint.visible is False  # back_seconds=0: подсказка скрыта сразу после ответа


def test_the_connect_screen_also_asks_for_a_second_press():
    app, view, clock, _ = make()
    app.back_seconds = 2.5

    press_back(app, view)
    clock.now += 0.5
    press_back(app, view)

    assert views_shown(app) == ["connect"] and view.decisions == [False, True]


def test_back_while_busy_never_exits_and_does_not_navigate():
    app, view, _, _ = make(STORED)
    app._busy = True  # noqa: SLF001 - идёт отправка или подключение

    press_back(app, view)
    press_back(app, view)

    assert view.decisions == [False, False] and views_shown(app) == ["camera"]


def test_the_exit_hint_is_hidden_when_going_back_a_screen():
    app, _, _, _ = make(STORED)
    app.back_seconds = 2.5

    assert asyncio.run(app._handle_back()) is False  # noqa: SLF001 - первое нажатие показывает подсказку
    assert app.back_hint.visible
    asyncio.run(app.on_capture(None))
    assert asyncio.run(app._handle_back()) is False  # noqa: SLF001 - возврат с результатов

    assert views_shown(app) == ["camera"] and not app.back_hint.visible


def test_the_hint_overlays_the_screen_instead_of_shrinking_the_camera_view():
    """Раньше подсказка была элементом той же Column, где camera_view тоже expand=True: появляясь, она отжимала
    высоту у окна камеры. Теперь это отдельный слой Stack, а не соседний по потоку элемент."""
    app, _, _, _ = make(STORED)

    stack = app.page.added[0].content  # SafeArea -> Stack
    assert isinstance(stack, ft.Stack)
    flow_column = stack.controls[0]
    assert app.back_hint not in flow_column.controls
    assert app.camera_view in flow_column.controls


def test_a_page_without_views_does_not_break_the_build():
    class Bare(StubPage):
        def __init__(self):
            super().__init__()
            del self.views

    page = Bare()
    app = MobileApp(
        page,
        ConnectionStore(FakePrefs()),
        CameraController(FakeCameraApi(), FakePermission(), settle_seconds=0, retry_seconds=0),
        preview=ft.Container(),
        picker=FakePicker(),
        clipboard=FakeClipboard(),
        mount_seconds=0,
    )

    app.build()

    assert page.added
