"""Замер качества: синтетические «плохие фото» из библиотеки и реальные фото с разметкой."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "desktop"))

from gmagc_desktop.library.index import LibraryIndex, build_index, load_index, save_index  # noqa: E402
from gmagc_desktop.matcher.embedder import OnnxEmbedder, PixelEmbedder  # noqa: E402
from gmagc_desktop.matcher.imageio import load_library_gray, load_photo_bgr  # noqa: E402
from gmagc_desktop.matcher.pipeline import normalize_photo  # noqa: E402
from gmagc_desktop.matcher.search import Searcher  # noqa: E402
from gmagc_desktop.matcher.synthetic import simulate_photo  # noqa: E402

PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png"}


def _progress(done: int, total: int) -> None:
    print(f"\rindexing {done}/{total}", end="", file=sys.stderr, flush=True)


def load_or_build(root: Path, embedder, index_path: Path) -> LibraryIndex:
    index = build_index(root, embedder, existing=load_index(index_path), progress=_progress)
    print(file=sys.stderr)
    save_index(index, index_path)
    return index


def synthetic_eval(index: LibraryIndex, root: Path, searcher: Searcher, samples: int, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    representatives: dict[int, int] = {}
    for position, group in enumerate(index.group_ids.tolist()):
        representatives.setdefault(group, position)
    if not representatives:
        raise SystemExit("library is empty")
    chosen = rng.choice(
        list(representatives.values()), size=min(samples, len(representatives)), replace=False
    )
    hits1 = hits5 = failed = 0
    milliseconds: list[float] = []
    for position in chosen:
        gray = load_library_gray(root / index.files[int(position)].rel_path)
        photo = simulate_photo(gray, rng)
        started = time.perf_counter()
        normalized = normalize_photo(photo)
        if normalized is None:
            failed += 1
            continue
        matches = searcher.search(normalized, top_n=5)
        milliseconds.append((time.perf_counter() - started) * 1000.0)
        target = int(index.group_ids[int(position)])
        found = [int(index.group_ids[m.index]) for m in matches]
        hits1 += bool(found) and found[0] == target
        hits5 += target in found
    total = len(chosen)
    return {
        "samples": total,
        "top1": hits1 / total,
        "top5": hits5 / total,
        "segmentation_failed": failed / total,
        "median_ms": statistics.median(milliseconds) if milliseconds else float("nan"),
    }


def real_eval(index: LibraryIndex, searcher: Searcher, photos_dir: Path, labels_path: Path):
    if not photos_dir.is_dir():
        return None
    labels = json.loads(labels_path.read_text(encoding="utf-8")) if labels_path.is_file() else {}
    by_path = {file.rel_path: i for i, file in enumerate(index.files)}
    rows: list[str] = []
    labeled = hits1 = hits5 = 0
    for photo_path in sorted(p for p in photos_dir.iterdir() if p.suffix.lower() in PHOTO_SUFFIXES):
        normalized = normalize_photo(load_photo_bgr(photo_path))
        if normalized is None:
            rows.append(f"{photo_path.name}: projection not found")
            continue
        matches = searcher.search(normalized, top_n=5)
        top = matches[0]
        note = ""
        expected = labels.get(photo_path.name, "unlabeled")
        if isinstance(expected, list):
            wanted = {int(index.group_ids[by_path[p]]) for p in expected if p in by_path}
            found = [int(index.group_ids[m.index]) for m in matches]
            labeled += 1
            first_ok = found[0] in wanted
            hits1 += first_ok
            hits5 += any(group in wanted for group in found)
            note = "  OK top-1" if first_ok else ("  OK top-5" if any(g in wanted for g in found) else "  MISS")
        elif expected is None:
            note = "  (not in library)"
        rows.append(
            f"{photo_path.name}: {index.files[top.index].rel_path}  {top.score * 100:.1f}%{note}"
        )
    return {
        "rows": rows,
        "labeled": labeled,
        "top1": hits1 / labeled if labeled else None,
        "top5": hits5 / labeled if labeled else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", required=True, type=Path)
    parser.add_argument("--model", type=Path, default=None)
    parser.add_argument("--index", type=Path, default=None)
    parser.add_argument("--samples", type=int, default=300)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--w-embed", type=float, default=0.5)
    parser.add_argument("--photos", type=Path, default=ROOT / "photo")
    parser.add_argument("--labels", type=Path, default=None)
    args = parser.parse_args(argv)

    embedder = OnnxEmbedder(args.model) if args.model else PixelEmbedder()
    index_path = args.index or ROOT / ".gmagc-cache" / f"index-{embedder.model_id}.npz"
    index = load_or_build(args.library, embedder, index_path)
    searcher = Searcher(index.search_data(), embedder, w_embed=args.w_embed)

    families = len(set(index.group_ids.tolist()))
    print(f"model: {embedder.model_id}  w_embed={args.w_embed}  files={len(index)}  families={families}")

    stats = synthetic_eval(index, args.library, searcher, args.samples, args.seed)
    print(
        f"synthetic (n={stats['samples']}): top-1 {stats['top1'] * 100:.1f}%  "
        f"top-5 {stats['top5'] * 100:.1f}%  "
        f"segmentation failed {stats['segmentation_failed'] * 100:.1f}%  "
        f"median {stats['median_ms']:.0f} ms"
    )

    real = real_eval(index, searcher, args.photos, args.labels or args.photos / "labels.json")
    if real is None:
        print("no real photos folder, skipped")
        return 0
    if real["labeled"]:
        print(
            f"real photos: labeled={real['labeled']}  top-1 {real['top1'] * 100:.1f}%  "
            f"top-5 {real['top5'] * 100:.1f}%"
        )
    else:
        print("real photos: no labels yet (fill labels.json)")
    print("\n".join(real["rows"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
