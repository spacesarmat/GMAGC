import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QImage

from gmagc_common import i18n
from gmagc_common.protocol import Connection, Health, MatchResponse, ResultItem, Status, build_link
from gmagc_common.qr_decode import decode_qr
from gmagc_phone.app import build_window
from gmagc_phone.camera import FakeCamera
from gmagc_phone.controller import MODE_SCAN
from gmagc_phone.settings import PhoneSettings
from gmagc_phone.tasks import InlineExecutor

CONN = Connection("192.168.1.5", 8765, "ABCD2345")


class FakeClient:
    def __init__(self, connection):
        self.connection = connection
        self.matched = []

    def verify(self):
        return Health("GMAGC", 1, "1.4.0", True, 10), Status(True, 10, 3, False, 0, 0)

    def match(self, data, top=None):
        self.matched.append(data)
        item = ResultItem(1, "a.png", "C:/g/a.png", 0.93, ("C:/g/b.png",), b"")
        return MatchResponse("r1", "found", 10.0, (item,), None)


@pytest.fixture(autouse=True)
def russian():
    i18n.set_language("ru")


@pytest.fixture
def settings(tmp_path):
    return PhoneSettings(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))


@pytest.fixture
def setup(qtbot, settings):
    backend = FakeCamera()
    picked = []
    window = build_window(
        settings,
        backend=backend,
        executor=InlineExecutor(),
        client_factory=FakeClient,
        pick_file=lambda: picked[0] if picked else "",
    )
    qtbot.addWidget(window)
    window.resize(400, 800)
    window.show()
    return window, backend, picked


def test_starts_on_connect_screen(setup):
    window, _, _ = setup
    window.controller.start()
    assert window.stack.currentWidget() is window.screens["connect"]


def test_manual_connect_opens_camera_and_starts_backend(setup):
    window, backend, _ = setup
    connect = window.screens["connect"]
    connect.address.setText("192.168.1.5:8765")
    connect.code.setText("ABCD2345")
    connect.connect_button.click()
    assert window.stack.currentWidget() is window.screens["camera"]
    assert backend.started == 1


def test_connect_error_is_visible(setup):
    window, _, _ = setup
    connect = window.screens["connect"]
    connect.connect_button.click()
    assert not connect.error.isHidden()
    assert connect.error.text()


def test_shutter_sends_photo_and_shows_results(setup):
    window, backend, _ = setup
    window.controller.connect_to(CONN)
    window.screens["camera"].shutter.click()
    assert backend.captures == 1
    assert window.stack.currentWidget() is window.screens["results"]
    results = window.screens["results"]
    assert results.cards_col.count() == 1
    assert backend.stopped == 1  # камера выключается вне экрана камеры


def test_result_card_copies_path(setup, qtbot):
    window, _, _ = setup
    window.controller.connect_to(CONN)
    window.screens["camera"].shutter.click()
    card = window.screens["results"].cards_col.itemAt(0).widget()
    copied = []
    window.controller.copied.connect(copied.append)
    qtbot.mouseClick(card, __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.MouseButton.LeftButton)
    assert copied == ["C:/g/a.png"]


def test_pick_file_sends_photo(setup, tmp_path):
    window, _, picked = setup
    window.controller.connect_to(CONN)
    photo = tmp_path / "p.jpg"
    photo.write_bytes(b"fakejpeg")
    picked.append(str(photo))
    window.screens["camera"].pick.click()
    assert window.stack.currentWidget() is window.screens["results"]


def test_gallery_lists_history_and_reopens(setup):
    window, _, _ = setup
    window.controller.connect_to(CONN)
    window.screens["camera"].shutter.click()
    window.controller.show_camera()
    window.controller.open_overlay("gallery")
    gallery = window.screens["gallery"]
    assert gallery.list_col.count() == 1
    assert gallery.empty.isHidden()
    window.controller.open_history(0)
    assert window.stack.currentWidget() is window.screens["results"]


def test_back_from_overlay_and_results(setup):
    window, _, _ = setup
    window.controller.connect_to(CONN)
    window.controller.open_overlay("settings")
    window.go_back()
    assert window.controller.view == "camera"
    window.screens["camera"].shutter.click()
    window.go_back()
    assert window.controller.view == "camera"


def test_double_back_on_camera_quits(setup):
    window, _, _ = setup
    quits = []
    window.quit_app = lambda: quits.append(1)
    window.controller.connect_to(CONN)
    window.go_back()
    assert quits == []
    window.go_back()
    assert quits == [1]


def test_qr_scan_connects(setup):
    window, backend, _ = setup
    import segno

    window.controller.show_camera(MODE_SCAN)
    qr = segno.make(build_link(CONN.host, CONN.port, CONN.code), error="m")
    size = qr.symbol_size(scale=8, border=4)[0]
    image = QImage(size, size, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    for y, row in enumerate(qr.matrix):
        for x, dark in enumerate(row):
            if dark:
                for dy in range(8):
                    for dx in range(8):
                        image.setPixelColor((x + 4) * 8 + dx, (y + 4) * 8 + dy, QColor("black"))
    backend.frame.emit(image)
    window.camera_screen._scan_tick()
    assert window.controller.connection == CONN
    assert window.controller.mode != MODE_SCAN
    assert decode_qr is not None


def test_foreign_qr_shows_note(setup):
    window, backend, _ = setup
    window.controller.show_camera(MODE_SCAN)
    window.camera_screen._qr_read("https://example.com")
    assert not window.camera_screen.note.isHidden()
    assert window.controller.connection is None


def test_zoom_cycles_within_range(setup):
    window, backend, _ = setup
    camera = window.camera_screen
    camera.zoom_button.click()
    assert backend.zoom == 2.0
    camera.zoom_button.click()
    assert backend.zoom == 4.0
    camera.zoom_button.click()
    assert backend.zoom == 1.0


def test_tap_focus_reports_to_backend(setup):
    window, backend, _ = setup
    window.camera_screen._focus(0.5, 0.25)
    assert backend.focus_points == [(0.5, 0.25)]


def test_camera_error_shows_note(qtbot, settings):
    backend = FakeCamera(fail="Камера не найдена")
    window = build_window(settings, backend=backend, executor=InlineExecutor(), client_factory=FakeClient)
    qtbot.addWidget(window)
    window.show()
    window.controller.connect_to(CONN)
    assert "не найдена" in window.camera_screen.note.text()


def test_language_switch_updates_settings(setup, settings):
    window, _, _ = setup
    seen = []
    window.controller.language_changed.connect(seen.append)
    window.screens["settings"].language.setCurrentIndex(2)
    window.screens["settings"]._language_picked(2)
    assert seen == ["en"]
    assert settings.load_language() == "en"


def test_about_links_open_urls(qtbot, settings):
    from gmagc_phone.controller import PhoneController
    from gmagc_phone.screens.info import AboutScreen

    opened = []
    screen = AboutScreen(PhoneController(settings, executor=InlineExecutor()), open_link=opened.append)
    qtbot.addWidget(screen)
    for link, _url in screen.links:
        link.click()
    assert len(opened) == 3
    assert all(url.startswith("https://") for url in opened)


def test_camera_stops_in_background_and_resumes(setup):
    from PySide6.QtCore import Qt

    window, backend, _ = setup
    window.controller.connect_to(CONN)
    started = backend.started
    window._app_state_changed(Qt.ApplicationState.ApplicationSuspended)
    assert backend.stopped == 1
    window._app_state_changed(Qt.ApplicationState.ApplicationActive)
    assert backend.started == started + 1


def test_language_change_rebuilds_inside_one_window(qtbot, settings):
    from gmagc_phone.app import Shell

    def make():
        return build_window(settings, backend=FakeCamera(), executor=InlineExecutor(), client_factory=FakeClient)

    before = _visible_windows()
    shell = Shell(settings, make_window=make, extras=False)
    qtbot.addWidget(shell)
    shell.show()
    shell.open_content()
    first = shell.content
    first.screens["settings"]._language_picked(2)
    qtbot.waitUntil(lambda: shell.content is not first)
    assert settings.load_language() == "en"
    assert shell.content.screens["connect"].scan.text() == "Scan the QR code from the PC"
    qtbot.wait(50)
    assert _visible_windows() - before == {shell}  # никаких лишних окон
    i18n.set_language("ru")


def test_pages_do_not_flash_stray_windows(qtbot, settings):
    before = _visible_windows()
    window = build_window(settings, backend=FakeCamera(), executor=InlineExecutor(), client_factory=FakeClient)
    qtbot.addWidget(window)
    window.show()
    window.controller.connect_to(CONN)
    window.controller.open_overlay("gallery")
    window.controller.open_overlay("settings")
    window.controller.open_overlay("profiles")
    assert _visible_windows() - before == {window}


def _visible_windows():
    from PySide6.QtWidgets import QApplication

    return {w for w in QApplication.topLevelWidgets() if w.isVisible()}
