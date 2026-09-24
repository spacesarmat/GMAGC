import base64
import xml.etree.ElementTree as ET
import zlib
from dataclasses import replace

import pytest

from gmagc_common.fixtures import (
    GOBO_THUMB_BYTES,
    Channel,
    FixtureProfile,
    Gobo,
    Mode,
    ProfileError,
    Range,
    gobo_rgba,
    profile_from_dict,
    profile_to_dict,
)
from gmagc_common.ma2_export import export_ma2

NS = "{http://schemas.malighting.de/grandma2/xml/MA}"


def thumb(value=200):
    """Миниатюра 64×64: весь кадр одного серого, непрозрачный."""
    pixel = bytes([value, value, value, 255])
    return base64.b64encode(zlib.compress(pixel * 64 * 64)).decode()


def profile(ranges, template="gobo_wheel"):
    channels = (Channel(1, 8, "Dimmer", "dimmer"), Channel(2, 8, "Gobo", template, 0, tuple(ranges)))
    return FixtureProfile("a" * 32, "ACME", "Spot", "", (Mode("Standard", channels),))


GOBO_RANGES = (
    Range(0, 9, "open"),
    Range(10, 19, "star", Gobo("star", "gmagc/star.png", thumb())),
    Range(20, 29, "dots", Gobo("dots", "gmagc/dots.png", thumb(90))),
)


def test_a_gobo_survives_the_json_round_trip_and_old_profiles_still_load():
    original = profile(GOBO_RANGES)

    restored = profile_from_dict(profile_to_dict(original))

    assert restored == original
    plain = profile_to_dict(profile([Range(0, 9, "open")]))
    assert "gobo" not in plain["modes"][0]["channels"][1]["ranges"][0]
    assert profile_from_dict(plain).modes[0].channels[1].ranges[0].gobo is None


@pytest.mark.parametrize("bad", ["!!!", base64.b64encode(zlib.compress(b"short")).decode(), 5])
def test_a_broken_thumbnail_is_refused_on_load(bad):
    data = profile_to_dict(profile(GOBO_RANGES))
    data["modes"][0]["channels"][1]["ranges"][1]["gobo"]["thumb"] = bad

    with pytest.raises(ProfileError):
        profile_from_dict(data)


def test_the_thumbnail_decodes_to_raw_rgba_of_the_wheel_picture_size():
    rgba = gobo_rgba(Gobo("g", "p.png", thumb(7)))

    assert len(rgba) == GOBO_THUMB_BYTES == 64 * 64 * 4 and rgba[:4] == bytes([7, 7, 7, 255])
    assert gobo_rgba(Gobo("g", "p.png", "")) is None


def test_ma2_gets_a_wheel_with_a_slot_per_range_and_the_picture_inside():
    xml = export_ma2(profile(GOBO_RANGES))

    root = ET.fromstring(xml)
    wheels = root.find(f".//{NS}Wheels")
    assert wheels.get("index") == "1"
    wheel = wheels.find(f"{NS}Wheel")
    assert wheel.attrib == {
        "index": "0",
        "subattribute": "GOBO1",
        "attribute": "GOBO1",
        "feature": "GOBO1",
        "preset": "GOBO",
    }
    slots = wheel.findall(f"{NS}Slot")
    assert [(s.get("index"), s.get("media_name"), s.get("media_filename")) for s in slots] == [
        ("0", "open", None),
        ("1", "star", "gmagc/star.png"),
        ("2", "dots", "gmagc/dots.png"),
    ]
    assert slots[0].find(f"{NS}media") is None
    media = slots[1].find(f"{NS}media")
    assert media.attrib == {"width": "64", "height": "64"}
    assert base64.b64decode("".join(media.find(f"{NS}Image").text.split())) == gobo_rgba(GOBO_RANGES[1].gobo)


def test_ma2_channel_function_points_at_the_wheel_and_every_set_at_its_slot():
    root = ET.fromstring(export_ma2(profile(GOBO_RANGES)))

    channel_type = [c for c in root.iter(f"{NS}ChannelType") if c.get("attribute") == "GOBO1"][0]
    function = channel_type.find(f"{NS}ChannelFunction")
    assert function.get("wheel") == "1"
    sets = function.findall(f"{NS}ChannelSet")
    assert [(s.get("name"), s.get("slot_index"), s.get("slot_from"), s.get("slot_to")) for s in sets] == [
        ("open", "0", "0", "0"),
        ("star", "1", "0", "0"),
        ("dots", "2", "0", "0"),
    ]
    assert [(s.get("from_dmx"), s.get("to_dmx")) for s in sets] == [("0", "9"), ("10", "19"), ("20", "29")]


def test_a_gobo_wheel_without_pictures_and_other_channels_stay_as_before():
    root = ET.fromstring(export_ma2(profile([Range(0, 9, "open"), Range(10, 19, "x")])))

    assert root.find(f".//{NS}Wheels").get("index") is None and len(root.find(f".//{NS}Wheels")) == 0
    function = [c for c in root.iter(f"{NS}ChannelType") if c.get("attribute") == "GOBO1"][0].find(f"{NS}ChannelFunction")
    assert function.get("wheel") is None and function.find(f"{NS}ChannelSet").get("slot_index") is None


def test_a_gobo_on_a_channel_that_is_not_a_gobo_wheel_is_ignored():
    root = ET.fromstring(export_ma2(profile(GOBO_RANGES, template="control")))

    assert len(root.find(f".//{NS}Wheels")) == 0


def test_two_gobo_wheels_are_numbered_in_order():
    channels = (
        Channel(1, 8, "Gobo 1", "gobo_wheel", 0, GOBO_RANGES),
        Channel(2, 8, "Gobo 2", "gobo_wheel", 0, GOBO_RANGES[:2]),
    )
    two = FixtureProfile("a" * 32, "ACME", "Spot", "", (Mode("Standard", channels),))

    root = ET.fromstring(export_ma2(two))

    wheels = root.find(f".//{NS}Wheels")
    assert wheels.get("index") == "2" and [w.get("attribute") for w in wheels] == ["GOBO1", "GOBO2"]
    functions = [c.find(f"{NS}ChannelFunction").get("wheel") for c in root.iter(f"{NS}ChannelType")]
    assert functions == ["1", "2"]


def test_a_broken_thumbnail_in_memory_fails_the_export_clearly():
    from gmagc_common.ma3_export import ExportError

    bad = replace(GOBO_RANGES[1], gobo=Gobo("star", "gmagc/star.png", "@@@"))

    with pytest.raises(ExportError):
        export_ma2(profile([GOBO_RANGES[0], bad]))
