import asyncio

import flet_camera as fc
import flet_permission_handler as ph
import pytest

from gmagc_mobile.camera import CameraController
from tests.fakes_mobile import FakeCameraApi, FakePermission, cam, frame_event


def make(api=None, permission=None):
    api = api or FakeCameraApi()
    return CameraController(api, permission or FakePermission(), settle_seconds=0, retry_seconds=0), api


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


def test_scanning_starts_the_frame_stream_and_wires_the_callback():
    controller, api = started(FakeCameraApi(streaming=True))
    seen = []

    async def on_frame(event):
        seen.append(event)

    assert asyncio.run(controller.start_scanning(on_frame)) is True
    assert api.stream_started == 1 and api.on_stream_image is on_frame

    asyncio.run(api.on_stream_image(frame_event(width=10, height=10)))
    assert seen and seen[0].width == 10

    asyncio.run(controller.stop_scanning())
    assert api.stream_stopped == 1 and api.on_stream_image is None


def test_scanning_is_refused_when_the_camera_does_not_support_it():
    controller, api = started(FakeCameraApi(streaming=False))

    started_ok = asyncio.run(controller.start_scanning(lambda event: None))

    assert started_ok is False and api.stream_started == 0


def test_scanning_is_refused_when_the_camera_is_not_ready():
    idle, api = make(FakeCameraApi(streaming=True))

    assert asyncio.run(idle.start_scanning(lambda event: None)) is False and api.stream_started == 0


def test_a_plugin_that_lacks_streaming_support_falls_back_gracefully():
    """Старые версии плагина без нужных методов: сканирование тихо недоступно, а не падение экрана."""

    class NoStreamingApi(FakeCameraApi):
        async def supports_image_streaming(self):
            raise AttributeError("no such method")

    controller, _ = started(NoStreamingApi())

    assert asyncio.run(controller.start_scanning(lambda event: None)) is False


def test_a_failure_starting_the_stream_is_reported_and_scanning_stays_off():
    controller, api = started(FakeCameraApi(streaming=True, stream_fail="дым пошёл"))

    assert asyncio.run(controller.start_scanning(lambda event: None)) is False
    assert "дым пошёл" in controller.error


def test_stopping_scanning_that_never_started_does_nothing():
    controller, api = started()
    asyncio.run(controller.stop_scanning())
    assert api.stream_stopped == 0


def test_an_unsupported_platform_reports_it_without_touching_the_camera():
    permission = FakePermission()
    api = FakeCameraApi()
    controller = CameraController(api, permission, settle_seconds=0, supported=False)

    assert asyncio.run(controller.start()) is False

    assert not controller.ready and "только на телефоне" in controller.error
    assert permission.requested == [] and api.calls == []


def test_the_initial_zoom_is_one_even_when_the_camera_reports_a_wider_minimum():
    controller, _ = started(FakeCameraApi(min_zoom=0.6, max_zoom=8.0))

    assert (controller.min_zoom, controller.max_zoom, controller.zoom) == (0.6, 8.0, 1.0)


def test_the_initial_zoom_is_the_minimum_when_one_is_out_of_range():
    controller, _ = started(FakeCameraApi(min_zoom=2.0, max_zoom=5.0))

    assert controller.zoom == 2.0


def test_invalidate_marks_the_camera_not_ready_and_start_creates_a_new_controller():
    controller, api = started()
    asyncio.run(controller.set_zoom(3))
    asyncio.run(controller.toggle_focus_lock())

    controller.invalidate()
    assert not controller.ready
    with pytest.raises(RuntimeError):
        asyncio.run(controller.take_picture())

    assert asyncio.run(controller.start()) is True

    assert len([c for c in api.calls if c[0] == "initialize"]) == 2
    assert controller.ready and controller.zoom == 1.0 and controller.focus_locked is False


def test_restart_reinitializes_a_camera_that_was_ready():
    controller, api = started()

    assert asyncio.run(controller.restart()) is True

    assert len([c for c in api.calls if c[0] == "initialize"]) == 2 and controller.ready


def test_a_plugin_failure_on_the_first_attempt_is_retried_once():
    api = FakeCameraApi()
    original = api.initialize
    attempts = []

    async def flaky(description, preset, enable_audio=True):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("виджет камеры ещё не появился")
        await original(description, preset, enable_audio)

    api.initialize = flaky
    controller, _ = make(api)

    assert asyncio.run(controller.start()) is True
    assert len(attempts) == 2 and controller.ready and controller.error == ""


def test_a_denied_permission_is_not_retried():
    permission = FakePermission(ph.PermissionStatus.DENIED)
    controller, _ = make(permission=permission)

    assert asyncio.run(controller.start()) is False
    assert len(permission.requested) == 1
