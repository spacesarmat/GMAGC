import json

import pytest

from gmagc_desktop.service.search_service import SearchService
from gmagc_desktop.service.settings import Settings, load_settings, save_settings


def test_update_defaults_check_on_start_and_nothing_skipped():
    settings = Settings()

    assert settings.check_updates is True and settings.skipped_version == "" and settings.last_update_check == 0.0


def test_update_settings_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    save_settings(Settings(check_updates=False, skipped_version="0.6.0", last_update_check=1_700_000_000.5), path)

    loaded = load_settings(path)

    assert (loaded.check_updates, loaded.skipped_version, loaded.last_update_check) == (False, "0.6.0", 1_700_000_000.5)


@pytest.mark.parametrize(
    "raw",
    [
        {"check_updates": "yes", "skipped_version": 5, "last_update_check": "today"},
        {"skipped_version": "latest", "last_update_check": -1},
        {"skipped_version": "1.2", "last_update_check": True},
        {"last_update_check": float("inf")},
        {"last_update_check": None},
    ],
)
def test_bad_update_values_fall_back_to_defaults(tmp_path, raw):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    loaded = load_settings(path)

    assert loaded.check_updates is True and loaded.skipped_version == "" and loaded.last_update_check == 0.0


def test_the_service_persists_update_choices(tmp_path):
    service = SearchService(tmp_path / "data")
    service.load()

    service.set_check_updates(False)
    service.mark_update_checked(1_700_000_123.0)
    service.skip_update("0.7.1")

    other = SearchService(tmp_path / "data")
    other.load()
    assert other.settings.check_updates is False
    assert other.settings.last_update_check == 1_700_000_123.0 and other.settings.skipped_version == "0.7.1"


def test_a_malformed_version_is_not_stored_as_skipped(tmp_path):
    service = SearchService(tmp_path / "data")
    service.load()

    service.skip_update("not-a-version")

    assert service.settings.skipped_version == ""
