import asyncio

from gmagc_mobile.store import KEY_LANGUAGE, LanguageStore
from tests.fakes_mobile import FakePrefs


def run(coroutine):
    return asyncio.run(coroutine)


def test_the_language_defaults_to_auto():
    assert run(LanguageStore(FakePrefs()).load()) == "auto"


def test_a_saved_language_comes_back_and_unknown_values_become_auto():
    prefs = FakePrefs()
    store = LanguageStore(prefs)

    run(store.save("en"))
    assert run(LanguageStore(prefs).load()) == "en"
    prefs.data[KEY_LANGUAGE] = "klingon"
    assert run(LanguageStore(prefs).load()) == "auto"
    run(store.save("klingon"))
    assert prefs.data[KEY_LANGUAGE] == "auto"


def test_unavailable_storage_gives_auto_and_does_not_raise_on_save():
    store = LanguageStore(FakePrefs(fail=True))

    assert run(store.load()) == "auto"
    run(store.save("en"))  # сохранить нельзя, но интерфейс от этого не падает
