"""HTML-отчёт по фото: вырезка проекции и top-N результатов для ручной разметки."""

from __future__ import annotations

import argparse
import base64
import html
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "desktop"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from benchmark import PHOTO_SUFFIXES, load_or_build  # noqa: E402
from _thumbs import square_pad  # noqa: E402

from gmagc_desktop.cli import build_embedder  # noqa: E402
from gmagc_desktop.library.index import LibraryNotFound, LibraryScanError  # noqa: E402
from gmagc_desktop.matcher.imageio import load_library_gray, load_photo_bgr  # noqa: E402
from gmagc_desktop.matcher.pipeline import normalize_photo  # noqa: E402
from gmagc_desktop.matcher.search import DEFAULT_W_EMBED, Searcher  # noqa: E402

THUMB = 128


def data_uri(gray: np.ndarray) -> str:
    small = cv2.resize(square_pad(gray), (THUMB, THUMB), interpolation=cv2.INTER_AREA)
    ok, buffer = cv2.imencode(".png", small)
    return "data:image/png;base64," + base64.b64encode(buffer.tobytes()).decode("ascii")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", required=True, type=Path)
    parser.add_argument("--model", default=None)
    parser.add_argument("--index", type=Path, default=None)
    parser.add_argument("--photos", type=Path, default=ROOT / "photo")
    parser.add_argument("--out", type=Path, default=ROOT / ".gmagc-cache" / "photo_report.html")
    parser.add_argument("--top", type=int, default=5)
    args = parser.parse_args(argv)

    # Check if photos directory exists
    if not args.photos.is_dir():
        print(f"photos folder not found: {args.photos}", file=sys.stderr)
        return 3

    embedder = build_embedder(args.model)
    if embedder is None:
        return 3
    index_path = args.index or ROOT / ".gmagc-cache" / f"index-{embedder.model_id}.npz"
    try:
        index = load_or_build(args.library, embedder, index_path)
    except (LibraryNotFound, LibraryScanError) as error:
        print(f"cannot read library: {error}", file=sys.stderr)
        return 3
    searcher = Searcher(index.search_data(), embedder, w_embed=DEFAULT_W_EMBED)

    sections = []
    template: dict[str, None] = {}
    for photo_path in sorted(p for p in args.photos.iterdir() if p.is_file() and p.suffix.lower() in PHOTO_SUFFIXES):
        template[photo_path.name] = None
        cards = []

        # Try to read the photo
        try:
            photo = load_photo_bgr(photo_path)
        except (OSError, ValueError) as error:
            cards.append(f"<p>cannot read photo: {html.escape(str(error))}</p>")
            sections.append(f"<h2>{html.escape(photo_path.name)}</h2><div class=\"row\">{''.join(cards)}</div>")
            continue

        normalized = normalize_photo(photo)
        if normalized is None:
            cards.append("<p>projection not found</p>")
        else:
            cards.append(f'<div class="card"><img src="{data_uri(normalized)}"><b>photo</b></div>')
            for rank, match in enumerate(searcher.search(normalized, top_n=args.top), start=1):
                file = index.files[match.index]
                copies = "; ".join(index.files[i].rel_path for i in match.members)

                # Try to load the thumbnail, use blank image if it fails
                try:
                    thumb_gray = load_library_gray(args.library / file.rel_path)
                    thumb = data_uri(thumb_gray)
                except (OSError, ValueError):
                    # Use blank 1x1 black image
                    blank = np.zeros((1, 1), np.uint8)
                    thumb = data_uri(blank)

                cards.append(
                    f'<div class="card"><img src="{thumb}">'
                    f"<b>#{rank} {match.score * 100:.1f}%</b>"
                    f'<span title="{html.escape(copies)}">{html.escape(file.rel_path)}'
                    f"{f' (+{len(match.members) - 1})' if len(match.members) > 1 else ''}</span></div>"
                )
        sections.append(f"<h2>{html.escape(photo_path.name)}</h2><div class=\"row\">{''.join(cards)}</div>")

    style = (
        ".row{display:flex;gap:12px;flex-wrap:wrap}.card{width:150px;font:12px sans-serif}"
        ".card img{width:128px;height:128px;background:#000;display:block}"
        ".card span{display:block;word-break:break-all}"
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        f"<!doctype html><meta charset=utf-8><style>{style}</style>{''.join(sections)}",
        encoding="utf-8",
    )
    (args.out.parent / "labels.template.json").write_text(
        json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"report: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
