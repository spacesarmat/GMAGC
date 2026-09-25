"""Чтение QR на чистом Python: матрицы из segno, поврежденные модули, снимки с поворотом, перекосом и шумом."""

import random

import pytest
import segno

from gmagc_common import qr_decode
from gmagc_common.protocol import build_link, parse_link


def matrix_of(text, error="M", version=None):
    code = segno.make(text, error=error, version=version, micro=False, boost_error=False, encoding="utf-8")
    return [[1 if cell else 0 for cell in row] for row in code.matrix], code


def render(matrix, scale=6, border=4, invert=False):
    """Серое изображение: тёмные модули = 20, светлые = 235; вокруг светлая тихая зона."""
    size = len(matrix)
    side = (size + 2 * border) * scale
    data = bytearray([235] * (side * side))
    for r in range(size):
        for c in range(size):
            if matrix[r][c]:
                for y in range((r + border) * scale, (r + border + 1) * scale):
                    start = y * side + (c + border) * scale
                    data[start : start + scale] = bytes([20]) * scale
    if invert:
        data = bytearray(255 - v for v in data)
    return bytes(data), side, side


def rotate(gray, w, h):
    """Поворот на 90° по часовой стрелке."""
    return bytes(gray[(h - 1 - x) * w + y] for y in range(w) for x in range(h)), h, w


@pytest.mark.parametrize("error", ["L", "M", "Q", "H"])
@pytest.mark.parametrize("text", ["gmagc://192.168.0.5:8765/V7QJ2B4Z", "A" * 20, "1234567890" * 3, "Привет, гобо!"])
def test_matrices_from_a_reference_generator_are_decoded_in_every_level_and_mode(text, error):
    matrix, _ = matrix_of(text, error)

    assert qr_decode.decode_matrix(matrix) == text


@pytest.mark.parametrize("version", range(1, 11))
@pytest.mark.parametrize("error", ["L", "M", "Q", "H"])
def test_every_supported_version_and_level_decodes(version, error):
    text = "GMAGC-1"  # 7 байт помещаются даже в версию 1 с уровнем H
    matrix, code = matrix_of(text, error, version)

    assert qr_decode.decode_matrix(matrix) == text
    assert len(matrix) == 17 + 4 * version and code.version == version


def test_damaged_modules_are_repaired_by_the_error_correction():
    text = "gmagc://10.0.0.7:8765/ABCD2345"
    matrix, _ = matrix_of(text, "H")
    rng = random.Random(7)
    for _ in range(12):  # случайные модули вне поисковых узоров: несколько кодовых слов повреждены
        r, c = rng.randrange(9, len(matrix) - 9), rng.randrange(9, len(matrix) - 9)
        matrix[r][c] ^= 1

    assert qr_decode.decode_matrix(matrix) == text


def test_too_much_damage_gives_none_instead_of_wrong_text():
    matrix, _ = matrix_of("gmagc://10.0.0.7:8765/ABCD2345", "L")
    for r in range(10, len(matrix) - 3):
        for c in range(10, len(matrix) - 3):
            matrix[r][c] ^= 1

    assert qr_decode.decode_matrix(matrix) is None


def test_a_rendered_image_is_read():
    text = "gmagc://192.168.0.5:8765/V7QJ2B4Z"
    matrix, _ = matrix_of(text, "M")
    gray, w, h = render(matrix, scale=5)

    assert qr_decode.decode_qr(gray, w, h) == text


@pytest.mark.parametrize("turns", [1, 2, 3])
def test_a_rotated_image_is_read(turns):
    text = "gmagc://192.168.0.5:8765/V7QJ2B4Z"
    matrix, _ = matrix_of(text, "M")
    gray, w, h = render(matrix, scale=5)
    for _ in range(turns):
        gray, w, h = rotate(gray, w, h)

    assert qr_decode.decode_qr(gray, w, h) == text


def test_noise_and_uneven_light_do_not_stop_the_reader():
    text = "gmagc://192.168.0.5:8765/V7QJ2B4Z"
    matrix, _ = matrix_of(text, "Q")
    gray, w, h = render(matrix, scale=6)
    rng = random.Random(3)
    out = bytearray(gray)
    for y in range(h):
        for x in range(w):
            shade = int(60 * x / w) - 20  # свет слева ярче, чем справа
            out[y * w + x] = min(255, max(0, out[y * w + x] + shade + rng.randint(-25, 25)))

    assert qr_decode.decode_qr(bytes(out), w, h) == text


def test_a_skewed_image_is_read():
    text = "gmagc://192.168.0.5:8765/V7QJ2B4Z"
    matrix, _ = matrix_of(text, "M")
    gray, w, h = render(matrix, scale=6)
    skew = 0.08  # сдвиг строк: небольшой перекос от неровно взятого телефона
    out = bytearray([235] * (w * h))
    for y in range(h):
        shift = int((y - h / 2) * skew)
        for x in range(w):
            sx = x - shift
            if 0 <= sx < w:
                out[y * w + x] = gray[y * w + sx]

    assert qr_decode.decode_qr(bytes(out), w, h) == text


def test_a_large_camera_frame_is_reduced_and_read():
    text = "gmagc://192.168.0.5:8765/V7QJ2B4Z"
    matrix, _ = matrix_of(text, "M")
    tile, side, _ = render(matrix, scale=16)
    frame_w, frame_h = 1600, 1200
    frame = bytearray([200] * (frame_w * frame_h))
    left, top = 400, 200
    for y in range(side):
        frame[(top + y) * frame_w + left : (top + y) * frame_w + left + side] = tile[y * side : (y + 1) * side]

    assert qr_decode.decode_qr(bytes(frame), frame_w, frame_h) == text


def test_pictures_without_a_code_or_with_bad_sizes():
    assert qr_decode.decode_qr(bytes([200]) * 100 * 100, 100, 100) is None
    with pytest.raises(ValueError):
        qr_decode.decode_qr(b"\x00" * 10, 100, 100)


def test_the_connection_link_survives_the_whole_path():
    link = build_link("192.168.0.5", 8765, "V7QJ2B4Z")
    matrix, _ = matrix_of(link, "M")
    gray, w, h = render(matrix, scale=5)

    connection = parse_link(qr_decode.decode_qr(gray, w, h))

    assert (connection.host, connection.port, connection.code) == ("192.168.0.5", 8765, "V7QJ2B4Z")
