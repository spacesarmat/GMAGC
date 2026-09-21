import time

from gmagc_desktop.service.results import Outcome, Result, SearchOutcome
from gmagc_desktop.ui.texts import history_text, source_text


def outcome(kind=Outcome.FOUND, results=True):
    items = (Result(1, "a.png", "v/a.png", "/lib/v/a.png", 0.812, (), b"x"),) if results else ()
    return SearchOutcome(kind, items, b"p", 3.0)


def stamp(when):
    return time.strftime("%H:%M:%S", time.localtime(when))


def test_source_text_names_the_client_and_the_time():
    assert source_text(1_700_000_000.0, "192.168.1.23") == f"Запрос с телефона 192.168.1.23, {stamp(1_700_000_000.0)}"


def test_history_text_shows_the_best_match_or_the_missing_projection():
    when = 1_700_000_000.0
    assert history_text(when, "192.168.1.23", outcome()) == f"{stamp(when)} · 192.168.1.23 · a.png 81.2%"
    assert history_text(when, "10.0.0.7", outcome(Outcome.NO_PROJECTION, results=False)).endswith("проекция не найдена")
    assert history_text(when, "10.0.0.7", outcome(Outcome.LOW_CONFIDENCE, results=False)).endswith("проекция не найдена")
