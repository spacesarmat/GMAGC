import pytest

from gmagc_common.fixtures import Channel, FixtureProfile, Mode
from gmagc_common.ma3_export import ExportError
from gmagc_desktop.service.fixture_export import (
    FixtureExporter,
    NoTargetError,
    default_ma2_dir,
    default_ma3_dir,
)
from gmagc_desktop.service.settings import Settings


def ready_profile():
    modes = (
        Mode("Standard", (Channel(1, 8, "Диммер", "dimmer"),)),
        Mode("Extended", (Channel(1, 8, "Диммер", "dimmer"), Channel(2, 8, "Красный", "red"))),
    )
    return FixtureProfile("a" * 32, "SHEHDS", "380W Beam", "", modes)


def make_program_data(tmp_path, ma3=True, ma2_versions=("gma2_V_3.9.63",)):
    root = tmp_path / "ProgramData"
    if ma3:
        (root / "MALightingTechnology" / "gma3_library" / "fixturetypes").mkdir(parents=True)
    for version in ma2_versions:
        (root / "MA Lighting Technologies" / "grandma" / version / "importexport").mkdir(parents=True)
    return {"PROGRAMDATA": str(root)}


def test_the_default_folders_are_found_in_program_data(tmp_path):
    environ = make_program_data(tmp_path, ma2_versions=("gma2_V_3.9.60", "gma2_V_3.9.63", "gma2_V_3.10.1"))

    assert default_ma3_dir(environ).name == "fixturetypes"
    assert default_ma2_dir(environ).parent.name == "gma2_V_3.10.1"  # самая новая версия, сравнение по числам


def test_missing_installations_give_no_default_folders(tmp_path):
    environ = make_program_data(tmp_path, ma3=False, ma2_versions=())

    assert default_ma3_dir(environ) is None and default_ma2_dir(environ) is None
    assert default_ma3_dir({}) is None and default_ma2_dir({}) is None


def test_a_profile_is_written_as_one_ma3_file_and_one_ma2_file_per_mode(tmp_path):
    environ = make_program_data(tmp_path)
    exporter = FixtureExporter(lambda: Settings(), environ)

    result = exporter.store(ready_profile())

    targets = sorted(target for target, _ in result.written)
    assert targets == ["ma2", "ma2", "ma3"] and result.skipped == ()
    names = sorted(path.replace("\\", "/").rsplit("/", 1)[1] for _, path in result.written)
    assert names == ["shehds@380w_beam.xml", "shehds@380w_beam@extended.xml", "shehds@380w_beam@standard.xml"]
    for _, path in result.written:
        assert open(path, encoding="utf-8").read().startswith("<?xml")


def test_configured_folders_win_over_the_defaults_and_are_created(tmp_path):
    environ = make_program_data(tmp_path)
    ma3 = tmp_path / "mine" / "ma3"
    settings = Settings(ma3_fixture_dir=str(ma3))
    exporter = FixtureExporter(lambda: settings, environ)

    result = exporter.store(ready_profile())

    assert (ma3 / "shehds@380w_beam.xml").exists()
    assert any(target == "ma2" for target, _ in result.written)  # MA2 остаётся на найденной папке


def test_a_missing_console_is_skipped_with_a_message_while_the_other_is_written(tmp_path):
    environ = make_program_data(tmp_path, ma2_versions=())
    exporter = FixtureExporter(lambda: Settings(), environ)

    result = exporter.store(ready_profile())

    assert [target for target, _ in result.written] == ["ma3"]
    assert result.skipped == ("no_folder:ma2",)


def test_when_no_folder_is_available_nothing_is_written_and_the_reason_is_raised(tmp_path):
    environ = make_program_data(tmp_path, ma3=False, ma2_versions=())
    exporter = FixtureExporter(lambda: Settings(), environ)

    with pytest.raises(NoTargetError) as error:
        exporter.store(ready_profile())

    assert "grandMA3" in str(error.value) and "grandMA2" in str(error.value)


def test_a_profile_with_errors_is_rejected_before_anything_is_written(tmp_path):
    environ = make_program_data(tmp_path)
    exporter = FixtureExporter(lambda: Settings(), environ)

    with pytest.raises(ExportError):
        exporter.store(FixtureProfile("a" * 32, "", "", "", (Mode("m"),)))

    assert not list((tmp_path / "ProgramData").rglob("*.xml"))


def test_a_repeated_store_overwrites_the_same_files(tmp_path):
    environ = make_program_data(tmp_path)
    exporter = FixtureExporter(lambda: Settings(), environ)

    exporter.store(ready_profile())
    exporter.store(ready_profile())

    assert len(list((tmp_path / "ProgramData").rglob("*.xml"))) == 3


def test_a_folder_that_cannot_be_created_is_skipped_with_the_reason(tmp_path):
    blocker = tmp_path / "file.txt"
    blocker.write_text("x", encoding="utf-8")
    environ = make_program_data(tmp_path, ma2_versions=())
    exporter = FixtureExporter(lambda: Settings(ma2_fixture_dir=str(blocker / "sub")), environ)

    result = exporter.store(ready_profile())

    assert [target for target, _ in result.written] == ["ma3"] and result.skipped[0].startswith("cannot_use:ma2:")
