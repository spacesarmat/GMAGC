"""Экран «Телефон» на Qt: сервер, QR и код, история запросов с телефона."""

import threading

import pytest

from gmagc_common.protocol import format_code
from gmagc_desktop.qt.app import build_window
from gmagc_desktop.qt.controller import HISTORY_LIMIT, AppController, InlineExecutor
from gmagc_desktop.qt.screens.phone import PhoneScreen
from gmagc_desktop.server.api import RequestRecord
from tests.fakes import FakeServer


def make(service, server=None, addresses=("192.168.0.5",)):
    copied = []
    controller = AppController(
        service,
        InlineExecutor(),
        copy_text=copied.append,
        server=server or FakeServer(),
        addresses=lambda: list(addresses),
        qr=lambda link: b"\x89PNG-fake:" + link.encode(),
    )
    screen = PhoneScreen(controller)
    screen.show()
    return screen, controller, copied


def record(service, photo, client="10.0.0.5", when=1_700_000_000.0):
    return RequestRecord("r1", when, client, photo, service.search_image_bytes(photo, top_n=3))


def test_the_screen_starts_switched_off_without_qr_and_code(qapp, service):
    service.set_server_enabled(False)
    screen, controller, _ = make(service)

    assert not screen.server_switch.isChecked() and screen.status_label.text() == "Выключен"
    assert not screen.qr_label.isVisible() and not screen.code_label.isVisible() and not screen.code_row.isVisible()
    assert not screen.history_card.isVisible()


def test_an_enabled_server_shows_the_address_code_qr_and_other_addresses(qapp, service):
    server = FakeServer(port=8765)
    screen, controller, _ = make(service, server, addresses=("192.168.0.5", "10.0.0.2", "172.16.0.9"))

    controller.start_server_if_enabled()

    assert server.starts == [service.settings.port] and server.running
    assert screen.status_label.text() == "Работает: 192.168.0.5:8765"
    code = service.settings.access_code
    assert screen.code_label.isVisible() and screen.code_label.text() == f"Код: {format_code(code)}"
    assert screen.code_row.isVisible() and screen.qr_label.isVisible() and screen.qr_label.width() == 220
    assert screen.addresses_label.isVisible() and screen.addresses_label.text().endswith("10.0.0.2, 172.16.0.9")


def test_a_disabled_setting_does_not_start_the_server_at_launch(qapp, service):
    service.set_server_enabled(False)
    server = FakeServer()
    screen, controller, _ = make(service, server)

    controller.start_server_if_enabled()

    assert server.starts == [] and screen.status_label.text() == "Выключен"


def test_the_switch_starts_and_stops_the_server_and_remembers_the_choice(qapp, service):
    service.set_server_enabled(False)
    server = FakeServer()
    screen, controller, _ = make(service, server)

    screen.server_switch.setChecked(True)
    assert server.running and service.settings.server_enabled and screen.qr_label.isVisible()

    screen.server_switch.setChecked(False)
    assert not server.running and server.stops == 1 and not service.settings.server_enabled
    assert screen.status_label.text() == "Выключен" and not screen.qr_label.isVisible()


def test_a_start_error_is_shown_in_the_status(qapp, service):
    service.set_server_enabled(False)
    screen, controller, _ = make(service, FakeServer(error="порт занят"))

    screen.server_switch.setChecked(True)

    assert screen.status_label.text() == "Не удалось запустить: порт занят" and not screen.qr_label.isVisible()


def test_a_server_without_a_network_address_asks_to_connect_to_wifi(qapp, service):
    screen, controller, _ = make(service, FakeServer(port=8765), addresses=())

    controller.start_server_if_enabled()

    assert "адрес ПК в сети не найден" in screen.status_label.text() and "8765" in screen.status_label.text()
    assert not screen.qr_label.isVisible() and not screen.code_label.isVisible()


def test_copying_the_code_puts_it_in_the_clipboard_and_says_so(qapp, service):
    screen, controller, copied = make(service)
    controller.start_server_if_enabled()

    screen.copy_button.click()

    assert copied == [format_code(service.settings.access_code)]
    assert screen.note_label.isVisible() and screen.note_label.text() == "Код скопирован"


def test_a_new_code_replaces_the_old_one_on_the_screen(qapp, service):
    screen, controller, _ = make(service)
    controller.start_server_if_enabled()
    old = screen.code_label.text()

    screen.new_button.click()

    new = f"Код: {format_code(service.settings.access_code)}"
    assert screen.code_label.text() != old and screen.code_label.text() == new


def test_a_phone_request_is_recorded_shown_on_the_search_screen_and_switches_to_it(qapp, service, photo_jpeg):
    window = build_window(service, InlineExecutor(), server=FakeServer(), addresses=lambda: ["192.168.0.5"])
    window.show_screen("phone")
    controller = window.controller
    entry = record(service, photo_jpeg)

    controller.phone_request.emit(entry)

    assert window.current == "search" and controller.history == [entry]
    search = window.screens["search"]
    assert "10.0.0.5" in search.source_label.text() and len(search.cards) == 3
    phone = window.screens["phone"]
    assert not phone.history_card.isHidden() and len(phone.history_buttons) == 1
    assert "10.0.0.5" in phone.history_buttons[0].text()


def test_clicking_a_history_row_shows_that_request_again(qapp, service, photo_jpeg):
    window = build_window(service, InlineExecutor(), server=FakeServer(), addresses=lambda: ["192.168.0.5"])
    controller = window.controller
    controller.phone_request.emit(record(service, photo_jpeg, client="10.0.0.5"))
    controller.phone_request.emit(record(service, photo_jpeg, client="10.0.0.6"))
    window.show_screen("phone")
    search = window.screens["search"]
    assert "10.0.0.6" in search.source_label.text()

    window.screens["phone"].history_buttons[1].click()  # ниже — более старый запрос

    assert window.current == "search" and "10.0.0.5" in search.source_label.text()


def test_the_history_keeps_only_the_latest_requests_newest_first(qapp, service, photo_jpeg):
    screen, controller, _ = make(service)

    for number in range(HISTORY_LIMIT + 3):
        controller.phone_request.emit(record(service, photo_jpeg, client=f"10.0.0.{number}"))

    assert len(controller.history) == HISTORY_LIMIT == len(screen.history_buttons)
    assert controller.history[0].client == f"10.0.0.{HISTORY_LIMIT + 2}"


def test_a_request_from_the_server_thread_reaches_the_main_thread(qapp, qtbot, service, photo_jpeg):
    server = FakeServer()
    screen, controller, _ = make(service, server)
    controller.start_server_if_enabled()
    entry = record(service, photo_jpeg)

    threading.Thread(target=lambda: server.on_request(entry)).start()  # так вызывает сервер телефона

    qtbot.waitUntil(lambda: controller.history == [entry], timeout=3000)
    assert threading.current_thread() is threading.main_thread()


def test_stopping_the_server_when_the_app_closes_is_safe_without_a_server(qapp, service):
    controller = AppController(service, InlineExecutor())

    controller.stop_server()  # сервер не создавался: ничего не падает

    fake = FakeServer()
    other = AppController(service, InlineExecutor(), server=fake)
    other.start_server_if_enabled()
    other.stop_server()
    assert fake.stops == 1


@pytest.mark.parametrize("screen_name", ["phone", "search", "library"])
def test_the_window_builds_with_a_fake_server_and_navigates(qapp, service, screen_name):
    window = build_window(service, InlineExecutor(), server=FakeServer())

    window.show_screen(screen_name)

    assert window.current == screen_name
