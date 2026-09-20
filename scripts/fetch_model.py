"""Скачивание ONNX-модели эмбеддингов (dev-инструмент; единственное место, где нужен интернет)."""

from __future__ import annotations

import argparse
import hashlib
import os
import urllib.request
from pathlib import Path

BASE_URL = "https://huggingface.co/onnx-community/dinov2-small/resolve/main/onnx/"
VARIANTS = {"fp32": "model.onnx", "int8": "model_int8.onnx", "fp16": "model_fp16.onnx"}


def variant_url(variant: str) -> str:
    return BASE_URL + VARIANTS[variant]


def download(url: str, target: Path, timeout: float = 60.0) -> str:
    """Скачивает url через временный файл и возвращает SHA-256. target появляется только после полной загрузки."""
    part = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    written = 0
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response, open(part, "wb") as handle:
            expected = response.headers.get("Content-Length")
            while chunk := response.read(1 << 20):
                handle.write(chunk)
                digest.update(chunk)
                written += len(chunk)
        if expected is not None and written != int(expected):
            raise OSError(f"incomplete download: got {written} of {expected} bytes")
        os.replace(part, target)
    finally:
        part.unlink(missing_ok=True)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=sorted(VARIANTS), default="fp32")
    parser.add_argument("--out", type=Path, default=Path("models"))
    parser.add_argument("--force", action="store_true", help="скачать заново, даже если файл уже есть")
    args = parser.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / f"dinov2-small-{args.variant}.onnx"

    if target.exists() and not args.force:
        print(f"{target} already exists; use --force to download it again")
        return 0

    url = variant_url(args.variant)
    print(f"downloading {url}")
    checksum = download(url, target)
    (args.out / f"{target.name}.sha256").write_text(f"{checksum}  {target.name}\n", encoding="utf-8")
    print(f"saved {target} sha256={checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
