import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import flet as ft
import numpy as np
import pytest

import gmagc_desktop.ui.app as app_module
from gmagc_desktop.about import AUTHOR, NAME, VERSION
from gmagc_desktop.library.index import IndexCancelled
from gmagc_desktop.matcher.synthetic import simulate_photo
from gmagc_desktop.service import autostart
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
    services.setdefault("support", False)  # окно поддержки автора в тестах экрана не показываем
    services.setdefault("picker", FakePicker())  # настоящий ft.FilePicker() тестам не нужен
    services.setdefault("clipboard", FakeClipboard())  # настоящий ft.Clipboard() тестам не нужен
    # server_enabled=True по умолчанию (сервер стартует вместе с приложением) — без этой подмены
    # build() дёргает настоящий lan_addresses() -> socket.getaddrinfo(socket.gethostname(), ...);
    # на macOS-раннере CI имя хоста оканчивается на .local, и его резолв через mDNS виснет
    # на 30+ секунд (найдено по трассировке зависшего теста, см. историю коммитов).
    services.setdefault("addresses", lambda: [])
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


def shown_texts(page):
    """Тексты и в содержимом страницы, и в верхнем меню (AppBar живёт в page.views[0], не в page.added)."""
    appbar = page.views[0].appbar
    return texts(page.added[0]) + (texts(appbar) if appbar else [])


def test_initial_screen_shows_name_version_author_and_empty_state(tmp_path):
    app, page = make_app(tmp_path)

    shown = " ".join(t for t in shown_texts(page) if t)
    assert page.title == f"{NAME} {VERSION} — {AUTHOR}"
    assert NAME in shown and AUTHOR in shown
    assert "не выбрана" in shown and "Индекс не построен" in shown
    assert len(page.services) == 2


def test_the_splash_is_shown_first_and_then_replaced_by_the_real_screen(tmp_path):
    """Иначе окно остаётся пустым, пока грузятся настройки/индекс — сплэш с логотипом закрывает это время."""
    app, page = make_app(tmp_path)

    assert page.clean_calls == 1  # сплэш показали и убрали ровно раз, освободив место реальному экрану
    assert app.splash not in page.added
    assert app.splash.visible is not False  # сам сплэш не «выключен» — просто больше не на странице


def test_the_appbar_has_the_logo_author_in_the_title_and_a_settings_menu(tmp_path):
    app, page = make_app(tmp_path)
    appbar = page.views[0].appbar

    assert appbar is not None
    assert appbar.leading.src == "logo.svg"
    assert appbar.title.value == f"{NAME} — {AUTHOR}"
    assert app.menu_button in appbar.actions
    assert app.dark_theme_item in app.menu_button.items and app.large_text_item in app.menu_button.items


def test_the_left_column_holds_only_the_phone_section_library_is_in_the_main_area(tmp_path):
    app, page = make_app(tmp_path)
    root_row = next(c for c in walk(page.added[0]) if isinstance(c, ft.Row) and c.vertical_alignment is not None)
    left, right = root_row.controls[0], root_row.controls[2]

    assert "Телефон" in texts(left) and "Библиотека" not in texts(left)
    assert "Библиотека" in texts(right) and "Телефон" not in texts(right)
    assert app.onboarding_hint in list(walk(right))


def test_the_theme_starts_light_and_normal_sized(tmp_path):
    app, page = make_app(tmp_path)

    assert page.theme_mode == ft.ThemeMode.LIGHT
    assert page.theme.text_theme is None and not app.dark_theme_item.checked and not app.large_text_item.checked


def test_toggling_dark_theme_updates_the_page_and_persists(tmp_path):
    app, page = make_app(tmp_path)

    app.on_toggle_dark_theme(None)

    assert page.theme_mode == ft.ThemeMode.DARK
    assert app.service.settings.dark_theme is True
    assert app.dark_theme_item.checked is True

    other, _ = make_app(tmp_path)
    assert other.dark_theme_item.checked is True and other.page.theme_mode == ft.ThemeMode.DARK


def test_toggling_large_text_enlarges_the_default_theme_text():
    from gmagc_desktop.ui.app import _theme

    normal = _theme(False)
    large = _theme(True)

    assert normal.text_theme is None
    assert large.text_theme.body_medium.size == 16 and large.text_theme.title_large.size == 26


def test_both_theme_variants_use_the_shared_brand_seed_color():
    from gmagc_common.theme import SEED_COLOR
    from gmagc_desktop.ui.app import _theme

    assert _theme(False).color_scheme_seed == SEED_COLOR
    assert _theme(True).color_scheme_seed == SEED_COLOR


def test_toggling_large_text_updates_the_page_and_persists(tmp_path):
    app, page = make_app(tmp_path)

    app.on_toggle_large_text(None)

    assert page.theme.text_theme is not None and page.dark_theme.text_theme is not None
    assert app.service.settings.large_text is True
    assert app.large_text_item.checked is True


def test_the_autostart_item_reflects_the_current_state_when_supported(tmp_path, monkeypatch):
    monkeypatch.setattr(autostart, "is_supported", lambda: True)
    monkeypatch.setattr(autostart, "is_autostart_enabled", lambda: True)

    app, page = make_app(tmp_path)

    assert app.autostart_item.checked is True
    assert app.autostart_item in list(walk(page.views[0].appbar))


def test_the_autostart_item_is_hidden_when_unsupported(tmp_path, monkeypatch):
    monkeypatch.setattr(autostart, "is_supported", lambda: False)

    app, page = make_app(tmp_path)

    assert app.autostart_item not in list(walk(page.views[0].appbar))


def test_toggling_autostart_calls_set_autostart_with_the_current_exe(tmp_path, monkeypatch):
    monkeypatch.setattr(autostart, "is_supported", lambda: True)
    monkeypatch.setattr(autostart, "is_autostart_enabled", lambda: False)
    calls = []
    monkeypatch.setattr(autostart, "set_autostart", lambda enabled, exe: calls.append((enabled, exe)))
    monkeypatch.setattr(app_module, "current_executable", lambda: Path("C:/Apps/GMAGC/gmagc-desktop.exe"))
    app, _ = make_app(tmp_path)

    app.on_toggle_autostart(None)

    assert calls == [(True, Path("C:/Apps/GMAGC/gmagc-desktop.exe"))]
    assert app.autostart_item.checked is True


def test_a_missing_executable_path_disables_the_item_and_shows_a_banner(tmp_path, monkeypatch):
    monkeypatch.setattr(autostart, "is_supported", lambda: True)
    monkeypatch.setattr(autostart, "is_autostart_enabled", lambda: False)
    calls = []
    monkeypatch.setattr(autostart, "set_autostart", lambda enabled, exe: calls.append((enabled, exe)))
    monkeypatch.setattr(app_module, "current_executable", lambda: None)
    app, _ = make_app(tmp_path)

    app.on_toggle_autostart(None)

    assert calls == [] and app.autostart_item.checked is False
    assert app.banner.visible and "Не удалось определить путь" in app.banner_text.value


def test_choosing_a_folder_builds_the_index_and_restores_the_controls(tmp_path, library):
    app, _ = indexed_app(tmp_path, library)

    assert app.status_label.value.startswith("6 файлов, 5 семейств")
    assert app.library_text.value == str(library)
    assert not app.progress.visible and not app.cancel_button.visible and not app.banner.visible
    assert not app.choose_folder_button.disabled and not app.pick_photo_button.disabled


# ---- подсказка при первом запуске -----------------------------------------------------------------
def test_the_onboarding_hint_shows_when_no_library_is_chosen_yet(tmp_path):
    app, page = make_app(tmp_path)

    assert app.onboarding_hint.visible
    assert app.onboarding_hint in list(walk(page.added[0]))


def test_the_onboarding_hint_is_hidden_once_a_library_is_already_saved(tmp_path, library):
    first, _ = make_app(tmp_path)
    first.service.set_library(str(library))

    second, _ = make_app(tmp_path)  # тот же data_dir: настройки библиотеки уже сохранены на диске

    assert not second.onboarding_hint.visible


def test_choosing_a_folder_hides_the_onboarding_hint_even_without_a_page_restart(tmp_path, library):
    app, _ = indexed_app(tmp_path, library)

    assert not app.onboarding_hint.visible


def test_dismissing_the_onboarding_hint_hides_it_without_choosing_a_folder(tmp_path):
    app, _ = make_app(tmp_path)

    app.on_dismiss_onboarding(None)

    assert not app.onboarding_hint.visible


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


def test_the_score_badge_colour_follows_the_match_confidence(tmp_path):
    from gmagc_desktop.service.results import Result

    app, _ = make_app(tmp_path)

    def badge(score):
        result = Result(1, "a", "a.png", "/lib/a.png", score, (), b"")
        card = app._result_card(result)  # noqa: SLF001 - сборка карточки результата, не публичный API
        return card.content.content.controls[2].controls[0]

    good, low, bad = badge(0.92), badge(0.78), badge(0.50)
    assert good.bgcolor != low.bgcolor != bad.bgcolor
    assert "92" in good.content.value and "78" in low.content.value and "50" in bad.content.value


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


def test_core_check_menu_item_shows_the_result(tmp_path):
    app, page = make_app(tmp_path, check=lambda: {"ok": True, "shape": (224, 224), "versions": {"numpy": "9.9"}})
    assert app.check_label in list(walk(page.views[0].appbar))  # доступно из верхнего меню

    app.on_check(None)

    assert "ОК" in app.check_label.value and "numpy: 9.9" in app.check_label.value


def key(k, ctrl=False, shift=False, alt=False, meta=False):
    return SimpleNamespace(key=k, ctrl=ctrl, shift=shift, alt=alt, meta=meta)


def test_ctrl_v_pastes_a_photo_from_the_clipboard(tmp_path, library):
    photo = save_photo(tmp_path / "p.png", ell_photo())
    app, _ = indexed_app(tmp_path, library, clipboard=FakeClipboard(image=photo.read_bytes()))

    asyncio.run(app.on_key(key("V", ctrl=True)))

    assert len(app.results_column.controls) == 5


def test_f5_rebuilds_the_index(tmp_path, library):
    app, _ = make_app(tmp_path, picker=FakePicker(folder=str(library)))
    asyncio.run(app.on_choose_folder(None))
    app.status_label.value = "устарело"

    asyncio.run(app.on_key(key("F5")))

    assert "6" in app.status_label.value  # индекс снова построен, файлы посчитаны


def test_other_keys_and_v_without_ctrl_do_nothing(tmp_path, library):
    app, _ = indexed_app(tmp_path, library, clipboard=FakeClipboard(image=b"\x89PNG-not-really"))

    asyncio.run(app.on_key(key("V", ctrl=False)))
    asyncio.run(app.on_key(key("A", ctrl=True)))
    asyncio.run(app.on_key(key("Escape")))

    assert app.results_column.controls == [] and not app.banner.visible


def test_export_settings_saves_json_via_the_picker(tmp_path, library):
    save_path = str(tmp_path / "out" / "gmagc-settings.json")
    app, _ = indexed_app(tmp_path, library, picker=FakePicker(save_path=save_path))

    asyncio.run(app.on_export_settings(None))

    assert app.picker.saved == [(save_path, app.service.export_settings_json().encode("utf-8"))]
    assert app.banner.visible and save_path in app.banner_text.value


def test_cancelling_the_export_dialog_shows_no_banner(tmp_path, library):
    app, _ = indexed_app(tmp_path, library, picker=FakePicker(save_path=None))

    asyncio.run(app.on_export_settings(None))

    assert app.picker.saved == [] and not app.banner.visible


def test_import_settings_replaces_settings_and_refreshes_the_screen(tmp_path, library):
    imported = tmp_path / "imported.json"
    imported.write_text('{"top_n": 42, "library_dir": ""}', encoding="utf-8")
    app, _ = make_app(tmp_path, picker=FakePicker(files=[str(imported)]))

    asyncio.run(app.on_import_settings(None))

    assert app.service.settings.top_n == 42
    assert app.library_text.value == "не выбрана" and app.status_label.value == "Индекс не построен"
    assert app.banner.visible and "импортированы" in app.banner_text.value


def test_importing_the_same_library_reloads_its_index_in_the_screen(tmp_path, library):
    imported = tmp_path / "imported.json"
    picker = FakePicker(folder=str(library), files=[str(imported)])
    app, _ = indexed_app(tmp_path, library, picker=picker)
    imported.write_text(json.dumps({"library_dir": str(library)}), encoding="utf-8")

    asyncio.run(app.on_import_settings(None))

    assert "6" in app.status_label.value  # индекс той же библиотеки снова загружен, а не потерян


def test_import_with_no_file_chosen_does_nothing(tmp_path, library):
    app, _ = indexed_app(tmp_path, library, picker=FakePicker(files=[]))
    before = app.service.settings.top_n

    asyncio.run(app.on_import_settings(None))

    assert app.service.settings.top_n == before and not app.banner.visible


def test_import_of_an_unreadable_file_shows_an_error(tmp_path, library):
    app, _ = indexed_app(tmp_path, library, picker=FakePicker(files=[str(tmp_path / "missing.json")]))

    asyncio.run(app.on_import_settings(None))

    assert app.banner.visible and "Не удалось прочитать файл" in app.banner_text.value


def test_demo_variables_run_indexing_and_a_search_at_startup(tmp_path, library, monkeypatch):
    photo = save_photo(tmp_path / "demo.png", ell_photo())
    monkeypatch.setenv("GMAGC_DEMO_LIBRARY", str(library))
    monkeypatch.setenv("GMAGC_DEMO_PHOTO", str(photo))

    app, _ = make_app(tmp_path)

    assert app.status_label.value.startswith("6 файлов") and len(app.results_column.controls) == 5
