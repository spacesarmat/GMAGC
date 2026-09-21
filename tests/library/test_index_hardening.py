import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from gmagc_desktop.library import index as index_module
from gmagc_desktop.library.index import LibraryIndex, build_index, load_index, save_index
from gmagc_desktop.library.scan import LibraryFile
from gmagc_desktop.matcher.embedder import PixelEmbedder
from tests.fixtures import shape_images, write_library


def _truncated_png(path: Path) -> None:
    buffer = io.BytesIO()
    Image.fromarray(shape_images()["dots"], "L").save(buffer, format="PNG")
    data = buffer.getvalue()
    path.write_bytes(data[: len(data) // 2])


def _one_file_index(rel_path: str) -> LibraryIndex:
    return LibraryIndex(
        "pixels-16",
        [LibraryFile(rel_path, 10, 5)],
        np.zeros((1, 4), np.float32),
        np.zeros((1, 64, 64), np.uint8),
        np.zeros(1, np.int32),
    )


def test_truncated_png_is_a_permanent_skip_not_a_transient_failure(tmp_path, monkeypatch):
    library = tmp_path / "lib"
    library.mkdir()
    write_library(library)
    _truncated_png(library / "vendor_a" / "cut.png")

    first = build_index(library, PixelEmbedder())

    assert "vendor_a/cut.png" in [f.rel_path for f in first.skipped]
    assert first.transient == []

    opened = []
    real = index_module.load_library_gray
    monkeypatch.setattr(index_module, "load_library_gray", lambda path: opened.append(Path(path).name) or real(path))
    build_index(library, PixelEmbedder(), existing=first)
    assert "cut.png" not in opened  # окончательно испорченный файл повторно не открывается


@pytest.mark.parametrize("bad", ["../evil.png", "/abs/evil.png", "C:/evil.png", "a/../../evil.png", "..\\evil.png"])
def test_load_index_rejects_unsafe_relative_paths(tmp_path, bad):
    target = tmp_path / "index.npz"
    save_index(_one_file_index(bad), target)

    assert load_index(target) is None


def test_load_index_accepts_nested_relative_paths(tmp_path):
    target = tmp_path / "index.npz"
    save_index(_one_file_index("vendor/sub dir/a.png"), target)

    loaded = load_index(target)

    assert loaded is not None and loaded.files[0].rel_path == "vendor/sub dir/a.png"


def test_save_index_leaves_no_temp_files_and_keeps_the_old_index_on_failure(tmp_path, monkeypatch):
    library = tmp_path / "lib"
    library.mkdir()
    write_library(library)
    index = build_index(library, PixelEmbedder())
    target = tmp_path / "cache" / "index.npz"

    save_index(index, target)
    assert [p.name for p in target.parent.iterdir()] == ["index.npz"]
    before = target.read_bytes()

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(np, "savez_compressed", boom)
    with pytest.raises(OSError, match="disk full"):
        save_index(index, target)

    assert target.read_bytes() == before
    assert [p.name for p in target.parent.iterdir()] == ["index.npz"]
