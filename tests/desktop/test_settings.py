import sys

from gmagc_desktop.service.settings import (
    Settings,
    data_dir,
    load_settings,
    save_settings,
    settings_from_json,
    settings_to_json,
)


def test_missing_and_corrupt_files_give_defaults(tmp_path):
    assert load_settings(tmp_path / "nope.json") == Settings()

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert load_settings(broken) == Settings()

    listing = tmp_path / "list.json"
    listing.write_text("[1, 2]", encoding="utf-8")
    assert load_settings(listing) == Settings()


def test_settings_from_json_parses_the_same_text_a_file_would_hold():
    text = '{"library_dir": "D:\\\\gobos", "top_n": 15}'

    assert settings_from_json(text) == Settings(library_dir="D:\\gobos", top_n=15)


def test_settings_from_json_falls_back_to_defaults_on_bad_text():
    assert settings_from_json("{not json") == Settings()
    assert settings_from_json("[1, 2]") == Settings()


def test_theme_and_text_size_default_to_off_and_reject_non_boolean_values():
    assert settings_from_json("{}") == Settings(dark_theme=False, large_text=False)
    assert settings_from_json('{"dark_theme": true, "large_text": true}') == Settings(
        dark_theme=True, large_text=True
    )
    assert settings_from_json('{"dark_theme": "yes"}') == Settings(dark_theme=False)


def test_settings_to_json_roundtrips_through_settings_from_json():
    original = Settings(library_dir="D:\\Библиотека гобо", top_n=15, access_code="ABCD2345")

    assert settings_from_json(settings_to_json(original)) == original


def test_roundtrip_keeps_a_cyrillic_library_path(tmp_path):
    target = tmp_path / "data" / "settings.json"

    save_settings(Settings(library_dir="D:\\Библиотека гобо", top_n=15), target)

    assert load_settings(target) == Settings(library_dir="D:\\Библиотека гобо", top_n=15)


def test_invalid_values_fall_back_to_defaults(tmp_path):
    target = tmp_path / "settings.json"
    target.write_text('{"library_dir": 5, "top_n": 999}', encoding="utf-8")

    assert load_settings(target) == Settings(library_dir="", top_n=10)


def test_data_dir_can_be_overridden_and_follows_the_platform(monkeypatch, tmp_path):
    monkeypatch.setenv("GMAGC_DATA_DIR", str(tmp_path / "custom"))
    assert data_dir() == tmp_path / "custom"

    monkeypatch.delenv("GMAGC_DATA_DIR")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    assert data_dir().parts[-2:] == ("@ANDY_BUM", "GMAGC")
    assert str(data_dir()).startswith(str(tmp_path / "local"))

    monkeypatch.setattr(sys, "platform", "darwin")
    assert data_dir().parts[-3:] == ("Library", "Application Support", "GMAGC")
