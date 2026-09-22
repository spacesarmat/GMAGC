import asyncio

import flet as ft

from gmagc_common.support import AUTHOR_TELEGRAM_URL, CHANNEL_URL, REMIND_AFTER_SECONDS, SUPPORT_URL
from gmagc_mobile.app import MobileApp
from gmagc_mobile.camera import CameraController
from gmagc_mobile.store import ConnectionStore
from gmagc_mobile.support import KEY_LAST, KEY_LAUNCHES, KEY_MUTED, SupportPrompt
from tests.fakes import FakeClipboard, FakePicker, StubPage, walk
from tests.fakes_mobile import FakeCameraApi, FakeLauncher, FakePermission, FakePrefs, Script

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


def test_the_channel_link_opens_the_gmagc_channel():
    prompt, _, launcher, _ = make()

    run(prompt.on_open_channel(None))

    assert launcher.opened == [CHANNEL_URL] and CHANNEL_URL == "https://t.me/gmagclight"


# ---- встроено в экран (ссылки нужны сразу на трёх экранах) ------------------------------------------
def make_app(support_flag=True):
    page = StubPage()
    prefs = FakePrefs()
    launcher = FakeLauncher()
    app = MobileApp(
        page,
        ConnectionStore(prefs),
        CameraController(FakeCameraApi(), FakePermission(), settle_seconds=0, retry_seconds=0),
        preview=ft.Container(),
        picker=FakePicker(),
        clipboard=FakeClipboard(),
        client_factory=Script().factory,
        marker_seconds=0,
        mount_seconds=0,
        support=support_flag,
        launcher=launcher,
        prefs=prefs,
        tracker=None,
    )
    app.build()
    return app, launcher


def link_texts(view):
    return [c.content.value for c in walk(view) if isinstance(c, ft.TextButton) and isinstance(c.content, ft.Text)]


def test_support_links_appear_on_the_about_screen():
    """Ссылки поддержки собраны в одном месте («О программе»), открывается с экранов подключения и камеры."""
    app, _ = make_app()

    texts = link_texts(app.about_view)
    assert "Поддержать автора" in texts and "Telegram автора" in texts and "Канал GMAGC" in texts


def test_support_links_do_not_crowd_the_connect_or_camera_screens():
    app, _ = make_app()

    labels = {"Поддержать автора", "Telegram автора", "Канал GMAGC"}
    assert not labels & set(link_texts(app.connect_view))
    assert not labels & set(link_texts(app.camera_view))


def test_the_channel_link_opens_the_channel():
    app, launcher = make_app()

    button = next(c for c in walk(app.about_view) if isinstance(c, ft.TextButton) and c.content.value == "Канал GMAGC")
    run(button.on_click(None))

    assert launcher.opened == [CHANNEL_URL]


def test_no_support_links_when_support_is_disabled():
    app, _ = make_app(support_flag=False)

    labels = {"Поддержать автора", "Telegram автора", "Канал GMAGC"}
    assert not labels & set(link_texts(app.about_view))
