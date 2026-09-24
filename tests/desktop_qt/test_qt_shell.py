"""Каркас Qt-приложения: тема, контроллер (индексация), экран «Библиотека», главное окно."""

import pytest
from PySide6.QtWidgets import QApplication

from gmagc_desktop.qt.app import build_window
from gmagc_desktop.qt.controller import AppController, InlineExecutor
from gmagc_desktop.qt.icons import icon
from gmagc_desktop.qt.screens.library import LibraryScreen
from gmagc_desktop.qt.theme import BASE_FONT_PX, LARGE_FONT_PX, font_px, stylesheet
from gmagc_desktop.service.search_service import SearchService
from tests.fixtures import write_library


@pytest.fixture()
def empty_service(tmp_path):
    service = SearchService(tmp_path / "data")
    service.load()
    return service


@pytest.fixture()
def library_dir(tmp_path):
    folder = tmp_path / "lib"
    folder.mkdir()
    write_library(folder)
    return folder


def test_the_stylesheet_uses_the_desktop_palette_and_scales_with_large_text():
    normal, large = stylesheet(False), stylesheet(True)

    assert "#090c10" in normal and "#36c5ef" in normal  # фон и акцент палитры ПК
    assert f"font-size: {BASE_FONT_PX}px" in normal and f"font-size: {LARGE_FONT_PX}px" in large
    assert font_px(True) > font_px(False)


def test_icons_are_drawn_and_an_unknown_icon_is_empty(qapp):
    assert not icon("search", "#ffffff").isNull()
    assert icon("no_such_icon", "#ffffff").isNull()


def test_indexing_reports_progress_and_finishes_with_a_status(qapp, empty_service, library_dir):
    controller = AppController(empty_service, InlineExecutor())
    progress, busy, changed = [], [], []
    controller.progress.connect(lambda done, total: progress.append((done, total)))
    controller.busy_changed.connect(lambda b, i: busy.append((b, i)))
    controller.library_changed.connect(lambda: changed.append(1))

    controller.choose_library(library_dir)

    assert progress and progress[-1][0] == progress[-1][1]
    assert busy[0] == (True, True) and busy[-1] == (False, False)
    assert changed and controller.status_line != "Индекс не построен"
    assert empty_service.status() is not None and not controller.busy


def test_indexing_without_a_library_shows_a_hint_and_does_not_start(qapp, empty_service):
    controller = AppController(empty_service, InlineExecutor())
    banners = []
    controller.banner_shown.connect(lambda text, error: banners.append((text, error)))

    controller.start_index()

    assert banners == [("Сначала выберите папку библиотеки и постройте индекс", True)] and not controller.busy


def test_a_cancelled_indexing_says_so_without_an_error(qapp, empty_service, library_dir, monkeypatch):
    from gmagc_desktop.library.index import IndexCancelled

    controller = AppController(empty_service, InlineExecutor())
    empty_service.set_library(library_dir)
    banners = []
    controller.banner_shown.connect(lambda text, error: banners.append((text, error)))

    def cancelled(progress=None, cancel=None):
        raise IndexCancelled

    monkeypatch.setattr(empty_service, "build_index", cancelled)

    controller.start_index()

    assert ("Индексация отменена", False) in banners and not controller.busy


def test_a_second_start_while_busy_is_ignored(qapp, empty_service, library_dir):
    controller = AppController(empty_service, InlineExecutor())
    empty_service.set_library(library_dir)
    controller.set_busy(True, indexing=True)
    started = []
    controller.executor = type("Spy", (), {"submit": lambda self, task: started.append(task)})()

    controller.start_index()

    assert started == []


def test_the_library_screen_shows_the_state_and_starts_indexing_after_choosing_a_folder(
    qapp, empty_service, library_dir
):
    controller = AppController(empty_service, InlineExecutor())
    screen = LibraryScreen(controller, pick_directory=lambda _parent: str(library_dir))
    assert screen.path_label.text() == "не выбрана" and screen.status_label.text() == "Индекс не построен"

    screen.choose_button.click()

    assert screen.path_label.text() == str(library_dir)
    assert "гобо" in screen.status_label.text() or screen.status_label.text() != "Индекс не построен"
    assert not screen.progress_bar.isVisibleTo(screen) and screen.choose_button.isEnabled()


def test_choosing_nothing_changes_nothing(qapp, empty_service):
    controller = AppController(empty_service, InlineExecutor())
    screen = LibraryScreen(controller, pick_directory=lambda _parent: "")

    screen.choose_button.click()

    assert empty_service.settings.library_dir == "" and not controller.busy


def test_the_library_screen_disables_buttons_and_shows_progress_while_indexing(qapp, empty_service):
    controller = AppController(empty_service, InlineExecutor())
    screen = LibraryScreen(controller)
    screen.show()

    controller.set_busy(True, indexing=True)
    controller.progress.emit(3, 10)

    assert not screen.choose_button.isEnabled() and not screen.rebuild_button.isEnabled()
    assert screen.progress_bar.isVisible() and screen.cancel_button.isVisible()
    assert screen.progress_bar.value() == 3 and "3 из 10" in screen.progress_label.text()

    controller.set_busy(False)
    assert screen.choose_button.isEnabled() and not screen.progress_bar.isVisible()


def test_the_cancel_button_asks_the_controller_to_stop(qapp, empty_service):
    controller = AppController(empty_service, InlineExecutor())
    screen = LibraryScreen(controller)
    screen.show()
    controller.set_busy(True, indexing=True)

    screen.cancel_button.click()

    assert controller._cancel is True


def test_the_main_window_navigates_between_screens_and_updates_the_breadcrumb(qapp, empty_service):
    window = build_window(empty_service, InlineExecutor())

    assert window.current == "search" and window.breadcrumb.text() == "GMAGC / Поиск гобо"
    window.nav_buttons["library"].click()

    assert window.current == "library" and window.stack.currentWidget() is window.screens["library"]
    assert window.breadcrumb.text() == "GMAGC / Библиотека"
    assert window.nav_buttons["library"].isChecked() and not window.nav_buttons["search"].isChecked()


def test_the_onboarding_hint_shows_until_a_library_is_chosen_and_can_be_dismissed(qapp, empty_service, library_dir):
    window = build_window(empty_service, InlineExecutor())
    window.show()
    assert window.onboarding.isVisible()

    window.onboarding.goto_button.click()
    assert window.current == "library" and not window.onboarding.isVisible()  # только на экране поиска
    window.show_screen("search")
    assert window.onboarding.isVisible()

    window.onboarding.dismiss_button.click()
    window.show_screen("library")
    window.show_screen("search")
    assert not window.onboarding.isVisible()


def test_choosing_a_library_hides_the_hint_and_updates_the_statusbar(qapp, empty_service, library_dir):
    window = build_window(empty_service, InlineExecutor(), pick_directory=lambda _parent: str(library_dir))
    window.show()
    assert window.statusbar_index.text() == "INDEX: NOT BUILT"

    window.screens["library"].choose_button.click()

    assert not window.onboarding.isVisible() and window.statusbar_index.text().startswith("INDEX: ")
    assert "NOT BUILT" not in window.statusbar_index.text()


def test_banners_appear_in_the_window_with_error_and_info_styles(qapp, empty_service):
    window = build_window(empty_service, InlineExecutor())
    window.show()

    window.controller.show_banner("Что-то сломалось", error=True)
    assert window.banner.isVisible() and window.banner.label.text() == "Что-то сломалось"
    assert window.banner.property("error") == "true"

    window.controller.show_banner("Сведение", error=False)
    assert window.banner.property("error") == "false"

    window.controller.hide_banner()
    assert not window.banner.isVisible()


def test_the_application_object_exists_for_widget_tests(qapp):
    assert QApplication.instance() is qapp
