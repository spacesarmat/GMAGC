import time
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
    """Сервис с построенным индексом синтетической библиотеки и кодом доступа."""
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

    def wait_for_records(count, timeout=5.0):
        """Сервер сначала отвечает телефону, потом сообщает о запросе: тесту нужно дождаться записи, а не читать сразу."""
        deadline = time.monotonic() + timeout
        while len(records) < count and time.monotonic() < deadline:
            time.sleep(0.01)
        return records

    yield SimpleNamespace(
        server=server, port=port, code=service.settings.access_code, records=records, wait_for_records=wait_for_records
    )
    server.stop()
