import json
import socketserver
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from gmagc_common.fixtures import Channel, FixtureProfile, Mode, profile_to_dict
from gmagc_common.protocol import MAX_IMAGE_BYTES, Connection, FixtureUploadResult, MatchResponse
from gmagc_desktop.server.runner import PhoneServer
from gmagc_desktop.service.search_service import SearchService
from gmagc_common.phone_client import (
    BAD_IMAGE,
    BAD_PROFILE,
    NO_INDEX,
    NO_TARGET,
    PROTOCOL,
    RATE_LIMITED,
    SERVER,
    TOO_LARGE,
    UNAUTHORIZED,
    UNREACHABLE,
    ClientError,
    GmagcClient,
)


def make_client(running, code=None, **options):
    return GmagcClient(Connection("127.0.0.1", running.port, code or running.code), **options)


@contextmanager
def stub_server(status=200, body=b"{}", content_type="application/json", delay=0.0):
    """Поддельный сервер: на любой запрос отвечает заданным телом."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            time.sleep(delay)
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_POST = do_GET

        def log_message(self, *args):
            pass

    class _Server(ThreadingHTTPServer):
        def server_bind(self) -> None:
            # HTTPServer.server_bind вызывает getfqdn(): на macOS-раннерах CI это резолв .local-имени
            # через mDNS, который там может виснуть на десятки секунд (та же причина, что и в
            # gmagc_desktop.server.runner._Server). Имя сервера тестам не нужно.
            socketserver.TCPServer.server_bind(self)
            host, port = self.server_address[:2]
            self.server_name, self.server_port = str(host), port

    server = _Server(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield Connection("127.0.0.1", server.server_address[1], "ABCD2345")
    finally:
        server.shutdown()
        server.server_close()


def test_verify_returns_the_health_and_the_status(running):
    health, status = make_client(running).verify()

    assert health.app == "GMAGC" and health.indexed and health.files == 6
    assert status.indexed and status.families == 5 and status.indexing is False


def test_a_wrong_code_is_unauthorized(running):
    with pytest.raises(ClientError) as error:
        make_client(running, "ABCD2346").verify()

    assert error.value.kind == UNAUTHORIZED


def test_five_wrong_codes_lead_to_the_rate_limit_with_a_wait_time(running):
    client = make_client(running, "ABCD2346")
    for _ in range(5):
        with pytest.raises(ClientError) as error:
            client.status()
        assert error.value.kind == UNAUTHORIZED

    with pytest.raises(ClientError) as error:
        client.status()

    assert error.value.kind == RATE_LIMITED and 1 <= error.value.retry_after <= 30


def test_the_default_match_timeout_is_short_enough_to_not_freeze_the_ui():
    """60с (прежнее значение) держало кнопку «Назад» замороженной почти минуту при обрыве связи
    с полуоткрытым TCP-соединением (сервер выключен, но RST ещё не пришёл) — реальный отзыв пользователя."""
    client = GmagcClient(Connection("127.0.0.1", 1, "AAAA-AAAA"))

    assert client._match_timeout <= 20.0  # noqa: SLF001 - проверяем именно значение по умолчанию


def test_match_returns_the_parsed_response(running, photo_jpeg):
    response = make_client(running).match(photo_jpeg)

    assert isinstance(response, MatchResponse) and response.outcome in {"found", "low_confidence"}
    assert len(response.results) == 5 and response.results[0].path.endswith(".png")
    assert response.results[0].thumbnail_png.startswith(b"\x89PNG")


def test_match_honors_top(running, photo_jpeg):
    assert len(make_client(running).match(photo_jpeg, top=2).results) == 2


def test_a_closed_port_is_unreachable(running):
    running.server.stop()

    with pytest.raises(ClientError) as error:
        make_client(running).verify()

    assert error.value.kind == UNREACHABLE


def test_a_slow_server_times_out_as_unreachable():
    with stub_server(delay=1.5) as connection, pytest.raises(ClientError) as error:
        GmagcClient(connection, timeout=0.3).health()

    assert error.value.kind == UNREACHABLE


def test_junk_and_empty_images_are_bad_image(running):
    with pytest.raises(ClientError) as error:
        make_client(running).match(b"not an image")
    assert error.value.kind == BAD_IMAGE

    with pytest.raises(ClientError) as error:
        make_client(running).match(b"")
    assert error.value.kind == BAD_IMAGE


def test_an_oversized_image_is_too_large(running):
    with pytest.raises(ClientError) as error:
        make_client(running).match(b"\0" * (MAX_IMAGE_BYTES + 1))

    assert error.value.kind == TOO_LARGE


def test_a_pc_without_an_index_is_no_index(tmp_path, photo_jpeg):
    empty = SearchService(tmp_path / "empty")
    empty.load()
    code = empty.ensure_access_code()
    server = PhoneServer(empty, host="127.0.0.1")
    port = server.start(0)
    try:
        with pytest.raises(ClientError) as error:
            GmagcClient(Connection("127.0.0.1", port, code)).match(photo_jpeg)
        assert error.value.kind == NO_INDEX
        health, status = GmagcClient(Connection("127.0.0.1", port, code)).verify()
        assert health.indexed is False and status.indexed is False
    finally:
        server.stop()


def test_a_foreign_json_server_is_a_protocol_error():
    with stub_server(body=b'{"hello": "world"}') as connection, pytest.raises(ClientError) as error:
        GmagcClient(connection).health()

    assert error.value.kind == PROTOCOL and "не сервер GMAGC" in error.value.message


def test_a_non_json_server_is_a_protocol_error():
    with stub_server(body=b"<html>router</html>", content_type="text/html") as connection:
        with pytest.raises(ClientError) as error:
            GmagcClient(connection).health()

    assert error.value.kind == PROTOCOL


def test_an_incompatible_api_version_is_reported():
    body = json.dumps({"app": "GMAGC", "api": 99, "version": "9.0.0", "indexed": True, "files": 1}).encode()
    with stub_server(body=body) as connection, pytest.raises(ClientError) as error:
        GmagcClient(connection).health()

    assert error.value.kind == PROTOCOL and "API 99" in error.value.message


def test_an_unknown_error_reply_is_a_server_error():
    with stub_server(status=503, body=b'{"oops": 1}') as connection, pytest.raises(ClientError) as error:
        GmagcClient(connection).health()

    assert error.value.kind == SERVER and "503" in error.value.message


def test_a_known_error_code_keeps_the_server_message():
    body = json.dumps({"error": "server_error", "message": "ошибка поиска на ПК"}).encode()
    with stub_server(status=500, body=body) as connection, pytest.raises(ClientError) as error:
        GmagcClient(connection).match(b"x")

    assert error.value.kind == SERVER and error.value.message == "ошибка поиска на ПК"


def fixture_profile():
    modes = (Mode("Standard", (Channel(1, 8, "Диммер", "dimmer"),)),)
    return FixtureProfile("a" * 32, "SHEHDS", "380W Beam", "", modes)


def test_send_fixture_stores_the_profile_on_the_pc_and_returns_the_written_files(running, service, tmp_path):
    service.set_fixture_dirs(str(tmp_path / "ma3"), str(tmp_path / "ma2"))

    result = make_client(running).send_fixture(profile_to_dict(fixture_profile()))

    assert isinstance(result, FixtureUploadResult)
    assert sorted(target for target, _ in result.written) == ["ma2", "ma3", "ma3"] and result.skipped == ()
    assert (tmp_path / "ma3" / "shehds@380w_beam.xml").exists()


def test_send_fixture_reports_a_profile_that_is_not_ready(running, service, tmp_path):
    service.set_fixture_dirs(str(tmp_path / "ma3"), str(tmp_path / "ma2"))
    broken = profile_to_dict(FixtureProfile("a" * 32, "", "", "", (Mode("m"),)))

    with pytest.raises(ClientError) as error:
        make_client(running).send_fixture(broken)

    assert error.value.kind == BAD_PROFILE and "производител" in error.value.message


def test_send_fixture_with_a_wrong_code_is_unauthorized(running):
    with pytest.raises(ClientError) as error:
        make_client(running, code="ABCD2346").send_fixture(profile_to_dict(fixture_profile()))

    assert error.value.kind == UNAUTHORIZED


def test_send_fixture_reports_when_the_pc_has_nowhere_to_write():
    body = json.dumps({"error": "no_target", "message": "некуда записать"}, ensure_ascii=False).encode("utf-8")
    with stub_server(status=409, body=body) as connection:
        client = GmagcClient(connection)
        with pytest.raises(ClientError) as error:
            client.send_fixture(profile_to_dict(fixture_profile()))

    assert error.value.kind == NO_TARGET and "некуда" in error.value.message


def test_send_fixture_reports_an_unreachable_pc():
    client = GmagcClient(Connection("127.0.0.1", 1, "ABCD2345"), timeout=0.5)

    with pytest.raises(ClientError) as error:
        client.send_fixture(profile_to_dict(fixture_profile()))

    assert error.value.kind == UNREACHABLE


def test_scan_fixture_returns_the_draft_recognised_on_the_pc(running):
    import json as _json
    from pathlib import Path

    from gmagc_desktop.scan.engine import LocalScanner
    from gmagc_desktop.scan.table import items_from_dict

    path = Path(__file__).resolve().parents[1] / "data" / "ocr" / "led_bar_photo_4ch.json"
    items = items_from_dict(_json.loads(path.read_text(encoding="utf-8")))
    running.server._context.scanner = LocalScanner(ocr=lambda _image: items)

    draft = make_client(running).scan_fixture(b"\xff\xd8photo")

    assert [m.name for m in draft.modes] == ["4CH"] and len(draft.modes[0].channels) == 4


def test_scan_fixture_reports_missing_recognition_on_the_pc():
    body = json.dumps({"error": "scan_unavailable", "message": "нет модуля"}, ensure_ascii=False).encode("utf-8")
    with stub_server(status=409, body=body) as connection:
        with pytest.raises(ClientError) as error:
            GmagcClient(connection).scan_fixture(b"photo")

    assert error.value.kind == "scan_unavailable"


def test_scan_fixture_rejects_a_reply_that_is_not_a_draft():
    with stub_server(body=b'{"modes": 5}') as connection:
        with pytest.raises(ClientError) as error:
            GmagcClient(connection).scan_fixture(b"photo")

    assert error.value.kind == "protocol"


def test_scan_fixture_passes_the_chosen_engine_to_the_pc(running):
    seen = []

    class Recorder:
        def scan(self, data):
            seen.append("cloud")
            from gmagc_common.scan_draft import ScanDraft

            return ScanDraft((), ("no_table",), "cloud")

    running.server._context.cloud = Recorder()

    draft = make_client(running).scan_fixture(b"photo", engine="cloud")

    assert seen == ["cloud"] and draft.engine == "cloud"


def test_find_gobos_and_gobo_read_the_pc_library(running, service):
    from gmagc_common.protocol import GoboItem, GoboList

    rel = sorted(f.rel_path for f in service._index.files)[0]
    stem = rel.rsplit("/", 1)[-1].rsplit(".", 1)[0]

    found = make_client(running).find_gobos(stem, limit=3)
    one = make_client(running).gobo(rel)

    assert isinstance(found, GoboList) and found.total >= 1 and isinstance(one, GoboItem) and one.source == rel


def test_gobo_lookup_of_an_unknown_file_is_a_client_error(running):
    with pytest.raises(ClientError) as error:
        make_client(running).gobo("nope.png")

    assert error.value.kind == SERVER
