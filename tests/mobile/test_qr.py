import io

import pytest
from PIL import Image, ImageFilter

from gmagc_common.protocol import Connection, build_link
from gmagc_desktop.server.qr import qr_png
from gmagc_mobile import qr

LINK = build_link("192.168.1.121", 8765, "ZBZ36YNK")

try:
    from pyzbar import pyzbar as _pyzbar  # noqa: F401

    HAVE_ZBAR = True
except Exception:  # noqa: BLE001 - нет колеса или разделяемой библиотеки zbar
    HAVE_ZBAR = False
needs_zbar = pytest.mark.skipif(not HAVE_ZBAR, reason="нет библиотеки zbar")


def camera_shot(link=LINK, size=(1280, 720), qr_side=360):
    """Похоже на снимок экрана камерой: QR на сером фоне, слегка размытый."""
    code = Image.open(io.BytesIO(qr_png(link))).convert("RGB").resize((qr_side, qr_side), Image.NEAREST)
    canvas = Image.new("RGB", size, (70, 70, 80))
    canvas.paste(code, ((size[0] - qr_side) // 2, (size[1] - qr_side) // 2))
    buffer = io.BytesIO()
    canvas.filter(ImageFilter.GaussianBlur(1.2)).save(buffer, "JPEG", quality=80)
    return buffer.getvalue()


def test_a_missing_decoder_is_reported_as_unavailable(monkeypatch):
    def unavailable():
        raise qr.QrUnavailable("нет zbar")

    monkeypatch.setattr(qr, "_load", unavailable)

    with pytest.raises(qr.QrUnavailable):
        qr.connection_from_qr(b"anything")


@needs_zbar
def test_the_qr_of_the_pc_screen_is_read_from_a_photo():
    assert qr.decode_qr(camera_shot()) == LINK
    assert qr.connection_from_qr(camera_shot()) == Connection("192.168.1.121", 8765, "ZBZ36YNK")


@needs_zbar
def test_the_plain_qr_image_is_read():
    assert qr.decode_qr(qr_png(LINK)) == LINK


@needs_zbar
def test_a_photo_without_a_qr_gives_none():
    buffer = io.BytesIO()
    Image.new("RGB", (640, 480), (120, 120, 120)).save(buffer, "PNG")

    assert qr.decode_qr(buffer.getvalue()) is None
    assert qr.connection_from_qr(buffer.getvalue()) is None


@needs_zbar
def test_bytes_that_are_not_an_image_give_none():
    assert qr.decode_qr(b"definitely not an image") is None


@needs_zbar
def test_a_qr_with_foreign_text_is_not_a_connection():
    assert qr.decode_qr(camera_shot("https://example.com/")) == "https://example.com/"
    assert qr.connection_from_qr(camera_shot("https://example.com/")) is None
