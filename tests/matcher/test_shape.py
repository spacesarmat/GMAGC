import numpy as np

from gmagc_desktop.matcher.normalize import normalize_gray
from gmagc_desktop.matcher.shape import MASK_SIZE, ShapeMatcher, soft_mask
from gmagc_desktop.matcher.variants import rotate_image
from tests.helpers import l_shape, sample_gobo


def angle_error(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def query_mask() -> np.ndarray:
    return soft_mask(normalize_gray(l_shape()))


def test_soft_mask_shape_and_dtype():
    mask = query_mask()
    assert mask.shape == (MASK_SIZE, MASK_SIZE) and mask.dtype == np.uint8


def test_identical_shape_scores_high_with_zero_angle():
    query = query_mask()
    match = ShapeMatcher(query).score(query)
    assert match.score > 0.95
    assert angle_error(match.angle, 0.0) < 1.5 and not match.mirrored


def test_rotated_shape_recovers_angle():
    query = query_mask()
    match = ShapeMatcher(query).score(rotate_image(query, 47.0))
    assert match.score > 0.9
    assert angle_error(match.angle, 47.0) < 2.0 and not match.mirrored


def test_mirrored_and_rotated_shape_is_flagged_mirrored():
    query = query_mask()
    candidate = rotate_image(np.ascontiguousarray(query[:, ::-1]), 40.0)
    match = ShapeMatcher(query).score(candidate)
    assert match.score > 0.9 and match.mirrored
    assert angle_error(match.angle, 40.0) < 2.0


def test_different_shape_scores_clearly_lower():
    query = query_mask()
    other = soft_mask(normalize_gray(sample_gobo()))
    matcher = ShapeMatcher(query)
    assert matcher.score(other).score < 0.6 < matcher.score(rotate_image(query, 30.0)).score
