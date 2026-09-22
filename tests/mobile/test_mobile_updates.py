import asyncio

import flet as ft
import pytest

from gmagc_common.updates import ReleaseInfo, UpdateCheckError
from gmagc_mobile.about import VERSION
from gmagc_mobile.app import MobileApp
from gmagc_mobile.camera import CameraController
from gmagc_mobile.store import ConnectionStore
from gmagc_mobile.update_bar import UpdateBar
from gmagc_mobile.updates import KEY_LAST, KEY_SKIPPED, UpdateTracker
from tests.fakes import FakeClipboard, FakePicker, StubPage
from tests.fakes_mobile import FakeCameraApi, FakeLauncher, FakePermission, FakePrefs, Script
from tests.updates_stub import release_json

NOW = 1_800_000_000.0


def release(version="0.9.0", platforms=("windows", "macos", "android")):
    return ReleaseInfo.from_api(release_json(version, "https://example.invalid", platforms=platforms))


def tracker(prefs=None, fetch=None, now=NOW):
    return UpdateTracker(
        prefs if prefs is not None else FakePrefs(),
        current_version="0.5.2",
        fetch=fetch or (lambda v: release()),
        now=lambda: now,
    )


def run(coroutine):
    return asyncio.run(coroutine)


def test_a_newer_release_gives_a_notice_with_the_apk_link_and_records_the_check():
    prefs = FakePrefs()

    notice = run(tracker(prefs).check())

    assert notice.version == "0.9.0" and notice.url == "https://example.invalid/GMAGC-android-0.9.0.apk"
    assert notice.page_url.endswith("/releases/tag/v0.9.0") and prefs.data[KEY_LAST] == NOW


def test_a_recent_check_does_not_touch_the_network():
    def forbidden(version):
        raise AssertionError("сеть не должна вызываться")

    assert run(tracker(FakePrefs({KEY_LAST: NOW - 3600}), fetch=forbidden).check()) is None


def test_a_forced_check_ignores_the_schedule():
    prefs = FakePrefs({KEY_LAST: NOW - 60})

    assert run(tracker(prefs).check(force=True)).version == "0.9.0"


def test_no_newer_release_gives_none_but_records_the_check_and_errors_are_not_recorded():
    prefs = FakePrefs()
    assert run(tracker(prefs, fetch=lambda v: None).check()) is None and prefs.data[KEY_LAST] == NOW

    def broken(version):
        raise UpdateCheckError("Нет связи с GitHub")

    prefs = FakePrefs()
    with pytest.raises(UpdateCheckError):
        run(tracker(prefs, fetch=broken).check())
    assert KEY_LAST not in prefs.data


def test_a_skipped_version_is_hidden_from_the_background_check_only():
    prefs = FakePrefs()
    update = tracker(prefs)
    run(update.skip("0.9.0"))

    assert prefs.data[KEY_SKIPPED] == "0.9.0"
    assert run(update.check()) is None
    assert run(update.check(force=True)).version == "0.9.0"


def test_a_release_without_an_apk_falls_back_to_the_release_page():
    notice = run(tracker(fetch=lambda v: release(platforms=("windows",))).check())

    assert notice.url == notice.page_url


def test_broken_stored_values_and_a_failing_storage_are_tolerated():
    assert run(tracker(FakePrefs({KEY_LAST: "yesterday", KEY_SKIPPED: 5})).check()).version == "0.9.0"
    assert run(tracker(FakePrefs(fail=True)).check()).version == "0.9.0"


# ---- полоса на экране -------------------------------------------------------------------------------
def make_bar(update=None, launcher=None):
    page = StubPage()
    launcher = launcher or FakeLauncher()
    bar = UpdateBar(update or tracker(), launcher, page, delay=0)
    return bar, launcher, page


def test_the_startup_check_shows_the_bar():
    bar, _, _ = make_bar()

    run(bar.startup())

    assert bar.container.visible and bar.text.value == f"Доступна версия 0.9.0 (у вас {VERSION})"


def test_a_failed_background_check_is_silent_and_a_manual_one_reports():
    def broken(version):
        raise UpdateCheckError("Нет связи с GitHub")

    bar, _, _ = make_bar(tracker(fetch=broken))
    run(bar.startup())
    assert not bar.container.visible and bar.status.value == ""

    run(bar.on_check_now(None))
    assert bar.status.value == "Нет связи с GitHub"


def test_a_manual_check_without_news_says_so():
    bar, _, _ = make_bar(tracker(fetch=lambda v: None))

    run(bar.on_check_now(None))

    assert bar.status.value == f"Установлена последняя версия ({VERSION})" and not bar.container.visible


def test_download_opens_the_apk_link_and_skip_hides_the_bar():
    bar, launcher, _ = make_bar()
    run(bar.startup())

    run(bar.on_download(None))
    run(bar.on_skip(None))

    assert launcher.opened == ["https://example.invalid/GMAGC-android-0.9.0.apk"] and not bar.container.visible


def test_a_successful_download_closes_the_app_so_the_old_version_does_not_linger_alongside_the_new_one():
    """Иначе после ручной установки APK рядом остаётся висеть старый процесс — будто открыты две версии сразу."""
    bar, _, page = make_bar()
    run(bar.startup())

    run(bar.on_download(None))

    assert page.window.closed is True


def test_a_failing_launcher_is_reported_not_raised():
    class Broken:
        async def launch_url(self, url, **kwargs):
            raise RuntimeError("нет браузера")

    bar, _, page = make_bar(launcher=Broken())
    run(bar.startup())

    run(bar.on_download(None))

    assert "нет браузера" in bar.status.value
    assert page.window.closed is False  # ссылка не открылась — закрывать приложение незачем


# ---- встроено в экран ---------------------------------------------------------------------------------
def make_app(update, launcher=None, check_on_start=True):
    page = StubPage()
    app = MobileApp(
        page,
        ConnectionStore(FakePrefs()),
        CameraController(FakeCameraApi(), FakePermission(), settle_seconds=0, retry_seconds=0),
        preview=ft.Container(),
        picker=FakePicker(),
        clipboard=FakeClipboard(),
        client_factory=Script().factory,
        marker_seconds=0,
        mount_seconds=0,
        tracker=update,
        launcher=launcher or FakeLauncher(),
        check_on_start=check_on_start,
        update_delay=0,
    )
    app.build()
    return app, page


def test_the_screen_checks_for_updates_after_start_and_shows_the_bar():
    async def scenario():
        app, _ = make_app(tracker())
        await app.start()
        await app.update_task
        return app

    app = run(scenario())

    assert app.update_bar.container.visible and "0.9.0" in app.update_bar.text.value


def test_the_screen_does_not_check_when_no_tracker_is_given():
    app, _ = make_app(None)
    run(app.start())
    assert app.update_bar is None


def test_the_screen_always_checks_on_start_even_with_a_leftover_disabled_preference():
    """На Android нет выключателя: даже старое значение gmagc.updates.enabled=False в хранилище не должно мешать."""

    async def scenario():
        app, _ = make_app(tracker(FakePrefs({"gmagc.updates.enabled": False})))
        await app.start()
        await app.update_task
        return app

    app = run(scenario())

    assert app.update_bar.container.visible and "0.9.0" in app.update_bar.text.value


async def _finish(app):
    return await app.update_task


def test_the_settings_screen_has_the_manual_check_and_no_switch_to_turn_it_off():
    app, _ = make_app(tracker(), check_on_start=False)

    controls = list(_walk(app.settings_view))

    assert app.update_bar.check_button in controls
    assert not any(isinstance(control, ft.Switch) for control in controls)
    assert app.update_bar.container in list(_walk(_root(app)))


def _root(app):
    return app.page.added[0]


def _walk(control):
    yield control
    for attribute in ("content", "controls"):
        value = getattr(control, attribute, None)
        for child in value if isinstance(value, list) else [value] if value is not None else []:
            if isinstance(child, ft.Control):
                yield from _walk(child)
