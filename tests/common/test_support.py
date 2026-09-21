import pytest

from gmagc_common.support import (
    AUTHOR_TELEGRAM_URL,
    FIRST_ASK_LAUNCH,
    LATER,
    NEVER,
    REMIND_AFTER_SECONDS,
    SUPPORT,
    SUPPORT_URL,
    SupportState,
    after_answer,
    register_launch,
    should_ask,
)

NOW = 1_800_000_000.0


def launched(times):
    state = SupportState()
    for _ in range(times):
        state = register_launch(state)
    return state


def test_the_links_are_the_authors_donation_page_and_telegram():
    assert SUPPORT_URL == "https://boosty.to/djmaker/donate"
    assert AUTHOR_TELEGRAM_URL == "https://t.me/Andy_bum"


def test_launches_are_counted_and_the_first_ask_waits_for_the_fifth_launch():
    assert register_launch(SupportState()).launches == 1
    assert not should_ask(launched(FIRST_ASK_LAUNCH - 1), NOW)
    assert should_ask(launched(FIRST_ASK_LAUNCH), NOW)
    assert should_ask(launched(FIRST_ASK_LAUNCH + 10), NOW)


def test_later_postpones_the_next_ask_by_thirty_days():
    state = after_answer(launched(5), NOW, LATER)

    assert state.last_ask == NOW and state.muted is False
    assert not should_ask(state, NOW + REMIND_AFTER_SECONDS - 1)
    assert should_ask(state, NOW + REMIND_AFTER_SECONDS)


@pytest.mark.parametrize("answer", [SUPPORT, NEVER])
def test_support_and_never_stop_the_asking_for_good(answer):
    state = after_answer(launched(5), NOW, answer)

    assert state.muted is True and state.last_ask == NOW
    assert not should_ask(state, NOW + 10 * REMIND_AFTER_SECONDS)


def test_a_clock_that_went_back_asks_again_and_an_unknown_answer_is_an_error():
    state = after_answer(launched(5), NOW, LATER)
    assert should_ask(state, NOW - 100)
    with pytest.raises(ValueError):
        after_answer(state, NOW, "maybe")
