import cv2
import numpy as np
import pytest

from gmagc_desktop import cli
from gmagc_desktop.library.index import LibraryIndex, save_index
from gmagc_desktop.matcher.embedder import PixelEmbedder
from gmagc_desktop.matcher.synthetic import simulate_photo
from tests.fixtures import make_folder_unlistable, shape_images, write_library


@pytest.fixture()
def indexed(tmp_path, capsys):
    library = tmp_path / "lib"
    library.mkdir()
    write_library(library)
    index_path = tmp_path / "index.npz"
    assert cli.main(["index", str(library), "--index", str(index_path)]) == 0
    capsys.readouterr()
    return library, index_path, tmp_path


def save_photo(directory, name, image):
    path = directory / name
    cv2.imencode(".png", image)[1].tofile(str(path))
    return path


def test_index_reports_counts(tmp_path, capsys):
    library = tmp_path / "lib"
    library.mkdir()
    write_library(library)
    assert cli.main(["index", str(library), "--index", str(tmp_path / "i.npz")]) == 0
    assert "6 files indexed (5 unique), 1 skipped" in capsys.readouterr().out


def test_index_reports_files_that_are_unreadable_right_now_and_writes_no_trace_of_them(tmp_path, monkeypatch, capsys):
    from gmagc_desktop.library import index as index_module

    library = tmp_path / "lib"
    library.mkdir()
    write_library(library)
    real = index_module.load_library_gray

    def loader(path):
        if path.name == "ring.png":
            raise OSError("device not ready")
        return real(path)

    monkeypatch.setattr(index_module, "load_library_gray", loader)
    target = tmp_path / "i.npz"

    assert cli.main(["index", str(library), "--index", str(target)]) == 0

    out = capsys.readouterr().out
    assert "5 files indexed (4 unique), 1 skipped, 1 unreadable now (will be retried)" in out
    with np.load(target) as data:
        assert "vendor_a/ring.png" not in data["rel_paths"].tolist() + data["skipped_paths"].tolist()


def test_index_of_missing_library_returns_3_and_writes_nothing(tmp_path, capsys):
    target = tmp_path / "i.npz"
    assert cli.main(["index", str(tmp_path / "nope"), "--index", str(target)]) == 3
    assert "library folder not found" in capsys.readouterr().err
    assert not target.exists()


def test_search_finds_the_right_gobo(indexed, capsys):
    library, index_path, tmp = indexed
    photo = save_photo(tmp, "p.png", simulate_photo(shape_images()["ell"], np.random.default_rng(5)))

    code = cli.main(["search", str(photo), "--index", str(index_path), "--top", "3"])

    first = capsys.readouterr().out.splitlines()[0]
    assert code == 0 and first.startswith(" 1.") and "ell" in first and "(+1 copies)" in first


def test_search_prints_full_paths_when_library_given(indexed, capsys):
    library, index_path, tmp = indexed
    photo = save_photo(tmp, "p.png", simulate_photo(shape_images()["ring"], np.random.default_rng(6)))
    cli.main(["search", str(photo), "--index", str(index_path), "--library", str(library)])
    assert str(library) in capsys.readouterr().out.splitlines()[0]


def test_search_without_projection_returns_2(indexed, capsys):
    library, index_path, tmp = indexed
    flat = save_photo(tmp, "flat.png", np.full((480, 640, 3), 90, np.uint8))
    assert cli.main(["search", str(flat), "--index", str(index_path)]) == 2
    assert "projection not found" in capsys.readouterr().err


def test_search_without_index_returns_1(tmp_path, capsys):
    photo = save_photo(tmp_path, "p.png", np.full((32, 32, 3), 90, np.uint8))
    assert cli.main(["search", str(photo), "--index", str(tmp_path / "nope.npz")]) == 1
    assert "index not found" in capsys.readouterr().err


def test_search_with_other_model_than_index_returns_1(indexed, monkeypatch, capsys):
    library, index_path, tmp = indexed
    photo = save_photo(tmp, "p.png", simulate_photo(shape_images()["ell"], np.random.default_rng(5)))
    monkeypatch.setattr(cli, "make_embedder", lambda model: PixelEmbedder(side=8))
    assert cli.main(["search", str(photo), "--index", str(index_path)]) == 1
    assert "index was built with" in capsys.readouterr().err


def test_search_with_embedder_of_other_dimensions_returns_1_and_asks_to_rebuild(indexed, monkeypatch, capsys):
    library, index_path, tmp = indexed
    photo = save_photo(tmp, "p.png", simulate_photo(shape_images()["ell"], np.random.default_rng(5)))
    other = PixelEmbedder(side=8)
    other.model_id = "pixels-16"  # тот же model_id, что в индексе, но другая размерность векторов
    monkeypatch.setattr(cli, "make_embedder", lambda model: other)

    code = cli.main(["search", str(photo), "--index", str(index_path)])

    out, err = capsys.readouterr()
    assert code == 1 and "rebuild the index" in err and "Traceback" not in err
    assert out == ""


def test_search_with_missing_photo_returns_3(indexed, monkeypatch, capsys):
    library, index_path, tmp = indexed
    msg = "model must not be built before photo is read"
    monkeypatch.setattr(cli, "make_embedder", lambda model: (_ for _ in ()).throw(AssertionError(msg)))
    code = cli.main(["search", str(tmp / "nope.png"), "--index", str(index_path)])
    out, err = capsys.readouterr()
    assert code == 3
    assert "cannot read photo" in err
    assert "Traceback" not in err


def test_search_with_zero_byte_photo_returns_3(indexed, capsys):
    library, index_path, tmp = indexed
    path = tmp / "empty.jpg"
    path.write_bytes(b"")
    code = cli.main(["search", str(path), "--index", str(index_path)])
    out, err = capsys.readouterr()
    assert code == 3
    assert "cannot read photo" in err


def test_search_with_non_image_photo_returns_3(indexed, capsys):
    library, index_path, tmp = indexed
    path = tmp / "text.png"
    path.write_bytes(b"not an image")
    code = cli.main(["search", str(path), "--index", str(index_path)])
    out, err = capsys.readouterr()
    assert code == 3
    assert "cannot read photo" in err


def test_search_with_missing_model_returns_3(indexed, capsys):
    library, index_path, tmp = indexed
    photo = save_photo(tmp, "p.png", simulate_photo(shape_images()["ell"], np.random.default_rng(5)))
    code = cli.main(["search", str(photo), "--index", str(index_path), "--model", str(tmp / "nope.onnx")])
    out, err = capsys.readouterr()
    assert code == 3
    assert "cannot load model" in err


def test_index_with_missing_model_returns_3(tmp_path, capsys):
    library = tmp_path / "lib"
    library.mkdir()
    write_library(library)
    target = tmp_path / "x.npz"
    code = cli.main(["index", str(library), "--index", str(target), "--model", str(tmp_path / "nope.onnx")])
    out, err = capsys.readouterr()
    assert code == 3
    assert not target.exists()


def test_search_with_corrupt_model_returns_3(indexed, capsys):
    library, index_path, tmp = indexed
    garbage = tmp / "garbage.onnx"
    garbage.write_bytes(b"not an onnx model")
    photo = save_photo(tmp, "p.png", simulate_photo(shape_images()["ell"], np.random.default_rng(5)))
    code = cli.main(["search", str(photo), "--index", str(index_path), "--model", str(garbage)])
    out, err = capsys.readouterr()
    assert code == 3
    assert "cannot load model" in err
    assert "Traceback" not in err


def test_index_with_corrupt_model_returns_3(tmp_path, capsys):
    library = tmp_path / "lib"
    library.mkdir()
    write_library(library)
    garbage = tmp_path / "garbage.onnx"
    garbage.write_bytes(b"not an onnx model")
    target = tmp_path / "y.npz"
    code = cli.main(["index", str(library), "--index", str(target), "--model", str(garbage)])
    out, err = capsys.readouterr()
    assert code == 3
    assert "cannot load model" in err
    assert not target.exists()


def test_index_with_an_unlistable_folder_returns_3_and_keeps_the_existing_index(indexed, monkeypatch, capsys):
    library, index_path, tmp = indexed
    before = index_path.read_bytes()
    make_folder_unlistable(monkeypatch, "vendor_b")

    code = cli.main(["index", str(library), "--index", str(index_path)])

    err = capsys.readouterr().err
    assert code == 3
    assert "cannot list directory" in err and "refusing to build a partial index" in err
    assert index_path.read_bytes() == before


def test_index_of_an_empty_library_returns_3_and_keeps_the_existing_index(indexed, capsys):
    library, index_path, tmp = indexed
    before = index_path.read_bytes()
    empty = tmp / "empty_lib"
    empty.mkdir()

    code = cli.main(["index", str(empty), "--index", str(index_path)])

    assert code == 3 and "no PNG/BMP files found" in capsys.readouterr().err
    assert index_path.read_bytes() == before


def test_index_of_an_empty_library_writes_no_index_file(tmp_path, capsys):
    empty = tmp_path / "empty_lib"
    empty.mkdir()
    target = tmp_path / "fresh.npz"

    assert cli.main(["index", str(empty), "--index", str(target)]) == 3
    assert not target.exists()


def test_search_on_an_empty_index_returns_1_with_a_hint(tmp_path, capsys):
    empty_index = LibraryIndex(
        "pixels-16",
        [],
        np.zeros((0, 0), np.float32),
        np.zeros((0, 64, 64), np.uint8),
        np.zeros(0, np.int32),
    )
    index_path = tmp_path / "empty.npz"
    save_index(empty_index, index_path)
    photo = save_photo(tmp_path, "p.png", simulate_photo(shape_images()["ell"], np.random.default_rng(5)))

    code = cli.main(["search", str(photo), "--index", str(index_path)])

    assert code == 1
    assert "index is empty; rebuild it with the 'index' command" in capsys.readouterr().err


def test_read_photo_and_build_embedder_are_public_and_report_to_stderr(tmp_path, capsys):
    assert cli.read_photo(tmp_path / "nope.png") is None
    assert "cannot read photo" in capsys.readouterr().err
    assert cli.build_embedder(str(tmp_path / "nope.onnx")) is None
    assert "cannot load model" in capsys.readouterr().err
    assert isinstance(cli.build_embedder(None), PixelEmbedder)


def test_w_embed_default_is_defined_once(tmp_path):
    import inspect

    from gmagc_desktop.matcher.search import DEFAULT_W_EMBED, Searcher

    assert DEFAULT_W_EMBED == 0.5
    assert inspect.signature(Searcher).parameters["w_embed"].default == DEFAULT_W_EMBED
    args = cli.build_parser().parse_args(["search", "p.png", "--index", "i.npz"])
    assert args.w_embed == DEFAULT_W_EMBED
