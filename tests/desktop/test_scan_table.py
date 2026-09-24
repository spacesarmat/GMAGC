import json
from pathlib import Path

from gmagc_common.scan_draft import WARN_NO_TABLE, merge_drafts
from gmagc_desktop.scan.table import OcrItem, items_from_dict, parse_tables

DATA = Path(__file__).resolve().parents[1] / "data" / "ocr"


def load(name):
    return items_from_dict(json.loads((DATA / f"{name}.json").read_text(encoding="utf-8")))


def channels_of(draft, mode_name):
    mode = next(m for m in draft.modes if m.name == mode_name)
    return {c.dmx: c for c in mode.channels}


def test_a_photo_of_a_four_channel_table_gives_rgbw_dimming_channels():
    draft = parse_tables(load("led_bar_photo_4ch"))

    assert [m.name for m in draft.modes] == ["4CH"]
    channels = channels_of(draft, "4CH")
    assert sorted(channels) == [1, 2, 3, 4]
    assert [channels[n].template for n in (1, 2, 3, 4)] == ["red", "green", "blue", "white"]
    assert all("imming" in channels[n].name for n in channels) and draft.warnings == ()


def test_a_scanned_page_with_two_headings_gives_two_modes():
    draft = parse_tables(load("led_bar_scan_p04"))

    assert [m.name for m in draft.modes] == ["4CH", "9CH"]
    four = channels_of(draft, "4CH")
    assert [four[n].template for n in (1, 2, 3, 4)] == ["red", "green", "blue", "white"]
    nine = channels_of(draft, "9CH")
    assert sorted(nine) == [1, 2, 3]
    assert [nine[n].template for n in (1, 2, 3)] == ["dimmer", "shutter", "control"]
    assert [(r.start, r.end, r.name) for r in nine[3].ranges[:4]] == [
        (0, 5, "null"),
        (6, 9, "hop"),
        (10, 13, "Gradient"),
        (14, 17, "Pulsevariation"),  # пробел потерял сам OCR
    ]


def test_a_continuation_page_without_a_heading_gives_a_nameless_mode_with_the_repeated_channel():
    draft = parse_tables(load("led_bar_scan_p05"))

    assert [m.name for m in draft.modes] == [""]
    ranges = channels_of(draft, "")[3].ranges
    assert (ranges[0].start, ranges[0].end) == (18, 21) and len(ranges) > 50


def test_pages_of_the_scan_merge_into_one_nine_channel_mode():
    merged = merge_drafts(parse_tables(load("led_bar_scan_p04")), parse_tables(load("led_bar_scan_p05")))

    nine = channels_of(merged, "9CH")
    starts = [r.start for r in nine[3].ranges]
    assert starts[:5] == [0, 6, 10, 14, 18] and starts == sorted(starts) and len(nine[3].ranges) >= 54


def test_phone_photos_of_the_nine_channel_table_merge_into_the_full_mode():
    merged = merge_drafts(parse_tables(load("led_bar_photo_9ch_top")), parse_tables(load("led_bar_photo_9ch_end")))

    nine = channels_of(merged, "9CH")
    assert sorted(nine) == [1, 2, 3, 4, 5, 6, 7, 8, 9]
    assert [nine[n].template for n in (1, 2, 4, 6, 7, 8, 9)] == [
        "dimmer",
        "shutter",
        "control",
        "red",
        "green",
        "blue",
        "white",
    ]
    assert nine[3].template == "control" and len(nine[3].ranges) > 55
    assert nine[5].template == "custom" and "ackground" in nine[5].name
    assert nine[3].ranges[-1].end == 255


def test_an_orphan_range_block_at_the_top_of_a_page_continues_the_last_channel_of_the_mode():
    top = parse_tables(load("led_bar_photo_9ch_top"))
    end = parse_tables(load("led_bar_photo_9ch_end"))

    assert 0 in channels_of(end, "")  # диапазоны над первой меткой «Channel N» — продолжение прежнего канала
    assert len(channels_of(merge_drafts(top, end), "9CH")[3].ranges) > len(channels_of(top, "9CH")[3].ranges)


def test_a_page_without_any_table_gives_an_empty_draft_and_a_warning_code():
    page = [OcrItem(10, 10, 200, 30, "Specification", 0.9), OcrItem(10, 40, 200, 60, "Voltage: AC100-240V", 0.9)]
    draft = parse_tables(page)

    assert draft.modes == () and draft.warnings == (WARN_NO_TABLE,)
    assert parse_tables([]).warnings == (WARN_NO_TABLE,)


def test_a_fine_channel_is_folded_into_its_sixteen_bit_main_channel():
    items = [
        OcrItem(10, 10, 300, 30, "6.DMX Channel:3CH", 0.9),
        OcrItem(20, 60, 90, 80, "Channel1", 0.9),
        OcrItem(200, 60, 260, 80, "Pan", 0.9),
        OcrItem(350, 60, 500, 80, "Pan movement", 0.9),
        OcrItem(20, 100, 90, 120, "Channel2", 0.9),
        OcrItem(200, 100, 260, 120, "Pan fine", 0.9),
        OcrItem(350, 100, 500, 120, "Pan fine movement", 0.9),
        OcrItem(20, 140, 90, 160, "Channel3", 0.9),
        OcrItem(200, 140, 260, 160, "Tilt", 0.9),
        OcrItem(350, 140, 500, 160, "Tilt movement", 0.9),
    ]

    channels = channels_of(parse_tables(items), "3CH")

    assert sorted(channels) == [1, 3] and channels[1].bits == 16 and channels[1].template == "pan"
    assert channels[3].template == "tilt"


def test_extra_text_next_to_a_range_joins_its_name():
    items = [
        OcrItem(10, 10, 300, 30, "5.DMX Channel:2CH", 0.9),
        OcrItem(20, 60, 90, 80, "Channel1", 0.9),
        OcrItem(200, 60, 260, 80, "macro", 0.9),
        OcrItem(350, 60, 470, 80, "242--245: effect 60", 0.9),
        OcrItem(480, 60, 600, 80, "Color not selectable", 0.9),
        OcrItem(350, 84, 470, 104, "246--249: effect 61", 0.9),
    ]

    ranges = channels_of(parse_tables(items), "2CH")[1].ranges

    assert [(r.start, r.end, r.name) for r in ranges] == [
        (242, 245, "effect 60 Color not selectable"),
        (246, 249, "effect 61"),
    ]


# ---- строка «......» между каналами -----------------------------------------------------------
def synthetic_rows(rows, dots_after=None):
    """Строки таблицы `(метка, функция, описание)`; пустая метка вместе с «......» — строка пропуска."""
    items, y = [], 100.0
    for label, function, description in rows:
        for x0, text in ((80, label), (250, function), (500, description)):
            if text:
                items.append(OcrItem(x0, y, x0 + 8 * len(text), y + 16, text))
        y += 20
    return items


def test_a_dots_row_between_two_channels_fills_the_skipped_channels_with_numbered_names():
    rows = [
        ("Channel 9", "R Dimming", "Linear dimming"),
        ("Channel 10", "1 Dimming", "Linear dimming"),
        ("", "......", ""),
        ("Channel 13", "4 Dimming", "Linear dimming"),
    ]
    items = synthetic_rows(rows)
    items += [OcrItem(x, 140, x + 50, 156, "......") for x in (80, 250, 500)]
    items = [i for i in items if i.text]

    draft = parse_tables(items)

    channels = {c.dmx: c for c in draft.modes[0].channels}
    assert sorted(channels) == [9, 10, 11, 12, 13]
    assert [channels[n].name for n in (10, 11, 12, 13)] == ["1 Dimming", "2 Dimming", "3 Dimming", "4 Dimming"]
    assert channels[11].template == "dimmer" and channels[11].confidence < 1.0 and channels[10].confidence == 1.0
    assert channels[11].name and "......" not in channels[10].name + channels[10].note


def test_skipped_channels_without_a_number_pattern_copy_the_channel_name():
    items = [
        OcrItem(80, 100, 150, 116, "Channel 1"),
        OcrItem(250, 100, 320, 116, "Dimmer"),
        OcrItem(80, 120, 130, 136, "......"),
        OcrItem(250, 120, 300, 136, "......"),
        OcrItem(80, 140, 150, 156, "Channel 4"),
        OcrItem(250, 140, 320, 156, "Dimmer"),
    ]

    channels = {c.dmx: c for c in parse_tables(items).modes[0].channels}

    assert sorted(channels) == [1, 2, 3, 4] and channels[2].name == channels[3].name == "Dimmer"


def test_a_dots_row_without_a_following_channel_adds_nothing():
    items = [
        OcrItem(80, 100, 150, 116, "Channel 1"),
        OcrItem(250, 100, 320, 116, "Dimmer"),
        OcrItem(80, 120, 130, 136, "......"),
    ]

    assert [c.dmx for c in parse_tables(items).modes[0].channels] == [1]
