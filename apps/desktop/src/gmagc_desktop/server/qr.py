"""QR-код подключения (segno: чистый Python, PNG без Pillow)."""

from __future__ import annotations

import io

import segno


def qr_png(text: str, scale: int = 8) -> bytes:
    buffer = io.BytesIO()
    segno.make(text, error="m").save(buffer, kind="png", scale=scale, border=4)
    return buffer.getvalue()
