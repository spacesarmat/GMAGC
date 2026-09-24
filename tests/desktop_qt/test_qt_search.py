"""Экран «Поиск» на Qt: фото, вставка, поправки, карточки результатов, «это не то»."""

import cv2
import numpy as np
import pytest

from gmagc_desktop.qt.controller import AppController, InlineExecutor
from gmagc_desktop.qt.screens.search import SearchScreen
from gmagc_desktop.qt.widgets import FlowLayout
from gmagc_desktop.service.results import Outcome, SearchOutcome


@pytest.fixture()
def photo_file(tmp_path, photo_jpeg):
    path = tmp_path / "photo.jpg"
    path.write_bytes(photo_jpeg)
    return path


def make_screen(service, picks=None, clipboard=None):
    revealed, copied = [], []
    controller = AppController(
        service, InlineExecutor(), reveal=lambda p: revealed.append(p) or True, copy_text=copied.append
    )
    queue = list(picks or [])
    screen = SearchScreen(
        controller,
        pick_image=lambda _parent, _title: queue.pop(0) if queue else "",
        clipboard=clipboard or (lambda: (None, [])),
    )
    screen.resize(1000, 700)
    screen.show()
    return screen, controller, revealed, copied


def test_a_photo_from_a_file_gives_result_cards_metrics_and_previews(qapp, service, photo_file):
    screen, controller, _, _ = make_screen(service, picks=[str(photo_file)])

    screen.pick_button.click()

    assert len(screen.cards) == 5 and screen.summary_label.text() == "5 результатов"
    assert screen.photo_box.isVisible() and not screen.photo_label.pixmap().isNull()
    assert screen.photo_adjust_panel.isVisible()
    assert screen.cards[0].result.rank == 1 and screen.cards[0].name_label.full_text() in {"ell.png", "ell_small.png"}
    assert screen.metric_time.text().endswith("ms") and screen.metric_score.text().endswith("%")
    assert screen.metric_files.text() == "5" or int(screen.metric_files.text().replace(" ", "")) > 0
    assert screen.pick_button.isEnabled() and not controller.busy


def test_choosing_nothing_does_not_search(qapp, service):
    screen, controller, _, _ = make_screen(service, picks=[""])

    screen.pick_button.click()

    assert screen.cards == [] and controller.last_query_photo is None


def test_searching_without_a_library_shows_a_banner_and_no_cards(qapp, tmp_path, photo_file):
    from gmagc_desktop.service.search_service import SearchService

    empty = SearchService(tmp_path / "empty-data")
    empty.load()
    screen, controller, _, _ = make_screen(empty, picks=[str(photo_file)])
    banners = []
    controller.banner_shown.connect(lambda text, error: banners.append((text, error)))

    screen.pick_button.click()

    assert banners == [("Сначала выберите папку библиотеки и постройте индекс", True)] and screen.cards == []


def test_an_unreadable_file_and_a_broken_image_are_reported(qapp, service, tmp_path):
    screen, controller, _, _ = make_screen(service, picks=[str(tmp_path / "gone.jpg"), str(tmp_path / "bad.jpg")])
    (tmp_path / "bad.jpg").write_bytes(b"not an image")
    banners = []
    controller.banner_shown.connect(lambda text, error: banners.append(text))

    screen.pick_button.click()
    screen.pick_button.click()

    assert banners[0].startswith("Не удалось прочитать файл") and banners[1].startswith("Не удалось прочитать фото")
    assert screen.cards == [] and not controller.busy


def test_paste_takes_a_clipboard_image_then_an_image_file_and_otherwise_explains(qapp, service, photo_file, photo_jpeg):
    contents = [(photo_jpeg, []), (None, ["notes.txt", str(photo_file)]), (None, ["notes.txt"])]
    screen, controller, _, _ = make_screen(service, clipboard=lambda: contents.pop(0))
    banners = []
    controller.banner_shown.connect(lambda text, error: banners.append((text, error)))

    screen.paste_button.click()
    assert len(screen.cards) == 5
    screen.paste_button.click()
    assert len(screen.cards) == 5
    screen.paste_button.click()

    assert banners[-1] == ("В буфере обмена нет картинки или файла-изображения", True)


def test_moving_a_slider_updates_previews_and_releasing_it_searches_again(qapp, service, photo_file):
    screen, controller, _, _ = make_screen(service, picks=[str(photo_file)])
    screen.pick_button.click()
    searches = []
    original = controller.rerun_with_adjustments
    controller.rerun_with_adjustments = lambda: (searches.append(1), original())[1]  # noqa: E731
    screen.photo_adjust_panel.committed.disconnect()
    screen.photo_adjust_panel.committed.connect(controller.rerun_with_adjustments)

    screen.photo_adjust_panel.brightness.setValue(40)

    assert controller.photo_adjust == (40.0, 1.0, 0.0)
    assert screen.photo_adjust_panel.brightness_label.text() == "Яркость: +40"

    screen.photo_adjust_panel.committed.emit()
    assert searches == [1] and len(screen.cards) == 5


def test_projection_sliders_change_the_projection_adjustment_only(qapp, service, photo_file):
    screen, controller, _, _ = make_screen(service, picks=[str(photo_file)])
    screen.pick_button.click()
    assert screen.projection_adjust_panel.isVisible() and screen.projection_box.isVisible()

    screen.projection_adjust_panel.contrast.setValue(15)
    screen.projection_adjust_panel.exposure.setValue(-5)

    assert controller.projection_adjust == (0.0, 1.5, -0.5) and controller.photo_adjust == (0.0, 1.0, 0.0)
    assert screen.projection_adjust_panel.contrast_label.text() == "Контраст: 1.5×"
    assert screen.projection_adjust_panel.exposure_label.text() == "Экспозиция: -0.5 EV"


def test_reset_puts_the_sliders_back_and_searches_again(qapp, service, photo_file):
    screen, controller, _, _ = make_screen(service, picks=[str(photo_file)])
    screen.pick_button.click()
    screen.photo_adjust_panel.brightness.setValue(-30)

    screen.photo_adjust_panel.reset_button.click()

    assert controller.photo_adjust == (0.0, 1.0, 0.0) and screen.photo_adjust_panel.brightness.value() == 0
    assert screen.photo_adjust_panel.brightness_label.text() == "Яркость: 0" and len(screen.cards) == 5


def test_a_new_photo_resets_all_adjustments(qapp, service, photo_file):
    screen, controller, _, _ = make_screen(service, picks=[str(photo_file), str(photo_file)])
    screen.pick_button.click()
    screen.photo_adjust_panel.brightness.setValue(25)
    screen.projection_adjust_panel.exposure.setValue(10)

    screen.pick_button.click()

    assert controller.photo_adjust == (0.0, 1.0, 0.0) and controller.projection_adjust == (0.0, 1.0, 0.0)
    assert screen.photo_adjust_panel.brightness.value() == 0 and screen.projection_adjust_panel.exposure.value() == 0


def test_a_flat_photo_reports_no_projection_and_hides_the_projection_panel(qapp, service, tmp_path):
    ok, encoded = cv2.imencode(".png", np.full((480, 640, 3), 90, np.uint8))
    path = tmp_path / "flat.png"
    path.write_bytes(encoded.tobytes())
    screen, controller, _, _ = make_screen(service, picks=[str(path)])
    banners = []
    controller.banner_shown.connect(lambda text, error: banners.append((text, error)))

    screen.pick_button.click()

    assert banners[-1][1] is True and "Проекция на фото не найдена" in banners[-1][0]
    assert screen.cards == [] and not screen.projection_box.isVisible() and not screen.projection_adjust_panel.isVisible()


def test_clicking_a_card_copies_the_path_and_the_buttons_reveal_the_file(qapp, service, photo_file):
    screen, controller, revealed, copied = make_screen(service, picks=[str(photo_file)])
    screen.pick_button.click()
    card = screen.cards[0]

    card.clicked.emit(card.result.full_path)
    card.reveal_button.click()

    assert copied and copied[0].endswith(card.result.name)
    assert screen.copy_label.isVisible() and screen.copy_label.text().startswith("Путь скопирован: ")
    assert revealed == [card.result.full_path]


def test_this_is_not_it_remembers_the_correct_file_and_searches_again(qapp, service, photo_file, tmp_path):
    screen, controller, _, _ = make_screen(service, picks=[str(photo_file)])
    screen.pick_button.click()
    wrong = screen.cards[0].result
    right = screen.cards[-1].result
    screen._pick_image = lambda _parent, _title: right.full_path
    banners = []
    controller.banner_shown.connect(lambda text, error: banners.append((text, error)))

    screen.cards[0].wrong_button.click()

    assert ("Запомнено: при похожих запросах теперь будет показан верный файл", False) in banners
    assert screen.cards[0].result.rel_path != wrong.rel_path or screen.cards[0].result.rel_path == right.rel_path


def test_a_failed_correction_shows_the_reason(qapp, service, photo_file, tmp_path):
    screen, controller, _, _ = make_screen(service, picks=[str(photo_file)])
    screen.pick_button.click()
    screen._pick_image = lambda _parent, _title: str(tmp_path / "not-in-library.png")
    banners = []
    controller.banner_shown.connect(lambda text, error: banners.append((text, error)))

    screen.cards[0].wrong_button.click()

    assert banners and banners[-1][1] is True


def test_buttons_are_disabled_while_busy(qapp, service):
    screen, controller, _, _ = make_screen(service)

    controller.set_busy(True)

    assert not screen.pick_button.isEnabled() and not screen.paste_button.isEnabled()
    controller.set_busy(False)
    assert screen.pick_button.isEnabled()


def test_a_phone_request_is_shown_with_its_source_and_result(qapp, service, photo_jpeg):
    screen, controller, _, _ = make_screen(service)
    outcome = service.search_image_bytes(photo_jpeg, top_n=3)

    controller.show_phone_record(photo_jpeg, outcome, "Запрос с телефона 10.0.0.5, 12:00:00")

    assert screen.source_label.isVisible() and "10.0.0.5" in screen.source_label.text()
    assert len(screen.cards) == 3 and controller.last_score == outcome.results[0].score


def test_results_wrap_into_rows_by_the_available_width(qapp, service, photo_file):
    screen, controller, _, _ = make_screen(service, picks=[str(photo_file)])
    screen.pick_button.click()
    layout = screen.results_layout
    assert isinstance(layout, FlowLayout)

    wide = layout.heightForWidth(1300)
    narrow = layout.heightForWidth(430)

    assert narrow > wide  # в узкой панели карточки переносятся на новые строки


def test_the_outcome_message_for_low_confidence_is_a_warning_banner(qapp, service):
    screen, controller, _, _ = make_screen(service)
    banners = []
    controller.banner_shown.connect(lambda text, error: banners.append((text, error)))

    controller.show_outcome(SearchOutcome(Outcome.LOW_CONFIDENCE, (), None, 12.0))

    assert banners and banners[-1][1] is False and "ниже 72%" in banners[-1][0]
    assert screen.metric_time.text() == "12 ms" and screen.metric_score.text() == "—"
