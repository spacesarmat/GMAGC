import numpy as np
from PIL import Image

from gmagc_desktop.matcher.imageio import load_library_gray, load_photo_bgr


def test_transparent_background_becomes_black_even_if_rgb_is_white(tmp_path):
    image = Image.new("RGBA", (32, 32), (255, 255, 255, 0))
    for x in range(10, 20):
        for y in range(10, 20):
            image.putpixel((x, y), (255, 255, 255, 255))
    path = tmp_path / "g.png"
    image.save(path)

    gray = load_library_gray(path)

    assert gray.dtype == np.uint8 and gray.shape == (32, 32)
    assert gray[0, 0] == 0
    assert gray[15, 15] == 255


def test_palette_png_with_transparency(tmp_path):
    image = Image.new("P", (16, 16), 0)
    image.putpalette([255, 255, 255] + [0, 0, 0] * 255)
    image.info["transparency"] = 0
    path = tmp_path / "p.png"
    image.save(path, transparency=0)

    gray = load_library_gray(path)

    assert gray.shape == (16, 16)
    assert gray.max() == 0


def test_bmp_and_grayscale_modes(tmp_path):
    Image.new("RGB", (8, 8), (200, 200, 200)).save(tmp_path / "a.bmp")
    Image.new("L", (8, 8), 90).save(tmp_path / "b.png")

    assert load_library_gray(tmp_path / "a.bmp")[0, 0] == 200
    assert load_library_gray(tmp_path / "b.png")[0, 0] == 90


def test_photo_is_bgr_and_non_ascii_path_works(tmp_path):
    path = tmp_path / "фото.png"
    Image.new("RGB", (10, 6), (255, 0, 0)).save(path)  # красный в RGB

    bgr = load_photo_bgr(path)

    assert bgr.shape == (6, 10, 3)
    assert tuple(bgr[0, 0]) == (0, 0, 255)  # красный в BGR
