import cv2
import numpy as np
import pytest

from gmagc_desktop import cli
from gmagc_desktop.matcher.embedder import PixelEmbedder
from gmagc_desktop.matcher.synthetic import simulate_photo
from tests.fixtures import shape_images, write_library


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


def test_index_of_missing_library_returns_1_and_writes_nothing(tmp_path, capsys):
    target = tmp_path / "i.npz"
    assert cli.main(["index", str(tmp_path / "nope"), "--index", str(target)]) == 1
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


def test_search_with_other_model_than_index_returns_1(indexed, monkeypatch, capsys):
    library, index_path, tmp = indexed
    photo = save_photo(tmp, "p.png", simulate_photo(shape_images()["ell"], np.random.default_rng(5)))
    monkeypatch.setattr(cli, "make_embedder", lambda model: PixelEmbedder(side=8))
    assert cli.main(["search", str(photo), "--index", str(index_path)]) == 1
    assert "index was built with" in capsys.readouterr().err
