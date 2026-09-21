"""Командная строка ядра: index и search."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from gmagc_desktop.library.index import LibraryNotFound, LibraryScanError, build_index, load_index, save_index
from gmagc_desktop.matcher.embedder import Embedder, OnnxEmbedder, PixelEmbedder
from gmagc_desktop.matcher.imageio import load_photo_bgr
from gmagc_desktop.matcher.pipeline import normalize_photo
from gmagc_desktop.matcher.search import Searcher


def make_embedder(model: str | None) -> Embedder:
    return OnnxEmbedder(model) if model else PixelEmbedder()


def _read_photo(path: str | Path) -> np.ndarray | None:
    """Load photo from path; return None after printing error message to stderr."""
    try:
        return load_photo_bgr(path)
    except (OSError, ValueError) as error:
        print(f"cannot read photo {path}: {error}", file=sys.stderr)
        return None


def _build_embedder(model: str | None) -> Embedder | None:
    """Build embedder; return None after printing error message to stderr."""
    try:
        return make_embedder(model)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"cannot load model {model}: {error}", file=sys.stderr)
        return None


def _progress(done: int, total: int) -> None:
    print(f"\rindexing {done}/{total}", end="", file=sys.stderr, flush=True)


def _cmd_index(args: argparse.Namespace) -> int:
    embedder = _build_embedder(args.model)
    if embedder is None:
        return 3
    try:
        index = build_index(
            args.library, embedder, existing=load_index(args.index), progress=_progress
        )
    except (LibraryNotFound, LibraryScanError) as error:
        print(file=sys.stderr)
        print(error, file=sys.stderr)
        return 3
    print(file=sys.stderr)
    save_index(index, args.index)
    unique = len(set(index.group_ids.tolist()))
    retry = f", {len(index.transient)} unreadable now (will be retried)" if index.transient else ""
    print(f"{len(index)} files indexed ({unique} unique), {len(index.skipped)} skipped{retry}")
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    index = load_index(args.index)
    if index is None:
        print("index not found or unreadable; run 'index' first", file=sys.stderr)
        return 1
    if len(index) == 0:
        print("index is empty; rebuild it with the 'index' command", file=sys.stderr)
        return 1
    photo = _read_photo(args.photo)
    if photo is None:
        return 3
    embedder = _build_embedder(args.model)
    if embedder is None:
        return 3
    if index.model_id != embedder.model_id:
        print(
            f"index was built with '{index.model_id}', search uses '{embedder.model_id}'",
            file=sys.stderr,
        )
        return 1
    normalized = normalize_photo(photo)
    if normalized is None:
        print("projection not found on the photo", file=sys.stderr)
        return 2
    searcher = Searcher(index.search_data(), embedder, w_embed=args.w_embed)
    root = Path(args.library) if args.library else None
    for rank, match in enumerate(searcher.search(normalized, top_n=args.top), start=1):
        rel = index.files[match.index].rel_path
        shown = str(root / rel) if root else rel
        extra = f"  (+{len(match.members) - 1} copies)" if len(match.members) > 1 else ""
        print(f"{rank:2d}. {match.score * 100:5.1f}%  {shown}{extra}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gmagc", description=__doc__)
    commands = parser.add_subparsers(required=True)

    index = commands.add_parser("index", help="построить или обновить индекс библиотеки")
    index.add_argument("library", type=Path)
    index.add_argument("--index", type=Path, required=True)
    index.add_argument("--model", default=None, help="путь к ONNX-модели (иначе пиксельный baseline)")
    index.set_defaults(handler=_cmd_index)

    search = commands.add_parser("search", help="найти гобо по фото")
    search.add_argument("photo", type=Path)
    search.add_argument("--index", type=Path, required=True)
    search.add_argument("--model", default=None)
    search.add_argument("--library", type=Path, default=None, help="печатать полные пути")
    search.add_argument("--top", type=int, default=10)
    search.add_argument("--w-embed", type=float, default=0.5)
    search.set_defaults(handler=_cmd_search)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
