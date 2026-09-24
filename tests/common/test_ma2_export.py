import xml.etree.ElementTree as ET
from datetime import datetime

import pytest

from gmagc_common.fixtures import Channel, FixtureProfile, Mode, Range, channel_from_template
from gmagc_common.ma2_export import ExportError, export_ma2, export_ma2_files, ma2_file_name

NS = "{http://schemas.malighting.de/grandma2/xml/MA}"
NOW = datetime(2026, 9, 24, 12, 30, 0)
PROFILE_ID = "c851712f65ec200040f058d094f47e75"


def profile(*channels, modes=None):
    modes = modes or (Mode("19 channel", tuple(channels)),)
    return FixtureProfile(PROFILE_ID, "SHEHDS", "380W Beam", "380WB", tuple(modes))


def parse(text):
    root = ET.fromstring(text)
    return root, root.find(f"{NS}FixtureType")


def channel_types(fixture_type):
    return fixture_type.find(f"{NS}Modules").find(f"{NS}Module").findall(f"{NS}ChannelType")


def sets_of(channel_type):
    return channel_type.findall(f"{NS}ChannelFunction/{NS}ChannelSet")


def sample_profile():
    return profile(
        Channel(1, 16, "Pan", "pan", 128),
        Channel(3, 16, "Tilt", "tilt", 128),
        Channel(5, 8, "Диммер", "dimmer", 0),
        Channel(6, 8, "Красный", "red"),
    )


def test_the_output_is_well_formed_ma2_xml_with_one_fixture_type_named_after_profile_and_mode():
    text = export_ma2(sample_profile(), 0, now=NOW)

    root, fixture_type = parse(text)
    assert text.startswith('<?xml version="1.0" encoding="utf-8"?>')
    assert root.tag == f"{NS}MA" and root.get("major_vers") == "2" and len(root.findall(f"{NS}FixtureType")) == 1
    assert (fixture_type.get("name"), fixture_type.get("mode")) == ("380W Beam", "19 channel")
    assert fixture_type.find(f"{NS}manufacturer").text == "SHEHDS"
    assert fixture_type.find(f"{NS}short_manufacturer").text == "SHEHDS"
    assert fixture_type.find(f"{NS}short_name").text == "380WB"


def test_sections_follow_the_order_used_by_ma2_files():
    _, fixture_type = parse(export_ma2(sample_profile(), 0, now=NOW))

    tags = [child.tag.replace(NS, "") for child in fixture_type]
    assert tags == ["InfoItems", "short_name", "manufacturer", "short_manufacturer", "Modules", "Instances", "Wheels"]
    info = fixture_type.find(f"{NS}InfoItems")[0]
    assert info.get("type") == "Revision" and info.get("date") == "2026-09-24"


def test_a_moving_head_gets_a_headmover_module_and_a_light_without_pan_a_led_one():
    _, moving = parse(export_ma2(sample_profile(), 0, now=NOW))
    _, static = parse(export_ma2(profile(channel_from_template("dimmer", 1)), 0, now=NOW))

    head = moving.find(f"{NS}Modules/{NS}Module")
    led = static.find(f"{NS}Modules/{NS}Module")
    assert (head.get("class"), head.get("beamtype")) == ("Headmover", "Spot")
    assert (led.get("class"), led.get("beamtype")) == ("LED", "Wash")
    assert head.find(f"{NS}Body/{NS}Size") is not None
    instance = moving.find(f"{NS}Instances/{NS}Instance")
    assert (instance.get("module_index"), instance.get("patch")) == ("0", "1")


def test_channel_types_carry_ma2_attributes_features_presets_and_addresses():
    _, fixture_type = parse(export_ma2(sample_profile(), 0, now=NOW))

    pan, tilt, dim, red = channel_types(fixture_type)
    assert (pan.get("attribute"), pan.get("feature"), pan.get("preset")) == ("PAN", "POSITION", "POSITION")
    assert (tilt.get("attribute"), tilt.get("coarse"), tilt.get("fine")) == ("TILT", "3", "4")
    assert (dim.get("attribute"), dim.get("feature"), dim.get("preset")) == ("DIM", "DIMMER", "DIMMER")
    assert dim.get("coarse") == "5"
    assert dim.get("fine") is None and red.get("attribute") == "COLORRGB1"


def test_sixteen_bit_defaults_are_scaled_and_eight_bit_ones_are_kept():
    _, fixture_type = parse(export_ma2(sample_profile(), 0, now=NOW))

    pan, _, dim, _ = channel_types(fixture_type)
    assert pan.get("default") == "32768"
    assert dim.get("default") is None  # ноль по умолчанию не пишется, как в образцах
    other = profile(Channel(1, 8, "Диммер", "dimmer", 50))
    _, other_type = parse(export_ma2(other, 0, now=NOW))
    assert channel_types(other_type)[0].get("default") == "50"


def test_the_channel_function_repeats_attribute_feature_preset_and_has_the_full_dmx_span():
    _, fixture_type = parse(export_ma2(sample_profile(), 0, now=NOW))

    pan = channel_types(fixture_type)[0].find(f"{NS}ChannelFunction")
    assert (pan.get("attribute"), pan.get("subattribute"), pan.get("feature"), pan.get("preset")) == (
        "PAN",
        "PAN",
        "POSITION",
        "POSITION",
    )
    assert (pan.get("min_dmx_24"), pan.get("max_dmx_24")) == ("0", "16777215")
    assert (pan.get("from"), pan.get("to"), pan.get("physfrom"), pan.get("physto")) == ("-270", "270", "-270", "270")


def test_a_channel_without_ranges_gets_min_and_max_sets_and_pan_also_a_center():
    _, fixture_type = parse(export_ma2(sample_profile(), 0, now=NOW))

    pan, _, dim, _ = channel_types(fixture_type)
    assert [(s.get("name"), s.get("from_dmx"), s.get("to_dmx")) for s in sets_of(pan)] == [
        ("min", "0", "0"),
        ("center", "32768", "32768"),
        ("max", "65535", "65535"),
    ]
    assert [(s.get("name"), s.get("from_dmx")) for s in sets_of(dim)] == [("min", "0"), ("max", "255")]


def test_ranges_become_channel_sets_in_channel_units():
    gobo = Channel(1, 8, "Гобо", "gobo_wheel", 0, (Range(0, 9, "Открыто"), Range(10, 255, "Гобо 1")))
    zoom = Channel(2, 16, "Zoom", "zoom", 0, (Range(0, 127, "Шире"), Range(128, 255, "Уже")))

    _, fixture_type = parse(export_ma2(profile(gobo, zoom), 0, now=NOW))

    gobo_type, zoom_type = channel_types(fixture_type)
    assert [(s.get("name"), s.get("from_dmx"), s.get("to_dmx")) for s in sets_of(gobo_type)] == [
        ("Открыто", "0", "9"),
        ("Гобо 1", "10", "255"),
    ]
    assert [(s.get("from_dmx"), s.get("to_dmx")) for s in sets_of(zoom_type)] == [("0", "32767"), ("32768", "65535")]


def test_numbered_wheels_prisms_and_gobo_rotation_use_ma2_names():
    channels = (
        channel_from_template("color_wheel", 1),
        channel_from_template("gobo_wheel", 2),
        channel_from_template("gobo_rotation", 3),
        channel_from_template("gobo_wheel", 4),
        channel_from_template("prism", 5),
    )

    _, fixture_type = parse(export_ma2(profile(*channels), 0, now=NOW))

    attributes = [c.get("attribute") for c in channel_types(fixture_type)]
    assert attributes == ["COLOR1", "GOBO1", "GOBO1_POS", "GOBO2", "PRISMA1"]
    assert [c.get("feature") for c in channel_types(fixture_type)][1:3] == ["GOBO1", "GOBO1"]
    assert channel_types(fixture_type)[1].get("preset") == "GOBO"


def test_channels_whose_attribute_is_not_confirmed_become_dummy_channels():
    channels = (channel_from_template("iris", 1), channel_from_template("control", 2), channel_from_template("cto", 3))

    _, fixture_type = parse(export_ma2(profile(*channels), 0, now=NOW))

    for channel_type in channel_types(fixture_type):
        function = channel_type.find(f"{NS}ChannelFunction")
        assert channel_type.get("attribute") == "DUMMY" and function.get("subattribute") == "NOFEATURE"
        assert (channel_type.get("feature"), channel_type.get("preset")) == ("CONTROL", "CONTROL")


def test_a_repeated_unnumbered_template_in_one_mode_is_an_error():
    channels = (channel_from_template("dimmer", 1), channel_from_template("dimmer", 2))

    with pytest.raises(ExportError, match="повторя"):
        export_ma2(profile(*channels), 0, now=NOW)


def test_a_profile_with_errors_is_not_exported():
    broken = FixtureProfile("a" * 32, "", "", "", (Mode("m"),))

    with pytest.raises(ExportError) as error:
        export_ma2(broken, 0, now=NOW)

    assert "производител" in str(error.value)


def test_an_unknown_mode_index_is_an_error():
    with pytest.raises(ExportError):
        export_ma2(sample_profile(), 5, now=NOW)


def test_the_file_name_follows_the_ma_library_rule():
    assert ma2_file_name(profile(), Mode("19 channel")) == "shehds@380w_beam@19_channel.xml"
    odd = FixtureProfile("a" * 32, "A&B Co.", "Beam/1", "", ())
    assert ma2_file_name(odd, Mode('Мой "режим"')) == "a_b_co@beam_1@мой_режим.xml"


def test_every_mode_gets_its_own_file():
    two = profile(
        modes=(
            Mode("Standard", (channel_from_template("dimmer", 1),)),
            Mode("Extended", (channel_from_template("dimmer", 1), channel_from_template("red", 2))),
        )
    )

    files = export_ma2_files(two, now=NOW)

    assert [name for name, _ in files] == ["shehds@380w_beam@standard.xml", "shehds@380w_beam@extended.xml"]
    assert [len(channel_types(parse(text)[1])) for _, text in files] == [1, 2]


def test_names_with_xml_special_characters_are_escaped():
    tricky = FixtureProfile("a" * 32, "A&B <Co>", 'Beam "1"', "S", (Mode("m<1>", (Channel(1, 8, "a<b", "dimmer"),)),))

    _, fixture_type = parse(export_ma2(tricky, 0, now=NOW))

    assert fixture_type.get("name") == 'Beam "1"' and fixture_type.get("mode") == "m<1>"
    assert fixture_type.find(f"{NS}manufacturer").text == "A&B <Co>"
