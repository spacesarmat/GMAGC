import sys
from pathlib import Path

import cv2
import numpy as np

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import benchmark  # noqa: E402

from gmagc_desktop import cli  # noqa: E402
from gmagc_desktop.matcher.synthetic import simulate_photo  # noqa: E402
from tests.fixtures import shape_images, write_library  # noqa: E402


def make_library(tmp_path):
    library = tmp_path / "lib"
    library.mkdir()
    write_library(library)
    return library


def save_photo(directory, name, gobo, seed):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    cv2.imencode(".png", simulate_photo(gobo, np.random.default_rng(seed)))[1].tofile(str(path))
    return path


def test_benchmark_synthetic_smoke(tmp_path, capsys):
    library = make_library(tmp_path)
    code = benchmark.main(
        [
            "--library", str(library),
            "--samples", "4",
            "--index", str(tmp_path / "idx.npz"),
            "--photos", str(tmp_path / "no_photos"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "synthetic (n=4)" in out and "top-1" in out and "top-5" in out
    assert "no real photos" in out


def test_benchmark_real_photos_with_labels(tmp_path, capsys):
    library = make_library(tmp_path)
    photos = tmp_path / "photos"
    save_photo(photos, "a.png", shape_images()["ell"], 5)
    save_photo(photos, "b.png", shape_images()["ring"], 6)
    (photos / "labels.json").write_text(
        '{"a.png": ["vendor_c/ell_small.png"], "b.png": null}', encoding="utf-8"
    )
    code = benchmark.main(
        [
            "--library", str(library),
            "--samples", "2",
            "--index", str(tmp_path / "idx.npz"),
            "--photos", str(photos),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "real photos: labeled=1" in out
    assert "a.png:" in out and "b.png:" in out and "(not in library)" in out


def test_load_or_build_reuses_cache(tmp_path):
    library = make_library(tmp_path)
    embedder = cli.make_embedder(None)
    path = tmp_path / "cache" / "idx.npz"
    first = benchmark.load_or_build(library, embedder, path)
    second = benchmark.load_or_build(library, embedder, path)
    assert path.exists() and len(first) == len(second) == 6
