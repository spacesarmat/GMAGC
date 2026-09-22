from gmagc_desktop.service.results import IndexStatus, Outcome
from gmagc_desktop.ui.texts import outcome_message, score_text, status_text


def test_status_text_for_missing_and_built_indexes():
    assert status_text(None) == "Индекс не построен"
    assert status_text(IndexStatus(11178, 9396, 0, 0)) == "11\u00a0178 файлов, 9\u00a0396 семейств"
    assert status_text(IndexStatus(6, 5, 1, 2)) == (
        "6 файлов, 5 семейств, пропущено 1, нечитаемо сейчас 2 (повторю при обновлении)"
    )
    assert status_text(IndexStatus(6, 5, 0, 0, stale=True)) == (
        "6 файлов, 5 семейств. Библиотека изменилась — обновите индекс"
    )


def test_score_is_a_clamped_percentage():
    assert score_text(0.873) == "87.3%"
    assert score_text(1.0004) == "100.0%"
    assert score_text(-0.1) == "0.0%"


def test_outcome_messages():
    assert outcome_message(Outcome.FOUND) is None
    assert "ниже 72%" in outcome_message(Outcome.LOW_CONFIDENCE)
    assert "переснимите" in outcome_message(Outcome.NO_PROJECTION)
