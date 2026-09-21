import asyncio

import flet_camera as fc
import flet_permission_handler as ph
import pytest

from gmagc_mobile.camera import CameraController
from tests.fakes_mobile import FakeCameraApi, FakePermission, cam


def make(api=None, permission=None):
    api = api or FakeCameraApi()
    return CameraController(api, permission or FakePermission(), settle_seconds=0), api


def started(api=None):
    controller, api = make(api)
    assert asyncio.run(controller.start())
    return controller, api


def test_start_asks_for_the_camera_permission_and_picks_the_back_camera():
    permission = FakePermission()
    controller, api = make(permission=permission)

    assert asyncio.run(controller.start()) is True

    assert permission.requested == [ph.Permission.CAMERA]
    assert api.calls[0] == ("initialize", fc.CameraLensDirection.BACK, fc.ResolutionPreset.HIGH, False)
    assert controller.ready and controller.error == ""
    assert (controller.min_zoom, controller.max_zoom, controller.zoom) == (1.0, 6.0, 1.0)


def test_without_a_back_camera_the_first_one_is_used():
    api = FakeCameraApi(cameras=[cam("front")])
    controller, _ = make(api)

    assert asyncio.run(controller.start()) is True
    assert api.calls[0][1] == fc.CameraLensDirection.FRONT


def test_a_denied_permission_is_reported_and_the_camera_stays_off():
    controller, api = make(permission=FakePermission(ph.PermissionStatus.DENIED))

    assert asyncio.run(controller.start()) is False

    assert not controller.ready and "разрешите" in controller.error and api.calls == []


def test_no_cameras_is_reported():
    controller, _ = make(FakeCameraApi(cameras=[]))

    assert asyncio.run(controller.start()) is False
    assert controller.error == "Камера не найдена"


@pytest.mark.parametrize("method", ["get_available_cameras", "initialize"])
def test_plugin_failures_become_a_message_not_an_exception(method):
    controller, _ = make(FakeCameraApi(fail=method))

    assert asyncio.run(controller.start()) is False
    assert controller.error.startswith("Ошибка камеры:") and method in controller.error


def test_an_unreadable_zoom_range_keeps_the_camera_usable_without_zoom():
    controller, _ = make(FakeCameraApi(fail="get_max_zoom_level"))

    assert asyncio.run(controller.start()) is True
    assert (controller.min_zoom, controller.max_zoom) == (1.0, 1.0)


def test_zoom_is_clamped_to_the_supported_range_and_sent_to_the_camera():
    controller, api = started(FakeCameraApi(min_zoom=1.0, max_zoom=4.0))

    assert asyncio.run(controller.set_zoom(2.5)) == 2.5
    assert asyncio.run(controller.set_zoom(99)) == 4.0
    assert asyncio.run(controller.set_zoom(0.2)) == 1.0

    assert [call for call in api.calls if call[0] == "zoom"] == [("zoom", 2.5), ("zoom", 4.0), ("zoom", 1.0)]
    assert controller.zoom == 1.0


def test_zoom_by_steps_up_and_down():
    controller, _ = started()

    assert asyncio.run(controller.zoom_by(0.5)) == 1.5
    assert asyncio.run(controller.zoom_by(0.5)) == 2.0
    assert asyncio.run(controller.zoom_by(-1.5)) == 1.0


def test_zoom_does_nothing_when_the_camera_has_no_zoom_range():
    controller, api = started(FakeCameraApi(min_zoom=1.0, max_zoom=1.0))

    assert asyncio.run(controller.set_zoom(3)) == 1.0
    assert not [call for call in api.calls if call[0] == "zoom"]


def test_a_failing_zoom_call_is_reported_and_keeps_the_old_zoom():
    controller, api = started()
    api.fail = "set_zoom_level"

    assert asyncio.run(controller.set_zoom(3)) == 1.0
    assert "сбой set_zoom_level" in controller.error


def test_a_tap_focuses_and_meters_at_the_normalized_point():
    controller, api = started()

    assert asyncio.run(controller.focus_at(200, 100, 400, 800)) is True

    assert ("focus_point", (0.5, 0.125)) in api.calls and ("exposure_point", (0.5, 0.125)) in api.calls
    assert not [call for call in api.calls if call[0] == "focus_mode"]


def test_points_outside_the_preview_are_clamped_and_an_unknown_size_is_ignored():
    controller, api = started()

    assert asyncio.run(controller.focus_at(-50, 900, 400, 800)) is True
    assert ("focus_point", (0.0, 1.0)) in api.calls
    api.calls.clear()
    assert asyncio.run(controller.focus_at(10, 10, 0, 0)) is False
    assert api.calls == []


def test_focus_is_ignored_while_the_camera_is_not_ready():
    controller, api = make()

    assert asyncio.run(controller.focus_at(10, 10, 100, 100)) is False
    assert api.calls == []


def test_a_camera_without_point_focus_reports_it():
    controller, api = started()
    api.fail = "set_focus_point"

    assert asyncio.run(controller.focus_at(10, 10, 100, 100)) is False
    assert controller.error.startswith("Фокус по точке недоступен")


def test_the_focus_lock_toggles_between_locked_and_auto():
    controller, api = started()

    assert asyncio.run(controller.toggle_focus_lock()) is True
    assert asyncio.run(controller.toggle_focus_lock()) is False

    assert [call for call in api.calls if call[0] == "focus_mode"] == [
        ("focus_mode", fc.FocusMode.LOCKED),
        ("focus_mode", fc.FocusMode.AUTO),
    ]


def test_a_tap_with_the_lock_on_refocuses_and_locks_again():
    controller, api = started()
    asyncio.run(controller.toggle_focus_lock())
    api.calls.clear()

    asyncio.run(controller.focus_at(100, 100, 200, 200))

    assert [call[0] for call in api.calls] == ["focus_mode", "focus_point", "exposure_point", "focus_mode"]
    assert api.calls[0] == ("focus_mode", fc.FocusMode.AUTO) and api.calls[-1] == ("focus_mode", fc.FocusMode.LOCKED)


def test_take_picture_returns_the_bytes_and_requires_a_ready_camera():
    controller, _ = started(FakeCameraApi(picture=b"\xff\xd8jpeg"))
    assert asyncio.run(controller.take_picture()) == b"\xff\xd8jpeg"

    idle, _ = make()
    with pytest.raises(RuntimeError):
        asyncio.run(idle.take_picture())


def test_pause_and_resume_only_touch_a_ready_camera_and_never_raise():
    idle, idle_api = make()
    asyncio.run(idle.pause())
    asyncio.run(idle.resume())
    assert idle_api.calls == []

    controller, api = started()
    asyncio.run(controller.pause())
    asyncio.run(controller.resume())
    assert api.calls[-2:] == [("pause",), ("resume",)]


def test_an_unsupported_platform_reports_it_without_touching_the_camera():
    permission = FakePermission()
    api = FakeCameraApi()
    controller = CameraController(api, permission, settle_seconds=0, supported=False)

    assert asyncio.run(controller.start()) is False

    assert not controller.ready and "только на телефоне" in controller.error
    assert permission.requested == [] and api.calls == []
