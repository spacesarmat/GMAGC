import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import export_ma3  # noqa: E402

from gmagc_common.fixtures import Channel, FixtureProfile, Mode, profile_to_dict  # noqa: E402


def write_profile(path, profile):
    path.write_text(json.dumps(profile_to_dict(profile), ensure_ascii=False), encoding="utf-8")


def ready_profile():
    return FixtureProfile("a" * 32, "SHEHDS", "380W Beam", "", (Mode("Стандарт", (Channel(1, 8, "Диммер", "dimmer"),)),))


def test_the_script_writes_the_xml_next_to_the_profile_by_default(tmp_path, capsys):
    source = tmp_path / "profile.json"
    write_profile(source, ready_profile())

    assert export_ma3.main([str(source)]) == 0

    target = tmp_path / "profile.xml"
    assert target.exists() and "<FixtureType" in target.read_text(encoding="utf-8")
    assert str(target) in capsys.readouterr().out


def test_the_script_honours_the_output_option(tmp_path):
    source = tmp_path / "profile.json"
    write_profile(source, ready_profile())
    target = tmp_path / "out" / "type.xml"

    assert export_ma3.main([str(source), "-o", str(target)]) == 0

    assert target.exists()


def test_a_missing_or_broken_profile_gives_exit_code_3(tmp_path, capsys):
    assert export_ma3.main([str(tmp_path / "missing.json")]) == 3
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")

    assert export_ma3.main([str(broken)]) == 3
    assert capsys.readouterr().err


def test_a_profile_that_is_not_ready_gives_exit_code_1_and_names_the_problem(tmp_path, capsys):
    source = tmp_path / "profile.json"
    write_profile(source, FixtureProfile("a" * 32, "", "", "", (Mode("m"),)))

    assert export_ma3.main([str(source)]) == 1
    assert "производител" in capsys.readouterr().err
    assert not (tmp_path / "profile.xml").exists()


def test_help_exits_cleanly():
    with pytest.raises(SystemExit) as info:
        export_ma3.main(["--help"])

    assert info.value.code == 0
