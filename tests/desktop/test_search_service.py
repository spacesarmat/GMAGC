import cv2
import numpy as np
import pytest

from gmagc_desktop.library.index import IndexCancelled, LibraryNotFound
from gmagc_desktop.matcher.synthetic import simulate_photo
from gmagc_desktop.service import search_service
from gmagc_desktop.service.results import Outcome
from gmagc_desktop.service.search_service import NoIndexError, PhotoError, SearchService
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


def ell_photo(seed=5):
    return simulate_photo(shape_images()["ell"], np.random.default_rng(seed))


def test_build_index_reports_status_and_progress(tmp_path, library):
    service = SearchService(tmp_path / "data")
    service.load()
    service.set_library(library)
    calls = []

    status = service.build_index(progress=lambda done, total: calls.append((done, total)))

    assert (status.files, status.families, status.skipped, status.transient) == (6, 5, 1, 0)
    assert calls and calls[-1][0] == calls[-1][1]


def test_search_returns_families_with_copies_thumbnails_and_projection(service, library):
    outcome = service.search_photo(ell_photo())

    assert len(outcome.results) == 5  # по одной карточке на семейство
    top = outcome.results[0]
    assert top.name in {"ell.png", "ell_small.png"} and len(top.copies) == 1
    assert top.full_path.startswith(str(library)) and all(c.startswith(str(library)) for c in top.copies)
    assert top.thumbnail_png.startswith(b"\x89PNG") and outcome.projection_png.startswith(b"\x89PNG")
    assert 0.0 < top.score <= 1.0 and outcome.took_ms > 0
    assert [r.rank for r in outcome.results] == [1, 2, 3, 4, 5]
    assert [r.score for r in outcome.results] == sorted((r.score for r in outcome.results), reverse=True)


def test_low_confidence_threshold_decides_the_outcome_kind(service, monkeypatch):
    monkeypatch.setattr(search_service, "LOW_CONFIDENCE_SCORE", 2.0)
    assert service.search_photo(ell_photo()).kind is Outcome.LOW_CONFIDENCE

    monkeypatch.setattr(search_service, "LOW_CONFIDENCE_SCORE", 0.0)
    assert service.search_photo(ell_photo()).kind is Outcome.FOUND


def test_flat_photo_has_no_projection(service):
    outcome = service.search_photo(np.full((480, 640, 3), 90, np.uint8))

    assert outcome.kind is Outcome.NO_PROJECTION and outcome.results == ()


def test_search_without_an_index_raises(tmp_path):
    service = SearchService(tmp_path / "data")
    service.load()

    with pytest.raises(NoIndexError):
        service.search_photo(ell_photo())
    with pytest.raises(NoIndexError, match="папка библиотеки не выбрана"):
        service.build_index()


def test_unreadable_photos_raise_photo_error(service, tmp_path):
    with pytest.raises(PhotoError):
        service.search_file(tmp_path / "missing.png")
    with pytest.raises(PhotoError):
        service.search_image_bytes(b"junk")
    with pytest.raises(PhotoError):
        service.search_image_bytes(b"")


def test_file_and_bytes_searches_agree(service, tmp_path):
    ok, buffer = cv2.imencode(".png", ell_photo())
    path = tmp_path / "photo.png"
    path.write_bytes(buffer.tobytes())

    from_file = service.search_file(path)
    from_bytes = service.search_image_bytes(buffer.tobytes())

    assert [r.rel_path for r in from_file.results] == [r.rel_path for r in from_bytes.results]


def test_load_restores_settings_and_index_from_the_cache(tmp_path, service, library):
    fresh = SearchService(tmp_path / "data")

    status = fresh.load()

    assert status == service.status() and fresh.settings.library_dir == str(library)
    assert fresh.search_photo(ell_photo()).results


def test_cancelled_build_leaves_no_index(tmp_path, library):
    service = SearchService(tmp_path / "data")
    service.load()
    service.set_library(library)

    with pytest.raises(IndexCancelled):
        service.build_index(cancel=lambda: True)

    assert service.status() is None and not (tmp_path / "data" / "index.npz").exists()


def test_changing_the_library_drops_the_old_index_and_cache(service, tmp_path):
    other = tmp_path / "other"
    other.mkdir()

    service.set_library(other)

    assert service.status() is None
    assert not (tmp_path / "data" / "index.npz").exists()
    with pytest.raises(NoIndexError):
        service.search_photo(ell_photo())


def test_missing_library_folder_is_reported(tmp_path):
    service = SearchService(tmp_path / "data")
    service.load()
    service.set_library(tmp_path / "nope")

    with pytest.raises(LibraryNotFound):
        service.build_index()


def test_a_vanished_library_file_gets_a_blank_thumbnail(service, library):
    (library / "vendor_c" / "gobo.png").unlink()

    outcome = service.search_photo(simulate_photo(shape_images()["gobo"], np.random.default_rng(3)))

    assert any(r.name == "gobo.png" and r.thumbnail_png == search_service.BLANK_THUMBNAIL for r in outcome.results)
