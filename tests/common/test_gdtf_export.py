import base64
import io
import xml.etree.ElementTree as ET
import zipfile
import zlib
from datetime import datetime

import pytest
from PIL import Image

from gmagc_common.fixtures import Channel, FixtureProfile, Gobo, Mode, Range
from gmagc_common.gdtf_export import export_gdtf, fixture_type_id, gdtf_file_name
from gmagc_common.ma3_export import ExportError
from gmagc_common.png_lite import rgba_to_png

NOW = datetime(2026, 9, 24, 12, 0, 0)


def thumb(value=200):
    return base64.b64encode(zlib.compress(bytes([value, value, value, 255]) * 64 * 64)).decode()


GOBOS = (
    Range(0, 9, "open"),
    Range(10, 19, "star", Gobo("star", "GMAGC/star_1a2b3c.png", thumb(), "Stars/star.bmp")),
    Range(20, 29, "dots. 1", Gobo("dots", "GMAGC/dots_4d5e6f.png", thumb(90), "Dots/dots.png")),
)


def moving_head():
    channels = (
        Channel(1, 8, "Dimmer", "dimmer"),
        Channel(2, 16, "Pan", "pan", 128),
        Channel(4, 16, "Tilt", "tilt"),
        Channel(6, 8, "Shutter", "shutter", 0, (Range(5, 9, "closed"), Range(10, 255, "open"))),
        Channel(7, 8, "Gobo", "gobo_wheel", 0, GOBOS),
        Channel(8, 8, "Macro", "control"),
        Channel(9, 8, "Background", "custom"),
    )
    return FixtureProfile("a" * 32, "ACME", "Spot 300", "", (Mode("Standard", channels), Mode("Small", channels[:3])))


def load(profile, **kwargs):
    data = export_gdtf(profile, NOW, **kwargs)
    archive = zipfile.ZipFile(io.BytesIO(data))
    return archive, ET.fromstring(archive.read("description.xml"))


def test_the_archive_holds_the_description_and_one_png_per_gobo_slot():
    archive, root = load(moving_head())

    assert archive.namelist() == ["description.xml", "wheels/star_1a2b3c.png", "wheels/dots_4d5e6f.png"]
    assert root.tag == "GDTF" and root.get("DataVersion") == "1.2"
    fixture = root.find("FixtureType")
    assert fixture.get("Name") == "Spot 300" and fixture.get("Manufacturer") == "ACME"
    assert len(fixture.get("FixtureTypeID")) == 36 and fixture.get("FixtureTypeID") == fixture_type_id("a" * 32)
    order = ["AttributeDefinitions", "Wheels", "Models", "Geometries", "DMXModes", "Revisions"]
    assert [child.tag for child in fixture] == order  # порядок разделов задан спецификацией
    assert [c.tag for c in fixture.find("AttributeDefinitions")] == ["ActivationGroups", "FeatureGroups", "Attributes"]


def test_the_gobo_pictures_are_png_with_a_transparent_holder_as_required_by_annex_e():
    archive, _ = load(moving_head())

    image = Image.open(io.BytesIO(archive.read("wheels/star_1a2b3c.png")))
    assert image.format == "PNG" and image.mode == "RGBA" and image.size == (64, 64)
    assert image.getpixel((0, 0))[3] == 0 and image.getpixel((32, 32)) == (200, 200, 200, 255)


def test_attributes_come_from_the_standard_list_with_features_and_groups_defined():
    _, root = load(moving_head())

    definitions = root.find(".//AttributeDefinitions")
    attributes = {a.get("Name"): a for a in definitions.iter("Attribute")}
    assert list(attributes) == ["Dimmer", "Pan", "Tilt", "Shutter1", "Gobo1", "Control1", "Control2"]
    assert attributes["Pan"].get("Feature") == "Position.PanTilt" and attributes["Pan"].get("PhysicalUnit") == "Angle"
    assert attributes["Gobo1"].get("ActivationGroup") == "Gobo1"
    groups = {g.get("Name"): [f.get("Name") for f in g] for g in definitions.iter("FeatureGroup")}
    for attribute in attributes.values():
        group, feature = attribute.get("Feature").split(".")
        assert feature in groups[group]
    assert {a.get("Name") for a in definitions.iter("ActivationGroup")} == {"PanTilt", "Gobo1"}


def test_dmx_channels_have_offsets_high_byte_first_and_dmx_values_with_byte_counts():
    _, root = load(moving_head())

    mode = root.find(".//DMXMode[@Name='Standard']")
    channels = {c.find("LogicalChannel").get("Attribute"): c for c in mode.iter("DMXChannel")}
    assert channels["Pan"].get("Offset") == "2,3" and channels["Dimmer"].get("Offset") == "1"
    pan = channels["Pan"].find(".//ChannelFunction")
    assert pan.get("DMXFrom") == "0/2" and pan.get("Default") == "32768/2"
    assert (pan.get("PhysicalFrom"), pan.get("PhysicalTo")) == ("-270", "270")
    assert all(c.get("Geometry") == "Body" for c in channels.values())
    names = [c.get("Geometry") + "_" + c.find("LogicalChannel").get("Attribute") for c in mode.iter("DMXChannel")]
    assert len(set(names)) == len(names)  # имя канала DMX уникально в режиме


def test_ranges_become_channel_sets_and_values_below_the_first_range_are_covered():
    _, root = load(moving_head())

    shutter = root.find(".//DMXChannel[@Offset='6']//ChannelFunction")
    sets = shutter.findall("ChannelSet")
    assert [(s.get("Name"), s.get("DMXFrom")) for s in sets] == [(None, "0/1"), ("closed", "5/1"), ("open", "10/1")]


def test_the_gobo_wheel_links_slots_pictures_and_channel_sets():
    _, root = load(moving_head())

    wheel = root.find(".//Wheels/Wheel")
    assert wheel.get("Name") == "Gobo1" and len(root.find(".//Wheels")) == 1
    assert [(s.get("Name"), s.get("MediaFileName")) for s in wheel] == [
        ("open", None),
        ("star", "star_1a2b3c"),
        ("dots_ 1", "dots_4d5e6f"),  # точка в имени запрещена (приложение C) и заменена
    ]
    function = root.find(".//DMXMode[@Name='Standard']//DMXChannel[@Offset='7']//ChannelFunction")
    assert function.get("Wheel") == "Gobo1"
    sets = function.findall("ChannelSet")
    assert [(s.get("WheelSlotIndex"), s.get("DMXFrom")) for s in sets] == [("1", "0/1"), ("2", "10/1"), ("3", "20/1")]


def test_all_modes_are_in_one_file_and_the_same_wheel_is_defined_once():
    _, root = load(moving_head())

    assert [m.get("Name") for m in root.iter("DMXMode")] == ["Standard", "Small"]
    assert len(root.find(".//Wheels")) == 1


def test_custom_and_control_channels_get_numbered_control_attributes():
    _, root = load(moving_head())

    channels = root.find(".//DMXMode[@Name='Standard']").iter("DMXChannel")
    used = [c.find("LogicalChannel").get("Attribute") for c in channels]
    assert used[-2:] == ["Control1", "Control2"]


def test_pictures_from_the_pc_replace_the_thumbnails():
    big = rgba_to_png(2, 2, bytes([9, 9, 9, 255]) * 4)

    archive, _ = load(moving_head(), pictures={"GMAGC/star_1a2b3c.png": big})

    assert archive.read("wheels/star_1a2b3c.png") == big
    assert Image.open(io.BytesIO(archive.read("wheels/dots_4d5e6f.png"))).size == (64, 64)


def test_a_gobo_without_a_thumbnail_and_without_a_pc_picture_is_a_slot_without_media():
    ranges = (Range(0, 9, "open"), Range(10, 19, "star", Gobo("star", "GMAGC/star_1a2b3c.png")))
    channel = Channel(1, 8, "Gobo", "gobo_wheel", 0, ranges)
    profile = FixtureProfile("b" * 32, "M", "N", "", (Mode("Std", (channel,)),))

    archive, root = load(profile)

    assert archive.namelist() == ["description.xml"] and all(s.get("MediaFileName") is None for s in root.iter("Slot"))


def test_a_repeated_unnumbered_template_or_an_unready_profile_is_refused():
    channels = (Channel(1, 8, "A", "dimmer"), Channel(2, 8, "B", "dimmer"))
    with pytest.raises(ExportError):
        export_gdtf(FixtureProfile("c" * 32, "M", "N", "", (Mode("Std", channels),)), NOW)
    with pytest.raises(ExportError):
        export_gdtf(FixtureProfile("d" * 32, "", "", "", (Mode("m"),)), NOW)


def test_the_export_is_reproducible_and_the_file_name_follows_the_gdtf_rule():
    assert export_gdtf(moving_head(), NOW) == export_gdtf(moving_head(), NOW)
    assert gdtf_file_name(moving_head()) == "acme@spot_300.gdtf"


def test_png_writer_rejects_wrong_sizes_and_masks_the_corners_only_when_asked():
    with pytest.raises(ValueError):
        rgba_to_png(2, 2, b"\x00" * 3)
    flat = Image.open(io.BytesIO(rgba_to_png(8, 8, bytes([1, 2, 3, 255]) * 64)))
    assert flat.getpixel((0, 0)) == (1, 2, 3, 255)
    round_ = Image.open(io.BytesIO(rgba_to_png(8, 8, bytes([1, 2, 3, 255]) * 64, circle=True)))
    assert round_.getpixel((0, 0))[3] == 0 and round_.getpixel((4, 4))[3] == 255
