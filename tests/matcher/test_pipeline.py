import numpy as np

from gmagc_desktop.matcher.normalize import NORM_SIZE
from gmagc_desktop.matcher.pipeline import normalize_photo
from gmagc_desktop.matcher.synthetic import simulate_photo
from tests.helpers import sample_gobo


def test_simulated_photo_gives_normalized_image():
    out = normalize_photo(simulate_photo(sample_gobo(), np.random.default_rng(2)))
    assert out is not None and out.shape == (NORM_SIZE, NORM_SIZE)


def test_flat_photo_gives_none():
    assert normalize_photo(np.full((480, 640, 3), 90, np.uint8)) is None
