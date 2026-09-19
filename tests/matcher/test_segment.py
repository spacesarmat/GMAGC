import cv2
import numpy as np

from gmagc_desktop.matcher.segment import extract_projection
from gmagc_desktop.matcher.synthetic import simulate_photo
from tests.helpers import sample_gobo


def test_finds_projection_on_cluttered_wall():
    photo = simulate_photo(sample_gobo(), np.random.default_rng(1))
    crop = extract_projection(photo)
    assert crop is not None
    assert 120 < max(crop.shape) < 420  # ~30-40% высоты кадра после уменьшения до 1024 px
    assert (crop > 0).mean() > 0.05


def test_many_seeds_never_pick_the_background():
    for seed in range(12):
        photo = simulate_photo(sample_gobo(), np.random.default_rng(seed))
        crop = extract_projection(photo)
        assert crop is not None, seed
        assert 120 < max(crop.shape) < 420, seed


def test_returns_none_for_flat_photo():
    flat = np.full((480, 640, 3), 90, np.uint8)
    assert extract_projection(flat) is None


def test_close_up_projection_filling_the_frame_is_still_found():
    image = np.zeros((480, 640, 3), np.uint8)
    cv2.circle(image, (320, 240), 230, (255, 240, 220), 40)
    assert extract_projection(image) is not None


def test_multiple_blobs_are_merged_into_one_crop():
    photo = simulate_photo(sample_gobo(), np.random.default_rng(3))
    crop = extract_projection(photo)
    small = cv2.resize(crop, (64, 64))
    assert (small > 127).sum() > 100
