"""Чтение QR-кода подключения из снимка камеры (pyzbar + Pillow) и диагностика чтения."""

from __future__ import annotations

import base64
import io

from gmagc_common.protocol import Connection, parse_link

MAX_SIDE = 1600
SELFTEST_TEXT = "gmagc-selftest"
SELFTEST_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAHQAAAB0AQAAAAB84SuKAAAAlklEQVR42uVVuw3FIBCzsoD339Ib+J1JmlRP8pU5gRCFAX9O"
    "wK8SvrcHQJtn0YV3/dsPPmCZWTo8mJFZ4+kdHht8jljwj/Ch3+qfigLHz4o/KPGkoOM/8Cm0/GmMCCeLDV7zfEKu8zvQ6G+5"
    "1h9QPKz9t1jzf5p3jljkP8/Xpv/G/zY/9/3jYM/fiVB5/+k/YeX/Z/+PHzekg7128icuAAAAAElFTkSuQmCC"
)


class QrUnavailable(RuntimeError):
    """Библиотека чтения QR (pyzbar/zbar) или Pillow недоступна на этом устройстве."""


class QrImageError(Exception):
    """Снимок не удалось открыть как изображение (формат не поддержан Pillow)."""


def _load():
    try:
        from PIL import Image
        from pyzbar import pyzbar
    except Exception as error:  # noqa: BLE001 - нет колеса или нет разделяемой библиотеки zbar
        raise QrUnavailable(str(error)) from error
    return Image, pyzbar


def _variants(picture):
    """Подготовки одного снимка от простой к сложной: как есть, с контрастом, уменьшенные (гасят муар экрана)."""
    from PIL import Image, ImageOps

    yield picture
    yield ImageOps.autocontrast(picture, cutoff=2)
    for scale in (0.6, 0.4):
        size = (max(1, int(picture.width * scale)), max(1, int(picture.height * scale)))
        small = picture.resize(size, Image.LANCZOS)
        yield small
        yield ImageOps.autocontrast(small, cutoff=2)


def _scan(picture, pyzbar) -> str | None:
    for candidate in _variants(picture):
        for symbol in pyzbar.decode(candidate, symbols=[pyzbar.ZBarSymbol.QRCODE]):
            try:
                return symbol.data.decode("utf-8")
            except UnicodeDecodeError:
                continue
    return None


def decode_qr(image: bytes) -> str | None:
    """Текст первого QR-кода на снимке или None, если кода не видно; нечитаемый снимок даёт QrImageError."""
    Image, pyzbar = _load()
    try:
        with Image.open(io.BytesIO(image)) as opened:
            picture = opened.convert("L")
    except Exception as error:  # noqa: BLE001 - причина нужна для диагностики на телефоне
        raise QrImageError(f"{type(error).__name__}: {error}") from error
    picture.thumbnail((MAX_SIDE, MAX_SIDE))
    return _scan(picture, pyzbar)


def connection_from_qr(image: bytes) -> Connection | None:
    text = decode_qr(image)
    return parse_link(text) if text else None


def decode_frame(width: int, height: int, encoded_format: str, data: bytes) -> str | None:
    """Текст QR в кадре потока камеры: JPEG читается как снимок, сырой формат (NV21/YUV420) — по яркостной плоскости
    (первые width×height байт кадра), без перевода цвета — для чтения QR он не нужен."""
    if encoded_format.lower() in ("jpeg", "jpg", "png"):
        return decode_qr(data)
    Image, pyzbar = _load()
    size = width * height
    if width <= 0 or height <= 0 or len(data) < size:
        raise QrImageError(f"кадр камеры повреждён: {len(data)} байт для {width}×{height}")
    picture = Image.frombytes("L", (width, height), data[:size])
    picture.thumbnail((MAX_SIDE, MAX_SIDE))
    return _scan(picture, pyzbar)


def connection_from_frame(width: int, height: int, encoded_format: str, data: bytes) -> Connection | None:
    text = decode_frame(width, height, encoded_format, data)
    return parse_link(text) if text else None


def _image_kind(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "JPEG"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "PNG"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    if data[4:8] == b"ftyp":
        return "HEIF"
    return "неизвестный формат"


def describe_shot(data: bytes) -> str:
    """Формат, размер файла и размеры кадра: `JPEG, 212 КБ, 1280×720`."""
    text = f"{_image_kind(data)}, {len(data) // 1024} КБ"
    try:
        from PIL import Image  # только Pillow: размеры видны, даже если библиотека zbar не загрузилась

        with Image.open(io.BytesIO(data)) as picture:
            text += f", {picture.width}×{picture.height}"
    except Exception:  # noqa: BLE001 - диагностика не должна падать
        text += ", Pillow не открывает"
    return text


def selftest() -> str:
    """Читает встроенный QR тем же путём, что и снимок камеры: `ок` или причина сбоя."""
    try:
        text = decode_qr(SELFTEST_PNG)
    except QrUnavailable as error:
        return f"библиотека недоступна ({error})"
    except QrImageError as error:
        return f"Pillow не открывает PNG ({error})"
    except Exception as error:  # noqa: BLE001
        return f"сбой ({type(error).__name__}: {error})"
    return "ок" if text == SELFTEST_TEXT else f"не прочитан ({text!r})"


def diagnose(data: bytes) -> str:
    return f"снимок: {describe_shot(data)}; самопроверка чтения QR: {selftest()}"
