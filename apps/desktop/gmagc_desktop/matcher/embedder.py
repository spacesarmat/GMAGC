"""Эмбеддеры: признаки для поиска похожих нормализованных изображений."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


class Embedder(Protocol):
    model_id: str

    def embed(self, images: np.ndarray) -> np.ndarray:
        """(N, H, W) uint8 -> (N, D) float32 с L2-нормой 1."""
        ...


def l2_normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return (vectors / np.maximum(norms, 1e-12)).astype(np.float32)


class PixelEmbedder:
    """Baseline: уменьшенное изображение без среднего. Не требует модели."""

    def __init__(self, side: int = 16):
        self.side = side
        self.model_id = f"pixels-{side}"

    def embed(self, images: np.ndarray) -> np.ndarray:
        small = np.stack(
            [
                cv2.resize(image, (self.side, self.side), interpolation=cv2.INTER_AREA)
                for image in images
            ]
        ).astype(np.float32)
        small -= small.mean(axis=(1, 2), keepdims=True)
        return l2_normalize(small.reshape(len(images), -1))


def pool_output(output: np.ndarray) -> np.ndarray:
    """(N, D) без изменений; (N, T, D) -> concat(токен 0, среднее остальных токенов)."""
    if output.ndim == 2:
        return output
    if output.ndim == 3:
        return np.concatenate([output[:, 0], output[:, 1:].mean(axis=1)], axis=1)
    raise ValueError(f"unsupported model output rank: {output.ndim}")


class OnnxEmbedder:
    """Энкодер изображений в формате ONNX (например, DINOv2-small), офлайн через onnxruntime."""

    def __init__(
        self,
        model_path: str | Path,
        batch_size: int = 32,
        providers: list[str] | None = None,
    ):
        import onnxruntime as ort

        path = Path(model_path)
        self.model_id = f"onnx-{path.stem}-{path.stat().st_size}"
        self._batch_size = batch_size
        try:
            self._session = ort.InferenceSession(
                str(path), providers=providers or ["CPUExecutionProvider"]
            )
        except Exception as error:  # onnxruntime-исключения наследуются от Exception: переводим в ValueError на границе
            raise ValueError(f"cannot load ONNX model {path}: {error}") from error
        self._input_name = self._session.get_inputs()[0].name

    @staticmethod
    def _prepare(images: np.ndarray) -> np.ndarray:
        gray = images.astype(np.float32) / 255.0
        rgb = np.repeat(gray[:, None, :, :], 3, axis=1)
        rgb = (rgb - IMAGENET_MEAN[None, :, None, None]) / IMAGENET_STD[None, :, None, None]
        return rgb.astype(np.float32)

    def embed(self, images: np.ndarray) -> np.ndarray:
        if len(images) == 0:
            return np.zeros((0, 0), dtype=np.float32)
        chunks = []
        for start in range(0, len(images), self._batch_size):
            batch = self._prepare(images[start : start + self._batch_size])
            output = self._session.run(None, {self._input_name: batch})[0]
            chunks.append(pool_output(output))
        return l2_normalize(np.concatenate(chunks, axis=0))
