import numpy as np

from gmagc_desktop.matcher.variants import query_variants, rotate_image, variant_pose
from tests.helpers import l_shape


def test_variant_count_and_shape():
    image = l_shape((64, 64), 0.2, (0, 0))
    assert query_variants(image).shape == (48, 64, 64)
    assert query_variants(image, n_rotations=12, mirror=False).shape == (12, 64, 64)


def test_first_variant_is_original_and_second_block_is_mirrored():
    image = l_shape((64, 64), 0.2, (0, 0))
    variants = query_variants(image)
    assert np.array_equal(variants[0], image)
    assert np.array_equal(variants[24], image[:, ::-1])


def test_rotate_90_matches_numpy_rot90():
    image = l_shape((300, 300))
    diff = np.abs(rotate_image(image, 90).astype(int) - np.rot90(image, 1).astype(int))
    assert diff.mean() < 2


def test_variant_pose_maps_index_to_angle_and_mirror():
    assert variant_pose(0) == (0.0, False)
    assert variant_pose(1) == (15.0, False)
    assert variant_pose(24) == (0.0, True)
    assert variant_pose(25) == (15.0, True)
