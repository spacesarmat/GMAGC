import asyncio

from gmagc_common.protocol import Connection
from gmagc_mobile.store import KEY_CODE, KEY_HOST, KEY_PORT, ConnectionStore


class FakePrefs:
    """Замена ft.SharedPreferences: словарь с асинхронными методами."""

    def __init__(self, data=None, fail=False):
        self.data = dict(data or {})
        self.fail = fail

    async def get(self, key):
        if self.fail:
            raise RuntimeError("хранилище недоступно")
        return self.data.get(key)

    async def set(self, key, value):
        self.data[key] = value
        return True

    async def remove(self, key):
        return self.data.pop(key, None) is not None


def test_a_saved_connection_is_loaded_back():
    store = ConnectionStore(FakePrefs())
    connection = Connection("192.168.1.5", 8765, "ABCD2345")

    asyncio.run(store.save(connection))

    assert asyncio.run(store.load()) == connection


def test_nothing_saved_gives_none():
    assert asyncio.run(ConnectionStore(FakePrefs()).load()) is None


def test_clear_forgets_the_connection():
    prefs = FakePrefs()
    store = ConnectionStore(prefs)
    asyncio.run(store.save(Connection("192.168.1.5", 8765, "ABCD2345")))

    asyncio.run(store.clear())

    assert asyncio.run(store.load()) is None and prefs.data == {}


def test_a_whole_number_float_port_is_accepted():
    prefs = FakePrefs({KEY_HOST: "10.0.0.7", KEY_PORT: 8766.0, KEY_CODE: "abcd-2345"})

    assert asyncio.run(ConnectionStore(prefs).load()) == Connection("10.0.0.7", 8766, "ABCD2345")


def test_broken_stored_values_give_none():
    bad = [
        {KEY_HOST: "10.0.0.7", KEY_PORT: "8765", KEY_CODE: "ABCD2345"},
        {KEY_HOST: "10.0.0.7", KEY_PORT: True, KEY_CODE: "ABCD2345"},
        {KEY_HOST: "10.0.0.7", KEY_PORT: 8765.5, KEY_CODE: "ABCD2345"},
        {KEY_HOST: "10.0.0.7", KEY_PORT: 70000, KEY_CODE: "ABCD2345"},
        {KEY_HOST: "bad host", KEY_PORT: 8765, KEY_CODE: "ABCD2345"},
        {KEY_HOST: "10.0.0.7", KEY_PORT: 8765, KEY_CODE: "BAD"},
        {KEY_HOST: 5, KEY_PORT: 8765, KEY_CODE: "ABCD2345"},
    ]
    for data in bad:
        assert asyncio.run(ConnectionStore(FakePrefs(data)).load()) is None, data


def test_a_failing_storage_gives_none():
    assert asyncio.run(ConnectionStore(FakePrefs(fail=True)).load()) is None
