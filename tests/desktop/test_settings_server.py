import json

import pytest

from gmagc_common.protocol import DEFAULT_PORT
from gmagc_desktop.service.settings import Settings, load_settings, save_settings


def test_server_defaults_enable_the_server_on_the_default_port():
    settings = Settings()
    assert settings.server_enabled is True and settings.port == DEFAULT_PORT and settings.access_code == ""


def test_server_settings_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    save_settings(Settings(server_enabled=False, port=9000, access_code="ABCD2345"), path)

    loaded = load_settings(path)

    assert (loaded.server_enabled, loaded.port, loaded.access_code) == (False, 9000, "ABCD2345")


def test_access_code_is_normalized_on_load(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"access_code": "abcd-2345"}), encoding="utf-8")

    assert load_settings(path).access_code == "ABCD2345"


@pytest.mark.parametrize(
    "raw",
    [
        {"server_enabled": "no", "port": "9000", "access_code": 123},
        {"port": 80, "access_code": "short"},
        {"port": True},
        {"port": 70000},
        {"access_code": "ABCD0O1I"},
    ],
)
def test_bad_server_values_fall_back_to_defaults(tmp_path, raw):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    loaded = load_settings(path)

    assert loaded.server_enabled is True and loaded.port == DEFAULT_PORT and loaded.access_code == ""
