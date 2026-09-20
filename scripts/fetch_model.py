"""Скачивание ONNX-модели эмбеддингов (dev-инструмент; единственное место, где нужен интернет)."""

from __future__ import annotations

import argparse
import hashlib
import urllib.request
from pathlib import Path

BASE_URL = "https://huggingface.co/onnx-community/dinov2-small/resolve/main/onnx/"
VARIANTS = {"fp32": "model.onnx", "int8": "model_int8.onnx", "fp16": "model_fp16.onnx"}


def variant_url(variant: str) -> str:
    return BASE_URL + VARIANTS[variant]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=sorted(VARIANTS), default="fp32")
    parser.add_argument("--out", type=Path, default=Path("models"))
    args = parser.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / f"dinov2-small-{args.variant}.onnx"
    url = variant_url(args.variant)
    print(f"downloading {url}")
    digest = hashlib.sha256()
    with urllib.request.urlopen(url) as response, open(target, "wb") as handle:
        while chunk := response.read(1 << 20):
            handle.write(chunk)
            digest.update(chunk)
    checksum = digest.hexdigest()
    (args.out / f"{target.name}.sha256").write_text(f"{checksum}  {target.name}\n", encoding="utf-8")
    print(f"saved {target} sha256={checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
