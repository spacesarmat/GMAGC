from gmagc_common.protocol import Connection, MatchResponse, ResultItem, Status
from gmagc_common import phone_client as client
from gmagc_common.phone_client import ClientError
from gmagc_common.phone_texts import (
    error_text,
    history_text,
    no_index_note,
    outcome_message,
    score_text,
    share_text,
    status_line,
    zoom_text,
)


def item(rank, name, path, score, copies=()):
    return ResultItem(rank, name, path, score, tuple(copies), b"\x89PNG-thumb")


def sample_response(outcome="found", results=None):
    items = (
        results
        if results is not None
        else (
            item(1, "a.png", "C:\\gobos\\vendor\\a.png", 0.912, copies=("C:\\gobos\\other\\a.png",)),
            item(2, "b.png", "C:\\gobos\\vendor\\b.png", 0.803),
        )
    )
    return MatchResponse("r1", outcome, 12.5, tuple(items), b"\x89PNG-proj")


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
    assert "индекс" in no_index_note()


def test_zoom_text():
    assert zoom_text(1) == "×1.0" and zoom_text(2.0) == "×2.0" and zoom_text(3.25) == "×3.2"


def test_history_text_names_the_top_result_or_says_no_projection():
    assert history_text(sample_response()) == "a.png 91.2%"
    assert history_text(sample_response("no_projection", results=[])) == "проекция не найдена"


def test_share_text_summarizes_the_top_result_or_says_no_projection():
    text = share_text(sample_response())
    assert "a.png (91.2%)" in text and "C:\\gobos\\vendor\\a.png" in text
    assert share_text(sample_response("no_projection", results=[])) == "GMAGC: проекция на фото не найдена"


def test_the_status_line_uses_the_right_word_form_for_the_file_count_in_both_languages():
    from gmagc_common import i18n
    from gmagc_common.protocol import Connection, MatchResponse, ResultItem, Status

    pc = Connection("192.168.1.5", 8765, "ABCD2345")
    one, few, many = (Status(True, n, n, False, 0, 0) for n in (1, 2, 5))

    assert [status_line(pc, s).endswith(word) for s, word in ((one, "файл"), (few, "файла"), (many, "файлов"))] == [True] * 3
    i18n.set_language("en")
    assert status_line(pc, one).endswith("1 file") and status_line(pc, many).endswith("5 files")
