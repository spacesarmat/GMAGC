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
def test_bytes_that_are_not_an_image_raise_an_image_error_with_the_reason():
    with pytest.raises(qr.QrImageError) as error:
        qr.decode_qr(b"definitely not an image")

    assert "UnidentifiedImageError" in str(error.value)


@needs_zbar
def test_a_qr_with_foreign_text_is_not_a_connection():
    assert qr.decode_qr(camera_shot("https://example.com/")) == "https://example.com/"
    assert qr.connection_from_qr(camera_shot("https://example.com/")) is None


@needs_zbar
def test_the_built_in_selftest_qr_is_readable_by_the_real_pipeline():
    assert qr.decode_qr(qr.SELFTEST_PNG) == qr.SELFTEST_TEXT
    assert qr.selftest() == "ок"


@needs_zbar
def test_a_qr_photographed_with_moire_is_still_read_after_preprocessing():
    import numpy as np

    rng = np.random.default_rng(3)
    buffer = io.BytesIO(camera_shot(qr_side=220))
    picture = Image.open(buffer).convert("L")
    pixels = np.array(picture).astype(np.float32)
    yy, xx = np.mgrid[0 : pixels.shape[0], 0 : pixels.shape[1]]
    pixels += 22 * np.sin(2 * np.pi * (xx * 0.9 + yy * 0.4) / 5.5) + rng.normal(0, 5, pixels.shape)
    noisy = io.BytesIO()
    Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8)).save(noisy, "JPEG", quality=60)

    assert qr.decode_qr(noisy.getvalue()) == LINK


def gray_frame(link=LINK, size=(400, 400), qr_side=300):
    """Похоже на кадр потока камеры в сыром формате (NV21/YUV420): яркостная плоскость + произвольная «цветность»."""
    code = Image.open(io.BytesIO(qr_png(link))).convert("L").resize((qr_side, qr_side), Image.NEAREST)
    canvas = Image.new("L", size, 200)
    canvas.paste(code, ((size[0] - qr_side) // 2, (size[1] - qr_side) // 2))
    y_plane = canvas.tobytes()
    chroma = bytes(len(y_plane) // 2)  # NV21: за яркостью следует плоскость цветности, для чтения QR она не нужна
    return size[0], size[1], y_plane + chroma


@needs_zbar
def test_a_jpeg_stream_frame_is_read_like_a_photo():
    width, height, jpeg = 1280, 720, camera_shot()

    assert qr.decode_frame(width, height, "jpeg", jpeg) == LINK
    assert qr.connection_from_frame(width, height, "jpeg", jpeg) == Connection("192.168.1.121", 8765, "ZBZ36YNK")


@needs_zbar
def test_a_raw_stream_frame_is_read_from_its_luma_plane():
    width, height, raw = gray_frame()

    assert qr.decode_frame(width, height, "nv21", raw) == LINK
    assert qr.connection_from_frame(width, height, "yuv420", raw) == Connection("192.168.1.121", 8765, "ZBZ36YNK")


@needs_zbar
def test_a_truncated_raw_frame_is_reported_as_a_frame_error():
    with pytest.raises(qr.QrImageError) as error:
        qr.decode_frame(100, 100, "nv21", b"too short")

    assert "кадр" in str(error.value)


def test_the_shot_description_names_the_format_size_and_dimensions():
    jpeg = io.BytesIO()
    Image.new("RGB", (64, 48), (10, 20, 30)).save(jpeg, "JPEG")

    assert qr.describe_shot(jpeg.getvalue()).startswith("JPEG, 0 КБ, 64×48")
    assert qr.describe_shot(b"\x89PNG\r\n\x1a\n" + b"x" * 2048).startswith("PNG, 2 КБ")
    assert qr.describe_shot(b"RIFF\x00\x00\x00\x00WEBPxxxx").startswith("WEBP")
    assert qr.describe_shot(b"\x00\x00\x00\x18ftypheic").startswith("HEIF")
    assert qr.describe_shot(b"garbage").startswith("неизвестный формат, 0 КБ")


def test_the_selftest_and_diagnosis_report_a_missing_library(monkeypatch):
    def unavailable():
        raise qr.QrUnavailable("нет zbar")

    monkeypatch.setattr(qr, "_load", unavailable)

    assert qr.selftest() == "библиотека недоступна (нет zbar)"
    assert "самопроверка чтения QR: библиотека недоступна" in qr.diagnose(b"\xff\xd8\xffabc")
