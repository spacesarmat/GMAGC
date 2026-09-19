import numpy as np

from gmagc_desktop.matcher.normalize import NORM_SIZE, normalize_gray
from tests.helpers import iou, l_shape


def test_output_shape_and_dtype():
    out = normalize_gray(l_shape())
    assert out.shape == (NORM_SIZE, NORM_SIZE) and out.dtype == np.uint8


def test_invariant_to_shift_and_scale():
    a = normalize_gray(l_shape((300, 300), 1.0, (0, 0)))
    b = normalize_gray(l_shape((200, 260), 0.5, (20, 15)))
    assert iou(a, b) > 0.9


def test_blank_image_returns_none():
    assert normalize_gray(np.zeros((64, 64), np.uint8)) is None


def test_shape_fits_into_canvas():
    out = normalize_gray(l_shape())
    ys, xs = np.nonzero(out > 127)
    assert xs.min() > 0 and ys.min() > 0
    assert xs.max() < NORM_SIZE - 1 and ys.max() < NORM_SIZE - 1
