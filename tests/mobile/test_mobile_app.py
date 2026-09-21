import asyncio
from pathlib import Path
from types import SimpleNamespace

import flet as ft
import flet_permission_handler as ph
import pytest

from gmagc_common.protocol import Connection, Health, Status
from gmagc_mobile import client
from gmagc_mobile.about import AUTHOR, NAME, VERSION
from gmagc_mobile.app import MobileApp, build_page
from gmagc_mobile.camera import CameraController
from gmagc_mobile.client import ClientError
from gmagc_mobile.qr import QrUnavailable
from gmagc_mobile.store import KEY_CODE, KEY_HOST, KEY_PORT, ConnectionStore
from tests.fakes import FakeClipboard, FakePicker, StubPage, texts, walk
from tests.fakes_mobile import FakeCameraApi, FakePermission, FakePrefs, Script, sample_response

PC = Connection("192.168.1.121", 8765, "ZBZ36YNK")
STORED = {KEY_HOST: "192.168.1.121", KEY_PORT: 8765, KEY_CODE: "ZBZ36YNK"}


def make_app(prefs=None, script=None, camera_api=None, permission=None, qr_reader=None, picker=None, clipboard=None):
    script = script or Script()
    prefs = prefs if prefs is not None else FakePrefs()
    camera_api = camera_api or FakeCameraApi()
    controller = CameraController(camera_api, permission or FakePermission(), settle_seconds=0)
    page = StubPage()
    app = MobileApp(
        page,
        ConnectionStore(prefs),
        controller,
        preview=ft.Container(),
        picker=picker or FakePicker(),
        clipboard=clipboard or FakeClipboard(),
        client_factory=script.factory,
        qr_reader=qr_reader or (lambda data: None),
        marker_seconds=0,
    )
    app.build()
    return app, page, script, prefs, camera_api


def run(coroutine):
    return asyncio.run(coroutine)


def start(**kwargs):
    app, page, script, prefs, camera_api = make_app(**kwargs)
    run(app.start())
    return app, page, script, prefs, camera_api


def connect_manually(app, address="192.168.1.121:8765", code="zbz3-6ynk"):
    app.address_field.value = address
    app.code_field.value = code
    run(app.on_connect(None))


def views(app):
    return [name for name in ("connect", "camera", "results") if getattr(app, f"{name}_view").visible]


def shoot(app):
    run(app.on_capture(None))


def test_the_first_start_shows_the_connect_screen_and_leaves_the_camera_off():
    app, page, script, _, camera_api = start()

    assert views(app) == ["connect"] and camera_api.calls == [] and script.connections == []
    shown = " ".join(t for t in texts(page.added[0]) if t)
    assert NAME in shown and VERSION in shown and AUTHOR in shown


def test_a_stored_connection_is_restored_and_opens_the_camera():
    app, _, script, _, camera_api = start(prefs=FakePrefs(STORED))

    assert script.connections == [PC] and views(app) == ["camera"]
    assert app.address_field.value == "192.168.1.121:8765" and app.camera.ready
    assert app.camera_title.value == "Подключено: 192.168.1.121:8765 · 11\u00a0178 файлов"
    assert camera_api.calls[0][0] == "initialize"


def test_a_stored_connection_to_an_unreachable_pc_shows_the_error_and_keeps_the_data():
    script = Script()
    script.verify_result = ClientError(client.UNREACHABLE, "ConnectionRefusedError: x")
    app, _, _, prefs, _ = start(prefs=FakePrefs(STORED), script=script)

    assert views(app) == ["connect"] and app.connect_error.visible
    assert "Нет связи с ПК" in app.connect_error.value and prefs.data == STORED
    assert app.address_field.value == "192.168.1.121:8765" and app.code_field.value == "ZBZ36YNK"


def test_manual_connect_verifies_saves_and_opens_the_camera():
    app, _, script, prefs, _ = start()

    connect_manually(app)

    assert script.connections == [PC] and views(app) == ["camera"] and not app.connect_error.visible
    assert prefs.data == STORED


def test_manual_connect_without_a_port_uses_the_default_one():
    app, _, script, _, _ = start()

    connect_manually(app, address="192.168.1.121")

    assert script.connections == [PC]


@pytest.mark.parametrize(
    ("address", "code", "fragment"),
    [
        ("", "ZBZ36YNK", "Введите адрес ПК"),
        ("bad host", "ZBZ36YNK", "Введите адрес ПК"),
        ("192.168.1.5", "BAD", "8 символов"),
    ],
)
def test_invalid_input_is_reported_without_calling_the_pc(address, code, fragment):
    app, _, script, _, _ = start()

    connect_manually(app, address, code)

    assert fragment in app.connect_error.value and app.connect_error.visible
    assert script.connections == [] and views(app) == ["connect"]


def test_a_wrong_code_stays_on_the_connect_screen_and_saves_nothing():
    script = Script()
    script.verify_result = ClientError(client.UNAUTHORIZED, "неверный код доступа")
    app, _, _, prefs, _ = start(script=script)

    connect_manually(app)

    assert views(app) == ["connect"] and "Неверный код" in app.connect_error.value and prefs.data == {}
    assert "Неверный код" in app.diag_text.value


def test_a_pc_without_an_index_connects_with_a_note():
    script = Script()
    script.verify_result = (Health("GMAGC", 1, "0.5.0", False, 0), Status(False, 0, 0, False, 0, 0))
    app, _, _, _, _ = start(script=script)

    connect_manually(app)

    assert views(app) == ["camera"] and "не построен" in app.camera_title.value
    assert app.camera_message.visible and "индекс" in app.camera_message.value


def test_the_qr_scan_reads_the_link_and_connects():
    seen = []

    def reader(data):
        seen.append(data)
        return PC

    app, _, script, prefs, camera_api = start(qr_reader=reader)

    run(app.on_scan_qr(None))
    assert views(app) == ["camera"] and app.mode == "scan" and app.scan_now_button.visible
    assert not app.capture_button.visible and "QR" in app.camera_title.value
    run(app.on_scan_now(None))

    assert seen == [b"JPEG-shot"] and script.connections == [PC] and prefs.data == STORED
    assert app.mode == "shoot" and app.capture_button.visible and not app.scan_now_button.visible


def test_a_qr_scan_without_a_code_asks_to_move_closer():
    app, _, script, _, _ = start()
    run(app.on_scan_qr(None))

    run(app.on_scan_now(None))

    assert script.connections == [] and views(app) == ["camera"] and app.mode == "scan"
    assert "QR-код не найден" in app.camera_message.value and not app.scan_now_button.disabled


def test_an_unavailable_qr_reader_asks_for_manual_entry():
    def reader(data):
        raise QrUnavailable("нет zbar")

    app, _, _, _, _ = start(qr_reader=reader)
    run(app.on_scan_qr(None))

    run(app.on_scan_now(None))

    assert "вручную" in app.camera_message.value


def test_cancelling_the_scan_returns_to_the_connect_screen():
    app, _, _, _, _ = start()
    run(app.on_scan_qr(None))

    run(app.on_cancel_scan(None))

    assert views(app) == ["connect"]


def test_a_denied_camera_permission_is_shown_and_manual_entry_still_works():
    app, _, _, _, _ = start(permission=FakePermission(ph.PermissionStatus.DENIED))
    run(app.on_scan_qr(None))

    assert "разрешите" in app.camera_message.value and app.scan_now_button.disabled
    run(app.on_cancel_scan(None))
    connect_manually(app)
    assert views(app) == ["camera"] and app.capture_button.disabled and not app.gallery_button.disabled


def test_capture_sends_the_shot_and_shows_the_results():
    app, _, script, _, camera_api = start(prefs=FakePrefs(STORED))

    shoot(app)

    assert script.matches == [b"JPEG-shot"] and views(app) == ["results"]
    assert len(app.results_column.controls) == 2 and app.results_photo.visible and app.results_projection.visible
    first = texts(app.results_column.controls[0])
    assert "a.png" in first and "C:\\gobos\\vendor\\a.png" in first and "91.2%" in first and "ещё 1 файлов" in first
    assert not app.results_banner.visible and ("pause",) in camera_api.calls
    assert not app.capture_button.disabled


def test_low_confidence_and_no_projection_show_banners():
    script = Script()
    script.match_result = sample_response("low_confidence")
    app, _, _, _, _ = start(prefs=FakePrefs(STORED), script=script)
    shoot(app)
    assert app.results_banner.visible and "ненадёжно" in app.results_banner_text.value

    script.match_result = sample_response("no_projection", results=[])
    run(app.on_again(None))
    shoot(app)
    assert "переснимите" in app.results_banner_text.value and app.results_column.controls == []


def test_a_search_error_stays_on_the_camera_with_a_message():
    script = Script()
    script.match_result = ClientError(client.UNREACHABLE, "TimeoutError: timed out")
    app, _, _, _, _ = start(prefs=FakePrefs(STORED), script=script)

    shoot(app)

    assert views(app) == ["camera"] and "Нет связи с ПК" in app.camera_message.value
    assert not app.capture_button.disabled and "Нет связи" in app.diag_text.value


def test_a_changed_code_on_the_pc_sends_the_user_back_to_the_connect_screen():
    script = Script()
    script.match_result = ClientError(client.UNAUTHORIZED, "неверный код доступа")
    app, _, _, _, _ = start(prefs=FakePrefs(STORED), script=script)

    shoot(app)

    assert views(app) == ["connect"] and "Неверный код" in app.connect_error.value


def test_a_camera_failure_while_shooting_is_reported():
    app, _, script, _, camera_api = start(prefs=FakePrefs(STORED))
    camera_api.fail = "take_picture"

    shoot(app)

    assert views(app) == ["camera"] and "Не удалось снять" in app.camera_message.value and script.matches == []
    assert not app.capture_button.disabled


def test_shoot_again_returns_to_the_camera_and_resumes_the_preview():
    app, _, _, _, camera_api = start(prefs=FakePrefs(STORED))
    shoot(app)

    run(app.on_again(None))

    assert views(app) == ["camera"] and camera_api.calls[-1] == ("resume",)


def test_clicking_a_card_and_the_copy_button_copy_the_path_as_is():
    clipboard = FakeClipboard()
    app, _, _, _, _ = start(prefs=FakePrefs(STORED), clipboard=clipboard)
    shoot(app)
    card = next(c for c in walk(app.results_column.controls[0]) if isinstance(c, ft.Container) and c.data)
    button = next(c for c in walk(app.results_column.controls[0]) if isinstance(c, ft.Button))

    run(card.on_click(SimpleNamespace(control=card)))
    run(button.on_click(SimpleNamespace(control=button)))

    assert clipboard.copied == ["C:\\gobos\\vendor\\a.png", "C:\\gobos\\vendor\\a.png"]
    assert app.copy_note.visible and "C:\\gobos\\vendor\\a.png" in app.copy_note.value


def test_the_gallery_photo_is_prepared_and_sent(tmp_path):
    photo = tmp_path / "shot.jpg"
    photo.write_bytes(b"gallery-bytes")
    app, _, script, _, _ = start(prefs=FakePrefs(STORED), picker=FakePicker(files=[str(photo)]))

    run(app.on_gallery(None))

    assert script.matches == [b"gallery-bytes"] and views(app) == ["results"]


def test_an_empty_gallery_choice_does_nothing_and_a_missing_file_is_reported():
    app, _, script, _, _ = start(prefs=FakePrefs(STORED))
    run(app.on_gallery(None))
    assert script.matches == [] and views(app) == ["camera"]

    app.picker.files = [str(Path("no-such-dir") / "missing.jpg")]
    run(app.on_gallery(None))
    assert "Не удалось подготовить фото" in app.camera_message.value and script.matches == []


def test_a_huge_gallery_file_is_shrunk_before_sending(tmp_path, monkeypatch):
    photo = tmp_path / "big.jpg"
    photo.write_bytes(b"huge")
    monkeypatch.setattr("gmagc_mobile.app.prepare_upload", lambda data: b"shrunk")
    app, _, script, _, _ = start(prefs=FakePrefs(STORED), picker=FakePicker(files=[str(photo)]))

    run(app.on_gallery(None))

    assert script.matches == [b"shrunk"]


def test_change_pc_forgets_the_connection():
    app, _, _, prefs, _ = start(prefs=FakePrefs(STORED))

    run(app.on_change_pc(None))

    assert views(app) == ["connect"] and prefs.data == {} and app.client is None and app.connection is None


def test_demo_variables_connect_and_search_at_startup(tmp_path, monkeypatch):
    photo = tmp_path / "demo.jpg"
    photo.write_bytes(b"demo-photo")
    monkeypatch.setenv("GMAGC_MOBILE_DEMO_LINK", "gmagc://connect?host=192.168.1.121&port=8765&code=ZBZ36YNK")
    monkeypatch.setenv("GMAGC_MOBILE_DEMO_PHOTO", str(photo))

    app, _, script, _, _ = start()

    assert script.connections == [PC] and script.matches == [b"demo-photo"] and views(app) == ["results"]


def test_build_page_wires_services_and_starts(monkeypatch):
    page = StubPage()
    script = Script()
    app = asyncio.run(
        build_page(
            page,
            prefs=FakePrefs(STORED),
            permission=FakePermission(),
            camera_control=ft.Container(),
            controller=CameraController(FakeCameraApi(), FakePermission(), settle_seconds=0),
            picker=FakePicker(),
            clipboard=FakeClipboard(),
            client_factory=script.factory,
        )
    )

    assert page.title == f"{NAME} {VERSION}" and script.connections == [PC] and views(app) == ["camera"]
    assert len(page.services) == 4
