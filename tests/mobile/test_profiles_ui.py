import asyncio
from dataclasses import replace

from gmagc_common.fixtures import Channel, FixtureProfile, Mode, new_profile
from gmagc_mobile.profile_store import ProfileStore, profile_key
from gmagc_mobile.profiles_ui import ProfileEditor
from tests.fakes import StubPage, texts
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
