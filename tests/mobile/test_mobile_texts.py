from gmagc_common.protocol import Connection, Status
from gmagc_mobile import client
from gmagc_mobile.client import ClientError
from gmagc_mobile.texts import (
    NO_INDEX_NOTE,
    error_text,
    history_text,
    outcome_message,
    score_text,
    share_text,
    status_line,
    zoom_text,
)
from tests.fakes_mobile import sample_response


def test_each_error_kind_has_a_clear_text():
    assert "одной сети Wi-Fi" in error_text(ClientError(client.UNREACHABLE, "ConnectionRefusedError: x"))
    assert "ConnectionRefusedError" in error_text(ClientError(client.UNREACHABLE, "ConnectionRefusedError: x"))
    assert "Неверный код" in error_text(ClientError(client.UNAUTHORIZED, "неверный код доступа"))
    assert "12 с" in error_text(ClientError(client.RATE_LIMITED, "x", retry_after=12))
    assert "30 с" in error_text(ClientError(client.RATE_LIMITED, "x"))
    assert "индекс" in error_text(ClientError(client.NO_INDEX, "x"))
    assert "прочитать изображение" in error_text(ClientError(client.BAD_IMAGE, "x"))
    assert "слишком большое" in error_text(ClientError(client.TOO_LARGE, "x"))
    assert error_text(ClientError(client.PROTOCOL, "Это не сервер GMAGC")) == "Это не сервер GMAGC"
    assert error_text(ClientError(client.SERVER, "ошибка поиска на ПК")) == "Ошибка на ПК: ошибка поиска на ПК"


def test_outcome_messages():
    assert outcome_message("found") is None
    assert "ненадёжно" in outcome_message("low_confidence")
    assert "переснимите" in outcome_message("no_projection")
    assert outcome_message("something_new") is None


def test_score_is_a_percentage_capped_at_100():
    assert score_text(0.8123) == "81.2%"
    assert score_text(1.7) == "100.0%" and score_text(-1) == "0.0%"


def test_status_line_shows_the_pc_and_the_library_size():
    line = status_line(Connection("192.168.1.5", 8765, "ABCD2345"), Status(True, 11178, 9396, False, 0, 0))

    assert line == "Подключено: 192.168.1.5:8765 · 11\u00a0178 файлов"
    assert "не построен" in status_line(Connection("10.0.0.7", 8766, "ABCD2345"), Status(False, 0, 0, False, 0, 0))
    assert "индексация" in status_line(Connection("10.0.0.7", 8766, "ABCD2345"), Status(True, 5, 5, True, 2, 5))
    assert "индекс" in NO_INDEX_NOTE


def test_zoom_text():
    assert zoom_text(1) == "×1.0" and zoom_text(2.0) == "×2.0" and zoom_text(3.25) == "×3.2"


def test_history_text_names_the_top_result_or_says_no_projection():
    assert history_text(sample_response()) == "a.png 91.2%"
    assert history_text(sample_response("no_projection", results=[])) == "проекция не найдена"


def test_share_text_summarizes_the_top_result_or_says_no_projection():
    text = share_text(sample_response())
    assert "a.png (91.2%)" in text and "C:\\gobos\\vendor\\a.png" in text
    assert share_text(sample_response("no_projection", results=[])) == "GMAGC: проекция на фото не найдена"
