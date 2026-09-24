"""Миниатюры гобо для интерфейса и отчётов."""

from __future__ import annotations

import base64
import zlib

import cv2
import numpy as np

from gmagc_common.fixtures import GOBO_THUMB_SIDE


def square_pad(gray: np.ndarray) -> np.ndarray:
    """Дополняет изображение чёрным до квадрата, оригинал по центру."""
    side = max(gray.shape)
    square = np.zeros((side, side), np.uint8)
    y, x = (side - gray.shape[0]) // 2, (side - gray.shape[1]) // 2
    square[y : y + gray.shape[0], x : x + gray.shape[1]] = gray
    return square


def thumbnail_png(gray: np.ndarray, size: int = 96) -> bytes:
    """PNG-миниатюра size x size: изображение вписано в квадрат с чёрными полями."""
    small = cv2.resize(square_pad(gray), (size, size), interpolation=cv2.INTER_AREA)
    ok, buffer = cv2.imencode(".png", small)
    if not ok:
        raise ValueError("не удалось закодировать миниатюру")
    return buffer.tobytes()


def gobo_thumb(gray: np.ndarray) -> str:
    """Миниатюра слота колеса в типе прибора: RGBA 64×64 (гобо серым, непрозрачно), сжатая zlib и закодированная в base64."""
    small = cv2.resize(square_pad(gray), (GOBO_THUMB_SIDE, GOBO_THUMB_SIDE), interpolation=cv2.INTER_AREA)
    rgba = np.dstack([small, small, small, np.full_like(small, 255)])
    return base64.b64encode(zlib.compress(rgba.tobytes())).decode("ascii")
