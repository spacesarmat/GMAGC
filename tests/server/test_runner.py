import socket

import pytest

from gmagc_desktop.server import runner
from gmagc_desktop.server.runner import PORT_TRIES, PhoneServer, ServerStartError


def test_start_serves_and_stop_frees_the_port(service):
    server = PhoneServer(service, host="127.0.0.1")
    assert not server.running and server.port == 0

    port = server.start(0)

    assert server.running and server.port == port > 0
    assert server.start(0) == port  # повторный запуск ничего не меняет
    with socket.create_connection(("127.0.0.1", port), timeout=5):
        pass
    server.stop()
    assert not server.running and server.port == 0
    with pytest.raises(OSError), socket.create_connection(("127.0.0.1", port), timeout=2):
        pass
    server.stop()  # повторная остановка безопасна


def test_a_busy_port_moves_to_the_next_one(service):
    first = PhoneServer(service, host="127.0.0.1")
    second = PhoneServer(service, host="127.0.0.1")
    port = first.start(0)
    try:
        actual = second.start(port)

        assert port < actual < port + PORT_TRIES and second.running
    finally:
        second.stop()
        first.stop()


def test_no_free_port_raises_a_clear_error(service, monkeypatch):
    monkeypatch.setattr(runner, "PORT_TRIES", 1)
    first = PhoneServer(service, host="127.0.0.1")
    second = PhoneServer(service, host="127.0.0.1")
    port = first.start(0)
    try:
        with pytest.raises(ServerStartError) as error:
            second.start(port)

        assert str(port) in str(error.value) and not second.running
    finally:
        first.stop()


def test_on_request_can_be_replaced_after_creation(service):
    server = PhoneServer(service, host="127.0.0.1")
    assert server.on_request is None
    marker = lambda _record: None  # noqa: E731
    server.on_request = marker
    assert server.on_request is marker
