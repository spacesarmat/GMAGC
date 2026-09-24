import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QImage

from gmagc_common.phone_client import UNAUTHORIZED, UNREACHABLE, ClientError
from gmagc_common.protocol import Connection, Health, MatchResponse, ResultItem, Status
from gmagc_phone.controller import HISTORY_LIMIT, MODE_SCAN, MODE_SHOOT, PhoneController
from gmagc_phone.imaging import grayscale_frame, prepare_upload
from gmagc_phone.settings import PhoneSettings
from gmagc_phone.tasks import InlineExecutor

CONN = Connection("192.168.1.5", 8765, "ABCD2345")


def response(name="a.png"):
    item = ResultItem(1, name, "C:/g/" + name, 0.9, (), b"")
    return MatchResponse("r1", "found", 12.0, (item,), None)


class FakeClient:
    def __init__(self, connection, status=None, error=None, match=None):
        self.connection = connection
        self.status_value = status or Status(True, 10, 3, False, 0, 0)
        self.error = error
        self.match_value = match or response()
        self.matched = []

    def verify(self):
        if self.error:
            raise self.error
        return Health("GMAGC", 1, "1.4.0", True, 10), self.status_value

    def match(self, data, top=None):
        self.matched.append(data)
        if self.error:
            raise self.error
        return self.match_value


@pytest.fixture
def settings(tmp_path):
    return PhoneSettings(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))


def make(settings, **client_kwargs):
    clients = []

    def factory(connection):
        client = FakeClient(connection, **client_kwargs)
        clients.append(client)
        return client

    controller = PhoneController(settings, factory, InlineExecutor())
    return controller, clients


def test_start_without_saved_connection_shows_connect(settings):
    controller, _ = make(settings)
    seen = []
    controller.screen_requested.connect(seen.append)
    controller.start()
    assert seen == ["connect"]


def test_start_with_saved_connection_opens_camera(settings):
    settings.save_connection(CONN)
    controller, _ = make(settings)
    seen = []
    controller.screen_requested.connect(seen.append)
    controller.start()
    assert seen == ["camera"]
    assert controller.connection == CONN


def test_manual_connect_validates_address_and_code(settings):
    controller, clients = make(settings)
    errors = []
    controller.connect_error.connect(errors.append)
    controller.connect("не адрес", "ABCD2345")
    controller.connect("192.168.1.5", "123")
    assert clients == []
    assert len(errors) == 2 and all(errors)


def test_connect_saves_and_shows_camera(settings):
    controller, _ = make(settings)
    controller.connect("192.168.1.5:8765", "abcd-2345")
    assert settings.load_connection() == CONN
    assert controller.view == "camera"


def test_connect_failure_shows_error_on_connect_screen(settings):
    controller, _ = make(settings, error=ClientError(UNAUTHORIZED, "нет"))
    errors = []
    controller.connect_error.connect(errors.append)
    controller.connect("192.168.1.5:8765", "ABCD2345")
    assert controller.view == "connect"
    assert errors[-1]
    assert settings.load_connection() is None


def test_no_index_note_on_camera(settings):
    controller, _ = make(settings, status=Status(False, 0, 0, False, 0, 0))
    notes = []
    controller.camera_note.connect(notes.append)
    controller.connect("192.168.1.5:8765", "ABCD2345")
    assert notes[-1]


def test_search_shows_results_and_history(settings):
    controller, clients = make(settings)
    controller.connect("192.168.1.5:8765", "ABCD2345")
    shown = []
    controller.results_shown.connect(lambda photo, resp: shown.append((photo, resp)))
    controller.search(b"photo")
    assert controller.view == "results"
    assert shown[0][0] == b"photo"
    assert len(controller.history) == 1
    assert clients[0].matched == [b"photo"]


def test_history_is_limited(settings):
    controller, _ = make(settings)
    controller.connect("192.168.1.5:8765", "ABCD2345")
    for i in range(HISTORY_LIMIT + 3):
        controller.search(str(i).encode())
        controller.show_camera()
    assert len(controller.history) == HISTORY_LIMIT
    assert controller.history[0][0] == str(HISTORY_LIMIT + 2).encode()


def test_search_in_scan_mode_does_not_switch_screen(settings):
    controller, _ = make(settings)
    controller.connect("192.168.1.5:8765", "ABCD2345")
    controller.set_mode(MODE_SCAN)
    controller.search(b"x")
    assert controller.view == "camera"
    assert len(controller.history) == 1


def test_network_failure_offers_retry_and_retry_resends(settings):
    controller, clients = make(settings)
    controller.connect("192.168.1.5:8765", "ABCD2345")
    clients[0].error = ClientError(UNREACHABLE, "нет связи")
    retry_flags, online = [], []
    controller.retry_changed.connect(retry_flags.append)
    controller.connectivity_changed.connect(online.append)
    controller.search(b"photo")
    assert retry_flags[-1] is True and online[-1] is False
    assert controller.view == "camera"
    clients[0].error = None
    controller.retry()
    assert controller.view == "results"
    assert clients[0].matched == [b"photo", b"photo"]


def test_unauthorized_on_search_returns_to_connect(settings):
    controller, clients = make(settings)
    controller.connect("192.168.1.5:8765", "ABCD2345")
    clients[0].error = ClientError(UNAUTHORIZED, "код")
    controller.search(b"photo")
    assert controller.view == "connect"


def test_search_without_connection_asks_to_connect(settings):
    controller, _ = make(settings)
    controller.search(b"x")
    assert controller.view == "connect"


def test_overlays_return_to_origin(settings):
    controller, _ = make(settings)
    controller.connect("192.168.1.5:8765", "ABCD2345")
    controller.open_overlay("settings")
    assert controller.view == "settings"
    controller.close_overlay()
    assert controller.view == "camera"
    controller.change_pc()
    controller.open_overlay("help")
    controller.close_overlay()
    assert controller.view == "connect"
    assert settings.load_connection() is None


def test_open_history_shows_saved_result(settings):
    controller, clients = make(settings)
    controller.connect("192.168.1.5:8765", "ABCD2345")
    controller.search(b"a")
    controller.show_camera()
    controller.open_history(0)
    assert controller.view == "results"
    assert clients[0].matched == [b"a"]
    assert controller.result_share_text()


def test_copy_path(settings):
    copied = []
    controller = PhoneController(settings, executor=InlineExecutor(), copy_text=copied.append)
    controller.copy_path("C:/g/a.png")
    assert copied == ["C:/g/a.png"]


def test_settings_survive_corrupt_values(tmp_path):
    store = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    store.setValue("connection/host", "192.168.1.5")
    store.setValue("connection/port", "abc")
    store.setValue("connection/code", "ABCD2345")
    store.setValue("profiles", "{не json")
    assert PhoneSettings(store).load_connection() is None
    assert PhoneSettings(store).load_profiles() == []


def test_settings_language_roundtrip(settings):
    settings.save_language("en")
    assert settings.load_language() == "en"


def test_prepare_upload_small_file_untouched():
    assert prepare_upload(b"abc", limit=10) == b"abc"


def test_prepare_upload_shrinks_big_image():
    from PySide6.QtCore import QBuffer, QIODevice

    image = QImage(1200, 900, QImage.Format.Format_RGB32)
    for y in range(0, 900, 3):
        for x in range(0, 1200, 7):
            image.setPixelColor(x, y, QColor((x * 3) % 256, (y * 5) % 256, (x + y) % 256))
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    raw = bytes(buffer.data())
    out = prepare_upload(raw, limit=len(raw) - 1)
    assert len(out) < len(raw)
    assert out[:2] == b"\xff\xd8"


def test_prepare_upload_rejects_garbage():
    with pytest.raises(ValueError):
        prepare_upload(b"x" * 100, limit=10)


def test_grayscale_frame_size_and_bytes():
    image = QImage(800, 600, QImage.Format.Format_RGB32)
    image.fill(QColor(255, 255, 255))
    data, width, height = grayscale_frame(image)
    assert (width, height) == (640, 480)
    assert len(data) == width * height
    assert set(data) == {255}


def test_mode_constants_differ():
    assert MODE_SHOOT != MODE_SCAN
