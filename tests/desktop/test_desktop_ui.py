import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import flet as ft
import numpy as np
import pytest

import gmagc_desktop.ui.app as app_module
from gmagc_common import i18n
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
    return texts(page.added[0])


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


def test_the_sidebar_has_the_brand_and_navigation_and_starts_on_search(tmp_path):
    app, page = make_app(tmp_path)

    shown = shown_texts(page)
    assert NAME in shown and "Поиск гобо" in shown and "Телефон" in shown and "Библиотека" in shown
    assert "Настройки" in shown and AUTHOR in shown
    assert app.search_view.visible and not app.phone_view.visible
    assert not app.library_view.visible and not app.settings_view.visible
    assert app.breadcrumb.value == "GMAGC / Поиск гобо"


def test_clicking_nav_items_switches_the_visible_screen_and_the_breadcrumb(tmp_path):
    app, _ = make_app(tmp_path)

    app._nav_containers["library"].on_click(None)  # noqa: SLF001 - переключение экрана, не отдельный публичный метод
    assert app.library_view.visible and not app.search_view.visible
    assert app.breadcrumb.value == "GMAGC / Библиотека"

    app._nav_containers["settings"].on_click(None)  # noqa: SLF001
    assert app.settings_view.visible and not app.library_view.visible
    assert app.breadcrumb.value == "GMAGC / Настройки"


def test_the_library_screen_holds_the_library_controls_not_the_search_screen(tmp_path):
    app, _ = make_app(tmp_path)

    assert app.choose_folder_button in list(walk(app.library_view))
    assert app.pick_photo_button not in list(walk(app.library_view))
    assert app.pick_photo_button in list(walk(app.search_view))
    assert app.onboarding_hint in list(walk(app.search_view))


def test_the_theme_is_always_dark_and_normal_sized_by_default(tmp_path):
    app, page = make_app(tmp_path)

    assert page.theme_mode == ft.ThemeMode.DARK
    assert page.theme.text_theme is None and app.large_text_switch.value is False


def test_toggling_large_text_enlarges_the_default_theme_text():
    from gmagc_desktop.ui.app import _theme

    normal = _theme(False)
    large = _theme(True)

    assert normal.text_theme is None
    assert large.text_theme.body_medium.size == 16 and large.text_theme.title_large.size == 26


def test_both_theme_variants_use_the_desktop_accent_colour():
    from gmagc_common.theme import DESKTOP_ACCENT
    from gmagc_desktop.ui.app import _theme

    assert _theme(False).color_scheme_seed == DESKTOP_ACCENT
    assert _theme(True).color_scheme_seed == DESKTOP_ACCENT


def test_the_results_count_dropdown_shows_the_setting_and_saves_a_new_choice(tmp_path):
    app, page = make_app(tmp_path)
    assert app.results_count_dropdown.value == "50"
    assert app.results_count_dropdown in list(walk(app.settings_view))

    app.results_count_dropdown.value = "100"
    app.on_results_count_change(None)

    assert app.service.settings.results_count == 100


def test_desktop_searches_ask_for_the_chosen_number_of_results(tmp_path, library, monkeypatch):
    from gmagc_desktop.service.search_service import SearchService

    app, _ = indexed_app(tmp_path, library)
    app.results_count_dropdown.value = "20"
    app.on_results_count_change(None)
    captured = []
    real_search_photo = SearchService.search_photo

    def spy(self, photo_bgr, top_n=None, **kwargs):
        captured.append(top_n)
        return real_search_photo(self, photo_bgr, top_n, **kwargs)

    monkeypatch.setattr(SearchService, "search_photo", spy)
    photo = save_photo(tmp_path / "p.png", ell_photo())
    app.picker.files = [str(photo)]
    asyncio.run(app.on_pick_photo(None))

    assert captured == [20]


def test_toggling_large_text_updates_the_page_and_persists(tmp_path):
    app, page = make_app(tmp_path)

    app.large_text_switch.value = True
    app.on_toggle_large_text(None)

    assert page.theme.text_theme is not None and page.dark_theme.text_theme is not None
    assert app.service.settings.large_text is True


def test_the_autostart_switch_reflects_the_current_state_when_supported(tmp_path, monkeypatch):
    monkeypatch.setattr(autostart, "is_supported", lambda: True)
    monkeypatch.setattr(autostart, "is_autostart_enabled", lambda: True)

    app, _ = make_app(tmp_path)

    assert app.autostart_switch.value is True
    assert app.autostart_switch in list(walk(app.settings_view))


def test_the_autostart_switch_is_hidden_when_unsupported(tmp_path, monkeypatch):
    monkeypatch.setattr(autostart, "is_supported", lambda: False)

    app, _ = make_app(tmp_path)

    assert app.autostart_switch not in list(walk(app.settings_view))


def test_toggling_autostart_calls_set_autostart_with_the_current_exe(tmp_path, monkeypatch):
    monkeypatch.setattr(autostart, "is_supported", lambda: True)
    monkeypatch.setattr(autostart, "is_autostart_enabled", lambda: False)
    calls = []
    monkeypatch.setattr(autostart, "set_autostart", lambda enabled, exe: calls.append((enabled, exe)))
    monkeypatch.setattr(app_module, "current_executable", lambda: Path("C:/Apps/GMAGC/gmagc-desktop.exe"))
    app, _ = make_app(tmp_path)

    app.autostart_switch.value = True
    app.on_toggle_autostart(None)

    assert calls == [(True, Path("C:/Apps/GMAGC/gmagc-desktop.exe"))]
    assert app.autostart_switch.value is True


def test_a_missing_executable_path_disables_the_switch_and_shows_a_banner(tmp_path, monkeypatch):
    monkeypatch.setattr(autostart, "is_supported", lambda: True)
    monkeypatch.setattr(autostart, "is_autostart_enabled", lambda: False)
    calls = []
    monkeypatch.setattr(autostart, "set_autostart", lambda enabled, exe: calls.append((enabled, exe)))
    monkeypatch.setattr(app_module, "current_executable", lambda: None)
    app, _ = make_app(tmp_path)

    app.autostart_switch.value = True
    app.on_toggle_autostart(None)

    assert calls == [] and app.autostart_switch.value is False
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


def _report_wrong_button(app):
    return next(
        c for c in walk(app.results_column) if isinstance(c, ft.IconButton) and c.tooltip and "не то" in c.tooltip
    )


def test_reporting_a_wrong_result_learns_and_immediately_refreshes_results(tmp_path, library):
    app, _ = indexed_app(tmp_path, library)
    photo = save_photo(tmp_path / "p.png", ell_photo())
    app.picker.files = [str(photo)]
    asyncio.run(app.on_pick_photo(None))
    assert app.results_column.controls[0].data.endswith("ell.png")

    button = _report_wrong_button(app)
    app.picker.files = [str(library / "vendor_c" / "gobo.png")]

    asyncio.run(app.on_report_wrong(SimpleNamespace(control=button)))

    assert "Запомнено" in app.banner_text.value
    assert app.results_column.controls[0].data.endswith("gobo.png")


def test_reporting_a_wrong_result_shows_an_error_for_a_file_outside_the_library(tmp_path, library):
    app, _ = indexed_app(tmp_path, library)
    photo = save_photo(tmp_path / "p.png", ell_photo())
    app.picker.files = [str(photo)]
    asyncio.run(app.on_pick_photo(None))
    button = _report_wrong_button(app)
    app.picker.files = [str(tmp_path / "outside.png")]

    asyncio.run(app.on_report_wrong(SimpleNamespace(control=button)))

    assert app.banner.visible and "не в папке библиотеки" in app.banner_text.value


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


def test_the_adjustment_panel_appears_once_a_photo_is_shown_with_neutral_sliders(tmp_path, library):
    app, _ = indexed_app(tmp_path, library)
    assert not app.adjust_panel.visible

    photo = save_photo(tmp_path / "p.png", ell_photo())
    app.picker.files = [str(photo)]
    asyncio.run(app.on_pick_photo(None))

    assert app.adjust_panel.visible
    assert app.adjust_brightness_slider.value == 0.0
    assert app.adjust_contrast_slider.value == 1.0
    assert app.adjust_exposure_slider.value == 0.0


def test_moving_a_slider_updates_the_label_and_live_preview_without_searching_yet(tmp_path, library, monkeypatch):
    app, _ = indexed_app(tmp_path, library)
    photo = save_photo(tmp_path / "p.png", ell_photo())
    app.picker.files = [str(photo)]
    asyncio.run(app.on_pick_photo(None))
    photo_before = app.photo_holder.controls[1].src
    calls = []
    monkeypatch.setattr(app.service, "search_photo", lambda *a, **k: calls.append(a))

    app.adjust_brightness_slider.value = 40.0
    app.on_adjust_change(None)

    assert app.adjust_brightness_label.value == "Яркость: +40"
    assert app.photo_holder.controls[1].src != photo_before
    assert calls == []


def test_moving_the_projection_slider_updates_its_own_live_preview_without_searching_yet(
    tmp_path, library, monkeypatch
):
    app, _ = indexed_app(tmp_path, library)
    photo = save_photo(tmp_path / "p.png", ell_photo())
    app.picker.files = [str(photo)]
    asyncio.run(app.on_pick_photo(None))
    projection_before = app.projection_holder.controls[1].src
    photo_before = app.photo_holder.controls[1].src
    calls = []
    monkeypatch.setattr(app.service, "search_photo", lambda *a, **k: calls.append(a))

    app.proj_adjust_contrast_slider.value = 1.8
    app.on_proj_adjust_change(None)

    assert app.proj_adjust_contrast_label.value == "Контраст: 1.8×"
    assert app.projection_holder.controls[1].src != projection_before
    assert app.photo_holder.controls[1].src == photo_before  # поправка фото не менялась
    assert calls == []


def test_releasing_the_slider_reruns_search_with_the_adjusted_photo(tmp_path, library, monkeypatch):
    from gmagc_desktop.service.search_service import SearchService

    app, _ = indexed_app(tmp_path, library)
    original = ell_photo()
    photo = save_photo(tmp_path / "p.png", original)
    app.picker.files = [str(photo)]
    asyncio.run(app.on_pick_photo(None))

    captured = []
    real_search_photo = SearchService.search_photo

    def spy(self, photo_bgr, top_n=None, **kwargs):
        captured.append(photo_bgr)
        return real_search_photo(self, photo_bgr, top_n, **kwargs)

    monkeypatch.setattr(SearchService, "search_photo", spy)

    app.adjust_brightness_slider.value = 40.0
    app.on_adjust_commit(None)

    assert len(captured) == 1
    assert captured[0].mean() > original.astype(float).mean()


def test_reset_restores_neutral_sliders_and_the_original_top_result(tmp_path, library):
    app, _ = indexed_app(tmp_path, library)
    photo = save_photo(tmp_path / "p.png", ell_photo())
    app.picker.files = [str(photo)]
    asyncio.run(app.on_pick_photo(None))
    original_top = app.results_column.controls[0].data
    app.adjust_brightness_slider.value = 40.0
    app.on_adjust_commit(None)

    app.on_reset_adjustments(None)

    assert app.adjust_brightness_slider.value == 0.0
    assert app.adjust_brightness_label.value == "Яркость: 0"
    assert app.adjust_contrast_slider.value == 1.0
    assert app.adjust_exposure_slider.value == 0.0
    assert app.results_column.controls[0].data == original_top


def test_a_new_photo_resets_previously_adjusted_sliders(tmp_path, library):
    app, _ = indexed_app(tmp_path, library)
    photo = save_photo(tmp_path / "p.png", ell_photo())
    app.picker.files = [str(photo)]
    asyncio.run(app.on_pick_photo(None))
    app.adjust_brightness_slider.value = 40.0
    app.on_adjust_commit(None)
    assert app.adjust_brightness_slider.value == 40.0

    photo2 = save_photo(tmp_path / "p2.png", ell_photo())
    app.picker.files = [str(photo2)]
    asyncio.run(app.on_pick_photo(None))

    assert app.adjust_brightness_slider.value == 0.0
    assert app.adjust_brightness_label.value == "Яркость: 0"


def test_the_projection_adjustment_panel_appears_once_a_projection_is_found(tmp_path, library):
    app, _ = indexed_app(tmp_path, library)
    assert not app.proj_adjust_panel.visible

    photo = save_photo(tmp_path / "p.png", ell_photo())
    app.picker.files = [str(photo)]
    asyncio.run(app.on_pick_photo(None))

    assert app.proj_adjust_panel.visible
    assert app.proj_adjust_brightness_slider.value == 0.0


def test_the_projection_adjustment_panel_stays_hidden_when_no_projection_is_found(tmp_path, library):
    flat = save_photo(tmp_path / "flat.png", np.full((480, 640, 3), 90, np.uint8))
    app, _ = indexed_app(tmp_path, library)
    app.picker.files = [str(flat)]

    asyncio.run(app.on_pick_photo(None))

    assert not app.proj_adjust_panel.visible


def test_releasing_the_projection_slider_reruns_search_with_new_projection_adjustment(tmp_path, library, monkeypatch):
    from gmagc_desktop.service.search_service import SearchService

    app, _ = indexed_app(tmp_path, library)
    photo = save_photo(tmp_path / "p.png", ell_photo())
    app.picker.files = [str(photo)]
    asyncio.run(app.on_pick_photo(None))

    captured = []
    real_search_photo = SearchService.search_photo

    def spy(self, photo_bgr, top_n=None, **kwargs):
        captured.append(kwargs)
        return real_search_photo(self, photo_bgr, top_n, **kwargs)

    monkeypatch.setattr(SearchService, "search_photo", spy)

    app.proj_adjust_contrast_slider.value = 1.8
    app.on_proj_adjust_commit(None)

    assert len(captured) == 1
    assert captured[0]["projection_contrast"] == 1.8
    assert captured[0]["projection_brightness"] == 0.0


def test_resetting_projection_adjustments_does_not_touch_photo_adjustments(tmp_path, library):
    app, _ = indexed_app(tmp_path, library)
    photo = save_photo(tmp_path / "p.png", ell_photo())
    app.picker.files = [str(photo)]
    asyncio.run(app.on_pick_photo(None))
    app.adjust_brightness_slider.value = 30.0
    app.on_adjust_commit(None)
    app.proj_adjust_contrast_slider.value = 1.7
    app.on_proj_adjust_commit(None)

    app.on_reset_proj_adjustments(None)

    assert app.proj_adjust_contrast_slider.value == 1.0
    assert app.adjust_brightness_slider.value == 30.0  # поправка фото не сбрасывается


def test_the_score_badge_colour_follows_the_match_confidence(tmp_path):
    from gmagc_desktop.service.results import Result

    app, _ = make_app(tmp_path)

    def badge(score):
        result = Result(1, "a", "a.png", "/lib/a.png", score, (), b"")
        card = app._result_card(result)  # noqa: SLF001 - сборка карточки результата, не публичный API
        return next(
            c
            for c in walk(card)
            if isinstance(c, ft.Container) and isinstance(c.content, ft.Text) and c.content.value.endswith("%")
        )

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
    app, _ = make_app(tmp_path, check=lambda: {"ok": True, "shape": (224, 224), "versions": {"numpy": "9.9"}})
    assert app.check_label in list(walk(app.settings_view))  # доступно на экране «Настройки»

    app.on_check(None)

    assert "ОК" in app.check_label.value and "numpy: 9.9" in app.check_label.value


def test_the_log_file_lives_next_to_the_search_service_data_not_the_real_user_profile(tmp_path):
    app, _ = make_app(tmp_path)

    assert app._log_path == app.service.data_dir / "gmagc.log"
    assert app._log_path.parent == tmp_path / "data"


def test_send_log_opens_mail_with_diagnostics_and_reveals_the_log_file(tmp_path, library):
    opened = []
    revealed = []
    app, _ = indexed_app(tmp_path, library, open_url=opened.append, reveal=revealed.append)
    app._show_banner("что-то пошло не так", error=True)  # попадает в лог-файл

    app.on_send_log(None)

    assert len(opened) == 1
    assert opened[0].startswith(f"mailto:{app_module.SUPPORT_EMAIL}?")
    assert "subject=GMAGC" in opened[0]
    assert revealed == [str(app._log_path)]
    assert "что-то пошло не так" in app._log_path.read_text(encoding="utf-8")


def test_send_log_shows_a_message_when_the_log_has_no_errors_yet(tmp_path):
    opened = []
    app, _ = make_app(tmp_path, open_url=opened.append)

    app.on_send_log(None)

    assert opened  # письмо всё равно открывается — лог просто не прикладываем
    assert "пока пуст" in app.banner_text.value


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


def test_the_settings_screen_has_fixture_folder_fields_that_show_and_save_the_folders(tmp_path):
    app, _ = make_app(tmp_path)
    assert app.ma3_dir_field in list(walk(app.settings_view)) and app.ma2_dir_field in list(walk(app.settings_view))
    assert app.ma3_dir_field.value == "" and app.ma2_dir_field.value == ""

    app.ma3_dir_field.value = " C:/ma3 "
    app.ma2_dir_field.value = "C:/ma2"
    app.on_fixture_dirs_change(None)

    assert (app.service.settings.ma3_fixture_dir, app.service.settings.ma2_fixture_dir) == ("C:/ma3", "C:/ma2")


def test_the_fixture_folder_fields_start_from_the_saved_settings(tmp_path):
    from gmagc_desktop.service.search_service import SearchService

    first = SearchService(tmp_path / "data")
    first.load()
    first.set_fixture_dirs("D:/ma3", "D:/ma2")

    app, _ = make_app(tmp_path)

    assert (app.ma3_dir_field.value, app.ma2_dir_field.value) == ("D:/ma3", "D:/ma2")


def all_texts(app):
    return [c.value for c in walk(app.page.added[-1]) if isinstance(c, ft.Text)]


def test_the_language_dropdown_offers_auto_russian_and_english_and_shows_the_saved_choice(tmp_path):
    app, _ = make_app(tmp_path)

    assert app.language_dropdown in list(walk(app.settings_view))
    assert [o.key for o in app.language_dropdown.options] == ["auto", "ru", "en"]
    assert app.language_dropdown.value == "auto"


def test_switching_to_english_rebuilds_the_interface_in_english_and_opens_settings(tmp_path):
    app, page = make_app(tmp_path)
    old_services = list(page.services)

    app.language_dropdown.value = "en"
    app.on_language_change(None)

    new = app.rebuilt_as
    assert new is not None and new is not app and new.current_view == "settings"
    assert app.service.settings.language == "en" and i18n.current_language() == "en"
    texts_now = all_texts(new)
    assert "Settings" in texts_now and "Library" in texts_now and new.breadcrumb.value == "GMAGC / Settings"
    assert new.language_dropdown.value == "en"
    assert page.services == old_services  # выбор файлов и буфер обмена не задваиваются
    assert new.server is app.server and new.picker is app.picker and new.clipboard is app.clipboard


def test_switching_back_to_russian_restores_the_russian_labels(tmp_path):
    app, _ = make_app(tmp_path)
    app.language_dropdown.value = "en"
    app.on_language_change(None)
    english = app.rebuilt_as

    english.language_dropdown.value = "ru"
    english.on_language_change(None)

    assert i18n.current_language() == "ru" and "Настройки" in all_texts(english.rebuilt_as)


def test_the_saved_language_is_applied_when_the_app_starts(tmp_path):
    from gmagc_desktop.service.search_service import SearchService

    first = SearchService(tmp_path / "data")
    first.load()
    first.set_language("en")

    app, _ = make_app(tmp_path)

    assert i18n.current_language() == "en" and "Settings" in all_texts(app)


def test_a_rebuild_does_not_create_a_new_support_prompt(tmp_path):
    app, _ = make_app(tmp_path, support=True, support_delay=999)
    assert app.support is not None

    app.language_dropdown.value = "en"
    app.on_language_change(None)

    assert app.rebuilt_as.support is None  # повторный показ окна поддержки и счётчик запусков не нужны


def test_the_whole_desktop_interface_is_in_english_after_switching_the_language(tmp_path):
    app, _ = make_app(tmp_path)

    app.language_dropdown.value = "en"
    app.on_language_change(None)

    new = app.rebuilt_as
    everything = " | ".join(t for t in all_texts(new) if t)
    assert "Image search" in everything and "Number of search results" not in everything  # это label, не Text
    assert new.results_count_dropdown.label == "Number of search results"
    assert new.library_text.value == "not chosen" and new.status_label.value == "Index not built"
    assert "Export settings" in everything and "Check the core" in everything
    assert new.pick_photo_button.content == "Choose a photo…" or "Choose a photo…" in everything
