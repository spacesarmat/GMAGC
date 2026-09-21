import json
import re
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import benchmark  # noqa: E402
import inspect_groups  # noqa: E402
import report_photos  # noqa: E402

from gmagc_desktop import cli  # noqa: E402
from gmagc_desktop.matcher.search import Searcher  # noqa: E402
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


def build_searcher(tmp_path):
    library = make_library(tmp_path)
    embedder = cli.make_embedder(None)
    index = benchmark.load_or_build(library, embedder, tmp_path / "idx.npz")
    return index, Searcher(index.search_data(), embedder)


def write_labels(photos, mapping):
    photos.mkdir(parents=True, exist_ok=True)
    (photos / "labels.json").write_text(json.dumps(mapping), encoding="utf-8")


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
    # With 5 families, samples=4, all segmentable -> top-5 should be 100%
    match = re.search(r"top-1 ([\d.]+)%.*top-5 ([\d.]+)%", out)
    assert match, "synthetic line missing top-1/top-5 percentages"
    top1, top5 = float(match.group(1)), float(match.group(2))
    assert 0 <= top1 <= top5 <= 100, f"top-1={top1}% should be <= top-5={top5}%"
    assert top5 == 100.0, f"top-5 should be 100.0% with 5 families and 4 samples, got {top5}%"


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
    assert "OK top-1" in out
    assert "top-1 100.0%" in out


def test_load_or_build_reuses_cache(tmp_path):
    from PIL import Image
    from gmagc_desktop.matcher.embedder import PixelEmbedder

    class CountingEmbedder(PixelEmbedder):
        """PixelEmbedder, который считает, сколько СТРОК (изображений) он получил."""

        def __init__(self):
            super().__init__()
            self.rows_embedded = 0

        def embed(self, images):
            self.rows_embedded += len(images)
            return super().embed(images)

    library = make_library(tmp_path)
    embedder = CountingEmbedder()
    path = tmp_path / "cache" / "idx.npz"

    # First call: builds index, embeds 6 valid library files
    first = benchmark.load_or_build(library, embedder, path)
    assert embedder.rows_embedded == 6, f"first call should embed 6 files, got {embedder.rows_embedded}"
    assert len(first) == 6, "index should have 6 files"

    # Second call: reuses cache, should not embed anything new
    second = benchmark.load_or_build(library, embedder, path)
    assert embedder.rows_embedded == 6, (
        f"second call should reuse cache, rows should still be 6, got {embedder.rows_embedded}"
    )
    assert len(second) == 6, "cached index should still have 6 files"

    # Add ONE new image to library (create a real image so it can be embedded)
    new_photo = library / "vendor_c"
    Image.fromarray(np.eye(64, dtype=np.uint8) * 255, "L").save(new_photo / "diag.png")

    # Third call: incremental build, should embed the new file
    third = benchmark.load_or_build(library, embedder, path)
    assert embedder.rows_embedded == 7, f"third call should embed 1 new file, rows should be 7, got {embedder.rows_embedded}"
    assert len(third) == 7, "index should now have 7 files"


def test_real_eval_counts_a_family_hit(tmp_path):
    """Photo labeled with a family member -> top1==1.0, labeled==1."""
    index, searcher = build_searcher(tmp_path)
    photos = tmp_path / "photos"
    save_photo(photos, "a.png", shape_images()["ell"], 5)
    write_labels(photos, {"a.png": ["vendor_c/ell_small.png"]})

    result = benchmark.real_eval(index, searcher, photos, photos / "labels.json")
    assert result is not None
    assert result["labeled"] == 1
    assert result["top1"] == 1.0, f"expected 100% top1 for family hit, got {result['top1'] * 100}%"
    assert "OK top-1" in result["rows"][0]


def test_real_eval_distinguishes_top1_from_top5(tmp_path):
    """Photo labeled with a different family (in top-5) -> top1==0.0, top5==1.0."""
    index, searcher = build_searcher(tmp_path)
    photos = tmp_path / "photos"
    save_photo(photos, "a.png", shape_images()["ell"], 5)
    write_labels(photos, {"a.png": ["vendor_b/star.bmp"]})

    result = benchmark.real_eval(index, searcher, photos, photos / "labels.json")
    assert result is not None
    assert result["labeled"] == 1
    assert result["top1"] == 0.0, "should not match top-1 for different family"
    assert result["top5"] == 1.0, "should match in top-5 (only 5 families)"
    assert "OK top-5" in result["rows"][0]


def test_real_eval_counts_a_missing_projection_as_a_miss(tmp_path):
    """Labeled flat photo with no projection -> labeled==1, top1==0.0, row contains MISS."""
    index, searcher = build_searcher(tmp_path)
    photos = tmp_path / "photos"
    # Create a flat photo (no gobo, will fail to project)
    flat = np.full((480, 640, 3), 90, dtype=np.uint8)
    photos.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(photos / "flat.png"), flat)
    write_labels(photos, {"flat.png": ["vendor_c/ell_small.png"]})

    result = benchmark.real_eval(index, searcher, photos, photos / "labels.json")
    assert result is not None
    assert result["labeled"] == 1, "missing projection should count as labeled (it's a miss, not an omission)"
    assert result["top1"] == 0.0
    assert "projection not found  MISS" in result["rows"][0]


def test_real_eval_reports_unreadable_photos_without_aborting(tmp_path):
    """Unreadable photo + good labeled photo -> unreadable==1, labeled==1, run continues."""
    index, searcher = build_searcher(tmp_path)
    photos = tmp_path / "photos"
    photos.mkdir(parents=True, exist_ok=True)
    # Create an unreadable file
    (photos / "bad.png").write_bytes(b"junk")
    # Create a good labeled photo
    save_photo(photos, "good.png", shape_images()["ell"], 5)
    write_labels(photos, {"bad.png": None, "good.png": ["vendor_c/ell_small.png"]})

    result = benchmark.real_eval(index, searcher, photos, photos / "labels.json")
    assert result is not None
    assert result["unreadable"] == 1, "should report unreadable file"
    assert result["labeled"] == 1, "good photo should be labeled"
    assert result["top1"] == 1.0, "good photo should hit"
    assert any("bad.png" in row and "cannot read photo" in row for row in result["rows"])
    assert any("good.png" in row and "OK top-1" in row for row in result["rows"])


def test_real_eval_flags_label_errors_and_normalises_backslashes(tmp_path):
    """Labels with backslashes, missing paths, empty lists, wrong types -> flagged as errors."""
    index, searcher = build_searcher(tmp_path)
    photos = tmp_path / "photos"
    save_photo(photos, "a.png", shape_images()["ell"], 5)
    save_photo(photos, "b.png", shape_images()["ring"], 6)
    save_photo(photos, "c.png", shape_images()["ell"], 7)
    save_photo(photos, "d.png", shape_images()["ring"], 8)

    # a.png: backslash in path (should be normalized and hit)
    # b.png: non-existent path (should error)
    # c.png: empty list (should error)
    # d.png: string instead of list (should error)
    write_labels(
        photos,
        {
            "a.png": ["vendor_c\\ell_small.png"],
            "b.png": ["vendor_x/none.png"],
            "c.png": [],
            "d.png": "vendor_a/ring.bmp",
        },
    )

    result = benchmark.real_eval(index, searcher, photos, photos / "labels.json")
    assert result is not None
    assert result["label_errors"] == 3, f"expected 3 label errors, got {result['label_errors']}"
    assert result["labeled"] == 1, "only a.png should be labeled"
    assert result["top1"] == 1.0, "a.png (ell) should hit vendor_c/ell_small.png"
    assert any("LABEL ERROR" in row for row in result["rows"])


def test_real_eval_null_label_is_not_measured(tmp_path):
    """Photo labeled null (not in library) -> labeled==0, row has (not in library)."""
    index, searcher = build_searcher(tmp_path)
    photos = tmp_path / "photos"
    save_photo(photos, "a.png", shape_images()["ell"], 5)
    write_labels(photos, {"a.png": None})

    result = benchmark.real_eval(index, searcher, photos, photos / "labels.json")
    assert result is not None
    assert result["labeled"] == 0, "null label should not count as labeled"
    assert "(not in library)" in result["rows"][0]


def test_real_eval_raises_labels_error_for_malformed_json_and_main_returns_3(tmp_path, capsys):
    """Malformed JSON or missing --labels file -> LabelsError or exit code 3."""
    # Test 1: invalid JSON
    index, searcher = build_searcher(tmp_path)
    photos = tmp_path / "test1_photos"
    save_photo(photos, "a.png", shape_images()["ell"], 5)
    (photos / "labels.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(benchmark.LabelsError):
        benchmark.real_eval(index, searcher, photos, photos / "labels.json")

    # Test 2: JSON list instead of object
    (photos / "labels.json").write_text("[]", encoding="utf-8")
    with pytest.raises(benchmark.LabelsError):
        benchmark.real_eval(index, searcher, photos, photos / "labels.json")

    # Test 3: main returns 3 for cannot read labels
    lib_path = tmp_path / "lib3"
    lib_path.mkdir()
    write_library(lib_path)
    photos3 = tmp_path / "test3_photos"
    save_photo(photos3, "a.png", shape_images()["ell"], 5)
    (photos3 / "labels.json").write_text("{not json", encoding="utf-8")
    code = benchmark.main(
        [
            "--library", str(lib_path),
            "--samples", "2",
            "--index", str(tmp_path / "idx3.npz"),
            "--photos", str(photos3),
        ]
    )
    err = capsys.readouterr().err
    assert code == 3, "should return exit code 3 for malformed labels"
    assert "cannot read labels file" in err

    # Test 4: main returns 3 for missing --labels file
    lib_path4 = tmp_path / "lib4"
    lib_path4.mkdir()
    write_library(lib_path4)
    photos4 = tmp_path / "test4_photos"
    save_photo(photos4, "a.png", shape_images()["ell"], 5)
    capsys.readouterr()  # clear
    missing_labels = tmp_path / "missing_labels.json"
    code = benchmark.main(
        [
            "--library", str(lib_path4),
            "--samples", "2",
            "--index", str(tmp_path / "idx4.npz"),
            "--photos", str(photos4),
            "--labels", str(missing_labels),
        ]
    )
    err = capsys.readouterr().err
    assert code == 3, "should return exit code 3 for missing labels file"
    assert "labels file not found" in err


def test_synthetic_eval_is_deterministic_and_sane(tmp_path):
    """Synthetic eval with same seed produces same metrics; 5 families guarantee top-5 hit."""
    index, searcher = build_searcher(tmp_path)
    library = tmp_path / "lib"  # Already created by build_searcher via make_library

    # With samples=3, seed=3
    result1 = benchmark.synthetic_eval(index, library, searcher, samples=3, seed=3)
    result2 = benchmark.synthetic_eval(index, library, searcher, samples=3, seed=3)

    # Should have same metrics (ignore median_ms, which may differ slightly)
    assert result1["samples"] == result2["samples"] == 3
    assert result1["top1"] == result2["top1"], "same seed should produce same top1"
    assert result1["top5"] == result2["top5"], "same seed should produce same top5"
    seg_fail1, seg_fail2 = result1["segmentation_failed"], result2["segmentation_failed"]
    assert seg_fail1 == seg_fail2, "same seed should produce same segmentation_failed"

    # With 5 families, all fit in top-5, so real searcher should guarantee top5==1.0
    assert result1["top5"] == 1.0, f"with 5 families and pixel embedder, top5 should be 1.0, got {result1['top5']}"
    assert result1["segmentation_failed"] == 0.0, f"shapes should always segment, got {result1['segmentation_failed']}"

    # Sanity checks
    assert 0.0 <= result1["top1"] <= result1["top5"] <= 1.0
    assert 0.0 <= result1["segmentation_failed"] <= 1.0


def test_synthetic_eval_counts_misses_when_the_search_is_wrong(tmp_path):
    """Synthetic eval with an empty-result searcher should give top1==0.0, top5==0.0."""
    index, _ = build_searcher(tmp_path)
    library = tmp_path / "lib"

    class StubSearcher:
        def search(self, normalized, top_n=10):
            return []

    stub_searcher = StubSearcher()
    result = benchmark.synthetic_eval(index, library, stub_searcher, samples=3, seed=5)

    # Stub searcher returns no matches, so all should be misses
    assert result["top1"] == 0.0, f"no matches should give top1==0.0, got {result['top1']}"
    assert result["top5"] == 0.0, f"no matches should give top5==0.0, got {result['top5']}"
    assert result["samples"] == 3


def test_report_photos_writes_html_and_label_template(tmp_path):
    library = make_library(tmp_path)
    photos = tmp_path / "photos"
    save_photo(photos, "a.png", shape_images()["ell"], 5)
    out = tmp_path / "report" / "photo_report.html"

    code = report_photos.main(
        [
            "--library", str(library),
            "--index", str(tmp_path / "idx.npz"),
            "--photos", str(photos),
            "--out", str(out),
            "--top", "3",
        ]
    )

    html_text = out.read_text(encoding="utf-8")
    template = json.loads((out.parent / "labels.template.json").read_text(encoding="utf-8"))
    assert code == 0
    assert "a.png" in html_text and "vendor_" in html_text and "data:image/png;base64," in html_text
    assert template == {"a.png": None}


def test_inspect_groups_lists_duplicate_families(tmp_path, capsys):
    library = make_library(tmp_path)
    index_path = tmp_path / "idx.npz"
    cli.main(["index", str(library), "--index", str(index_path)])
    capsys.readouterr()
    sheet = tmp_path / "sheet.png"

    code = inspect_groups.main(
        ["--library", str(library), "--index", str(index_path), "--out", str(sheet)]
    )

    out = capsys.readouterr().out
    assert code == 0 and "5 families, 1 with duplicates, 2 files in them" in out
    assert "vendor_b/ell.png" in out and "vendor_c/ell_small.png" in out
    assert sheet.exists()


def test_report_photos_survives_an_unreadable_photo(tmp_path):
    library = make_library(tmp_path)
    photos = tmp_path / "photos"
    save_photo(photos, "good.png", shape_images()["ell"], 5)
    # Create an unreadable file
    (photos / "bad.png").write_bytes(b"junk")
    out = tmp_path / "report" / "photo_report.html"

    code = report_photos.main(
        [
            "--library", str(library),
            "--index", str(tmp_path / "idx.npz"),
            "--photos", str(photos),
            "--out", str(out),
        ]
    )

    html_text = out.read_text(encoding="utf-8")
    template = json.loads((out.parent / "labels.template.json").read_text(encoding="utf-8"))
    assert code == 0
    assert "cannot read photo" in html_text
    assert "good.png" in html_text
    assert "bad.png" in html_text
    assert template == {"bad.png": None, "good.png": None}


def test_report_photos_missing_photos_folder_returns_3(tmp_path, capsys):
    library = make_library(tmp_path)
    out = tmp_path / "report" / "photo_report.html"

    code = report_photos.main(
        [
            "--library", str(library),
            "--index", str(tmp_path / "idx.npz"),
            "--photos", str(tmp_path / "nonexistent"),
            "--out", str(out),
        ]
    )

    err = capsys.readouterr().err
    assert code == 3
    assert "photos folder not found" in err


def test_report_photos_missing_library_returns_3(tmp_path, capsys):
    photos = tmp_path / "photos"
    save_photo(photos, "a.png", shape_images()["ell"], 5)
    out = tmp_path / "report" / "photo_report.html"

    code = report_photos.main(
        [
            "--library", str(tmp_path / "nonexistent_lib"),
            "--index", str(tmp_path / "idx.npz"),
            "--photos", str(photos),
            "--out", str(out),
        ]
    )

    err = capsys.readouterr().err
    assert code == 3
    assert "cannot read library" in err or "cannot read" in err or "FileNotFoundError" in err


def test_benchmark_missing_library_returns_3(tmp_path, capsys):
    index_path = tmp_path / "idx.npz"

    code = benchmark.main(["--library", str(tmp_path / "unplugged"), "--index", str(index_path)])

    assert code == 3
    assert "library folder not found" in capsys.readouterr().err
    assert not index_path.exists()


def test_benchmark_empty_library_returns_3_without_writing_an_index(tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    index_path = tmp_path / "idx.npz"

    code = benchmark.main(["--library", str(empty), "--index", str(index_path)])

    assert code == 3
    assert "no PNG/BMP files found" in capsys.readouterr().err
    assert not index_path.exists()


@pytest.mark.parametrize("problem", ["missing", "garbage"])
def test_benchmark_bad_model_returns_3(tmp_path, capsys, problem):
    library = make_library(tmp_path)
    model = tmp_path / "model.onnx"
    if problem == "garbage":
        model.write_bytes(b"not an onnx model")
    index_path = tmp_path / "idx.npz"

    code = benchmark.main(["--library", str(library), "--model", str(model), "--index", str(index_path)])

    err = capsys.readouterr().err
    assert code == 3 and "cannot load model" in err and "Traceback" not in err
    assert not index_path.exists()


def test_benchmark_missing_labels_file_returns_3_before_any_index_is_built(tmp_path, capsys):
    library = make_library(tmp_path)
    photos = tmp_path / "photos"
    save_photo(photos, "a.png", shape_images()["ell"], 5)
    index_path = tmp_path / "idx.npz"

    code = benchmark.main(
        [
            "--library", str(library),
            "--index", str(index_path),
            "--photos", str(photos),
            "--labels", str(tmp_path / "missing_labels.json"),
        ]
    )

    captured = capsys.readouterr()
    assert code == 3 and "labels file not found" in captured.err
    assert not index_path.exists()
    assert "synthetic" not in captured.out


def test_report_photos_bad_model_returns_3(tmp_path, capsys):
    library = make_library(tmp_path)
    photos = tmp_path / "photos"
    save_photo(photos, "a.png", shape_images()["ell"], 5)
    index_path = tmp_path / "idx.npz"

    code = report_photos.main(
        [
            "--library", str(library),
            "--model", str(tmp_path / "nope.onnx"),
            "--index", str(index_path),
            "--photos", str(photos),
            "--out", str(tmp_path / "report" / "r.html"),
        ]
    )

    err = capsys.readouterr().err
    assert code == 3 and "cannot load model" in err and "Traceback" not in err
    assert not index_path.exists()


def test_report_photos_empty_library_returns_3(tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    photos = tmp_path / "photos"
    save_photo(photos, "a.png", shape_images()["ell"], 5)

    code = report_photos.main(
        [
            "--library", str(empty),
            "--index", str(tmp_path / "idx.npz"),
            "--photos", str(photos),
            "--out", str(tmp_path / "report" / "r.html"),
        ]
    )

    assert code == 3 and "no PNG/BMP files found" in capsys.readouterr().err


def test_inspect_groups_missing_library_returns_3(tmp_path, capsys):
    library = make_library(tmp_path)
    index_path = tmp_path / "idx.npz"
    cli.main(["index", str(library), "--index", str(index_path)])
    capsys.readouterr()

    code = inspect_groups.main(
        ["--library", str(tmp_path / "unplugged"), "--index", str(index_path), "--out", str(tmp_path / "s.png")]
    )

    err = capsys.readouterr().err
    assert code == 3 and f"library folder not found: {tmp_path / 'unplugged'}" in err
    assert not (tmp_path / "s.png").exists()
