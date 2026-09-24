import pytest

from gmagc_common.fixtures import (
    MAX_DMX,
    TEMPLATES,
    Channel,
    FixtureProfile,
    Mode,
    ProfileError,
    Range,
    channel_from_template,
    has_errors,
    new_profile,
    next_free_dmx,
    profile_from_dict,
    profile_to_dict,
    template_by_id,
    validate_profile,
)


def sample_profile():
    dimmer = Channel(1, 8, "Диммер", "dimmer", 0, (Range(0, 255, "0…100%"),))
    pan = Channel(2, 16, "Pan", "pan", 128, ())
    return FixtureProfile("abc", "SHEHDS", "380W Beam", "380WB", (Mode("19 channel", (dimmer, pan)),))


def test_a_new_profile_has_one_empty_mode_and_a_unique_id():
    first, second = new_profile(), new_profile()

    assert first.id != second.id and len(first.modes) == 1 and first.modes[0].channels == ()


def test_the_json_round_trip_keeps_every_field():
    profile = sample_profile()

    assert profile_from_dict(profile_to_dict(profile)) == profile


def test_a_channel_knows_its_width_and_last_address():
    assert Channel(2, 16, "Pan", "pan").width == 2 and Channel(2, 16, "Pan", "pan").last == 3
    assert Channel(5, 8, "Dim", "dimmer").last == 5


def test_every_template_is_usable_and_ids_are_unique():
    ids = [template.id for template in TEMPLATES]

    assert len(ids) == len(set(ids)) and {"dimmer", "pan", "tilt", "gobo_wheel", "custom"} <= set(ids)
    assert all(template.bits in (8, 16) for template in TEMPLATES)
    assert template_by_id("pan").bits == 16


def test_a_channel_from_a_template_gets_its_bits_name_and_ranges():
    channel = channel_from_template("shutter", 7)

    assert channel.dmx == 7 and channel.template == "shutter" and channel.bits == template_by_id("shutter").bits
    assert channel.name == template_by_id("shutter").title and channel.ranges == template_by_id("shutter").ranges


def test_an_unknown_template_is_rejected_when_asked_for_directly():
    with pytest.raises(ProfileError):
        template_by_id("nope")


def test_the_next_free_address_follows_the_last_used_one():
    mode = Mode("m", (Channel(1, 8, "a", "dimmer"), Channel(2, 16, "b", "pan")))

    assert next_free_dmx(Mode("empty")) == 1
    assert next_free_dmx(mode) == 4
    assert next_free_dmx(Mode("full", (Channel(MAX_DMX, 8, "z", "dimmer"),))) == MAX_DMX + 1


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.pop("modes"),
        lambda d: d.update(modes="x"),
        lambda d: d["modes"][0]["channels"][0].update(bits=12),
        lambda d: d["modes"][0]["channels"][0].update(dmx="1"),
        lambda d: d["modes"][0]["channels"][0].update(dmx=True),
        lambda d: d["modes"][0]["channels"][0]["ranges"].append({"start": 0}),
        lambda d: d.update(name=5),
    ],
)
def test_corrupted_data_raises_profile_error(mutate):
    data = profile_to_dict(sample_profile())
    mutate(data)

    with pytest.raises(ProfileError):
        profile_from_dict(data)


def test_a_non_dict_is_rejected():
    with pytest.raises(ProfileError):
        profile_from_dict([1, 2])


def test_an_unknown_template_in_saved_data_falls_back_to_custom():
    data = profile_to_dict(sample_profile())
    data["modes"][0]["channels"][0]["template"] = "from_the_future"

    assert profile_from_dict(data).modes[0].channels[0].template == "custom"


def issues_of(profile):
    return [(issue.path, issue.message, issue.error) for issue in validate_profile(profile)]


def profile_with(*channels, manufacturer="M", name="N", mode_name="Режим"):
    return FixtureProfile("i", manufacturer, name, "", (Mode(mode_name, tuple(channels)),))


def test_a_complete_profile_has_no_issues():
    assert validate_profile(sample_profile()) == []


def test_missing_manufacturer_name_and_modes_are_errors():
    issues = validate_profile(FixtureProfile("i", "", "", "", ()))

    messages = [issue.message for issue in issues]
    assert has_errors(issues) and any("производител" in m for m in messages) and any("название" in m for m in messages)
    assert any("режим" in m for m in messages)


def test_an_empty_mode_and_duplicate_mode_names_are_errors():
    profile = FixtureProfile("i", "M", "N", "", (Mode("A"), Mode("A", (Channel(1, 8, "x", "dimmer"),))))

    messages = [issue.message for issue in validate_profile(profile)]
    assert any("нет каналов" in m for m in messages) and any("повторяется" in m for m in messages)


def test_an_empty_channel_name_is_an_error():
    assert has_errors(validate_profile(profile_with(Channel(1, 8, " ", "dimmer"))))


def test_channels_must_not_overlap_including_the_fine_byte():
    profile = profile_with(Channel(1, 16, "Pan", "pan"), Channel(2, 8, "Tilt", "tilt"))

    assert any("пересека" in issue.message and issue.error for issue in validate_profile(profile))


def test_addresses_must_stay_inside_1_to_512():
    assert has_errors(validate_profile(profile_with(Channel(0, 8, "a", "dimmer"))))
    assert has_errors(validate_profile(profile_with(Channel(MAX_DMX, 16, "a", "pan"))))
    assert not has_errors(validate_profile(profile_with(Channel(MAX_DMX, 8, "a", "dimmer"))))


def test_a_gap_between_channels_is_only_a_warning():
    issues = validate_profile(profile_with(Channel(1, 8, "a", "dimmer"), Channel(5, 8, "b", "red")))

    assert len(issues) == 1 and issues[0].error is False and "пропуск" in issues[0].message


def test_the_default_value_must_be_a_byte():
    assert has_errors(validate_profile(profile_with(Channel(1, 8, "a", "dimmer", 256))))


def test_ranges_must_be_ordered_inside_a_byte_and_not_overlap():
    bad_order = Channel(1, 8, "a", "dimmer", 0, (Range(10, 5, "x"),))
    outside = Channel(1, 8, "a", "dimmer", 0, (Range(0, 300, "x"),))
    overlap = Channel(1, 8, "a", "dimmer", 0, (Range(0, 10, "x"), Range(10, 20, "y")))

    for channel in (bad_order, outside, overlap):
        assert has_errors(validate_profile(profile_with(channel)))


def test_a_hole_between_ranges_is_a_warning_and_the_path_names_the_channel():
    channel = Channel(1, 8, "Гобо", "gobo_wheel", 0, (Range(0, 9, "a"), Range(20, 255, "b")))

    issues = validate_profile(profile_with(channel, mode_name="Стандарт"))

    assert len(issues) == 1 and not issues[0].error and issues[0].path == "Стандарт → Гобо"
