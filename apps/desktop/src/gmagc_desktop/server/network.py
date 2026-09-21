"""Адреса ПК в локальной сети (работает без интернета)."""

from __future__ import annotations

import socket


def _usable(address: str) -> bool:
    return not address.startswith(("127.", "169.254.", "0."))


def _primary_address() -> str | None:
    """Адрес интерфейса, через который ушёл бы трафик в сеть. Пакеты не отправляются: UDP connect лишь выбирает маршрут."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))  # 192.0.2.0/24 зарезервирован для документации
            return probe.getsockname()[0]
    except OSError:
        return None


def _all_addresses() -> list[str]:
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return []
    return [str(info[4][0]) for info in infos]


def lan_addresses() -> list[str]:
    """IPv4 ПК: основной адрес маршрута первым, затем остальные (без loopback и link-local)."""
    found: list[str] = []
    primary = _primary_address()
    for address in ([primary] if primary else []) + _all_addresses():
        if address and _usable(address) and address not in found:
            found.append(address)
    return found
