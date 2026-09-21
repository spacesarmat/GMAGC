import os
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image, UnidentifiedImageError

from gmagc_desktop.library.index import (
    IndexCancelled,
    LibraryNotFound,
    LibraryScanError,
    build_index,
    load_index,
    save_index,
)
from gmagc_desktop.matcher.embedder import PixelEmbedder
from tests.fixtures import make_file_vanish_during_walk, make_folder_unlistable, write_library


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


def test_load_returns_none_when_the_npy_header_is_cut_off(tmp_path):
    """Оборванный заголовок .npy внутри npz: numpy бросает tokenize.TokenError, а не ValueError."""
    import struct
    import zipfile

    header = b"{'descr': '<i8', 'fortran_order': False, 'shape': (1,"
    header += b" " * ((64 - (10 + len(header) + 1) % 64) % 64) + b"\n"
    npy = b"\x93NUMPY\x01\x00" + struct.pack("<H", len(header)) + header + b"\x00" * 8
    damaged = tmp_path / "cut_header.npz"
    with zipfile.ZipFile(damaged, "w") as archive:
        archive.writestr("format_version.npy", npy)

    assert load_index(damaged) is None


def test_load_never_raises_on_damaged_cache(library, tmp_path):
    target = tmp_path / "index.npz"
    save_index(build_index(library, CountingEmbedder()), target)
    data = target.read_bytes()
    damaged = tmp_path / "damaged.npz"

    damaged.write_bytes(data[: len(data) // 2])
    assert load_index(damaged) is None

    for offset in range(64, len(data) - 64, max(1, len(data) // 40)):
        broken = bytearray(data)
        for i in range(offset, offset + 8):
            broken[i] ^= 0xFF
        damaged.write_bytes(bytes(broken))
        load_index(damaged)  # None или индекс допустимы, исключения быть не должно


def test_missing_library_root_raises_instead_of_returning_an_empty_index(tmp_path):
    with pytest.raises(FileNotFoundError):
        build_index(tmp_path / "unplugged", CountingEmbedder())


def test_skipped_files_are_not_reopened_until_they_change(library, monkeypatch):
    from gmagc_desktop.library import index as index_module

    opened = []
    real = index_module.load_library_gray
    monkeypatch.setattr(index_module, "load_library_gray", lambda path: opened.append(Path(path).name) or real(path))

    first = build_index(library, CountingEmbedder())
    assert "blank.png" in opened
    opened.clear()

    second = build_index(library, CountingEmbedder(), existing=first)
    assert opened == []  # ни один файл не открывался: строки и «пропущенные» взяты из кэша

    os.utime(library / "blank.png", ns=(2_000_000_000, 2_000_000_000))
    build_index(library, CountingEmbedder(), existing=second)
    assert opened == ["blank.png"]  # изменившийся пропущенный файл пробуем снова


def test_permission_and_program_errors_are_not_swallowed(library, monkeypatch):
    from gmagc_desktop.library import index as index_module

    def failing(error):
        def loader(path):
            raise error

        return loader

    monkeypatch.setattr(index_module, "load_library_gray", failing(PermissionError("locked")))
    with pytest.raises(PermissionError):
        build_index(library, CountingEmbedder())

    monkeypatch.setattr(index_module, "load_library_gray", failing(TypeError("bug")))
    with pytest.raises(TypeError):
        build_index(library, CountingEmbedder())


def test_corrupt_image_is_skipped_with_a_warning(library, caplog):
    (library / "vendor_a" / "broken.png").write_bytes(b"not a png")
    with caplog.at_level("WARNING"):
        index = build_index(library, CountingEmbedder())
    assert "vendor_a/broken.png" in [f.rel_path for f in index.skipped]
    assert "broken.png" in caplog.text


def test_missing_library_root_raises_library_not_found_with_the_path(tmp_path):
    with pytest.raises(LibraryNotFound, match="library folder not found") as caught:
        build_index(tmp_path / "unplugged", CountingEmbedder())
    assert isinstance(caught.value, FileNotFoundError) and "unplugged" in str(caught.value)


def test_unlistable_directory_aborts_instead_of_building_a_partial_index(library, monkeypatch):
    make_folder_unlistable(monkeypatch, "vendor_b")
    embedder = CountingEmbedder()

    with pytest.raises(LibraryScanError, match="refusing to build a partial index") as caught:
        build_index(library, embedder)

    assert "cannot list directory" in str(caught.value) and "vendor_b" in str(caught.value)
    assert "1 problem" in str(caught.value)
    assert embedder.count == 0  # ничего не встраивалось: индекс не строился


def test_empty_library_folder_raises_instead_of_returning_an_empty_index(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "notes.txt").write_text("not an image", encoding="utf-8")
    with pytest.raises(LibraryScanError, match="no PNG/BMP files found"):
        build_index(empty, CountingEmbedder())


def test_library_of_only_unreadable_files_raises(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    (root / "broken.png").write_bytes(b"not a png")
    (root / "also_broken.bmp").write_bytes(b"not a bmp")
    with pytest.raises(LibraryScanError, match=r"none of the 2 library files could be read"):
        build_index(root, CountingEmbedder())


def test_file_vanishing_between_walk_and_stat_is_skipped_by_the_build(library, monkeypatch):
    make_file_vanish_during_walk(monkeypatch, "vendor_a/ring.png")

    index = build_index(library, CountingEmbedder())

    paths = [f.rel_path for f in index.files]
    assert "vendor_a/ring.png" not in paths and "vendor_a/dots.png" in paths
    assert len(index) == 5 and [f.rel_path for f in index.skipped] == ["blank.png"]


def _fail_on(monkeypatch, name, error_factory):
    """Подменяет загрузчик: файл с именем name падает с error_factory() (пока флаг не сброшен)."""
    from gmagc_desktop.library import index as index_module

    real = index_module.load_library_gray
    state = {"failing": True, "opened": []}

    def loader(path):
        state["opened"].append(Path(path).name)
        if state["failing"] and Path(path).name == name:
            raise error_factory()
        return real(path)

    monkeypatch.setattr(index_module, "load_library_gray", loader)
    return state


def test_transient_read_failure_is_retried_and_never_persisted(library, tmp_path, monkeypatch, caplog):
    state = _fail_on(monkeypatch, "ring.png", lambda: OSError("device not ready"))

    with caplog.at_level("WARNING"):
        first = build_index(library, CountingEmbedder())

    assert [f.rel_path for f in first.transient] == ["vendor_a/ring.png"]
    assert "vendor_a/ring.png" not in [f.rel_path for f in first.skipped]
    assert "vendor_a/ring.png" not in [f.rel_path for f in first.files]
    assert "ring.png" in caplog.text and "device not ready" in caplog.text

    target = tmp_path / "cache" / "index.npz"
    save_index(first, target)
    with np.load(target) as data:
        persisted = set(data["rel_paths"].tolist()) | set(data["skipped_paths"].tolist())
    assert "vendor_a/ring.png" not in persisted
    loaded = load_index(target)
    assert loaded.transient == []

    state["failing"] = False
    embedder = CountingEmbedder()
    second = build_index(library, embedder, existing=loaded)

    assert embedder.count == 1  # пересчитан только файл, который раньше не удалось прочитать
    assert "vendor_a/ring.png" in [f.rel_path for f in second.files]
    assert second.transient == [] and [f.rel_path for f in second.skipped] == ["blank.png"]


@pytest.mark.parametrize(
    "make_error",
    [
        lambda: UnidentifiedImageError("cannot identify image file"),
        lambda: ValueError("bad value"),
        lambda: SyntaxError("broken PNG file"),
        lambda: cv2.error("bad image"),
        lambda: Image.DecompressionBombError("too large"),
    ],
    ids=["unidentified", "value", "syntax", "cv2", "bomb"],
)
def test_definitive_decode_failures_are_skipped_and_persisted(library, tmp_path, monkeypatch, make_error):
    _fail_on(monkeypatch, "ring.png", make_error)

    index = build_index(library, CountingEmbedder())

    assert "vendor_a/ring.png" in [f.rel_path for f in index.skipped]
    assert index.transient == []
    target = tmp_path / "index.npz"
    save_index(index, target)
    assert "vendor_a/ring.png" in [f.rel_path for f in load_index(target).skipped]


def test_corrupt_png_stays_skipped_and_is_not_reopened(library, monkeypatch):
    (library / "vendor_a" / "broken.png").write_bytes(b"not a png")
    first = build_index(library, CountingEmbedder())
    assert "vendor_a/broken.png" in [f.rel_path for f in first.skipped] and first.transient == []

    state = _fail_on(monkeypatch, "nothing.png", RuntimeError)  # только для учёта открытых файлов
    second = build_index(library, CountingEmbedder(), existing=first)

    assert state["opened"] == []
    assert "vendor_a/broken.png" in [f.rel_path for f in second.skipped]


def test_library_where_every_read_is_transient_raises_none_could_be_read(library, monkeypatch):
    from gmagc_desktop.library import index as index_module

    def unplugged(path):
        raise OSError("device not ready")

    monkeypatch.setattr(index_module, "load_library_gray", unplugged)
    with pytest.raises(LibraryScanError, match=r"none of the 7 library files could be read"):
        build_index(library, CountingEmbedder())
