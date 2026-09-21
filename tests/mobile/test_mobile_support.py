import asyncio

from gmagc_common.support import AUTHOR_TELEGRAM_URL, REMIND_AFTER_SECONDS, SUPPORT_URL
from gmagc_mobile.support import KEY_LAST, KEY_LAUNCHES, KEY_MUTED, SupportPrompt
from tests.fakes import StubPage
from tests.fakes_mobile import FakeLauncher, FakePrefs

NOW = 1_800_000_000.0


def run(coroutine):
    return asyncio.run(coroutine)


def make(prefs=None, busy=False):
    prefs = prefs if prefs is not None else FakePrefs()
    launcher, page = FakeLauncher(), StubPage()
    prompt = SupportPrompt(prefs, launcher, page, now=lambda: NOW, delay=0, busy=lambda: busy)
    return prompt, prefs, launcher, page


def test_the_dialog_appears_on_the_fifth_launch_only():
    for launch in range(1, 5):
        prompt, prefs, _, page = make(FakePrefs({KEY_LAUNCHES: launch - 1}))
        run(prompt.startup())
        assert prefs.data[KEY_LAUNCHES] == launch and page.dialogs == []

    prompt, prefs, _, page = make(FakePrefs({KEY_LAUNCHES: 4}))
    run(prompt.startup())

    assert prefs.data[KEY_LAUNCHES] == 5 and len(page.dialogs) == 1
    assert page.dialogs[0].title.value == "Поддержать автора"


def test_support_opens_the_link_and_mutes():
    prompt, prefs, launcher, page = make(FakePrefs({KEY_LAUNCHES: 4}))
    run(prompt.startup())

    run(prompt.on_support(None))

    assert launcher.opened == [SUPPORT_URL] and page.dialogs == []
    assert prefs.data[KEY_MUTED] is True and prefs.data[KEY_LAST] == NOW


def test_later_and_never():
    prompt, prefs, _, page = make(FakePrefs({KEY_LAUNCHES: 4}))
    run(prompt.startup())
    run(prompt.on_later(None))
    assert page.dialogs == [] and prefs.data[KEY_LAST] == NOW and prefs.data.get(KEY_MUTED) is not True

    prompt, prefs, _, page = make(FakePrefs({KEY_LAUNCHES: 5, KEY_LAST: NOW - REMIND_AFTER_SECONDS}))
    run(prompt.startup())
    assert len(page.dialogs) == 1
    run(prompt.on_never(None))
    assert prefs.data[KEY_MUTED] is True


def test_a_muted_recent_or_busy_user_is_left_alone_and_a_broken_storage_is_tolerated():
    cases = (
        (FakePrefs({KEY_LAUNCHES: 50, KEY_MUTED: True}), False),
        (FakePrefs({KEY_LAUNCHES: 50, KEY_LAST: NOW - 60}), False),
        (FakePrefs({KEY_LAUNCHES: 9}), True),
    )
    for prefs, busy in cases:
        prompt, _, _, page = make(prefs, busy=busy)
        run(prompt.startup())
        assert page.dialogs == []

    prompt, _, _, page = make(FakePrefs(fail=True))
    run(prompt.startup())
    assert page.dialogs == []


def test_the_permanent_link_opens_the_page_without_touching_the_schedule():
    prompt, prefs, launcher, _ = make(FakePrefs({KEY_LAUNCHES: 1}))

    run(prompt.on_open_link(None))

    assert launcher.opened == [SUPPORT_URL] and KEY_LAST not in prefs.data and KEY_MUTED not in prefs.data


def test_the_telegram_link_opens_the_authors_account():
    prompt, _, launcher, _ = make()

    run(prompt.on_open_telegram(None))

    assert launcher.opened == [AUTHOR_TELEGRAM_URL]
