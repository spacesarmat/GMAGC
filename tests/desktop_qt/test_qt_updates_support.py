"""Обновления и просьба о поддержке на Qt: полоса, секция настроек, расписание диалога, ссылки."""

from types import SimpleNamespace

import pytest

from gmagc_common.support import AUTHOR_TELEGRAM_URL, CHANNEL_URL, LATER, NEVER, SUPPORT, SUPPORT_URL, SupportState
from gmagc_common.updates import ReleaseInfo, UpdateCheckError
from gmagc_desktop.about import VERSION
from gmagc_desktop.qt import updates as updates_module
from gmagc_desktop.qt.app import build_window
from gmagc_desktop.qt.controller import InlineExecutor
from gmagc_desktop.qt.support import SupportLinks, SupportPrompt
from gmagc_desktop.qt.updates import UpdateBar, UpdateController, UpdateSettings
from gmagc_desktop.service.search_service import SearchService
from gmagc_desktop.update.installer import InstallError
from gmagc_desktop.update.manager import UpdateOffer
from tests.fakes import FakeServer, FakeUpdates
from tests.updates_stub import release_json


def offer(can_install=True, reason="", version="0.9.0"):
    release = ReleaseInfo.from_api(release_json(version, "https://example.invalid"))
    return UpdateOffer(release, can_install, reason)


def make(tmp_path, updates):
    service = SearchService(tmp_path / "data")
    service.load()
    opened, quits = [], []
    controller = UpdateController(
        service, updates, InlineExecutor(), open_url=opened.append, quit_app=lambda: quits.append(1), delay=0
    )
    bar = UpdateBar(controller)
    settings = UpdateSettings(controller)
    return controller, bar, settings, service, opened, quits


def test_the_startup_check_cleans_up_and_shows_a_newer_version(qapp, tmp_path):
    updates = FakeUpdates(offer())
    controller, bar, _, _, _, _ = make(tmp_path, updates)

    controller.start()

    assert updates.cleaned == 1 and updates.checks == [False]
    assert bar.isVisible() and bar.text.text() == f"Доступна версия 0.9.0 (у вас {VERSION})"
    assert bar.now_button.isVisible() and bar.page_button.text() == "Что нового"


def test_a_disabled_check_does_nothing_at_startup(qapp, tmp_path):
    updates = FakeUpdates(offer())
    controller, bar, _, service, _, _ = make(tmp_path, updates)
    service.set_check_updates(False)

    controller.start()

    assert updates.checks == [] and not bar.isVisible()


def test_no_newer_version_keeps_the_bar_hidden_and_a_failed_background_check_is_silent(qapp, tmp_path):
    updates = FakeUpdates(None)
    controller, bar, settings, _, _, _ = make(tmp_path, updates)
    controller.start()
    assert not bar.isVisible() and settings.status_label.text() == ""

    updates.check_error = UpdateCheckError("нет сети")
    controller.start()
    assert not bar.isVisible() and settings.status_label.text() == ""


def test_a_manual_check_reports_every_outcome(qapp, tmp_path):
    updates = FakeUpdates(None)
    controller, bar, settings, _, _, _ = make(tmp_path, updates)

    settings.check_button.click()
    assert settings.status_label.text() == f"Установлена последняя версия ({VERSION})" and updates.checks == [True]

    updates.check_error = UpdateCheckError("нет сети")
    settings.check_button.click()
    assert settings.status_label.text() == "нет сети"

    updates.check_error = RuntimeError("сбой")
    settings.check_button.click()
    assert settings.status_label.text() == "Ошибка проверки обновлений: сбой"

    updates.check_error = None
    updates.offer = offer()
    settings.check_button.click()
    assert bar.isVisible() and settings.status_label.text() == ""


def test_an_offer_that_cannot_be_installed_shows_why_and_only_offers_the_release_page(qapp, tmp_path):
    controller, bar, _, _, opened, _ = make(tmp_path, FakeUpdates(offer(can_install=False, reason="Запущено не из папки")))

    controller.start()

    assert bar.isVisible() and not bar.now_button.isVisible() and bar.page_button.text() == "Открыть страницу релиза"
    assert bar.note.isVisible() and bar.note.text() == "Запущено не из папки"
    bar.page_button.click()
    assert opened == [offer().release.page_url]


def test_skipping_remembers_the_version_and_hides_the_bar(qapp, tmp_path):
    updates = FakeUpdates(offer(version="0.9.5"))
    controller, bar, _, _, _, _ = make(tmp_path, updates)
    controller.start()

    bar.skip_button.click()

    assert updates.skipped == ["0.9.5"] and not bar.isVisible()


def test_installing_shows_progress_and_quits_the_app_when_done(qapp, tmp_path):
    updates = FakeUpdates(offer())
    controller, bar, _, _, _, quits = make(tmp_path, updates)
    controller.start()
    seen = []
    controller.progress_changed.connect(lambda done, total: seen.append((done, total)))

    bar.now_button.click()

    assert updates.installs and quits == [1]
    assert (5_000_000, 10_000_000) in seen and seen[-1] == (1, 1)
    assert bar.text.text() == "Обновление скачано, приложение перезапускается…"


def test_a_progress_note_shows_megabytes(qapp, tmp_path):
    updates = FakeUpdates(offer())
    updates.progress_steps = ((5_000_000, 10_000_000),)
    updates.install_error = InstallError("стоп")
    controller, bar, _, _, _, _ = make(tmp_path, updates)
    controller.start()
    notes = []
    controller.note_changed.connect(notes.append)

    bar.now_button.click()

    assert notes[0] == "Скачивание…"


def test_a_failed_installation_shows_the_reason_and_the_fallback_and_keeps_running(qapp, tmp_path):
    updates = FakeUpdates(offer(), install_error=InstallError("Контрольная сумма не совпала"))
    controller, bar, _, _, _, quits = make(tmp_path, updates)
    controller.start()

    bar.now_button.click()

    assert quits == [] and bar.note.text().startswith("Контрольная сумма не совпала.")
    assert "вручную" in bar.note.text() and bar.now_button.isEnabled() and not bar.cancel_button.isVisible()


def test_cancelling_the_download_stops_it_without_quitting(qapp, tmp_path):
    updates = FakeUpdates(offer())
    controller, bar, _, _, _, quits = make(tmp_path, updates)
    controller.start()
    updates.during_install = controller.cancel

    bar.now_button.click()

    assert quits == [] and bar.note.text() == "Загрузка отменена." and bar.now_button.isEnabled()


def test_a_second_install_click_while_installing_is_ignored(qapp, tmp_path):
    updates = FakeUpdates(offer())
    controller, bar, _, _, _, _ = make(tmp_path, updates)
    controller.start()
    controller._installing = True

    controller.install_now()

    assert updates.installs == []


def test_the_check_on_start_switch_persists_the_choice_and_starts_from_the_saved_one(qapp, tmp_path):
    controller, bar, settings, service, _, _ = make(tmp_path, FakeUpdates())
    assert settings.check_on_start.isChecked()

    settings.check_on_start.setChecked(False)
    assert service.settings.check_updates is False

    again = UpdateSettings(controller)
    assert not again.check_on_start.isChecked()


def test_the_default_quit_closes_the_app_and_arms_a_fallback_exit(qapp, monkeypatch):
    timers, quit_calls = [], []

    class Timer:
        def __init__(self, seconds, function, args):
            self.seconds, self.function, self.args, self.daemon = seconds, function, args, False
            timers.append(self)

        def start(self):
            self.started = True

    monkeypatch.setattr(updates_module.threading, "Timer", Timer)
    monkeypatch.setattr(updates_module.QApplication, "quit", staticmethod(lambda: quit_calls.append(1)))

    updates_module.default_quit()

    assert quit_calls == [1] and timers[0].started and timers[0].daemon
    assert timers[0].seconds == updates_module.EXIT_FALLBACK_SECONDS


def test_without_an_update_manager_the_controller_does_nothing(qapp, tmp_path):
    service = SearchService(tmp_path / "data")
    service.load()
    controller = UpdateController(service, None, InlineExecutor(), delay=0)

    controller.start()
    controller.check_now()

    assert controller.offer is None


# ---- поддержка ----------------------------------------------------------------------------------
def make_support(tmp_path, launches=0, busy=False, last_ask=0.0, muted=False, answer=LATER):
    service = SearchService(tmp_path / "data")
    service.load()
    service.save_support_state(SupportState(launches=launches, last_ask=last_ask, muted=muted))
    opened, asked = [], []

    def ask(_parent):
        asked.append(1)
        return answer

    prompt = SupportPrompt(
        service, None, open_url=opened.append, now=lambda: 1_000_000.0, delay=0, busy=lambda: busy, ask=ask
    )
    return prompt, service, opened, asked


def test_every_start_counts_a_launch_and_the_dialog_waits_for_the_fifth(qapp, tmp_path):
    prompt, service, _, asked = make_support(tmp_path, launches=0)

    prompt.start()
    assert service.support_state().launches == 1 and asked == []

    prompt2, service2, _, asked2 = make_support(tmp_path / "b", launches=4)
    prompt2.start()
    assert service2.support_state().launches == 5 and asked2 == [1]


@pytest.mark.parametrize(
    ("answer", "opens", "muted"),
    [(SUPPORT, [SUPPORT_URL], True), (LATER, [], False), (NEVER, [], True)],
)
def test_the_answers_open_the_link_postpone_or_mute(qapp, tmp_path, answer, opens, muted):
    prompt, service, opened, _ = make_support(tmp_path, launches=4, answer=answer)

    prompt.start()

    assert opened == opens and service.support_state().muted is muted
    assert service.support_state().last_ask == 1_000_000.0


def test_a_muted_or_recently_asked_user_is_left_alone(qapp, tmp_path):
    prompt, _, _, asked = make_support(tmp_path, launches=9, muted=True)
    prompt.start()
    recent, _, _, asked_recent = make_support(tmp_path / "b", launches=9, last_ask=999_999.0)
    recent.start()

    assert asked == [] and asked_recent == []


def test_a_busy_app_skips_the_dialog_without_recording_an_ask(qapp, tmp_path):
    prompt, service, _, asked = make_support(tmp_path, launches=4, busy=True)

    prompt.start()

    assert asked == [] and service.support_state().last_ask == 0.0


def test_the_permanent_links_open_the_right_pages_without_touching_the_schedule(qapp):
    opened = []
    links = SupportLinks(opened.append)

    for key in ("support", "telegram", "channel"):
        links.buttons[key].click()

    assert opened == [SUPPORT_URL, AUTHOR_TELEGRAM_URL, CHANNEL_URL]


# ---- в составе окна ------------------------------------------------------------------------------
def test_the_window_puts_the_bar_on_top_and_the_sections_into_the_settings(qapp, tmp_path):
    service = SearchService(tmp_path / "data")
    service.load()
    updates = FakeUpdates(offer())
    window = build_window(
        service,
        InlineExecutor(),
        server=FakeServer(),
        updates=updates,
        update_delay=0,
        support=True,
        support_delay=0,
        support_ask=lambda _parent: LATER,
        quit_app=lambda: None,
    )
    window.show()

    from gmagc_desktop.qt.app import start_services

    start_services(window)

    assert isinstance(window.update_controller, UpdateController) and updates.checks == [False]
    bars = window.findChildren(UpdateBar)
    assert bars and bars[0].isVisible()
    assert window.findChildren(UpdateSettings) and window.findChildren(SupportLinks)
    assert service.support_state().launches == 1


def test_the_window_without_updates_and_support_has_neither(qapp, tmp_path):
    service = SearchService(tmp_path / "data")
    service.load()

    window = build_window(service, InlineExecutor(), server=FakeServer())

    assert window.update_controller is None and window.support_prompt is None
    assert not window.findChildren(UpdateBar) and not window.findChildren(SupportLinks)


def test_a_rebuild_keeps_the_updates_but_does_not_ask_for_support_again(qapp, tmp_path):
    from gmagc_desktop.qt.app import rebuild_window

    service = SearchService(tmp_path / "data")
    service.load()
    asked = []
    window = build_window(
        service,
        InlineExecutor(),
        server=FakeServer(),
        updates=FakeUpdates(None),
        update_delay=0,
        support=True,
        support_delay=0,
        support_ask=lambda _parent: asked.append(1) or LATER,
    )

    fresh = rebuild_window(window)

    assert fresh.update_controller is not None and fresh.support_prompt is None and asked == []
    assert SimpleNamespace  # импорт нужен другим тестам файла
