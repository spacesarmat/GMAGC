"""Показать случайные семейства дублей (для подбора порогов группировки)."""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _thumbs import square_pad  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "desktop" / "src"))

from gmagc_desktop.library.index import load_index  # noqa: E402
from gmagc_desktop.matcher.imageio import load_library_gray  # noqa: E402

CELL = 96
COLUMNS = 8


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", required=True, type=Path)
    parser.add_argument("--index", required=True, type=Path)
    parser.add_argument("--count", type=int, default=12)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=Path, default=ROOT / ".gmagc-cache" / "groups_sheet.png")
    args = parser.parse_args(argv)

    if not args.library.is_dir():
        print(f"library folder not found: {args.library}", file=sys.stderr)
        return 3
    index = load_index(args.index)
    if index is None:
        print("index not found", file=sys.stderr)
        return 1
    families: dict[int, list[int]] = defaultdict(list)
    for position, group in enumerate(index.group_ids.tolist()):
        families[group].append(position)
    duplicated = [members for members in families.values() if len(members) > 1]
    print(
        f"{len(families)} families, {len(duplicated)} with duplicates, "
        f"{sum(len(m) for m in duplicated)} files in them"
    )
    if not duplicated:
        return 0

    rng = np.random.default_rng(args.seed)
    chosen = rng.choice(len(duplicated), size=min(args.count, len(duplicated)), replace=False)
    sheet = np.zeros((len(chosen) * CELL, COLUMNS * CELL), np.uint8)
    for row, choice in enumerate(chosen):
        members = duplicated[int(choice)]
        print(f"family of {len(members)}:")
        for column, position in enumerate(members):
            rel = index.files[position].rel_path
            print(f"  {rel}")
            if column < COLUMNS:
                try:
                    gray = load_library_gray(args.library / rel)
                except (OSError, ValueError):
                    # Use blank 1x1 black image if file cannot be read
                    gray = np.zeros((1, 1), np.uint8)
                square = square_pad(gray)
                sheet[row * CELL : (row + 1) * CELL, column * CELL : (column + 1) * CELL] = cv2.resize(
                    square, (CELL, CELL), interpolation=cv2.INTER_AREA
                )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imencode(".png", sheet)[1].tofile(str(args.out))
    print(f"sheet: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
