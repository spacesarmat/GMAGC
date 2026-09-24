import re
import xml.etree.ElementTree as ET
from datetime import datetime

import pytest

from gmagc_common.fixtures import Channel, FixtureProfile, Mode, Range, channel_from_template
from gmagc_common.ma3_export import ExportError, export_ma3, fixture_guid

GUID = re.compile(r"^([0-9A-F]{2} ){15}[0-9A-F]{2}$")
NOW = datetime(2026, 9, 24, 12, 30, 0)


PROFILE_ID = "c851712f65ec200040f058d094f47e75"


def profile(*channels, modes=None, pid=PROFILE_ID):
    modes = modes or (Mode("Стандарт", tuple(channels)),)
    return FixtureProfile(pid, "SHEHDS", "380W Beam", "380WB", tuple(modes))


def parse(text):
    root = ET.fromstring(text)
    return root, root.find("FixtureType")


def mode_channels(fixture_type, index=0):
    return fixture_type.find("DMXModes")[index].find("DMXChannels")


def attribute_names(fixture_type):
    return [a.get("Name") for a in fixture_type.find("AttributeDefinitions").find("Attributes")]


def sample_profile():
    return profile(
        Channel(1, 8, "Диммер", "dimmer", 0, (Range(0, 255, "0…100%"),)),
        Channel(2, 16, "Pan", "pan", 128),
        Channel(4, 16, "Tilt", "tilt", 128),
        Channel(6, 8, "Красный", "red"),
    )


def test_the_output_is_well_formed_xml_with_the_ma3_root_and_one_fixture_type():
    text = export_ma3(sample_profile(), now=NOW)

    root, fixture_type = parse(text)
    assert text.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert root.tag == "GMA3" and root.get("DataVersion") and len(root) == 1 and fixture_type is not None


def test_the_fixture_type_carries_name_manufacturer_short_name_and_a_guid():
    _, fixture_type = parse(export_ma3(sample_profile(), now=NOW))

    assert fixture_type.get("Name") == "380W Beam" and fixture_type.get("Manufacturer") == "SHEHDS"
    assert fixture_type.get("ShortName") == "380WB" and GUID.match(fixture_type.get("Guid"))


def test_a_missing_short_name_falls_back_to_the_first_characters_of_the_name():
    profile_without_short = FixtureProfile("a" * 32, "M", "Beam 380", "", (Mode("m", (Channel(1, 8, "d", "dimmer"),)),))

    _, fixture_type = parse(export_ma3(profile_without_short, now=NOW))

    assert fixture_type.get("ShortName") == "Beam 380"


def test_the_guid_is_stable_for_a_profile_and_differs_between_profiles():
    first = fixture_guid("c851712f65ec200040f058d094f47e75")

    assert first == "C8 51 71 2F 65 EC 20 00 40 F0 58 D0 94 F4 7E 75"
    assert fixture_guid("c851712f65ec200040f058d094f47e75") == first
    assert fixture_guid("not-a-hex-id") != first and GUID.match(fixture_guid("not-a-hex-id"))
    assert export_ma3(sample_profile(), now=NOW) == export_ma3(sample_profile(), now=NOW)


def test_sections_follow_the_order_used_by_ma_files():
    _, fixture_type = parse(export_ma3(sample_profile(), now=NOW))

    assert [child.tag for child in fixture_type] == [
        "AttributeDefinitions",
        "Wheels",
        "PhysicalDescriptions",
        "Models",
        "Geometries",
        "DMXModes",
        "Revisions",
    ]
    assert fixture_type.find("Revisions")[0].get("Date") == "24.09.2026 12:30:00"


def test_every_mode_becomes_a_dmx_mode_with_its_channels():
    two_modes = profile(
        modes=(
            Mode("Стандарт", (Channel(1, 8, "Диммер", "dimmer"),)),
            Mode("Расширенный", (Channel(1, 8, "Диммер", "dimmer"), Channel(2, 16, "Pan", "pan"))),
        )
    )

    _, fixture_type = parse(export_ma3(two_modes, now=NOW))

    modes = fixture_type.find("DMXModes")
    assert [m.get("Name") for m in modes] == ["Стандарт", "Расширенный"]
    assert [len(m.find("DMXChannels")) for m in modes] == [1, 2]
    assert all(m.get("Geometry") == "Body" for m in modes)


def test_a_16_bit_channel_gets_a_fine_address_and_an_8_bit_one_does_not():
    _, fixture_type = parse(export_ma3(sample_profile(), now=NOW))

    dimmer, pan, tilt, red = list(mode_channels(fixture_type))
    assert (dimmer.get("Coarse"), dimmer.get("Fine")) == ("1", None)
    assert (pan.get("Coarse"), pan.get("Fine")) == ("2", "3")
    assert (tilt.get("Coarse"), tilt.get("Fine")) == ("4", "5") and red.get("Coarse") == "6"


def test_channels_use_the_ma_attribute_of_their_template_and_reference_it_as_default_function():
    _, fixture_type = parse(export_ma3(sample_profile(), now=NOW))

    attributes = [ch.find("LogicalChannel").get("Attribute") for ch in mode_channels(fixture_type)]
    assert attributes == ["Dimmer", "Pan", "Tilt", "ColorRGB_R"]
    assert mode_channels(fixture_type)[1].get("DefaultChannelFunction") == "Pan.Pan 1"


def test_only_the_used_attributes_are_defined_together_with_their_groups_and_features():
    _, fixture_type = parse(export_ma3(sample_profile(), now=NOW))
    definitions = fixture_type.find("AttributeDefinitions")

    assert attribute_names(fixture_type) == ["Dimmer", "Pan", "Tilt", "ColorRGB_R"]
    assert {g.get("Name") for g in definitions.find("ActivationGroups")} == {"PanTilt", "ColorRGB"}
    features = {(g.get("Name"), f.get("Name")) for g in definitions.find("FeatureGroups") for f in g}
    assert features == {("Dimmer", "Dimmer"), ("Position", "PanTilt"), ("Color", "RGB")}


def test_dmx_values_are_written_as_24_bit_hex():
    _, fixture_type = parse(export_ma3(sample_profile(), now=NOW))
    dimmer, pan = list(mode_channels(fixture_type))[:2]

    assert pan.find("LogicalChannel/ChannelFunction").get("Default") == "800000"  # 16 бит, грубый байт 128
    assert dimmer.find("LogicalChannel/ChannelFunction").get("Default") == "000000"
    eight_bit = profile(Channel(1, 8, "Диммер", "dimmer", 1))
    _, other = parse(export_ma3(eight_bit, now=NOW))
    assert mode_channels(other)[0].find("LogicalChannel/ChannelFunction").get("Default") == "010101"


def test_pan_and_tilt_get_their_physical_range():
    _, fixture_type = parse(export_ma3(sample_profile(), now=NOW))
    _, pan, tilt, _ = list(mode_channels(fixture_type))

    pan_function = pan.find("LogicalChannel/ChannelFunction")
    tilt_function = tilt.find("LogicalChannel/ChannelFunction")
    assert (pan_function.get("PhysicalFrom"), pan_function.get("PhysicalTo")) == ("-270", "270")
    assert (tilt_function.get("PhysicalFrom"), tilt_function.get("PhysicalTo")) == ("-135", "135")


def test_ranges_become_channel_sets_with_hex_starts_and_the_first_has_no_dmx_from():
    gobos = Channel(
        1, 8, "Гобо", "gobo_wheel", 0, (Range(0, 9, "Открыто"), Range(10, 19, "Гобо 1"), Range(20, 255, "Гобо 2"))
    )

    _, fixture_type = parse(export_ma3(profile(gobos), now=NOW))

    sets = mode_channels(fixture_type)[0].findall("LogicalChannel/ChannelFunction/ChannelSet")
    assert [(s.get("Name"), s.get("DMXFrom")) for s in sets] == [
        ("Открыто", None),
        ("Гобо 1", "0A0A0A"),
        ("Гобо 2", "141414"),
    ]


def test_a_first_range_that_does_not_start_at_zero_gets_a_leading_unnamed_set():
    channel = Channel(1, 8, "Гобо", "gobo_wheel", 0, (Range(10, 255, "Гобо 1"),))

    _, fixture_type = parse(export_ma3(profile(channel), now=NOW))

    sets = mode_channels(fixture_type)[0].findall("LogicalChannel/ChannelFunction/ChannelSet")
    assert [(s.get("Name"), s.get("DMXFrom")) for s in sets] == [(None, None), ("Гобо 1", "0A0A0A")]


def test_sixteen_bit_ranges_use_the_coarse_byte_followed_by_zero_bytes():
    channel = Channel(1, 16, "Zoom", "zoom", 0, (Range(0, 127, "Уже"), Range(128, 255, "Шире")))

    _, fixture_type = parse(export_ma3(profile(channel), now=NOW))

    sets = mode_channels(fixture_type)[0].findall("LogicalChannel/ChannelFunction/ChannelSet")
    assert [s.get("DMXFrom") for s in sets] == [None, "800000"]


def test_a_channel_without_ranges_has_a_function_without_sets():
    _, fixture_type = parse(export_ma3(profile(Channel(1, 8, "Ctrl", "control")), now=NOW))

    function = mode_channels(fixture_type)[0].find("LogicalChannel/ChannelFunction")
    assert function is not None and len(function) == 0


def test_numbered_templates_get_increasing_attribute_numbers_in_a_mode():
    channels = (
        channel_from_template("gobo_wheel", 1),
        channel_from_template("gobo_rotation", 2),
        channel_from_template("gobo_wheel", 3),
        channel_from_template("gobo_rotation", 4),
    )

    _, fixture_type = parse(export_ma3(profile(*channels), now=NOW))

    attributes = [ch.find("LogicalChannel").get("Attribute") for ch in mode_channels(fixture_type)]
    assert attributes == ["Gobo1", "Gobo1PosRotate", "Gobo2", "Gobo2PosRotate"]
    expected = {"Gobo1", "Gobo1Pos", "Gobo1PosRotate", "Gobo2", "Gobo2Pos", "Gobo2PosRotate"}
    assert expected <= set(attribute_names(fixture_type))


def test_the_rotation_attribute_points_at_its_position_attribute():
    _, fixture_type = parse(export_ma3(profile(channel_from_template("gobo_rotation", 1)), now=NOW))

    definitions = {a.get("Name"): a for a in fixture_type.find("AttributeDefinitions").find("Attributes")}
    assert definitions["Gobo1PosRotate"].get("MainAttribute") == "Gobo1Pos"


def test_a_repeated_unnumbered_template_in_one_mode_is_an_error():
    channels = (channel_from_template("dimmer", 1), channel_from_template("dimmer", 2))

    with pytest.raises(ExportError, match="повторя"):
        export_ma3(profile(*channels), now=NOW)


def test_the_same_template_in_different_modes_is_fine():
    both = profile(
        modes=(
            Mode("A", (channel_from_template("dimmer", 1),)),
            Mode("B", (channel_from_template("dimmer", 1),)),
        )
    )

    _, fixture_type = parse(export_ma3(both, now=NOW))

    assert attribute_names(fixture_type) == ["Dimmer"]


def test_a_profile_with_errors_is_not_exported_and_the_message_lists_them():
    broken = FixtureProfile("a" * 32, "", "", "", (Mode("m"),))

    with pytest.raises(ExportError) as error:
        export_ma3(broken, now=NOW)

    assert "производител" in str(error.value) and "нет каналов" in str(error.value)


def test_names_with_xml_special_characters_are_escaped():
    tricky = FixtureProfile("a" * 32, "A&B <Co>", 'Beam "1"', "S", (Mode("m", (Channel(1, 8, "a<b", "dimmer"),)),))

    root, fixture_type = parse(export_ma3(tricky, now=NOW))

    assert fixture_type.get("Manufacturer") == "A&B <Co>" and fixture_type.get("Name") == 'Beam "1"'


def test_the_geometry_section_has_a_body_model_and_geometry():
    _, fixture_type = parse(export_ma3(sample_profile(), now=NOW))

    assert [m.get("Name") for m in fixture_type.find("Models")] == ["Body"]
    assert [g.get("Name") for g in fixture_type.find("Geometries")] == ["Body"]
    assert fixture_type.find("Geometries")[0].get("Model") == "Body"
