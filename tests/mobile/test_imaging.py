import io

import numpy as np
import pytest
from PIL import Image

from gmagc_mobile.imaging import UPLOAD_LIMIT, prepare_upload


def png_bytes(width, height):
    x = np.linspace(0, 255, width, dtype=np.uint8)
    y = np.linspace(0, 255, height, dtype=np.uint8)
    pixels = np.stack([np.tile(x, (height, 1)), np.tile(y[:, None], (1, width)), np.full((height, width), 90, np.uint8)], -1)
    buffer = io.BytesIO()
    Image.fromarray(pixels).save(buffer, "PNG")
    return buffer.getvalue()


def test_small_files_are_sent_as_is():
    data = png_bytes(64, 48)

    assert prepare_upload(data) is data and len(data) < UPLOAD_LIMIT


def blobs_png(width, height):
    """Гладкие цветные пятна: PNG получается большим, а JPEG маленьким."""
    rng = np.random.default_rng(3)
    small = Image.fromarray(rng.integers(0, 256, (40, 60, 3), dtype=np.uint8))
    buffer = io.BytesIO()
    small.resize((width, height), Image.BICUBIC).save(buffer, "PNG")
    return buffer.getvalue()


def test_a_file_over_the_limit_is_shrunk_to_a_jpeg_under_the_limit():
    data = blobs_png(3000, 2000)
    limit = 500_000
    assert len(data) > limit

    result = prepare_upload(data, limit=limit)

    assert result.startswith(b"\xff\xd8") and len(result) <= limit
    with Image.open(io.BytesIO(result)) as picture:
        assert max(picture.size) <= 2560


def test_an_image_that_cannot_fit_raises():
    with pytest.raises(ValueError):
        prepare_upload(png_bytes(400, 300), limit=10)


def test_a_big_non_image_raises():
    with pytest.raises(ValueError):
        prepare_upload(b"x" * 2000, limit=1000)
