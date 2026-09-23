import numpy as np

from gmagc_desktop.matcher.adjust import apply_adjustments


def test_neutral_values_are_a_no_op():
    image = np.random.default_rng(1).integers(0, 256, (40, 40, 3), dtype=np.uint8)
    result = apply_adjustments(image)
    assert np.array_equal(result, image)


def test_positive_brightness_lightens_the_image():
    image = np.full((20, 20, 3), 100, np.uint8)
    result = apply_adjustments(image, brightness=40)
    assert result.mean() > image.mean()


def test_negative_brightness_darkens_the_image():
    image = np.full((20, 20, 3), 100, np.uint8)
    result = apply_adjustments(image, brightness=-40)
    assert result.mean() < image.mean()


def test_contrast_above_one_widens_the_spread_around_midtone():
    image = np.zeros((20, 20, 3), np.uint8)
    image[:10] = 100
    image[10:] = 156
    result = apply_adjustments(image, contrast=1.8)
    assert result[:10].mean() < image[:10].mean()
    assert result[10:].mean() > image[10:].mean()


def test_contrast_below_one_narrows_the_spread_around_midtone():
    image = np.zeros((20, 20, 3), np.uint8)
    image[:10] = 60
    image[10:] = 196
    result = apply_adjustments(image, contrast=0.5)
    assert result[:10].mean() > image[:10].mean()
    assert result[10:].mean() < image[10:].mean()


def test_positive_exposure_scales_values_multiplicatively():
    dim = np.full((20, 20, 3), 40, np.uint8)
    bright = np.full((20, 20, 3), 160, np.uint8)
    dim_result = apply_adjustments(dim, exposure=1.0)
    bright_result = apply_adjustments(bright, exposure=1.0)
    # doubling (2**1.0): the gain in absolute value is bigger for the already-brighter pixel
    assert (dim_result.astype(int) - dim.astype(int)).mean() < (
        bright_result.astype(int) - bright.astype(int)
    ).mean()


def test_output_never_overflows_or_underflows_uint8_range():
    bright = np.full((10, 10, 3), 250, np.uint8)
    dark = np.full((10, 10, 3), 5, np.uint8)
    assert apply_adjustments(bright, brightness=80, exposure=2.0).max() <= 255
    assert apply_adjustments(dark, brightness=-80, contrast=2.0).min() >= 0


def test_output_keeps_input_dtype_and_shape():
    image = np.random.default_rng(2).integers(0, 256, (30, 50, 3), dtype=np.uint8)
    result = apply_adjustments(image, brightness=10, contrast=1.2, exposure=0.5)
    assert result.dtype == np.uint8
    assert result.shape == image.shape
