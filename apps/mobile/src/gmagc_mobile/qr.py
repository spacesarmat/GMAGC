"""Чтение QR-кода подключения из снимка камеры (pyzbar + Pillow)."""

from __future__ import annotations

import io

from gmagc_common.protocol import Connection, parse_link

MAX_SIDE = 1600


class QrUnavailable(RuntimeError):
    """Библиотека чтения QR (pyzbar/zbar) или Pillow недоступна на этом устройстве."""


def _load():
    try:
        from PIL import Image
        from pyzbar import pyzbar
    except Exception as error:  # noqa: BLE001 - нет колеса или нет разделяемой библиотеки zbar
        raise QrUnavailable(str(error)) from error
    return Image, pyzbar


def decode_qr(image: bytes) -> str | None:
    """Текст первого QR-кода на снимке или None, если кода не видно."""
    Image, pyzbar = _load()
    try:
        with Image.open(io.BytesIO(image)) as opened:
            picture = opened.convert("L")
    except Exception:  # noqa: BLE001 - не изображение
        return None
    picture.thumbnail((MAX_SIDE, MAX_SIDE))
    for symbol in pyzbar.decode(picture, symbols=[pyzbar.ZBarSymbol.QRCODE]):
        try:
            return symbol.data.decode("utf-8")
        except UnicodeDecodeError:
            continue
    return None


def connection_from_qr(image: bytes) -> Connection | None:
    text = decode_qr(image)
    return parse_link(text) if text else None
