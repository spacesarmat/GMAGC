import pytest

from gmagc_common.fixtures import Range
from gmagc_common.scan_draft import (
    DraftChannel,
    DraftMode,
    ScanDraft,
    fine_base_name,
    guess_template,
    merge_drafts,
    parse_range_line,
)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("0--5:null;", Range(0, 5, "null")),
        ("6--9:hop", Range(6, 9, "hop")),
        ("14--17:Pulse variation", Range(14, 17, "Pulse variation")),
        ("18--21: effect 4", Range(18, 21, "effect 4")),
        ("22-25:effect 5", Range(22, 25, "effect 5")),
        ("254--255:effect63", Range(254, 255, "effect63")),
        ("242--245: effect 60 Color not selectable", Range(242, 245, "effect 60 Color not selectable")),
        ("0-255 Dimmer", Range(0, 255, "Dimmer")),
        ("0~9 off", Range(0, 9, "off")),
        ("128 - 191 gobo shake", Range(128, 191, "gobo shake")),
        ("0–9: Open", Range(0, 9, "Open")),
    ],
)
def test_range_lines_from_dmx_tables_are_parsed(line, expected):
    assert parse_range_line(line) == expected


@pytest.mark.parametrize(
    "line",
    [
        "Speed, from slow to fast",
        "Color selection 1-43",
        "Strobing",
        "4.DMX Channel:4CH",
        "",
        "Total dimming, linear dimming",
    ],
)
def test_ordinary_text_is_not_a_range(line):
    assert parse_range_line(line) is None


def test_a_range_beyond_a_byte_is_rejected_or_clamped_by_the_caller_not_parsed_as_valid():
    assert parse_range_line("0--300:x") is None


@pytest.mark.parametrize(
    ("name", "template"),
    [
        ("R dimming", "red"),
        ("G Dimming", "green"),
        ("GDimming", "green"),
        ("B dimming", "blue"),
        ("W dimming", "white"),
        ("Red", "red"),
        ("Total dimming", "dimmer"),
        ("Dimmer", "dimmer"),
        ("Master intensity", "dimmer"),
        ("Strobing", "shutter"),
        ("Strobe / Shutter", "shutter"),
        ("Pan", "pan"),
        ("Tilt", "tilt"),
        ("Pan/Tilt speed", "pan_tilt_speed"),
        ("Gobo wheel", "gobo_wheel"),
        ("Gobo 1 rotation", "gobo_rotation"),
        ("Color wheel", "color_wheel"),
        ("Prism", "prism"),
        ("Zoom", "zoom"),
        ("Focus", "focus"),
        ("Iris", "iris"),
        ("Frost", "frost"),
        ("CTO", "cto"),
        ("macro", "control"),
        ("Macro function speed", "control"),
        ("Auto program", "control"),
        ("Background color", "custom"),
        ("Something unknown", "custom"),
        ("", "custom"),
    ],
)
def test_the_template_is_guessed_from_the_channel_name(name, template):
    assert guess_template(name) == template


def test_fine_channels_are_recognized_by_name():
    assert fine_base_name("Pan fine") == "Pan"
    assert fine_base_name("Tilt Fine") == "Tilt"
    assert fine_base_name("Pan (16 bit)") == "Pan"
    assert fine_base_name("Pan LSB") == "Pan"
    assert fine_base_name("Dimmer") is None


def channel(dmx, name, ranges=()):
    return DraftChannel(dmx, name, guess_template(name), 8, tuple(ranges))


def test_drafts_of_consecutive_pages_are_merged_into_the_same_mode_and_channel():
    first = ScanDraft(
        (DraftMode("9CH", (channel(1, "Total dimming"), channel(3, "macro", [Range(0, 5, "null")]))),), (), "local"
    )
    second = ScanDraft(
        (DraftMode("", (channel(3, "macro", [Range(18, 21, "effect 4")]), channel(4, "Macro speed"))),), ("w",), "local"
    )

    merged = merge_drafts(first, second)

    assert [m.name for m in merged.modes] == ["9CH"]
    channels = {c.dmx: c for c in merged.modes[0].channels}
    assert sorted(channels) == [1, 3, 4]
    assert [(r.start, r.end) for r in channels[3].ranges] == [(0, 5), (18, 21)]
    assert merged.warnings == ("w",)


def test_a_new_mode_name_starts_a_new_mode_and_the_same_name_extends_it():
    a = ScanDraft((DraftMode("4CH", (channel(1, "R dimming"),)),), (), "local")
    b = ScanDraft((DraftMode("9CH", (channel(1, "Total dimming"),)),), (), "local")
    c = ScanDraft((DraftMode("9CH", (channel(2, "Strobing"),)),), (), "local")

    merged = merge_drafts(merge_drafts(a, b), c)

    assert [(m.name, [ch.dmx for ch in m.channels]) for m in merged.modes] == [("4CH", [1]), ("9CH", [1, 2])]


def test_a_draft_survives_a_dict_round_trip():
    draft = ScanDraft((DraftMode("9CH", (channel(3, "macro", [Range(0, 5, "null")]),)),), ("warn",), "cloud")

    assert ScanDraft.from_dict(draft.to_dict()) == draft


def test_a_malformed_draft_dict_is_rejected():
    with pytest.raises(ValueError):
        ScanDraft.from_dict({"modes": "x"})


def test_a_channel_without_a_number_continues_the_last_channel_of_the_mode():
    first = ScanDraft((DraftMode("9CH", (channel(3, "macro", [Range(0, 5, "null")]), channel(4, "Speed"))),), (), "local")
    orphan = ScanDraft((DraftMode("", (DraftChannel(0, "", "custom", 8, (Range(226, 229, "effect 56"),)),)),), (), "local")

    merged = merge_drafts(first, orphan)

    channels = {c.dmx: c for c in merged.modes[0].channels}
    assert [(r.start, r.end) for r in channels[4].ranges] == [(226, 229)] and channels[3].ranges[0].start == 0
