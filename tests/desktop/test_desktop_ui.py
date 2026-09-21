import asyncio

import cv2
import flet as ft
import numpy as np
import pytest

from gmagc_desktop.about import AUTHOR, NAME, VERSION
from gmagc_desktop.library.index import IndexCancelled
from gmagc_desktop.matcher.synthetic import simulate_photo
from gmagc_desktop.service.search_service import SearchService
from gmagc_desktop.ui.app import build_page
from tests.fakes import FakeClipboard, FakePicker, FakeServer, StubPage, texts, walk
from tests.fixtures import shape_images, write_library


@pytest.fixture()
def library(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    write_library(root)
    return root


def make_app(tmp_path, **services):
    services.setdefault("server", FakeServer())  # настоящий сервер в тестах экрана не запускаем
    services.setdefault("updates", None)  # проверку обновлений в тестах отключаем
    page = StubPage()
    app = build_page(page, service=SearchService(tmp_path / "data"), **services)
    return app, page


def save_photo(path, image):
    ok, buffer = cv2.imencode(".png", image)
    path.write_bytes(buffer.tobytes())
    return path


def ell_photo():
    return simulate_photo(shape_images()["ell"], np.random.default_rng(5))


def indexed_app(tmp_path, library, **services):
    services.setdefault("picker", FakePicker(folder=str(library)))
    app, page = make_app(tmp_path, **services)
    asyncio.run(app.on_choose_folder(None))
    return app, page


def test_initial_screen_shows_name_version_author_and_empty_state(tmp_path):
    app, page = make_app(tmp_path)

    shown = " ".join(t for t in texts(page.added[0]) if t)
    assert page.title == f"{NAME} {VERSION}"
    assert NAME in shown and VERSION in shown and AUTHOR in shown
    assert "не выбрана" in shown and "Индекс не построен" in shown
    assert len(page.services) == 2


def test_choosing_a_folder_builds_the_index_and_restores_the_controls(tmp_path, library):
    app, _ = indexed_app(tmp_path, library)

    assert app.status_label.value.startswith("6 файлов, 5 семейств")
    assert app.library_text.value == str(library)
    assert not app.progress.visible and not app.cancel_button.visible and not app.banner.visible
    assert not app.choose_folder_button.disabled and not app.pick_photo_button.disabled


def test_missing_folder_is_reported_in_the_banner(tmp_path):
    app, _ = make_app(tmp_path, picker=FakePicker(folder=str(tmp_path / "nope")))

    asyncio.run(app.on_choose_folder(None))

    assert app.banner.visible and "library folder not found" in app.banner_text.value
    assert app.status_label.value == "Индекс не построен"
    assert not app.choose_folder_button.disabled


def test_rebuild_without_a_library_and_photo_without_an_index_ask_for_a_folder(tmp_path):
    photo = save_photo(tmp_path / "p.png", ell_photo())
    app, _ = make_app(tmp_path, picker=FakePicker(files=[str(photo)]))

    asyncio.run(app.on_rebuild(None))
    assert app.banner.visible and "Сначала выберите папку" in app.banner_text.value

    asyncio.run(app.on_pick_photo(None))
    assert "Сначала выберите папку" in app.banner_text.value


def test_indexing_errors_and_cancel_are_shown_not_raised(tmp_path, library, monkeypatch):
    app, _ = indexed_app(tmp_path, library)

    def cancelled(progress=None, cancel=None):
        raise IndexCancelled()

    monkeypatch.setattr(app.service, "build_index", cancelled)
    asyncio.run(app.on_rebuild(None))
    assert "Индексация отменена" in app.banner_text.value and not app.cancel_button.visible

    def boom(progress=None, cancel=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(app.service, "build_index", boom)
    asyncio.run(app.on_rebuild(None))
    assert "Ошибка индексации: boom" in app.banner_text.value and not app.choose_folder_button.disabled


def test_picked_photo_shows_the_photo_the_projection_and_result_cards(tmp_path, library):
    photo = save_photo(tmp_path / "p.png", ell_photo())
    app, _ = indexed_app(tmp_path, library)
    app.picker.files = [str(photo)]

    asyncio.run(app.on_pick_photo(None))

    assert app.photo_holder.visible and app.projection_holder.visible
    assert len(app.results_column.controls) == 5
    first = texts(app.results_column.controls[0])
    assert any(t.endswith(".png") and "ell" in t for t in first) and any(t.endswith("%") for t in first)
    assert not app.pick_photo_button.disabled


def test_flat_photo_shows_the_no_projection_message(tmp_path, library):
    photo = save_photo(tmp_path / "flat.png", np.full((480, 640, 3), 90, np.uint8))
    app, _ = indexed_app(tmp_path, library)
    app.picker.files = [str(photo)]

    asyncio.run(app.on_pick_photo(None))

    assert "Проекция на фото не найдена" in app.banner_text.value and app.results_column.controls == []


def test_the_folder_button_of_a_result_reveals_the_file(tmp_path, library):
    revealed = []
    photo = save_photo(tmp_path / "p.png", ell_photo())
    app, _ = indexed_app(tmp_path, library, reveal=revealed.append)
    app.picker.files = [str(photo)]
    asyncio.run(app.on_pick_photo(None))

    button = next(c for c in walk(app.results_column.controls[0]) if isinstance(c, ft.IconButton))
    button.on_click(None)

    assert len(revealed) == 1 and revealed[0].startswith(str(library)) and revealed[0].endswith(".png")


def test_paste_prefers_an_image_then_a_copied_file_then_reports_an_empty_clipboard(tmp_path, library):
    photo = save_photo(tmp_path / "p.png", ell_photo())
    app, _ = indexed_app(tmp_path, library, clipboard=FakeClipboard(image=photo.read_bytes()))
    asyncio.run(app.on_paste(None))
    assert len(app.results_column.controls) == 5

    app.results_column.controls = []
    app.clipboard.image = None
    app.clipboard.files = [str(tmp_path / "notes.txt"), str(photo)]
    asyncio.run(app.on_paste(None))
    assert len(app.results_column.controls) == 5

    app.results_column.controls = []
    app.clipboard.files = []
    asyncio.run(app.on_paste(None))
    assert "В буфере обмена" in app.banner_text.value and app.results_column.controls == []


def test_core_check_button_shows_the_result(tmp_path):
    app, page = make_app(tmp_path, check=lambda: {"ok": True, "shape": (224, 224), "versions": {"numpy": "9.9"}})

    button = next(c for c in walk(page.added[0]) if isinstance(c, ft.TextButton) and c.content.value == "Проверить ядро")
    button.on_click(None)

    assert "ОК" in app.check_label.value and "numpy: 9.9" in app.check_label.value


def test_demo_variables_run_indexing_and_a_search_at_startup(tmp_path, library, monkeypatch):
    photo = save_photo(tmp_path / "demo.png", ell_photo())
    monkeypatch.setenv("GMAGC_DEMO_LIBRARY", str(library))
    monkeypatch.setenv("GMAGC_DEMO_PHOTO", str(photo))

    app, _ = make_app(tmp_path)

    assert app.status_label.value.startswith("6 файлов") and len(app.results_column.controls) == 5
