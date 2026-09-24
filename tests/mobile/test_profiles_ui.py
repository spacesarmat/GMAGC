import asyncio
from dataclasses import replace

import flet as ft

from gmagc_common.fixtures import Channel, FixtureProfile, Mode, new_profile
from gmagc_mobile.profile_store import ProfileStore, profile_key
from gmagc_mobile.profiles_ui import ProfileEditor, parse_int
from tests.fakes import StubPage, texts, walk
from tests.fakes_mobile import FakePrefs, FakeShare


def run(coroutine):
    return asyncio.run(coroutine)


def make_editor(prefs=None):
    prefs = prefs if prefs is not None else FakePrefs()
    store = ProfileStore(prefs)
    editor = ProfileEditor(StubPage(), store, FakeShare(), on_exit=lambda: None)
    return editor, store, prefs


def shown(editor):
    return " | ".join(t for t in texts(editor.view) if t)


def test_an_empty_list_offers_to_create_the_first_profile():
    editor, _, _ = make_editor()

    run(editor.open())

    assert editor.screen == "list" and "Нет профилей" in shown(editor)


def test_a_new_profile_is_saved_at_once_and_opens_its_screen():
    editor, store, prefs = make_editor()
    run(editor.open())

    run(editor.on_new_profile(None))

    assert editor.screen == "profile" and editor.profile is not None
    assert len(run(store.list())) == 1 and profile_key(editor.profile.id) in prefs.data


def test_the_list_shows_saved_profiles_with_manufacturer_and_mode_count():
    editor, store, _ = make_editor()
    run(store.save(FixtureProfile("1", "SHEHDS", "380W Beam", "", (Mode("a"), Mode("b")))))

    run(editor.open())

    assert "380W Beam" in shown(editor) and "SHEHDS" in shown(editor) and "2" in shown(editor)


def test_opening_a_profile_from_the_list_shows_its_screen():
    editor, store, _ = make_editor()
    run(store.save(new_profile("M", "N")))
    run(editor.open())

    run(editor.on_open_profile(editor.profiles[0].id))

    assert editor.screen == "profile" and editor.profile.name == "N"


def test_deleting_needs_a_second_confirmation():
    editor, store, _ = make_editor()
    run(store.save(new_profile("M", "N")))
    run(editor.open())
    profile_id = editor.profiles[0].id

    editor.on_ask_delete(profile_id)
    assert len(run(store.list())) == 1 and "Удалить" in shown(editor)
    editor.on_cancel_delete()
    assert len(run(store.list())) == 1
    editor.on_ask_delete(profile_id)
    run(editor.on_confirm_delete(profile_id))

    assert run(store.list()) == [] and "Нет профилей" in shown(editor)


def test_back_from_a_profile_returns_to_the_list_and_from_the_list_is_not_handled():
    editor, store, _ = make_editor()
    run(editor.open())
    run(editor.on_new_profile(None))

    assert editor.go_back() is True and editor.screen == "list"
    assert editor.go_back() is False


def open_new(editor):
    run(editor.open())
    run(editor.on_new_profile(None))


def test_profile_fields_are_saved_as_you_type():
    editor, store, _ = make_editor()
    open_new(editor)

    run(editor.set_profile_text("manufacturer", "SHEHDS"))
    run(editor.set_profile_text("name", "380W Beam"))
    run(editor.set_profile_text("short_name", "380WB"))

    saved = run(store.list())[0]
    assert (saved.manufacturer, saved.name, saved.short_name) == ("SHEHDS", "380W Beam", "380WB")


def test_adding_a_mode_gives_it_a_unique_name_and_saves():
    editor, store, _ = make_editor()
    open_new(editor)

    run(editor.add_mode())

    names = [m.name for m in run(store.list())[0].modes]
    assert names == ["Режим 1", "Режим 2"]


def test_duplicating_a_mode_copies_its_channels_under_a_new_name():
    editor, store, _ = make_editor()
    open_new(editor)
    mode = replace(editor.profile.modes[0], channels=(Channel(1, 8, "d", "dimmer"),))
    with_channel = replace(editor.profile, modes=(mode,))
    run(editor._commit(with_channel))

    run(editor.duplicate_mode(0))

    modes = run(store.list())[0].modes
    assert len(modes) == 2 and modes[1].name != modes[0].name and modes[1].channels == modes[0].channels


def test_the_last_mode_can_not_be_deleted_but_others_can():
    editor, store, _ = make_editor()
    open_new(editor)

    run(editor.delete_mode(0))
    assert len(run(store.list())[0].modes) == 1

    run(editor.add_mode())
    run(editor.delete_mode(0))
    assert len(run(store.list())[0].modes) == 1


def test_renaming_a_mode_is_saved():
    editor, store, _ = make_editor()
    open_new(editor)

    run(editor.rename_mode(0, "Расширенный"))

    assert run(store.list())[0].modes[0].name == "Расширенный"


def test_the_profile_screen_lists_modes_and_shows_validation_messages():
    editor, _, _ = make_editor()
    open_new(editor)

    text = shown(editor)

    assert "Режим 1" in text and "не указан производитель" in text


def test_a_channel_added_from_a_template_gets_the_next_free_address():
    editor, store, _ = make_editor()
    open_new(editor)
    run(editor.open_mode(0))

    run(editor.add_channel("dimmer"))
    run(editor.add_channel("pan"))
    run(editor.add_channel("shutter"))

    channels = run(store.list())[0].modes[0].channels
    assert [(c.dmx, c.bits, c.template) for c in channels] == [(1, 8, "dimmer"), (2, 16, "pan"), (4, 8, "shutter")]


def test_deleting_a_channel_keeps_the_others_untouched():
    editor, store, _ = make_editor()
    open_new(editor)
    run(editor.open_mode(0))
    run(editor.add_channel("dimmer"))
    run(editor.add_channel("red"))

    run(editor.delete_channel(0))

    assert [c.template for c in run(store.list())[0].modes[0].channels] == ["red"]


def test_the_mode_screen_shows_channels_in_dmx_order_and_validation_messages():
    editor, _, _ = make_editor()
    open_new(editor)
    run(editor.open_mode(0))
    run(editor.add_channel("dimmer"))
    run(editor.add_channel("pan"))

    text = shown(editor)

    assert "Диммер" in text and "Pan" in text


def test_a_channel_added_beyond_512_is_reported_as_an_error_on_the_screen():
    editor, store, _ = make_editor()
    open_new(editor)
    run(editor.open_mode(0))
    profile = run(store.list())[0]
    run(editor._commit(replace(profile, modes=(replace(profile.modes[0], channels=(Channel(512, 8, "z", "dimmer"),)),))))
    run(editor.add_channel("dimmer"))

    assert "адрес должен лежать" in shown(editor)


def test_opening_a_channel_switches_to_the_channel_screen():
    editor, _, _ = make_editor()
    open_new(editor)
    run(editor.open_mode(0))
    run(editor.add_channel("dimmer"))

    run(editor.open_channel(0))

    assert editor.screen == "channel" and editor.go_back() is True and editor.screen == "mode"


def open_channel_of(editor, template="gobo_wheel"):
    open_new(editor)
    run(editor.open_mode(0))
    run(editor.add_channel(template))
    run(editor.open_channel(0))


def saved_channel(store):
    return run(store.list())[0].modes[0].channels[0]


def test_channel_fields_are_saved():
    editor, store, _ = make_editor()
    open_channel_of(editor)

    run(editor.set_channel(name="Гобо 1", dmx=9, bits=16, default=10))

    channel = saved_channel(store)
    assert (channel.name, channel.dmx, channel.bits, channel.default) == ("Гобо 1", 9, 16, 10)


def test_changing_the_template_keeps_name_and_address_but_takes_bits_and_ranges():
    editor, store, _ = make_editor()
    open_channel_of(editor, "dimmer")
    run(editor.set_channel(name="Мой канал", dmx=5))

    run(editor.set_channel(template="pan"))

    channel = saved_channel(store)
    assert (channel.name, channel.dmx, channel.template, channel.bits) == ("Мой канал", 5, "pan", 16)


def test_ranges_can_be_added_edited_and_deleted():
    editor, store, _ = make_editor()
    open_channel_of(editor, "control")

    run(editor.add_range())
    run(editor.set_range(0, start=0, end=9, name="Открыто"))
    run(editor.add_range())
    run(editor.set_range(1, start=10, end=255, name="Гобо 1"))
    assert [(r.start, r.end, r.name) for r in saved_channel(store).ranges] == [(0, 9, "Открыто"), (10, 255, "Гобо 1")]

    run(editor.delete_range(0))

    assert [r.name for r in saved_channel(store).ranges] == ["Гобо 1"]


def test_a_new_range_starts_right_after_the_previous_one():
    editor, store, _ = make_editor()
    open_channel_of(editor, "gobo_wheel")  # шаблон даёт диапазон 0–9

    run(editor.add_range())

    added = saved_channel(store).ranges[-1]
    assert (added.start, added.end) == (10, 255)


def test_non_numeric_input_keeps_the_previous_value():
    assert parse_int("12", 5) == 12 and parse_int("x", 5) == 5 and parse_int("", 5) == 5


def test_the_channel_screen_shows_range_rows():
    editor, _, _ = make_editor()
    open_channel_of(editor, "gobo_wheel")

    values = [c.value for c in walk(editor.view) if isinstance(c, ft.TextField)]
    assert "Открыто" in values
