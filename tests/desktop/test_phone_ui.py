import asyncio
import os
from types import SimpleNamespace

import cv2
import flet as ft
import numpy as np
import pytest

from gmagc_common.protocol import Connection, format_code, parse_link
from gmagc_desktop.matcher.synthetic import simulate_photo
from gmagc_desktop.server.api import RequestRecord
from gmagc_desktop.service.results import Outcome, Result, SearchOutcome
from gmagc_desktop.service.search_service import SearchService
from gmagc_desktop.service.settings import Settings, load_settings, save_settings
from gmagc_desktop.ui.app import HISTORY_LIMIT, build_page
from tests.fakes import FakeClipboard, FakePicker, FakeServer, StubPage, texts, walk
from tests.fixtures import shape_images, write_library


def make_app(tmp_path, *, enabled=True, addresses=("192.168.1.5",), server=None, **services):
    data = tmp_path / "data"
    if not enabled:
        save_settings(Settings(server_enabled=False), data / "settings.json")
    links = []
    services.setdefault("qr", lambda link: links.append(link) or b"PNG:" + link.encode())
    services.setdefault("clipboard", FakeClipboard())
    services.setdefault("updates", None)
    page = StubPage()
    app = build_page(
        page, service=SearchService(data), server=server or FakeServer(), addresses=lambda: list(addresses), **services
    )
    return app, page, links


def record(number=1, client="192.168.1.23", outcome=None):
    full_path = os.path.join(os.sep, "lib", "v", f"g{number}.png")
    result = Result(1, f"g{number}.png", f"v/g{number}.png", full_path, 0.9, (), b"\x89PNG")
    default = SearchOutcome(Outcome.FOUND, (result,), b"\x89PNG", 5.0)
    return RequestRecord(f"r{number}", 1_700_000_000.0 + number, client, b"\x89PNG-photo", outcome or default)


def test_the_server_starts_automatically_and_shows_the_address_code_and_qr(tmp_path):
    server = FakeServer(port=8765)

    app, _, links = make_app(tmp_path, server=server)

    code = app.service.settings.access_code
    assert server.starts == [8765] and app.server_switch.value is True
    assert app.server_status.value == "Работает: 192.168.1.5:8765"
    assert app.code_text.value == f"Код: {format_code(code)}" and app.code_text.visible and app.code_row.visible
    assert parse_link(links[-1]) == Connection("192.168.1.5", 8765, code)
    assert app.qr_holder.visible and app.qr_holder.controls[0].src.startswith(b"PNG:")
    assert server.on_request == app.on_phone_request


def test_the_code_survives_a_restart(tmp_path):
    first, _, _ = make_app(tmp_path)
    second, _, _ = make_app(tmp_path)

    assert second.service.settings.access_code == first.service.settings.access_code != ""


def test_a_disabled_server_is_not_started(tmp_path):
    server = FakeServer()

    app, _, _ = make_app(tmp_path, enabled=False, server=server)

    assert server.starts == [] and app.server_switch.value is False
    assert app.server_status.value == "Выключен" and not app.qr_holder.visible and not app.code_text.visible


def test_the_switch_stops_and_restarts_the_server_and_remembers_the_choice(tmp_path):
    server = FakeServer()
    app, _, _ = make_app(tmp_path, server=server)

    app.server_switch.value = False
    app.on_toggle_server(None)

    assert server.stops == 1 and app.server_status.value == "Выключен" and not app.qr_holder.visible
    assert load_settings(tmp_path / "data" / "settings.json").server_enabled is False

    app.server_switch.value = True
    app.on_toggle_server(None)

    assert server.starts == [8765, 8765] and app.server_status.value == "Работает: 192.168.1.5:8765"
    assert load_settings(tmp_path / "data" / "settings.json").server_enabled is True


def test_a_start_failure_is_shown_instead_of_the_qr(tmp_path):
    app, _, _ = make_app(tmp_path, server=FakeServer(error="порт 8765 занят"))

    assert app.server_status.value == "Не удалось запустить: порт 8765 занят"
    assert not app.qr_holder.visible and not app.code_text.visible


def test_without_a_network_address_the_qr_is_hidden_with_a_hint(tmp_path):
    app, _, _ = make_app(tmp_path, addresses=())

    assert "адрес ПК в сети не найден" in app.server_status.value and not app.qr_holder.visible


def test_other_addresses_are_listed_and_the_first_one_goes_into_the_qr(tmp_path):
    app, _, links = make_app(tmp_path, addresses=("192.168.1.5", "10.0.0.7", "172.16.0.2"))

    assert app.addresses_text.visible and "10.0.0.7, 172.16.0.2" in app.addresses_text.value
    assert parse_link(links[-1]).host == "192.168.1.5"


def test_a_new_code_replaces_the_code_everywhere(tmp_path):
    app, _, links = make_app(tmp_path)
    old = app.service.settings.access_code

    app.on_new_code(None)

    new = app.service.settings.access_code
    assert new != old and app.code_text.value == f"Код: {format_code(new)}"
    assert parse_link(links[-1]).code == new
    assert load_settings(tmp_path / "data" / "settings.json").access_code == new


def test_copy_code_puts_the_formatted_code_on_the_clipboard(tmp_path):
    app, _, _ = make_app(tmp_path)

    asyncio.run(app.on_copy_code(None))

    assert app.clipboard.copied == [format_code(app.service.settings.access_code)]
    assert app.phone_note.visible and "скопирован" in app.phone_note.value


def test_a_phone_request_is_shown_in_the_main_window_and_the_history(tmp_path):
    app, _, _ = make_app(tmp_path)

    app.on_phone_request(record(1))

    assert app.source_label.visible and "192.168.1.23" in app.source_label.value
    assert app.photo_holder.visible and app.projection_holder.visible and len(app.results_column.controls) == 1
    assert app.history_title.visible and len(app.history_column.controls) == 1
    row = texts(app.history_column.controls[0])[0]
    assert "192.168.1.23" in row and "g1.png" in row and "90.0%" in row


def test_the_history_keeps_the_latest_requests_newest_first(tmp_path):
    app, _, _ = make_app(tmp_path)

    for number in range(1, HISTORY_LIMIT + 3):
        app.on_phone_request(record(number))

    assert len(app.history_column.controls) == HISTORY_LIMIT
    assert f"g{HISTORY_LIMIT + 2}.png" in texts(app.history_column.controls[0])[0]
    assert "g3.png" in texts(app.history_column.controls[-1])[0]


def test_clicking_a_history_row_shows_that_request_again(tmp_path):
    app, _, _ = make_app(tmp_path)
    app.on_phone_request(record(1))
    app.on_phone_request(record(2))
    assert "g2.png" in " ".join(texts(app.results_column.controls[0]))

    older = app.history_column.controls[1]
    older.on_click(SimpleNamespace(control=older))

    assert "g1.png" in " ".join(texts(app.results_column.controls[0]))


def test_a_phone_request_without_a_projection_shows_the_message(tmp_path):
    app, _, _ = make_app(tmp_path)

    app.on_phone_request(record(1, outcome=SearchOutcome(Outcome.NO_PROJECTION, (), None, 2.0)))

    assert "Проекция на фото не найдена" in app.banner_text.value and app.results_column.controls == []
    assert "проекция не найдена" in texts(app.history_column.controls[0])[0]


def result_container(app):
    return next(c for c in walk(app.results_column.controls[0]) if isinstance(c, ft.Container) and c.data)


def test_clicking_a_result_copies_its_absolute_path_with_the_file_name(tmp_path):
    app, _, _ = make_app(tmp_path)
    rec = record(1)
    app.on_phone_request(rec)
    container = result_container(app)

    asyncio.run(container.on_click(SimpleNamespace(control=container)))

    expected = os.path.abspath(rec.outcome.results[0].full_path)
    assert app.clipboard.copied == [expected] and expected.endswith("g1.png")
    assert app.copy_label.visible and expected in app.copy_label.value


def test_a_relative_path_is_copied_as_an_absolute_one(tmp_path):
    app, _, _ = make_app(tmp_path)

    asyncio.run(app.copy_path(os.path.join("rel", "x.png")))

    assert app.clipboard.copied == [os.path.abspath(os.path.join("rel", "x.png"))]


def test_the_folder_button_reveals_the_file_and_does_not_copy(tmp_path):
    revealed = []
    app, _, _ = make_app(tmp_path, reveal=revealed.append)
    rec = record(1)
    app.on_phone_request(rec)

    button = next(c for c in walk(app.results_column.controls[0]) if isinstance(c, ft.IconButton))
    button.on_click(None)

    assert revealed == [rec.outcome.results[0].full_path] and app.clipboard.copied == []


def test_a_file_search_hides_the_phone_caption_and_the_copy_notice(tmp_path):
    library = tmp_path / "lib"
    library.mkdir()
    write_library(library)
    ok, buffer = cv2.imencode(".png", simulate_photo(shape_images()["ell"], np.random.default_rng(5)))
    photo = tmp_path / "p.png"
    photo.write_bytes(buffer.tobytes())
    app, _, _ = make_app(tmp_path, picker=FakePicker(files=[str(photo)]))
    app.service.set_library(library)
    app.service.build_index()
    app.on_phone_request(record(1))
    asyncio.run(app.copy_path("x.png"))
    assert app.source_label.visible and app.copy_label.visible

    asyncio.run(app.on_pick_photo(None))

    assert not app.source_label.visible and not app.copy_label.visible
    assert len(app.results_column.controls) == 5


@pytest.mark.parametrize("name", ["server_switch", "server_status", "qr_holder", "history_column"])
def test_the_phone_block_is_part_of_the_screen(tmp_path, name):
    app, page, _ = make_app(tmp_path)

    assert getattr(app, name) in list(walk(page.added[0]))
