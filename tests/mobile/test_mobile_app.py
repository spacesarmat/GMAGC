import asyncio
from pathlib import Path
from types import SimpleNamespace

import flet as ft
import flet_permission_handler as ph
import pytest

from gmagc_common.protocol import Connection, Health, Status
from gmagc_mobile import client
from gmagc_mobile.about import AUTHOR, NAME, VERSION
from gmagc_mobile.app import PAGE_PADDING, MobileApp, build_page
from gmagc_mobile.camera import CameraController
from gmagc_mobile.client import ClientError
from gmagc_mobile.qr import QrImageError, QrUnavailable
from gmagc_mobile.store import KEY_CODE, KEY_HOST, KEY_PORT, ConnectionStore
from tests.fakes import FakeClipboard, FakePicker, StubPage, texts, walk
from tests.fakes_mobile import FakeCameraApi, FakePermission, FakePrefs, FakeShare, Script, frame_event, sample_response

PC = Connection("192.168.1.121", 8765, "ZBZ36YNK")
STORED = {KEY_HOST: "192.168.1.121", KEY_PORT: 8765, KEY_CODE: "ZBZ36YNK"}


def make_app(
    prefs=None,
    script=None,
    camera_api=None,
    permission=None,
    qr_reader=None,
    frame_reader=None,
    picker=None,
    clipboard=None,
    share=None,
):
    script = script or Script()
    prefs = prefs if prefs is not None else FakePrefs()
    camera_api = camera_api or FakeCameraApi()
    controller = CameraController(camera_api, permission or FakePermission(), settle_seconds=0, retry_seconds=0)
    page = StubPage()
    app = MobileApp(
        page,
        ConnectionStore(prefs),
        controller,
        preview=ft.Container(),
        picker=picker or FakePicker(),
        clipboard=clipboard or FakeClipboard(),
        share=share or FakeShare(),
        client_factory=script.factory,
        qr_reader=qr_reader or (lambda data: None),
        frame_reader=frame_reader or (lambda width, height, encoded_format, data: None),
        marker_seconds=0,
        mount_seconds=0,
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
    names = ("connect", "camera", "results", "gallery", "settings", "about", "help")
    return [name for name in names if getattr(app, f"{name}_view").visible]


def shoot(app):
    run(app.on_capture(None))


def test_the_first_start_shows_the_connect_screen_and_leaves_the_camera_off():
    app, page, script, _, camera_api = start()

    assert views(app) == ["connect"] and camera_api.calls == [] and script.connections == []
    shown = " ".join(t for t in texts(page.added[0]) if t)
    assert NAME in shown and VERSION in shown and AUTHOR in shown


def test_opening_settings_about_and_help_from_the_connect_screen_returns_there():
    app, _, _, _, _ = start()
    assert views(app) == ["connect"]

    for open_handler, name in (
        (app.on_open_settings, "settings"),
        (app.on_open_about, "about"),
        (app.on_open_help, "help"),
    ):
        open_handler(None)
        assert views(app) == [name]
        app.on_close_overlay(None)
        assert views(app) == ["connect"]


def test_opening_gallery_and_settings_from_the_camera_screen_returns_there():
    app, _, _, _, _ = start(prefs=FakePrefs(STORED))
    assert views(app) == ["camera"]

    app.on_open_gallery(None)
    assert views(app) == ["gallery"]
    app.on_close_overlay(None)
    assert views(app) == ["camera"]

    app.on_open_settings(None)
    assert views(app) == ["settings"]
    app.on_close_overlay(None)
    assert views(app) == ["camera"]


def test_the_gallery_screen_shows_an_empty_hint_until_a_photo_is_taken():
    app, _, _, _, _ = start(prefs=FakePrefs(STORED))

    assert app.history_empty.visible is True
    shoot(app)
    run(app.on_again(None))

    assert app.history_empty.visible is False


def test_the_theme_uses_the_shared_brand_seed_and_is_always_dark():
    """Всегда тёмная, независимо от системной темы телефона — по одобренному референсу дизайна."""
    from gmagc_common.theme import SEED_COLOR

    _, page, _, _, _ = make_app()

    assert page.theme.color_scheme_seed == SEED_COLOR
    assert page.dark_theme.color_scheme_seed == SEED_COLOR
    assert page.theme_mode == ft.ThemeMode.DARK


def test_the_score_badge_colour_follows_the_match_confidence():
    from gmagc_common.protocol import ResultItem

    app, _, _, _, _ = make_app()

    def badge(score):
        item = ResultItem(1, "a", "/lib/a.png", score, (), b"")
        card = app._result_card(item)  # noqa: SLF001 - сборка карточки результата, не публичный API
        return card.content.content.controls[1].controls[0].controls[-1]

    good, low, bad = badge(0.92), badge(0.78), badge(0.50)
    assert good.bgcolor != low.bgcolor != bad.bgcolor
    assert "92" in good.content.value and "78" in low.content.value and "50" in bad.content.value


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


def test_a_phone_that_supports_streaming_scans_automatically_without_the_button():
    camera_api = FakeCameraApi(streaming=True)
    app, _, script, prefs, _ = start(camera_api=camera_api, frame_reader=lambda w, h, fmt, data: PC)

    run(app.on_scan_qr(None))
    assert camera_api.stream_started == 1 and not app.scan_now_button.visible and "автоматически" in app.camera_title.value

    run(camera_api.on_stream_image(frame_event()))

    assert script.connections == [PC] and prefs.data == STORED
    assert app.mode == "shoot" and camera_api.stream_stopped == 1


def test_frames_that_do_not_contain_a_code_are_silently_skipped():
    camera_api = FakeCameraApi(streaming=True)
    seen = []

    def reader(width, height, encoded_format, data):
        seen.append(data)
        return None

    app, _, script, _, _ = start(camera_api=camera_api, frame_reader=reader)
    run(app.on_scan_qr(None))

    run(camera_api.on_stream_image(frame_event(data=b"first")))

    assert seen == [b"first"] and script.connections == [] and views(app) == ["camera"] and app.mode == "scan"


def test_frames_are_throttled_and_never_processed_concurrently():
    camera_api = FakeCameraApi(streaming=True)
    seen = []
    app, _, _, _, _ = start(camera_api=camera_api, frame_reader=lambda w, h, fmt, data: seen.append(data) or None)
    run(app.on_scan_qr(None))

    run(camera_api.on_stream_image(frame_event(data=b"one")))
    run(camera_api.on_stream_image(frame_event(data=b"two")))  # тут же следом: должно быть отброшено паузой

    assert seen == [b"one"]

    app._scan_last = app._clock() - app.scan_interval - 1  # имитируем, что пауза истекла
    run(camera_api.on_stream_image(frame_event(data=b"three")))

    assert seen == [b"one", b"three"]


def test_when_the_reader_is_unavailable_streaming_stops_and_the_manual_button_returns():
    from gmagc_mobile.qr import QrUnavailable

    camera_api = FakeCameraApi(streaming=True)

    def reader(width, height, encoded_format, data):
        raise QrUnavailable("нет zbar")

    app, _, script, _, _ = start(camera_api=camera_api, frame_reader=reader)
    run(app.on_scan_qr(None))

    run(camera_api.on_stream_image(frame_event()))

    assert camera_api.stream_stopped == 1 and app.scan_now_button.visible and script.connections == []
    assert "недоступно" in app.camera_message.value


def test_a_phone_without_streaming_support_falls_back_to_the_manual_button():
    camera_api = FakeCameraApi(streaming=False)
    app, _, _, _, _ = start(camera_api=camera_api)

    run(app.on_scan_qr(None))

    assert camera_api.stream_started == 0 and app.scan_now_button.visible
    assert "Автосканирование недоступно" in app.camera_title.value


def test_cancelling_the_scan_stops_the_stream():
    camera_api = FakeCameraApi(streaming=True)
    app, _, _, _, _ = start(camera_api=camera_api)
    run(app.on_scan_qr(None))

    run(app.on_cancel_scan(None))

    assert camera_api.stream_stopped == 1 and views(app) == ["connect"]


def test_connecting_by_qr_shows_a_notice_that_the_connection_succeeded():
    app, page, _, _, _ = start(qr_reader=lambda data: PC)
    run(app.on_scan_qr(None))

    run(app.on_scan_now(None))

    assert len(page.dialogs) == 1
    snack_bar = page.dialogs[0]
    assert isinstance(snack_bar, ft.SnackBar) and "Подключено" in snack_bar.content.value


def test_connecting_manually_shows_no_qr_notice():
    app, page, _, _, _ = start()

    connect_manually(app)

    assert page.dialogs == []


def test_a_qr_scan_without_a_code_asks_to_move_closer_and_appends_the_diagnosis():
    app, _, script, _, _ = start()
    app.qr_diagnose = lambda data: f"снимок: {len(data)} байт; самопроверка: ок"
    run(app.on_scan_qr(None))

    run(app.on_scan_now(None))

    assert script.connections == [] and views(app) == ["camera"] and app.mode == "scan"
    assert "QR-код не найден" in app.camera_message.value and not app.scan_now_button.disabled
    assert "[снимок: 9 байт; самопроверка: ок]" in app.camera_message.value and "вручную" in app.camera_message.value
    assert "самопроверка" in app.diag_text.value


def test_an_unreadable_shot_is_reported_with_the_reason():
    def reader(data):
        raise QrImageError("UnidentifiedImageError: cannot identify image file")

    app, _, _, _, _ = start(qr_reader=reader)
    run(app.on_scan_qr(None))

    run(app.on_scan_now(None))

    assert "не удалось прочитать" in app.camera_message.value and "UnidentifiedImageError" in app.camera_message.value


def test_the_scan_screen_offers_manual_entry():
    app, _, _, _, _ = start()
    run(app.on_scan_qr(None))

    assert app.cancel_scan_button.visible and app.cancel_scan_button.content == "Ввести вручную"


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
    assert not app.results_banner.visible and not app.camera.ready  # вид камеры скрыт: контроллер камеры потерян
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


def test_a_search_error_offers_a_retry_that_resends_the_same_photo_without_reshooting():
    script = Script()
    script.match_result = ClientError(client.UNREACHABLE, "TimeoutError: timed out")
    app, _, _, _, _ = start(prefs=FakePrefs(STORED), script=script)

    shoot(app)
    assert app.retry_button.visible is True and script.matches == [b"JPEG-shot"]

    script.match_result = sample_response()  # ПК снова доступен
    run(app.on_retry(None))

    assert script.matches == [b"JPEG-shot", b"JPEG-shot"]  # тот же снимок, без повторной съёмки
    assert views(app) == ["results"] and app.retry_button.visible is False


def test_a_generic_search_exception_also_offers_retry():
    script = Script()
    script.match_result = RuntimeError("connection reset")
    app, _, _, _, _ = start(prefs=FakePrefs(STORED), script=script)

    shoot(app)

    assert app.retry_button.visible is True and "Ошибка" in app.camera_message.value


def test_retry_does_nothing_without_a_previous_failure():
    app, _, script, _, _ = start(prefs=FakePrefs(STORED))

    run(app.on_retry(None))

    assert script.matches == []


def test_an_unauthorized_error_does_not_offer_a_retry_on_the_camera():
    script = Script()
    script.match_result = ClientError(client.UNAUTHORIZED, "неверный код доступа")
    app, _, _, _, _ = start(prefs=FakePrefs(STORED), script=script)

    shoot(app)

    assert views(app) == ["connect"] and app.retry_button.visible is False


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


def initializations(camera_api):
    return len([call for call in camera_api.calls if call[0] == "initialize"])


def test_shoot_again_starts_the_camera_anew_because_the_hidden_preview_lost_its_controller():
    app, _, script, _, camera_api = start(prefs=FakePrefs(STORED))
    shoot(app)
    assert initializations(camera_api) == 1 and not app.camera.ready

    run(app.on_again(None))

    assert views(app) == ["camera"] and app.camera.ready and initializations(camera_api) == 2
    shoot(app)
    assert script.matches == [b"JPEG-shot", b"JPEG-shot"] and views(app) == ["results"]


def test_returning_to_the_scan_after_cancelling_starts_the_camera_anew():
    app, _, _, _, camera_api = start()
    run(app.on_scan_qr(None))
    assert initializations(camera_api) == 1

    run(app.on_cancel_scan(None))
    assert not app.camera.ready
    run(app.on_scan_qr(None))

    assert initializations(camera_api) == 2 and app.camera.ready and not app.camera_message.visible


def test_switching_between_scan_and_shoot_keeps_the_running_camera():
    app, _, _, _, camera_api = start(qr_reader=lambda data: PC)
    run(app.on_scan_qr(None))

    run(app.on_scan_now(None))  # подключение: вид камеры остаётся на экране, перезапуск не нужен

    assert app.mode == "shoot" and initializations(camera_api) == 1 and app.camera.ready


def test_a_lost_camera_controller_is_recovered_once_when_shooting():
    camera_api = FakeCameraApi(picture_failures=1)
    app, _, script, _, _ = start(prefs=FakePrefs(STORED), camera_api=camera_api)

    shoot(app)

    assert script.matches == [b"JPEG-shot"] and views(app) == ["results"]
    assert initializations(camera_api) == 2


def test_when_recovery_fails_the_shot_error_is_reported():
    camera_api = FakeCameraApi(picture_failures=5)
    app, _, script, _, _ = start(prefs=FakePrefs(STORED), camera_api=camera_api)

    shoot(app)

    assert script.matches == [] and views(app) == ["camera"] and "Не удалось снять" in app.camera_message.value
    assert not app.capture_button.disabled


def test_the_qr_scan_recovers_a_lost_controller_too():
    camera_api = FakeCameraApi(picture_failures=1)
    app, _, script, _, _ = start(qr_reader=lambda data: PC, camera_api=camera_api)
    run(app.on_scan_qr(None))

    run(app.on_scan_now(None))

    assert script.connections == [PC] and initializations(camera_api) == 2


def test_the_zoom_starts_at_one_when_the_camera_reaches_below_it():
    app, _, _, _, _ = start(prefs=FakePrefs(STORED), camera_api=FakeCameraApi(min_zoom=0.6, max_zoom=8.0))

    assert (app.zoom_slider.min, app.zoom_slider.max, app.zoom_slider.value) == (0.6, 8.0, 1.0)
    assert app.zoom_label.value == "×1.0"


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


def test_a_successful_search_is_added_to_the_history_and_can_be_revisited():
    app, _, _, _, _ = start(prefs=FakePrefs(STORED))

    shoot(app)
    assert app.history_empty.visible is False and len(app.history_column.controls) == 1
    assert any("a.png" in t and "91.2%" in t for t in texts(app.history_column.controls[0]))

    run(app.on_again(None))
    shoot(app)
    assert len(app.history_column.controls) == 2

    entry = app.history_column.controls[0]
    run(entry.on_click(SimpleNamespace(control=entry)))

    assert views(app) == ["results"] and len(app.results_column.controls) == 2


def test_history_keeps_only_the_last_ten_entries():
    app, _, _, _, _ = start(prefs=FakePrefs(STORED))

    for _ in range(12):
        run(app.on_again(None))
        shoot(app)

    assert len(app.history_column.controls) == 10


def test_revisiting_a_history_entry_does_not_duplicate_it():
    app, _, _, _, _ = start(prefs=FakePrefs(STORED))
    shoot(app)
    entry = app.history_column.controls[0]

    run(entry.on_click(SimpleNamespace(control=entry)))

    assert len(app.history_column.controls) == 1


def test_a_no_projection_result_is_labelled_in_the_history():
    script = Script()
    script.match_result = sample_response("no_projection", results=[])
    app, _, _, _, _ = start(prefs=FakePrefs(STORED), script=script)

    shoot(app)

    assert any("не найдена" in t for t in texts(app.history_column.controls[0]))


def test_share_sends_a_text_summary_of_the_top_result():
    share = FakeShare()
    app, _, _, _, _ = start(prefs=FakePrefs(STORED), share=share)

    shoot(app)
    run(app.on_share(None))

    assert share.texts and "a.png" in share.texts[0] and "C:\\gobos\\vendor\\a.png" in share.texts[0]


def test_a_failed_share_is_reported_without_raising():
    share = FakeShare(fail=True)
    app, _, _, _, _ = start(prefs=FakePrefs(STORED), share=share)

    shoot(app)
    run(app.on_share(None))

    assert "Не удалось поделиться" in app.copy_note.value


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
            controller=CameraController(FakeCameraApi(), FakePermission(), settle_seconds=0, retry_seconds=0),
            picker=FakePicker(),
            clipboard=FakeClipboard(),
            client_factory=script.factory,
            mount_seconds=0,
            tracker=None,
            support=False,
        )
    )

    assert page.title == f"{NAME} {VERSION}" and script.connections == [PC] and views(app) == ["camera"]
    assert len(page.services) == 6  # хранилище, разрешение, выбор файла, буфер обмена, «поделиться», загрузчик ссылок


def build_on(platform, web=False):
    page = StubPage()
    page.platform = platform
    page.web = web
    script = Script()
    app = asyncio.run(
        build_page(
            page,
            prefs=FakePrefs(),
            permission=FakePermission(),
            picker=FakePicker(),
            clipboard=FakeClipboard(),
            client_factory=script.factory,
            mount_seconds=0,
            tracker=None,
            support=False,
        )
    )
    return app


def test_the_camera_control_is_used_only_on_supported_platforms():
    import flet_camera as fc

    for platform, web in ((ft.PagePlatform.ANDROID, False), (ft.PagePlatform.IOS, False), (ft.PagePlatform.WINDOWS, True)):
        app = build_on(platform, web)
        assert app.camera.supported is True and isinstance(app.preview, fc.Camera), platform


def test_the_camera_preview_spans_the_full_width_beyond_the_page_padding():
    app, page, _, _, _ = start()

    assert page.padding == PAGE_PADDING
    margin = app.camera_preview_area.margin
    assert margin.left == -PAGE_PADDING and margin.right == -PAGE_PADDING
    assert margin.top == 0 and margin.bottom == 0


def test_the_shutter_and_gallery_buttons_sit_below_the_preview_outside_the_tap_focus_area():
    app, _, _, _, _ = start()

    # предпросмотр и метка фокуса остаются под обработчиком касания, кнопки съёмки в него не входят —
    # чтобы нажатие на кнопку не попадало и в обработчик касания кадра (фокус по точке)
    assert app.gesture.content.controls == [app.preview, app.marker]
    below_preview = [c for c in app.camera_view.controls if c is not app.camera_preview_area]
    assert not any(app.capture_button in getattr(c, "controls", []) for c in [app.gesture, *app.camera_stage.controls])
    assert any(app.capture_button in list(walk(row)) for row in below_preview)
    assert any(app.gallery_button in list(walk(row)) for row in below_preview)
    assert isinstance(app.capture_button, ft.FloatingActionButton)


def test_the_screen_is_locked_to_portrait_on_android_and_ios():
    for platform in (ft.PagePlatform.ANDROID, ft.PagePlatform.IOS):
        app = build_on(platform)
        assert app.page.orientation_calls == [[ft.DeviceOrientation.PORTRAIT_UP]], platform


def test_the_orientation_is_left_alone_on_desktop_and_web():
    for platform, web in ((ft.PagePlatform.WINDOWS, False), (ft.PagePlatform.WINDOWS, True)):
        app = build_on(platform, web)
        assert app.page.orientation_calls == []


def test_on_a_desktop_a_placeholder_replaces_the_camera_so_the_screen_still_works():
    import flet_camera as fc

    for platform in (ft.PagePlatform.WINDOWS, ft.PagePlatform.MACOS, ft.PagePlatform.LINUX):
        app = build_on(platform)
        assert app.camera.supported is False and not isinstance(app.preview, fc.Camera)
        assert views(app) == ["connect"]

    connect_manually(app)
    assert views(app) == ["camera"] and "только на телефоне" in app.camera_message.value
    assert app.capture_button.disabled and not app.gallery_button.disabled


def test_the_last_error_line_disappears_after_a_successful_connection_and_when_changing_the_pc():
    script = Script()
    script.verify_result = ClientError(client.UNREACHABLE, "TimeoutError: x")
    app, _, _, _, _ = start(script=script)
    connect_manually(app)
    assert app.diag_text.visible and app.last_error

    script.verify_result = Script().verify_result
    connect_manually(app)
    assert views(app) == ["camera"] and not app.diag_text.visible and app.last_error == ""

    app._remember("что-то пошло не так")  # noqa: SLF001
    run(app.on_change_pc(None))
    assert not app.diag_text.visible
