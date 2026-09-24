from gmagc_common.fixtures import Channel, Mode, Range
from gmagc_common.scan_apply import add_draft_channels, channel_from_draft
from gmagc_common.scan_draft import DraftChannel


def test_a_draft_channel_keeps_its_name_template_and_ranges():
    draft = DraftChannel(3, "Macro", "control", 8, (Range(0, 5, "null"), Range(6, 9, "hop")))

    channel = channel_from_draft(draft, 3)

    assert (channel.dmx, channel.bits, channel.name, channel.template) == (3, 8, "Macro", "control")
    assert [(r.start, r.end, r.name) for r in channel.ranges] == [(0, 5, "null"), (6, 9, "hop")]


def test_an_unknown_template_becomes_custom_and_a_16_bit_channel_stays_16_bit():
    channel = channel_from_draft(DraftChannel(1, "Pan", "nonsense", 16), 1)

    assert channel.template == "custom" and channel.bits == 16 and channel.last == 2


def test_a_channel_without_ranges_gets_the_ranges_of_its_template():
    channel = channel_from_draft(DraftChannel(1, "Shutter", "shutter"), 1)

    assert channel.ranges


def test_addresses_from_the_manual_are_kept_when_free():
    mode = add_draft_channels(Mode("9CH"), [DraftChannel(2, "B", "custom"), DraftChannel(1, "A", "custom")])

    assert [(c.dmx, c.name) for c in mode.channels] == [(1, "A"), (2, "B")]


def test_a_busy_address_moves_the_channel_after_the_last_one():
    start = Mode("m", (Channel(1, 8, "Dimmer", "dimmer"), Channel(2, 16, "Pan", "pan")))

    mode = add_draft_channels(start, [DraftChannel(2, "Extra", "custom"), DraftChannel(3, "Other", "custom")])

    assert [(c.dmx, c.name) for c in mode.channels[2:]] == [(4, "Extra"), (5, "Other")]


def test_a_channel_without_an_address_goes_last():
    mode = add_draft_channels(Mode("m", (Channel(1, 8, "A", "custom"),)), [DraftChannel(0, "Z", "custom")])

    assert mode.channels[-1].dmx == 2
