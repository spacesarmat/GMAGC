"""Подготовка фото из галереи к отправке на ПК (лимит сервера 10 МБ)."""

from __future__ import annotations

import io

UPLOAD_LIMIT = 8 * 1024 * 1024  # запас до лимита сервера
MAX_SIDE = 2560


def prepare_upload(data: bytes, limit: int = UPLOAD_LIMIT) -> bytes:
    """Файл до limit уходит как есть; больший уменьшается Pillow до JPEG не больше limit (иначе ValueError)."""
    if len(data) <= limit:
        return data
    try:
        from PIL import Image, ImageOps

        with Image.open(io.BytesIO(data)) as opened:
            picture = ImageOps.exif_transpose(opened).convert("RGB")
    except Exception as error:  # noqa: BLE001 - нет Pillow или файл не изображение
        raise ValueError("файл не удалось прочитать как изображение") from error
    picture.thumbnail((MAX_SIDE, MAX_SIDE))
    for quality in (85, 70, 55):
        buffer = io.BytesIO()
        picture.save(buffer, "JPEG", quality=quality)
        if len(buffer.getvalue()) <= limit:
            return buffer.getvalue()
    raise ValueError("изображение слишком большое даже после уменьшения")
