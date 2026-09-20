"""Маленькая синтетическая библиотека гобо для тестов индекса, поиска и CLI."""

from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from tests.helpers import l_shape, sample_gobo


def _ring(size: int = 256) -> np.ndarray:
    image = np.zeros((size, size), np.uint8)
    cv2.circle(image, (size // 2, size // 2), int(size * 0.38), 255, size // 12)
    return image


def _dots(size: int = 256) -> np.ndarray:
    image = np.zeros((size, size), np.uint8)
    for i in range(5):
        for j in range(5):
            if (i * 7 + j * 3) % 4 != 0:
                cv2.circle(image, (40 + i * 44, 40 + j * 44), 12 if (i + j) % 2 else 7, 255, -1)
    return image


def _star(size: int = 256) -> np.ndarray:
    points = []
    for k in range(10):
        radius = 110 if k % 2 == 0 else 45
        angle = k * np.pi / 5 - np.pi / 2
        points.append((size // 2 + radius * np.cos(angle), size // 2 + radius * np.sin(angle)))
    image = np.zeros((size, size), np.uint8)
    cv2.fillPoly(image, [np.array(points, np.int32)], 255)
    return image


def shape_images() -> dict[str, np.ndarray]:
    return {
        "ring": _ring(),
        "dots": _dots(),
        "star": _star(),
        "ell": l_shape((256, 256)),
        "ell_small": l_shape((128, 128), 0.5),
        "gobo": sample_gobo(256),
    }


def write_library(root: Path) -> None:
    images = shape_images()
    for folder in ("vendor_a", "vendor_b", "vendor_c"):
        (root / folder).mkdir(parents=True, exist_ok=True)

    Image.fromarray(images["ring"]).convert("RGB").save(root / "vendor_a" / "ring.png")
    alpha = images["dots"]
    rgba = np.dstack([np.full_like(alpha, 255)] * 3 + [alpha])  # белый RGB, фон прозрачный
    Image.fromarray(rgba, "RGBA").save(root / "vendor_a" / "dots.png")
    Image.fromarray(images["star"]).convert("RGB").save(root / "vendor_b" / "star.bmp")
    Image.fromarray(images["ell"], "L").save(root / "vendor_b" / "ell.png")
    Image.fromarray(images["ell_small"], "L").save(root / "vendor_c" / "ell_small.png")
    Image.fromarray(images["gobo"], "L").save(root / "vendor_c" / "gobo.png")
    Image.fromarray(np.zeros((64, 64), np.uint8), "L").save(root / "blank.png")
    Image.fromarray(images["ring"]).convert("RGB").save(root / "question.bmp")
    (root / "notes.txt").write_text("not an image", encoding="utf-8")
