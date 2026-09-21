import threading

import cv2
import numpy as np
import pytest

from gmagc_common.protocol import is_valid_code
from gmagc_desktop.matcher.synthetic import simulate_photo
from gmagc_desktop.service.search_service import SearchService
from tests.fixtures import shape_images, write_library


@pytest.fixture()
def library(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    write_library(root)
    return root


@pytest.fixture()
def service(tmp_path, library):
    instance = SearchService(tmp_path / "data")
    instance.load()
    instance.set_library(library)
    instance.build_index()
    return instance


def photo_png(seed=5):
    photo = simulate_photo(shape_images()["ell"], np.random.default_rng(seed))
    ok, buffer = cv2.imencode(".png", photo)
    assert ok
    return buffer.tobytes()


def test_access_code_is_generated_once_and_persisted(tmp_path):
    service = SearchService(tmp_path / "data")
    service.load()

    code = service.ensure_access_code()

    assert is_valid_code(code) and service.ensure_access_code() == code
    other = SearchService(tmp_path / "data")
    other.load()
    assert other.settings.access_code == code


def test_reset_access_code_changes_and_persists_it(tmp_path):
    service = SearchService(tmp_path / "data")
    service.load()
    old = service.ensure_access_code()

    new = service.reset_access_code()

    assert new != old and is_valid_code(new)
    other = SearchService(tmp_path / "data")
    other.load()
    assert other.settings.access_code == new


def test_set_server_enabled_is_persisted(tmp_path):
    service = SearchService(tmp_path / "data")
    service.load()

    service.set_server_enabled(False)

    other = SearchService(tmp_path / "data")
    other.load()
    assert other.settings.server_enabled is False


def test_indexing_state_follows_the_build(tmp_path, library):
    service = SearchService(tmp_path / "data")
    service.load()
    service.set_library(library)
    assert service.indexing_state() == (False, 0, 0)
    seen = []

    service.build_index(progress=lambda done, total: seen.append(service.indexing_state()))

    assert seen and all(state[0] for state in seen)
    assert seen[-1][1] == seen[-1][2] > 0
    assert service.indexing_state()[0] is False


def test_indexing_flag_is_cleared_when_the_build_fails(tmp_path):
    service = SearchService(tmp_path / "data")
    service.load()
    service.set_library(tmp_path / "missing")

    with pytest.raises(Exception):  # noqa: B017 - тип ошибки проверяют тесты индекса
        service.build_index()

    assert service.indexing_state()[0] is False


def test_search_image_bytes_honors_top_n(service):
    assert len(service.search_image_bytes(photo_png(), top_n=2).results) == 2


def test_search_waits_while_the_index_is_being_swapped(service):
    finished = threading.Event()

    def search():
        service.search_image_bytes(photo_png())
        finished.set()

    with service._lock:  # noqa: SLF001 - проверяем, что поиск держит общий замок
        thread = threading.Thread(target=search)
        thread.start()
        assert not finished.wait(0.4)
    assert finished.wait(15)
    thread.join()
