import xml.etree.ElementTree as ET
from dataclasses import replace

from gmagc_common.fixtures import Channel, FixtureProfile, Gobo, Mode, Range
from gmagc_common.ma3_export import export_ma3

RANGES = (
    Range(0, 9, "open"),
    Range(10, 19, "star", Gobo("star", "GMAGC/star_1a2b3c.png", "", "Stars/star.bmp")),
    Range(20, 29, "dots", Gobo("dots", "GMAGC/dots_4d5e6f.png", "", "Dots/dots.png")),
)


def profile(ranges=RANGES, template="gobo_wheel", modes=1):
    channels = (Channel(1, 8, "Dimmer", "dimmer"), Channel(2, 8, "Gobo", template, 0, tuple(ranges)))
    return FixtureProfile("a" * 32, "ACME", "Spot", "", tuple(Mode(f"M{n}", channels) for n in range(modes)))


def parse(p):
    return ET.fromstring(export_ma3(p))


def test_a_gobo_wheel_gets_a_wheel_with_a_slot_per_range_and_picture_dependencies():
    root = parse(profile())

    wheels = root.find(".//Wheels")
    wheel = wheels.find("Wheel")
    assert wheel.get("Name") == "Gobo1" and len(wheels) == 1
    slots = wheel.findall("Slot")
    assert [s.get("Name") for s in slots] == ["open", "star", "dots"]
    assert slots[0].get("MediaFileName") is None and slots[0].find("DependencyExport") is None
    star = slots[1]
    assert star.get("MediaFileName") == "GOBO/GMAGC/star_1a2b3c.png" and star.get("Color")
    dependency = star.find("DependencyExport/Dependency")
    assert dependency.get("Base") == "ShowData.MediaPools.Gobos" and dependency.get("RelAddr") == "[star_1a2b3c_png]"
    image = dependency.find("GoboImage")
    assert image.attrib["FileName"] == "star_1a2b3c.png" and image.attrib["FilePath"] == "GMAGC"
    assert image.attrib["Name"] == "[star_1a2b3c_png]" and len(image.attrib["Guid"].split()) == 16
    assert len({s.get("Guid") for s in slots}) == 3


def test_the_channel_function_names_the_wheel_and_every_set_points_at_its_slot():
    root = parse(profile())

    function = root.find(".//DMXChannel[@Coarse='2']//ChannelFunction")
    assert function.get("Wheel") == "Gobo1" and function.get("PhysicalTo") == "3.0000000000"
    sets = function.findall("ChannelSet")
    assert [(s.get("Name"), s.get("WheelSlotIndex"), s.get("DMXFrom")) for s in sets] == [
        ("open", "1", None),
        ("star", "2", "0A0A0A"),
        ("dots", "3", "141414"),
    ]
    assert all(s.get("HasPhysical") == "Yes" and s.get("PhysicalTo") == "0.0000" for s in sets)


def test_without_gobos_the_export_stays_as_before():
    root = parse(profile([Range(0, 9, "open"), Range(10, 19, "x")]))

    assert len(root.find(".//Wheels")) == 0
    function = root.find(".//DMXChannel[@Coarse='2']//ChannelFunction")
    assert function.get("Wheel") is None and function.find("ChannelSet").get("WheelSlotIndex") is None


def test_a_gobo_on_another_template_is_ignored():
    assert len(parse(profile(template="control")).find(".//Wheels")) == 0


def test_the_same_wheel_in_two_modes_is_defined_once_and_a_different_one_gets_its_own_name():
    root = parse(profile(modes=2))
    assert len(root.find(".//Wheels")) == 1
    assert [f.get("Wheel") for f in root.iter("ChannelFunction") if f.get("Wheel")] == ["Gobo1", "Gobo1"]

    other = replace(profile(modes=2).modes[1].channels[1], ranges=RANGES[:2])
    mixed = profile(modes=2)
    mixed = replace(mixed, modes=(mixed.modes[0], Mode("M1", (mixed.modes[1].channels[0], other))))
    root = parse(mixed)
    assert [w.get("Name") for w in root.find(".//Wheels")] == ["Gobo1", "Gobo1_2"]


def test_the_export_is_stable_between_runs():
    assert export_ma3(profile(), None).replace("\n", "") != ""
    a = ET.fromstring(export_ma3(profile())).find(".//Wheel/Slot[@Name='star']").get("Guid")
    b = ET.fromstring(export_ma3(profile())).find(".//Wheel/Slot[@Name='star']").get("Guid")
    assert a == b
