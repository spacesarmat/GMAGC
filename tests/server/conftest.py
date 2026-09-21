import http.client
import json
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from gmagc_desktop.matcher.synthetic import simulate_photo
from gmagc_desktop.server.runner import PhoneServer
from gmagc_desktop.service.search_service import SearchService
from tests.fixtures import shape_images, write_library


@pytest.fixture()
def service(tmp_path):
    library = tmp_path / "lib"
    library.mkdir()
    write_library(library)
    instance = SearchService(tmp_path / "data")
    instance.load()
    instance.set_library(library)
    instance.build_index()
    instance.ensure_access_code()
    return instance


@pytest.fixture()
def photo_jpeg():
    photo = simulate_photo(shape_images()["ell"], np.random.default_rng(5))
    ok, buffer = cv2.imencode(".jpg", photo)
    assert ok
    return buffer.tobytes()


@pytest.fixture()
def running(service):
    """Сервер на 127.0.0.1 со свободным портом; records собирает вызовы on_request."""
    records = []
    server = PhoneServer(service, on_request=records.append, host="127.0.0.1")
    port = server.start(0)
    yield SimpleNamespace(server=server, port=port, code=service.settings.access_code, records=records)
    server.stop()


@pytest.fixture()
def call(running):
    """call(метод, путь, body=None, code=<верный>) -> (статус, ответ http.client, JSON или None)."""

    def _call(method, path, body=None, code="valid", headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", running.port, timeout=20)
        head = dict(headers or {})
        token = running.code if code == "valid" else code
        if token is not None:
            head["Authorization"] = f"Bearer {token}"
        try:
            connection.request(method, path, body=body, headers=head)
            response = connection.getresponse()
            raw = response.read()
            return response.status, response, (json.loads(raw) if raw else None)
        finally:
            connection.close()

    return _call
