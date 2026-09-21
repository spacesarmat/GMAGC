import cv2
import numpy as np

from gmagc_desktop.matcher.thumbnail import square_pad, thumbnail_png


def test_thumbnail_png_is_a_square_png_of_the_requested_size():
    data = thumbnail_png(np.full((10, 20), 200, np.uint8), 32)

    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
    assert data.startswith(b"\x89PNG") and image.shape == (32, 32)


def test_square_pad_centres_a_tall_image():
    padded = square_pad(np.full((20, 10), 100, np.uint8))

    assert padded.shape == (20, 20)
    assert np.all(padded[:, :5] == 0) and np.all(padded[:, 15:] == 0) and np.all(padded[:, 5:15] == 100)
