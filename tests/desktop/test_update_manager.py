import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from gmagc_common.updates import ReleaseInfo, UpdateCheckError, fetch_latest
from gmagc_desktop.service.search_service import SearchService
from gmagc_desktop.update import manager as manager_module
from gmagc_desktop.update.installer import InstallCancelled, InstallError
from gmagc_desktop.update.manager import UpdateManager
from tests.updates_stub import release_json, stub_server

NOW = 1_800_000_000.0
DAY = 24 * 3600


def app_zip():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("gmagc-desktop.exe", b"MZ-new")
        archive.writestr("data/app.bin", b"new data")
    return buffer.getvalue()


@pytest.fixture()
def service(tmp_path):
    instance = SearchService(tmp_path / "data")
    instance.load()
    return instance


@pytest.fixture()
def install_dir(tmp_path):
    folder = tmp_path / "Apps" / "GMAGC"
    folder.mkdir(parents=True)
    (folder / "gmagc-desktop.exe").write_bytes(b"MZ-old")
    return folder


def release(version="0.6.0", platforms=("windows", "macos", "android")):
    return ReleaseInfo.from_api(release_json(version, "https://example.invalid", platforms=platforms))


def make_manager(service, tmp_path, install_dir, *, fetch=None, launched=None, **options):
    def launch_function(script, platform):
        if launched is not None:
            launched.append((script, platform))

    return UpdateManager(
        service,
        tmp_path / "data",
        current_version=options.pop("current_version", "0.5.1"),
        platform=options.pop("platform", "windows"),
        executable=options.pop("executable", install_dir / "gmagc-desktop.exe"),
        fetch=fetch or (lambda version: release()),
        now=lambda: NOW,
        launch=launch_function,
        pid=4242,
        **options,
    )


def test_a_recent_check_and_a_disabled_check_do_not_touch_the_network(service, tmp_path, install_dir):
    def forbidden(version):
        raise AssertionError("сеть не должна вызываться")

    manager = make_manager(service, tmp_path, install_dir, fetch=forbidden)
    service.mark_update_checked(NOW - 3600)
    assert manager.check() is None

    service.mark_update_checked(0)
    service.set_check_updates(False)
    assert manager.check() is None


def test_a_forced_check_ignores_the_schedule_and_the_switch(service, tmp_path, install_dir):
    service.set_check_updates(False)
    service.mark_update_checked(NOW - 60)
    manager = make_manager(service, tmp_path, install_dir)

    offer = manager.check(force=True)

    assert offer.release.version == "0.6.0" and offer.can_install is True and offer.reason == ""


def test_a_due_check_offers_a_newer_version_and_records_the_time(service, tmp_path, install_dir):
    manager = make_manager(service, tmp_path, install_dir)

    offer = manager.check()

    assert offer.release.version == "0.6.0" and service.settings.last_update_check == NOW


def test_no_newer_version_gives_none_but_still_records_the_check(service, tmp_path, install_dir):
    manager = make_manager(service, tmp_path, install_dir, fetch=lambda version: None)

    assert manager.check() is None
    assert service.settings.last_update_check == NOW


def test_a_failed_check_propagates_and_is_not_recorded(service, tmp_path, install_dir):
    def broken(version):
        raise UpdateCheckError("Нет связи с GitHub")

    manager = make_manager(service, tmp_path, install_dir, fetch=broken)

    with pytest.raises(UpdateCheckError):
        manager.check()

    assert service.settings.last_update_check == 0.0


def test_a_skipped_version_is_hidden_from_the_background_check_but_shown_on_demand(service, tmp_path, install_dir):
    manager = make_manager(service, tmp_path, install_dir)
    manager.skip("0.6.0")

    assert manager.check() is None
    assert manager.check(force=True).release.version == "0.6.0"
    assert service.settings.skipped_version == "0.6.0"

    manager = make_manager(service, tmp_path, install_dir, fetch=lambda version: release("0.7.0"))
    service.mark_update_checked(0)
    assert manager.check().release.version == "0.7.0"


def test_a_platform_without_a_file_cannot_install_from_the_app(service, tmp_path, install_dir):
    manager = make_manager(service, tmp_path, install_dir, fetch=lambda version: release(platforms=("android",)))

    offer = manager.check(force=True)

    assert offer.can_install is False and "нет готового файла" in offer.reason


def test_a_run_from_source_cannot_install_from_the_app(service, tmp_path, install_dir):
    manager = make_manager(service, tmp_path, install_dir, executable=Path("C:/Python312/python.exe"))

    offer = manager.check(force=True)

    assert offer.can_install is False and "не из собранной папки" in offer.reason


def test_a_release_without_a_checksum_cannot_install_from_the_app(service, tmp_path, install_dir):
    def without_sum(version):
        base = release()
        kept = tuple(a for a in base.assets if not a.name.endswith(".sha256"))
        return ReleaseInfo(base.version, base.tag, base.notes, base.page_url, kept)

    manager = make_manager(service, tmp_path, install_dir, fetch=without_sum)

    offer = manager.check(force=True)

    assert offer.can_install is False and "контрольной суммы" in offer.reason


def test_a_read_only_install_folder_cannot_install_from_the_app(service, tmp_path, install_dir, monkeypatch):
    monkeypatch.setattr(manager_module, "is_writable", lambda path: False)
    manager = make_manager(service, tmp_path, install_dir)

    offer = manager.check(force=True)

    assert offer.can_install is False and "нет прав на запись" in offer.reason.lower()


def serve_release(monkeypatch, zip_bytes, sha=None):
    """Поддельный GitHub с релизом 0.6.0 для Windows; GMAGC_UPDATE_URL разрешает локальные адреса."""
    routes = {}
    name = "GMAGC-desktop-windows-0.6.0.zip"
    server = stub_server(routes)
    base = server.__enter__()
    routes["/latest"] = {"body": json.dumps(release_json("0.6.0", base, platforms=("windows",))).encode()}
    routes[f"/{name}"] = {"body": zip_bytes}
    routes[f"/{name}.sha256"] = {"body": f"{sha or hashlib.sha256(zip_bytes).hexdigest()}  {name}\n".encode()}
    monkeypatch.setenv("GMAGC_UPDATE_URL", f"{base}/latest")
    return base, server


def test_install_downloads_verifies_stages_writes_the_helper_and_launches_it(service, tmp_path, install_dir, monkeypatch):
    base, server = serve_release(monkeypatch, app_zip())
    launched, steps = [], []
    try:
        manager = make_manager(
            service, tmp_path, install_dir, launched=launched,
            fetch=lambda version: fetch_latest(version, url=f"{base}/latest", allow_local=True),
        )
        offer = manager.check(force=True)
        assert offer.can_install

        script = manager.install(offer, progress=lambda done, total: steps.append((done, total)))
    finally:
        server.__exit__(None, None, None)

    work = tmp_path / "data" / "updates" / "0.6.0"
    assert script == work / "apply-update.cmd" and launched == [(script, "windows")]
    assert (work / "staged" / "gmagc-desktop.exe").read_bytes() == b"MZ-new"
    assert (work / "staged" / "data" / "app.bin").read_bytes() == b"new data"
    assert not list(work.glob("*.zip")) and steps
    text = script.read_text(encoding="utf-8")
    assert 'set "PID=4242"' in text and str(install_dir) in text and str(install_dir) + ".previous" in text
    assert str(tmp_path / "data" / "update.log") in text
    assert (install_dir / "gmagc-desktop.exe").read_bytes() == b"MZ-old"  # до перезапуска ничего не тронуто


def test_a_wrong_checksum_stops_the_installation_before_anything_is_launched(service, tmp_path, install_dir, monkeypatch):
    base, server = serve_release(monkeypatch, app_zip(), sha="0" * 64)
    launched = []
    try:
        manager = make_manager(
            service, tmp_path, install_dir, launched=launched,
            fetch=lambda version: fetch_latest(version, url=f"{base}/latest", allow_local=True),
        )
        offer = manager.check(force=True)
        with pytest.raises(InstallError):
            manager.install(offer)
    finally:
        server.__exit__(None, None, None)

    assert launched == [] and (install_dir / "gmagc-desktop.exe").read_bytes() == b"MZ-old"


def test_cancelling_the_installation_launches_nothing(service, tmp_path, install_dir, monkeypatch):
    base, server = serve_release(monkeypatch, app_zip())
    launched = []
    try:
        manager = make_manager(
            service, tmp_path, install_dir, launched=launched,
            fetch=lambda version: fetch_latest(version, url=f"{base}/latest", allow_local=True),
        )
        offer = manager.check(force=True)
        with pytest.raises(InstallCancelled):
            manager.install(offer, cancel=lambda: True)
    finally:
        server.__exit__(None, None, None)

    assert launched == []


def test_installing_an_offer_that_cannot_be_installed_is_refused(service, tmp_path, install_dir):
    manager = make_manager(service, tmp_path, install_dir, fetch=lambda version: release(platforms=("android",)))
    offer = manager.check(force=True)

    with pytest.raises(InstallError) as error:
        manager.install(offer)

    assert "нет готового файла" in str(error.value)


def test_cleanup_removes_leftovers_of_earlier_updates(service, tmp_path, install_dir):
    leftovers = tmp_path / "data" / "updates" / "0.5.9" / "staged"
    leftovers.mkdir(parents=True)
    (leftovers / "x.bin").write_bytes(b"1")
    manager = make_manager(service, tmp_path, install_dir)

    manager.cleanup()

    assert not (tmp_path / "data" / "updates").exists()
    manager.cleanup()  # повторный вызов безопасен
