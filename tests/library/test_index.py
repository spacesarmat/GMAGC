import os

import numpy as np
import pytest

from gmagc_desktop.library.index import (
    IndexCancelled,
    build_index,
    load_index,
    save_index,
)
from gmagc_desktop.matcher.embedder import PixelEmbedder
from tests.fixtures import write_library


class CountingEmbedder(PixelEmbedder):
    def __init__(self, tag: str = "pixels-16"):
        super().__init__()
        self.model_id = tag
        self.count = 0

    def embed(self, images):
        self.count += len(images)
        return super().embed(images)


@pytest.fixture()
def library(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    write_library(root)
    return root


def test_build_indexes_valid_files_skips_blank_and_groups_duplicates(library):
    index = build_index(library, CountingEmbedder())

    paths = [f.rel_path for f in index.files]
    assert paths == [
        "vendor_a/dots.png",
        "vendor_a/ring.png",
        "vendor_b/ell.png",
        "vendor_b/star.bmp",
        "vendor_c/ell_small.png",
        "vendor_c/gobo.png",
    ]
    assert [f.rel_path for f in index.skipped] == ["blank.png"]
    assert index.embeddings.shape[0] == index.masks.shape[0] == len(index) == 6
    groups = dict(zip(paths, index.group_ids.tolist(), strict=True))
    assert groups["vendor_b/ell.png"] == groups["vendor_c/ell_small.png"]
    assert len(set(groups.values())) == 5


def test_progress_reports_totals(library):
    calls = []
    build_index(library, CountingEmbedder(), progress=lambda done, total: calls.append((done, total)), batch_size=2)
    assert calls[-1] == (7, 7) and calls[0][1] == 7 and len(calls) == 4


def test_save_and_load_roundtrip(library, tmp_path):
    index = build_index(library, CountingEmbedder())
    target = tmp_path / "cache" / "index.npz"

    save_index(index, target)
    loaded = load_index(target)

    assert loaded.model_id == index.model_id
    assert loaded.files == index.files and loaded.skipped == index.skipped
    assert np.allclose(loaded.embeddings, index.embeddings, atol=1e-3)
    assert np.array_equal(loaded.masks, index.masks)
    assert np.array_equal(loaded.group_ids, index.group_ids)
    assert loaded.embeddings.dtype == np.float32


def test_incremental_build_embeds_only_new_files(library, tmp_path):
    first = CountingEmbedder()
    index = build_index(library, first)
    assert first.count == 6

    from PIL import Image

    Image.fromarray(np.eye(64, dtype=np.uint8) * 255, "L").save(library / "vendor_c" / "diag.png")
    second = CountingEmbedder()
    updated = build_index(library, second, existing=index)

    assert second.count == 1  # blank.png и старые файлы не пересчитываются
    assert len(updated) == 7 and "vendor_c/diag.png" in [f.rel_path for f in updated.files]


def test_changed_file_is_recomputed_and_removed_file_disappears(library):
    index = build_index(library, CountingEmbedder())
    (library / "vendor_a" / "ring.png").unlink()
    star = library / "vendor_b" / "star.bmp"
    os.utime(star, ns=(1_000_000_000, 1_000_000_000))  # другой mtime -> другая сигнатура

    embedder = CountingEmbedder()
    updated = build_index(library, embedder, existing=index)

    assert embedder.count == 1
    assert "vendor_a/ring.png" not in [f.rel_path for f in updated.files]


def test_model_change_forces_full_rebuild(library):
    index = build_index(library, CountingEmbedder("pixels-16"))
    other = CountingEmbedder("another-model")
    build_index(library, other, existing=index)
    assert other.count == 6


def test_cancel_stops_between_batches(library):
    with pytest.raises(IndexCancelled):
        build_index(library, CountingEmbedder(), batch_size=2, cancel=lambda: True)


def test_load_returns_none_for_missing_or_corrupt_file(tmp_path):
    assert load_index(tmp_path / "missing.npz") is None
    broken = tmp_path / "broken.npz"
    broken.write_bytes(b"not a zip")
    assert load_index(broken) is None
