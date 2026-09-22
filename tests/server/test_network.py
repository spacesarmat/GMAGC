import time

from gmagc_desktop.server import network


def test_primary_address_goes_first_and_duplicates_and_unusable_ones_are_dropped(monkeypatch):
    monkeypatch.setattr(network, "_primary_address", lambda: "192.168.1.5")
    monkeypatch.setattr(
        network, "_all_addresses", lambda: ["127.0.0.1", "169.254.10.3", "10.0.0.7", "192.168.1.5", "0.0.0.0"]
    )

    assert network.lan_addresses() == ["192.168.1.5", "10.0.0.7"]


def test_without_a_route_the_hostname_addresses_are_used(monkeypatch):
    monkeypatch.setattr(network, "_primary_address", lambda: None)
    monkeypatch.setattr(network, "_all_addresses", lambda: ["10.0.0.7"])

    assert network.lan_addresses() == ["10.0.0.7"]


def test_no_network_gives_an_empty_list(monkeypatch):
    monkeypatch.setattr(network, "_primary_address", lambda: None)
    monkeypatch.setattr(network, "_all_addresses", lambda: [])

    assert network.lan_addresses() == []


def test_a_slow_hostname_lookup_does_not_block_past_the_timeout(monkeypatch):
    """На некоторых системах (macOS, имя хоста оканчивается на .local) резолв через mDNS может
    подвисать на десятки секунд — этот список лишь дополняет основной адрес, ждать его нельзя."""

    def slow_getaddrinfo(*_args, **_kwargs):
        time.sleep(5)
        return [(None, None, None, None, ("10.0.0.9", 0))]

    monkeypatch.setattr(network.socket, "getaddrinfo", slow_getaddrinfo)
    monkeypatch.setattr(network, "HOSTNAME_LOOKUP_TIMEOUT", 0.05)

    started = time.monotonic()
    result = network._all_addresses()

    assert result == [] and time.monotonic() - started < 1.0


def test_real_lookup_returns_only_ipv4_strings():
    for address in network.lan_addresses():
        parts = address.split(".")
        assert len(parts) == 4 and all(part.isdigit() and 0 <= int(part) <= 255 for part in parts)
        assert not address.startswith(("127.", "169.254."))
