import pytest
from PySide6.QtCore import QSettings

from gmagc_common import i18n
from gmagc_common.support import LATER, NEVER, SUPPORT, SUPPORT_URL
from gmagc_common.updates import Asset, ReleaseInfo, UpdateCheckError
from gmagc_phone.about import VERSION
from gmagc_phone.app import build_window
from gmagc_phone.camera import FakeCamera
from gmagc_phone.extras import SupportPrompt, UpdateBar, UpdateController
from gmagc_phone.settings import PhoneSettings
from gmagc_phone.tasks import InlineExecutor

NOW = 1_000_000.0


@pytest.fixture(autouse=True)
def russian():
    i18n.set_language("ru")


@pytest.fixture
def settings(tmp_path):
    return PhoneSettings(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))


def release(version="9.0.0", with_apk=True):
    assets = (Asset(f"GMAGC-android-{version}.apk", "https://github.com/x/a.apk", 5),) if with_apk else ()
    return ReleaseInfo(version, f"v{version}", "", "https://github.com/x/releases", assets)


def controller(settings, fetch, opened=None, quits=None):
    return UpdateController(
        settings,
        InlineExecutor(),
        (opened if opened is not None else []).append,
        lambda: (quits if quits is not None else []).append(1),
        fetch=fetch,
        now=lambda: NOW,
    )


def test_new_release_shows_bar_and_downloads_apk(qtbot, settings):
    opened, quits = [], []
    updates = controller(settings, lambda v: release(), opened, quits)
    bar = UpdateBar(updates)
    qtbot.addWidget(bar)
    updates.startup()
    assert bar.isVisibleTo(bar.parentWidget()) or not bar.isHidden()
    assert "9.0.0" in bar.text.text()
    updates.download()
    assert opened == ["https://github.com/x/a.apk"] and quits == [1]


def test_release_without_apk_opens_page(settings):
    opened = []
    updates = controller(settings, lambda v: release(with_apk=False), opened)
    updates.startup()
    updates.download()
    assert opened == ["https://github.com/x/releases"]


def test_check_is_rate_limited_and_skip_is_remembered(settings):
    calls = []

    def fetch(version):
        calls.append(1)
        return release()

    updates = controller(settings, fetch)
    updates.startup()
    updates.skip()
    updates.startup()  # прошло меньше суток
    assert len(calls) == 1
    settings.save_last_check(0.0)
    seen = []
    updates.notice_changed.connect(seen.append)
    updates.startup()
    assert seen == []  # версия пропущена
    updates.check(force=True)
    assert seen and seen[0].version == "9.0.0"


def test_up_to_date_message_only_on_manual_check(settings):
    updates = controller(settings, lambda v: None)
    messages = []
    updates.status_changed.connect(messages.append)
    updates.startup()
    assert messages == [""]
    settings.save_last_check(0.0)
    updates.check(force=True)
    assert VERSION in messages[-1]


def test_network_errors_are_silent_unless_manual(settings):
    def broken(version):
        raise UpdateCheckError("нет сети")

    updates = controller(settings, broken)
    messages = []
    updates.status_changed.connect(messages.append)
    updates.startup()
    assert messages == [""]
    updates.check(force=True)
    assert messages[-1] == "нет сети"


def test_support_prompt_schedule(settings):
    answers = iter([LATER, SUPPORT])
    opened = []

    def make(now):
        return SupportPrompt(settings, None, opened.append, now=lambda: now, delay=0, ask=lambda parent: next(answers))

    for _ in range(4):
        make(NOW).start()
    assert opened == []
    make(NOW).start()  # пятый запуск — просьба, ответ «Позже»
    assert settings.load_support_state().last_ask == NOW
    make(NOW + 1).start()  # ещё рано
    make(NOW + 31 * 24 * 3600).start()  # через 30 суток снова; ответ «Поддержать» → ссылка и больше не спрашивать
    assert opened == [SUPPORT_URL]
    assert settings.load_support_state().muted


def test_support_prompt_never(settings):
    for _ in range(5):
        SupportPrompt(settings, None, lambda u: None, now=lambda: NOW, delay=0, ask=lambda p: NEVER).start()
    assert settings.load_support_state().muted


def test_support_prompt_waits_when_busy(settings):
    asked = []
    for _ in range(5):
        SupportPrompt(settings, None, lambda u: None, now=lambda: NOW, delay=0, busy=lambda: True,
                      ask=lambda p: asked.append(1) or LATER).start()
    assert asked == []


def test_settings_screen_gets_update_button(qtbot, settings):
    window = build_window(settings, backend=FakeCamera(), executor=InlineExecutor())
    qtbot.addWidget(window)
    updates = controller(settings, lambda v: None)
    window.screens["settings"].add_update_controls(updates)
    assert window.screens["settings"].layout_.count() >= 5
