import shutil

import cv2
import numpy as np
import pytest

from gmagc_desktop.library.index import IndexCancelled, LibraryNotFound
from gmagc_desktop.matcher.synthetic import simulate_photo
from gmagc_desktop.service import search_service
from gmagc_desktop.service.results import Outcome
from gmagc_desktop.service.search_service import CorrectionError, NoIndexError, PhotoError, SearchService
from gmagc_desktop.service.settings import Settings, settings_to_json
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


def test_the_service_persists_the_theme_and_text_size_choices(tmp_path):
    service = SearchService(tmp_path / "data")
    service.load()

    service.set_dark_theme(True)
    service.set_large_text(True)

    other = SearchService(tmp_path / "data")
    other.load()
    assert other.settings.dark_theme is True and other.settings.large_text is True


def test_export_settings_json_matches_the_current_settings(service):
    assert service.export_settings_json() == settings_to_json(service.settings)


def test_import_settings_json_replaces_settings_and_persists_to_disk(tmp_path):
    service = SearchService(tmp_path / "data")
    service.load()
    imported = settings_to_json(Settings(top_n=42, access_code="ZZZZ9999"))

    result = service.import_settings_json(imported)

    assert result.top_n == 42 and service.settings.top_n == 42
    reloaded = SearchService(tmp_path / "data")
    assert reloaded.load() is None and reloaded.settings.top_n == 42


def test_importing_a_different_library_forgets_the_loaded_index_and_its_cache_file(service, tmp_path, library):
    index_path = tmp_path / "data" / "index.npz"
    assert service.status() is not None and index_path.exists()

    service.import_settings_json(settings_to_json(Settings(library_dir=str(tmp_path / "other-lib"))))

    assert service.status() is None and not index_path.exists()


def test_importing_the_same_library_keeps_the_loaded_index(service, library):
    service.import_settings_json(settings_to_json(Settings(library_dir=str(library), top_n=7)))

    assert service.status() is not None and service.settings.top_n == 7


def test_build_index_reports_status_and_progress(tmp_path, library):
    service = SearchService(tmp_path / "data")
    service.load()
    service.set_library(library)
    calls = []

    status = service.build_index(progress=lambda done, total: calls.append((done, total)))

    assert (status.files, status.families, status.skipped, status.transient) == (6, 5, 1, 0)
    assert status.stale is False
    assert calls and calls[-1][0] == calls[-1][1]


def test_a_freshly_built_index_is_not_stale(service):
    assert service.index_is_stale() is False and service.status().stale is False


def test_adding_a_file_to_the_library_makes_the_index_stale(service, library):
    cv2.imwrite(str(library / "vendor_a" / "new_shape.png"), shape_images()["ell"])

    assert service.index_is_stale() is True and service.status().stale is True


def test_removing_a_library_file_makes_the_index_stale(service, library):
    next((library / "vendor_a").glob("*.png")).unlink()

    assert service.index_is_stale() is True


def test_touching_a_library_file_without_changing_it_leaves_the_index_fresh(service, library):
    """Пересборка индекса не запускается сама, только предупреждение: контроль по размеру и времени изменения."""
    assert service.index_is_stale() is False


def test_a_disconnected_library_folder_is_not_reported_as_stale(service, library):
    """Папка временно недоступна (например, отключён диск), а не «всё удалили» — предупреждение не показываем."""
    shutil.rmtree(library)

    assert service.index_is_stale() is False


def test_without_a_library_or_an_index_staleness_is_false(tmp_path):
    service = SearchService(tmp_path / "data")
    service.load()

    assert service.index_is_stale() is False and service.status() is None


def test_load_falls_back_to_the_backup_when_the_main_index_file_is_missing(service, tmp_path):
    service.build_index()  # второй раз: теперь есть index.npz.previous
    (tmp_path / "data" / "index.npz").unlink()

    status = service.load()

    assert status is not None and status.files == 6


def test_load_falls_back_to_the_backup_when_the_main_index_file_is_corrupt(service, tmp_path):
    service.build_index()
    (tmp_path / "data" / "index.npz").write_bytes(b"not a real npz file")

    status = service.load()

    assert status is not None and status.files == 6


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


# ---- обучение на исправлениях -----------------------------------------------------------------------
def test_add_correction_rejects_a_file_outside_the_library(service, tmp_path):
    outside = tmp_path / "elsewhere.png"
    outside.write_bytes(b"whatever, only the path matters here")

    with pytest.raises(CorrectionError):
        service.add_correction("vendor_b/ell.png", str(outside))


def test_add_correction_rejects_a_file_not_in_the_current_index(service, library):
    with pytest.raises(CorrectionError):
        service.add_correction("vendor_b/ell.png", str(library / "vendor_a" / "missing.png"))


def test_a_correction_promotes_the_correct_file_when_the_wrong_one_resurfaces(service, library):
    # первый результат по фото-эллу — vendor_b/ell.png; учим, что на самом деле нужен vendor_c/gobo.png
    wrong = service.search_photo(ell_photo()).results[0].rel_path
    assert wrong == "vendor_b/ell.png"

    service.add_correction(wrong, str(library / "vendor_c" / "gobo.png"))
    outcome = service.search_photo(ell_photo())

    assert outcome.results[0].rel_path == "vendor_c/gobo.png"
    assert outcome.results[0].score >= 0.9
    assert any(r.rel_path == "vendor_b/ell.png" for r in outcome.results)  # старый результат остаётся ниже, не исчезает


def test_a_correction_does_not_affect_searches_where_the_wrong_file_never_shows_up(service, library):
    # top_n=1 имитирует настоящую библиотеку: там неверный файл (эллы) обычно не попал бы в результаты
    # запроса на совсем другую форму (кольцо) — в этой тестовой библиотеке из 5 файлов иначе не проверить
    service.add_correction("vendor_b/ell.png", str(library / "vendor_c" / "gobo.png"))

    outcome = service.search_photo(simulate_photo(shape_images()["ring"], np.random.default_rng(9)), top_n=1)

    assert outcome.results[0].rel_path == "vendor_a/ring.png"


def test_corrections_persist_across_reload(tmp_path, library):
    service = SearchService(tmp_path / "data")
    service.load()
    service.set_library(library)
    service.build_index()
    wrong = service.search_photo(ell_photo()).results[0].rel_path
    service.add_correction(wrong, str(library / "vendor_c" / "gobo.png"))

    reloaded = SearchService(tmp_path / "data")
    reloaded.load()
    outcome = reloaded.search_photo(ell_photo())

    assert outcome.results[0].rel_path == "vendor_c/gobo.png"


def test_changing_the_library_drops_stale_corrections_too(service, tmp_path, library):
    service.add_correction("vendor_b/ell.png", str(library / "vendor_c" / "gobo.png"))
    other = tmp_path / "other"
    other.mkdir()

    service.set_library(other)

    assert service._corrections == []  # noqa: SLF001 - пути были относительны прежней библиотеки
