from gmagc_common.support import AUTHOR_TELEGRAM_URL, FIRST_ASK_LAUNCH, REMIND_AFTER_SECONDS, SUPPORT_URL
from gmagc_desktop.service.search_service import SearchService
from gmagc_desktop.service.settings import Settings, load_settings, save_settings
from gmagc_desktop.ui.support import SupportPrompt
from tests.fakes import StubPage

NOW = 1_800_000_000.0


def make(tmp_path, launches=0, busy=False, last_ask=0.0, muted=False):
    if launches or last_ask or muted:
        settings = Settings(launches=launches, support_last_ask=last_ask, support_muted=muted)
        save_settings(settings, tmp_path / "data" / "settings.json")
    service = SearchService(tmp_path / "data")
    service.load()
    opened = []
    page = StubPage()
    prompt = SupportPrompt(page, service, open_url=opened.append, now=lambda: NOW, delay=0, busy=lambda: busy)
    return prompt, service, page, opened


def test_the_settings_keep_the_support_state(tmp_path):
    save_settings(Settings(launches=7, support_last_ask=12.5, support_muted=True), tmp_path / "s.json")

    loaded = load_settings(tmp_path / "s.json")

    assert (loaded.launches, loaded.support_last_ask, loaded.support_muted) == (7, 12.5, True)
    assert load_settings(tmp_path / "missing.json").launches == 0


def test_every_start_counts_a_launch_and_the_dialog_waits_for_the_fifth(tmp_path):
    for launch in range(1, FIRST_ASK_LAUNCH):
        prompt, service, page, _ = make(tmp_path, launches=launch - 1)
        prompt.start()
        assert service.settings.launches == launch and page.dialogs == []

    prompt, service, page, _ = make(tmp_path, launches=FIRST_ASK_LAUNCH - 1)
    prompt.start()

    assert service.settings.launches == FIRST_ASK_LAUNCH and len(page.dialogs) == 1


def test_the_dialog_explains_and_offers_three_choices(tmp_path):
    prompt, _, page, _ = make(tmp_path, launches=5)
    prompt.start()

    dialog = page.dialogs[0]

    assert dialog.title.value == "Поддержать автора"
    assert [b.content.value if hasattr(b.content, "value") else b.content for b in dialog.actions] == [
        "Поддержать",
        "Позже",
        "Больше не показывать",
    ]


def test_support_opens_the_link_records_it_and_closes_the_dialog(tmp_path):
    prompt, service, page, opened = make(tmp_path, launches=5)
    prompt.start()

    prompt.on_support(None)

    assert opened == [SUPPORT_URL] and page.dialogs == [] and service.settings.support_muted is True
    assert service.settings.support_last_ask == NOW


def test_later_postpones_and_never_mutes(tmp_path):
    prompt, service, page, opened = make(tmp_path, launches=5)
    prompt.start()
    prompt.on_later(None)
    assert page.dialogs == [] and opened == [] and service.settings.support_muted is False
    assert service.settings.support_last_ask == NOW

    prompt, service, page, _ = make(tmp_path, launches=6, last_ask=NOW - REMIND_AFTER_SECONDS)
    prompt.start()
    assert len(page.dialogs) == 1
    prompt.on_never(None)
    assert service.settings.support_muted is True and page.dialogs == []


def test_a_muted_or_recently_asked_user_is_left_alone(tmp_path):
    prompt, _, page, _ = make(tmp_path, launches=50, muted=True)
    prompt.start()
    assert page.dialogs == []

    prompt, _, page, _ = make(tmp_path, launches=50, last_ask=NOW - 3600)
    prompt.start()
    assert page.dialogs == []


def test_a_busy_app_skips_the_dialog_without_recording_an_ask(tmp_path):
    prompt, service, page, _ = make(tmp_path, launches=9, busy=True)

    prompt.start()

    assert page.dialogs == [] and service.settings.support_last_ask == 0.0 and service.settings.launches == 10


def test_the_permanent_link_opens_the_page_and_never_changes_the_schedule(tmp_path):
    prompt, service, _, opened = make(tmp_path, launches=1)

    prompt.on_open_link(None)

    assert opened == [SUPPORT_URL] and service.settings.support_last_ask == 0.0 and service.settings.support_muted is False


def test_the_telegram_link_opens_the_authors_account(tmp_path):
    prompt, _, _, opened = make(tmp_path, launches=1)

    prompt.on_open_telegram(None)

    assert opened == [AUTHOR_TELEGRAM_URL] and AUTHOR_TELEGRAM_URL == "https://t.me/Andy_bum"
