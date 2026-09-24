import asyncio
import json

from gmagc_common.fixtures import Channel, FixtureProfile, Mode, new_profile, profile_to_dict
from gmagc_mobile.profile_store import INDEX_KEY, ProfileStore, profile_key
from tests.fakes_mobile import FakePrefs


def run(coroutine):
    return asyncio.run(coroutine)


def make_profile(name="A"):
    return FixtureProfile(f"id-{name}", "M", name, "", (Mode("m", (Channel(1, 8, "d", "dimmer"),)),))


def test_saved_profiles_come_back_in_creation_order():
    store = ProfileStore(FakePrefs())

    run(store.save(make_profile("A")))
    run(store.save(make_profile("B")))
    run(store.save(make_profile("A")))  # повторное сохранение не дублирует запись

    assert [p.name for p in run(store.list())] == ["A", "B"]


def test_a_profile_survives_a_reload_from_the_same_prefs():
    prefs = FakePrefs()
    run(ProfileStore(prefs).save(make_profile("A")))

    assert run(ProfileStore(prefs).list())[0] == make_profile("A")


def test_delete_removes_the_profile_and_its_index_entry():
    prefs = FakePrefs()
    store = ProfileStore(prefs)
    run(store.save(make_profile("A")))

    run(store.delete("id-A"))

    assert run(store.list()) == [] and profile_key("id-A") not in prefs.data


def test_a_corrupted_profile_is_skipped_without_breaking_the_list():
    prefs = FakePrefs()
    store = ProfileStore(prefs)
    run(store.save(make_profile("A")))
    run(store.save(make_profile("B")))
    prefs.data[profile_key("id-A")] = "not json"

    assert [p.name for p in run(store.list())] == ["B"]


def test_a_broken_index_gives_an_empty_list_and_unavailable_storage_too():
    assert run(ProfileStore(FakePrefs({INDEX_KEY: "{{"})).list()) == []
    assert run(ProfileStore(FakePrefs(fail=True)).list()) == []


def test_the_stored_value_is_a_json_string():
    prefs = FakePrefs()
    profile = new_profile("M", "N")
    run(ProfileStore(prefs).save(profile))

    assert json.loads(prefs.data[profile_key(profile.id)]) == profile_to_dict(profile)
