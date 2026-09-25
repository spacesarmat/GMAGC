"""Минимальная запись PNG из сырых пикселей RGBA (только стандартная библиотека): картинки слотов колёс в GDTF."""

from __future__ import annotations

import struct
import zlib


def _chunk(kind: bytes, data: bytes) -> bytes:
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)


def rgba_to_png(width: int, height: int, rgba: bytes, circle: bool = False) -> bytes:
    """PNG 8 бит RGBA. `circle` — всё вне вписанного круга делает полностью прозрачным (фон «держателя» гобо по GDTF)."""
    if len(rgba) != width * height * 4:
        raise ValueError("размер пикселей не совпадает с размерами картинки")
    rows = []
    centre_x, centre_y = (width - 1) / 2, (height - 1) / 2
    radius_squared = (min(width, height) / 2) ** 2
    for y in range(height):
        row = bytearray(rgba[y * width * 4 : (y + 1) * width * 4])
        if circle:
            for x in range(width):
                if (x - centre_x) ** 2 + (y - centre_y) ** 2 > radius_squared:
                    row[x * 4 + 3] = 0
        rows.append(b"\x00" + bytes(row))  # фильтр «нет» для каждой строки
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
        + _chunk(b"IEND", b"")
    )
