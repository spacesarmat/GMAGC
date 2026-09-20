import sys
from pathlib import Path

import numpy as np

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import _thumbs  # noqa: E402


def test_square_pad_rectangular_image():
    """A 10x20 image becomes 20x20 with the original centered."""
    gray = np.ones((10, 20), np.uint8) * 100
    result = _thumbs.square_pad(gray)

    assert result.shape == (20, 20), f"expected shape (20, 20), got {result.shape}"
    # Original should be centered: rows 5..15 hold the data
    assert np.all(result[0:5, :] == 0), "top padding should be zero"
    assert np.all(result[15:20, :] == 0), "bottom padding should be zero"
    assert np.all(result[5:15, :] == 100), "center rows should contain original data"


def test_square_pad_square_image():
    """A square image is returned equal to the input."""
    gray = np.ones((20, 20), np.uint8) * 50
    result = _thumbs.square_pad(gray)

    assert result.shape == (20, 20)
    assert np.array_equal(result, gray)
