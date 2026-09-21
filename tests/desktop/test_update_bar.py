import threading
from types import SimpleNamespace

from gmagc_common.updates import ReleaseInfo, UpdateCheckError
from gmagc_desktop.about import VERSION
from gmagc_desktop.service.search_service import SearchService
from gmagc_desktop.ui import update_bar as update_bar_module
from gmagc_desktop.ui.update_bar import UpdateBar
from gmagc_desktop.update.installer import InstallError
from gmagc_desktop.update.manager import UpdateOffer
from tests.fakes import FakeUpdates, StubPage
from tests.updates_stub import release_json


def offer(can_install=True, reason="", version="0.9.0"):
    release = ReleaseInfo.from_api(release_json(version, "https://example.invalid"))
    return UpdateOffer(release, can_install, reason)


def make(tmp_path, updates, **options):
    service = SearchService(tmp_path / "data")
    service.load()
    opened, quits = [], []
    page = StubPage()
    bar = UpdateBar(
        page,
        service,
        updates,
        open_url=opened.append,
        quit_app=lambda: quits.append(1),
        delay=0,
        **options,
    )
    return bar, service, page, opened, quits


def test_the_startup_check_cleans_up_and_shows_a_newer_version(tmp_path):
    updates = FakeUpdates(offer())
    bar, _, _, _, _ = make(tmp_path, updates)

    bar.start()

    assert updates.cleaned == 1 and updates.checks == [False]
    assert bar.container.visible and bar.text.value == f"Доступна версия 0.9.0 (у вас {VERSION})"
    assert bar.now_button.visible and bar.skip_button.visible and bar.page_button.visible
    assert not bar.note.visible and not bar.progress.visible and not bar.cancel_button.visible


def test_a_disabled_check_does_nothing_at_startup(tmp_path):
    updates = FakeUpdates(offer())
    bar, service, _, _, _ = make(tmp_path, updates)
    service.set_check_updates(False)

    bar.start()

    assert updates.checks == [] and updates.cleaned == 0 and not bar.container.visible


def test_no_newer_version_keeps_the_bar_hidden_and_a_failed_background_check_is_silent(tmp_path):
    bar, _, _, _, _ = make(tmp_path, FakeUpdates(offer=None))
    bar.start()
    assert not bar.container.visible and bar.status.value == ""

    bar, _, _, _, _ = make(tmp_path, FakeUpdates(check_error=UpdateCheckError("Нет связи с GitHub")))
    bar.start()
    assert not bar.container.visible and bar.status.value == ""

    bar, _, _, _, _ = make(tmp_path, FakeUpdates(check_error=RuntimeError("неожиданно")))
    bar.start()
    assert not bar.container.visible and bar.status.value == ""


def test_a_manual_check_reports_every_outcome(tmp_path):
    bar, _, _, _, _ = make(tmp_path, FakeUpdates(offer=None))
    bar.on_check(None)
    assert bar.status.value == f"Установлена последняя версия ({VERSION})"

    bar, _, _, _, _ = make(tmp_path, FakeUpdates(check_error=UpdateCheckError("Нет связи с GitHub")))
    bar.on_check(None)
    assert bar.status.value == "Нет связи с GitHub"

    bar, _, _, _, _ = make(tmp_path, FakeUpdates(check_error=RuntimeError("сбой")))
    bar.on_check(None)
    assert "Ошибка проверки обновлений: сбой" in bar.status.value

    updates = FakeUpdates(offer())
    bar, _, _, _, _ = make(tmp_path, updates)
    bar.on_check(None)
    assert updates.checks == [True] and bar.container.visible and bar.status.value == ""


def test_an_offer_that_cannot_be_installed_shows_why_and_only_offers_the_release_page(tmp_path):
    bar, _, _, opened, _ = make(tmp_path, FakeUpdates(offer(False, "Нет прав на запись в папку приложения")))

    bar.start()

    assert bar.note.visible and "Нет прав на запись" in bar.note.value
    assert not bar.now_button.visible and bar.page_button.content.value == "Открыть страницу релиза"
    bar.on_release_page(None)
    assert opened == ["https://example.invalid/releases/tag/v0.9.0"]


def test_the_release_notes_button_opens_the_release_page(tmp_path):
    bar, _, _, opened, _ = make(tmp_path, FakeUpdates(offer()))
    bar.start()

    assert bar.page_button.content.value == "Что нового"
    bar.on_release_page(None)

    assert opened == ["https://example.invalid/releases/tag/v0.9.0"]


def test_skipping_remembers_the_version_and_hides_the_bar(tmp_path):
    updates = FakeUpdates(offer())
    bar, _, _, _, _ = make(tmp_path, updates)
    bar.start()

    bar.on_skip(None)

    assert updates.skipped == ["0.9.0"] and not bar.container.visible


def test_installing_shows_progress_and_quits_the_app_when_done(tmp_path):
    updates = FakeUpdates(offer())
    bar, _, _, _, quits = make(tmp_path, updates)
    bar.start()
    seen = []
    original = updates.install

    def spy(offer_, progress=None, cancel=None):
        seen.append((bar.now_button.disabled, bar.progress.visible, bar.cancel_button.visible))
        return original(offer_, progress=progress, cancel=cancel)

    updates.install = spy

    bar.on_update_now(None)

    assert seen == [(True, True, True)] and len(updates.installs) == 1
    assert bar.progress.value == 1.0 and "перезапуск" in bar.text.value.lower() and quits == [1]


def test_a_progress_message_shows_megabytes(tmp_path):
    updates = FakeUpdates(offer())
    updates.progress_steps = ((5_000_000, 10_000_000),)
    bar, _, _, _, _ = make(tmp_path, updates)
    bar.start()
    texts = []
    updates.during_install = lambda: texts.append(bar.note.value)

    bar.on_update_now(None)

    assert texts == ["Скачивание: 5 из 10 МБ"]


def test_a_failed_installation_shows_the_reason_and_the_fallback_and_keeps_running(tmp_path):
    updates = FakeUpdates(offer(), install_error=InstallError("Контрольная сумма не совпала"))
    bar, _, _, _, quits = make(tmp_path, updates)
    bar.start()

    bar.on_update_now(None)

    assert quits == [] and bar.note.visible and "Контрольная сумма не совпала" in bar.note.value
    assert "странице релиза" in bar.note.value
    assert bar.now_button.visible and not bar.now_button.disabled
    assert not bar.progress.visible and not bar.cancel_button.visible


def test_cancelling_the_download_stops_it_without_quitting(tmp_path):
    updates = FakeUpdates(offer())
    bar, _, _, _, quits = make(tmp_path, updates)
    bar.start()
    updates.during_install = lambda: bar.on_cancel(None)

    bar.on_update_now(None)

    assert quits == [] and "Загрузка отменена" in bar.note.value and not bar.cancel_button.visible


def test_a_second_click_while_installing_is_ignored(tmp_path):
    updates = FakeUpdates(offer())
    bar, _, _, _, _ = make(tmp_path, updates)
    bar.start()
    updates.during_install = lambda: bar.on_update_now(None)

    bar.on_update_now(None)

    assert len(updates.installs) == 1


def test_the_switch_persists_the_choice(tmp_path):
    bar, service, _, _, _ = make(tmp_path, FakeUpdates())
    assert bar.switch.value is True

    bar.switch.value = False
    bar.on_toggle(None)

    assert service.settings.check_updates is False


def test_the_switch_starts_from_the_saved_setting(tmp_path):
    service = SearchService(tmp_path / "data")
    service.load()
    service.set_check_updates(False)
    bar = UpdateBar(StubPage(), service, FakeUpdates(), delay=0)

    assert bar.switch.value is False


def test_the_default_quit_closes_the_window_and_arms_a_fallback_exit(tmp_path, monkeypatch):
    timers = []

    class FakeTimer:
        def __init__(self, seconds, function, args):
            timers.append((seconds, function, args))

        def start(self):
            timers[-1] += ("started",)

    monkeypatch.setattr(update_bar_module.threading, "Timer", FakeTimer)
    service = SearchService(tmp_path / "data")
    service.load()
    page = StubPage()
    page.window = SimpleNamespace(destroy=lambda: None)
    tasks = []
    page.run_task = lambda handler, *args: tasks.append(handler)
    bar = UpdateBar(page, service, FakeUpdates(), delay=0)

    bar.quit_app()

    assert tasks == [page.window.destroy]
    assert timers and timers[0][0] > 0 and timers[0][-1] == "started"
    assert threading.active_count() >= 1
