"""Симулятор фото проекции гобо на стене (для тестов и бенчмарка)."""

from __future__ import annotations

import cv2
import numpy as np

TINT_BGR = np.array([1.0, 0.96, 0.85], dtype=np.float32)  # голубовато-белый свет
WALL_BGR = np.array([0.95, 1.0, 1.02], dtype=np.float32)


def _wall(rng: np.random.Generator, width: int, height: int) -> np.ndarray:
    gradient = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None]
    base = 80.0 + 30.0 * gradient + rng.normal(0.0, 5.0, (height, width)).astype(np.float32)
    base = cv2.GaussianBlur(base, (0, 0), 2.0)
    photo = base[:, :, None] * WALL_BGR
    for x in range(0, width, 64):  # потолочные окна: светлые, но темнее проекции
        photo[int(0.03 * height) : int(0.15 * height), x : x + 40] += 55.0
    xs = np.arange(width, dtype=np.float32)[None, :]
    ys = np.linspace(1.0, 0.0, int(0.45 * height), dtype=np.float32)[:, None]
    shaft = 45.0 * np.exp(-(((xs - width * 0.47) / (width * 0.02)) ** 2)) * ys  # луч света
    photo[: shaft.shape[0]] += shaft[:, :, None]
    return photo


def simulate_photo(
    gobo_gray: np.ndarray, rng: np.random.Generator, width: int = 1280, height: int = 960
) -> np.ndarray:
    """BGR uint8 «фото» гобо: поворот, зеркало, перспектива, размытие, шум, блик."""
    photo = _wall(rng, width, height)

    side = int(rng.uniform(0.28, 0.40) * height)
    gh, gw = gobo_gray.shape
    fit = side / max(gh, gw)
    patch = cv2.resize(
        gobo_gray,
        (max(1, round(gw * fit)), max(1, round(gh * fit))),
        interpolation=cv2.INTER_AREA,
    )
    canvas = np.zeros((side, side), np.uint8)
    y0, x0 = (side - patch.shape[0]) // 2, (side - patch.shape[1]) // 2
    canvas[y0 : y0 + patch.shape[0], x0 : x0 + patch.shape[1]] = patch
    if rng.random() < 0.5:
        canvas = np.ascontiguousarray(canvas[:, ::-1])

    angle = np.deg2rad(rng.uniform(0.0, 360.0))
    rotation = np.array(
        [[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]], dtype=np.float32
    )
    centre = np.array(
        [
            width * 0.5 + rng.uniform(-0.08, 0.08) * width,
            height * 0.45 + rng.uniform(-0.05, 0.05) * height,
        ],
        dtype=np.float32,
    )
    corners = np.array([(-1, -1), (1, -1), (1, 1), (-1, 1)], dtype=np.float32) * (side / 2)
    dst = centre + corners @ rotation.T + rng.uniform(-0.03, 0.03, (4, 2)) * side
    src = np.array([(0, 0), (side, 0), (side, side), (0, side)], dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(src, dst.astype(np.float32))
    layer = cv2.warpPerspective(canvas, matrix, (width, height), flags=cv2.INTER_LINEAR)
    layer = cv2.GaussianBlur(layer.astype(np.float32) / 255.0, (0, 0), rng.uniform(0.8, 2.0))

    photo += rng.uniform(150.0, 200.0) * layer[:, :, None] * TINT_BGR
    photo += rng.normal(0.0, 3.0, photo.shape).astype(np.float32)
    photo = np.clip(photo, 0, 255).astype(np.uint8)

    if rng.random() < 0.5:  # оранжевый блик у нижнего края проекции
        centre_x = int(centre[0] + rng.uniform(-0.1, 0.1) * side)
        cv2.ellipse(
            photo,
            (centre_x, int(centre[1] + 0.5 * side)),
            (int(0.18 * side), int(0.05 * side)),
            0,
            0,
            360,
            (40, 130, 230),
            -1,
        )
    return photo
