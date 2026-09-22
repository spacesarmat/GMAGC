import asyncio
from types import SimpleNamespace

import flet as ft
import flet_camera as fc

from gmagc_mobile.app import MobileApp
from gmagc_mobile.camera import CameraController
from gmagc_mobile.store import ConnectionStore
from tests.fakes import FakeClipboard, FakePicker, StubPage
from tests.fakes_mobile import FakeCameraApi, FakePermission, FakePrefs, Script


def make_running_app(camera_api=None):
    camera_api = camera_api or FakeCameraApi(min_zoom=1.0, max_zoom=5.0)
    controller = CameraController(camera_api, FakePermission(), settle_seconds=0, retry_seconds=0)
    prefs = FakePrefs({"gmagc.host": "192.168.1.121", "gmagc.port": 8765, "gmagc.code": "ZBZ36YNK"})
    app = MobileApp(
        StubPage(),
        ConnectionStore(prefs),
        controller,
        preview=ft.Container(),
        picker=FakePicker(),
        clipboard=FakeClipboard(),
        client_factory=Script().factory,
        marker_seconds=0,
        mount_seconds=0,
    )
    app.build()
    asyncio.run(app.start())
    return app, camera_api


def run(coroutine):
    return asyncio.run(coroutine)


def zoom_calls(api):
    return [call[1] for call in api.calls if call[0] == "zoom"]


def test_the_slider_range_follows_the_camera_after_start():
    app, _ = make_running_app()

    assert (app.zoom_slider.min, app.zoom_slider.max, app.zoom_slider.value) == (1.0, 5.0, 1.0)
    assert not app.zoom_slider.disabled and app.zoom_label.value == "×1.0"


def test_a_camera_without_zoom_disables_the_zoom_controls():
    app, _ = make_running_app(FakeCameraApi(min_zoom=1.0, max_zoom=1.0))

    assert app.zoom_slider.disabled and app.zoom_in_button.disabled and app.zoom_out_button.disabled


def test_moving_the_slider_zooms_the_camera_and_updates_the_label():
    app, api = make_running_app()

    run(app.on_zoom_slider(SimpleNamespace(control=SimpleNamespace(value=3.25))))

    assert zoom_calls(api) == [3.25] and app.zoom_label.value == "×3.2" and app.zoom_slider.value == 3.25


def test_plus_and_minus_buttons_step_the_zoom_within_the_range():
    app, api = make_running_app()

    run(app.on_zoom_in(None))
    run(app.on_zoom_in(None))
    run(app.on_zoom_out(None))
    for _ in range(20):
        run(app.on_zoom_in(None))

    assert zoom_calls(api)[:3] == [1.5, 2.0, 1.5] and zoom_calls(api)[-1] == 5.0
    assert app.zoom_label.value == "×5.0"


def test_pinching_scales_the_zoom_from_the_value_at_the_start():
    app, api = make_running_app()
    run(app.on_zoom_slider(SimpleNamespace(control=SimpleNamespace(value=2.0))))
    api.calls.clear()

    app.on_scale_start(None)
    run(app.on_scale_update(SimpleNamespace(pointer_count=2, scale=1.5)))
    run(app.on_scale_update(SimpleNamespace(pointer_count=2, scale=2.0)))
    run(app.on_scale_update(SimpleNamespace(pointer_count=2, scale=10.0)))

    assert zoom_calls(api) == [3.0, 4.0, 5.0]


def test_a_one_finger_drag_does_not_change_the_zoom():
    app, api = make_running_app()

    app.on_scale_start(None)
    run(app.on_scale_update(SimpleNamespace(pointer_count=1, scale=3.0)))

    assert zoom_calls(api) == []


def test_tapping_the_preview_focuses_at_the_normalized_point_and_shows_then_hides_the_marker():
    app, api = make_running_app()
    app.on_preview_size(SimpleNamespace(width=400.0, height=800.0))

    run(app.on_preview_tap(SimpleNamespace(local_position=SimpleNamespace(x=100.0, y=400.0))))

    assert ("focus_point", (0.25, 0.5)) in api.calls and ("exposure_point", (0.25, 0.5)) in api.calls
    assert not app.marker.visible and (app.marker.left, app.marker.top) == (100.0 - 32, 400.0 - 32)


def test_the_marker_stays_visible_while_the_focus_call_is_running():
    app, api = make_running_app()
    app.on_preview_size(SimpleNamespace(width=400.0, height=800.0))
    seen = []
    original = api.set_focus_point

    async def spying(point):
        seen.append(app.marker.visible)
        await original(point)

    api.set_focus_point = spying

    run(app.on_preview_tap(SimpleNamespace(local_position=SimpleNamespace(x=10.0, y=10.0))))

    assert seen == [True]


def test_a_tap_before_the_preview_size_is_known_does_not_touch_the_camera():
    app, api = make_running_app()
    api.calls.clear()

    run(app.on_preview_tap(SimpleNamespace(local_position=SimpleNamespace(x=10.0, y=10.0))))

    assert api.calls == []


def test_a_camera_without_point_focus_shows_a_message():
    app, api = make_running_app()
    app.on_preview_size(SimpleNamespace(width=400.0, height=800.0))
    api.fail = "set_focus_point"

    run(app.on_preview_tap(SimpleNamespace(local_position=SimpleNamespace(x=10.0, y=10.0))))

    assert app.camera_message.visible and "Фокус по точке недоступен" in app.camera_message.value


def test_the_focus_button_locks_and_unlocks_the_focus_and_changes_its_label():
    app, api = make_running_app()
    assert app.focus_text.value == "Фокус: авто"

    run(app.on_focus_lock(None))
    assert app.focus_text.value == "Фокус: зафиксирован"
    run(app.on_focus_lock(None))
    assert app.focus_text.value == "Фокус: авто"

    assert [c for c in api.calls if c[0] == "focus_mode"] == [
        ("focus_mode", fc.FocusMode.LOCKED),
        ("focus_mode", fc.FocusMode.AUTO),
    ]


def test_the_preview_is_wrapped_in_a_gesture_detector_with_the_handlers():
    app, _ = make_running_app()

    assert app.gesture.on_tap_down == app.on_preview_tap and app.gesture.on_scale_update == app.on_scale_update
    assert app.gesture.on_scale_start == app.on_scale_start and isinstance(app.gesture, ft.GestureDetector)
    assert app.gesture.on_size_change == app.on_preview_size


def test_the_camera_fills_the_available_width_by_matching_its_aspect_ratio():
    """Соотношение сторон камеры подгоняется под реально доступное место (кадр камеры на весь экран)."""
    app, _ = make_running_app()

    app.on_preview_size(SimpleNamespace(width=400.0, height=800.0))

    assert app.preview.aspect_ratio == 0.5 and app._preview_size == (400.0, 800.0)


def test_the_aspect_ratio_is_not_reapplied_when_the_size_does_not_change():
    app, _ = make_running_app()
    app.on_preview_size(SimpleNamespace(width=400.0, height=800.0))
    updates_before = app.page.updates

    app.on_preview_size(SimpleNamespace(width=400.0, height=800.0))

    assert app.page.updates == updates_before


def test_history_lives_on_its_own_gallery_screen_not_on_the_camera_screen():
    """История снимков росла без ограничения в той же нескроллящейся колонке, что и камера — после
    десятка снимков за сессию превью почти исчезало (реальный отзыв пользователя). История теперь —
    отдельный экран «Галерея» (открывается из нижней навигации), а не часть экрана камеры: он вообще
    не может отжать место у превью, сколько бы снимков ни накопилось."""
    from tests.fakes import walk

    app, _ = make_running_app()

    assert app.camera_preview_area in app.camera_view.controls
    assert app.history_column not in list(walk(app.camera_view))
    assert app.history_column in list(walk(app.gallery_view))
