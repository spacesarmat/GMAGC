import pytest

from gmagc_desktop.library.cache import update_index
from gmagc_desktop.library.index import IndexCancelled
from gmagc_desktop.matcher.embedder import PixelEmbedder
from tests.fixtures import write_library


@pytest.fixture()
def library(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    write_library(root)
    return root


def test_update_index_builds_saves_and_reuses_the_cache(library, tmp_path):
    path = tmp_path / "cache" / "index.npz"
    calls = []

    first = update_index(library, PixelEmbedder(), path, progress=lambda done, total: calls.append((done, total)))

    assert path.exists() and len(first) == 6
    assert calls and calls[-1][0] == calls[-1][1]

    second = update_index(library, PixelEmbedder(), path)

    assert len(second) == 6 and second.model_id == first.model_id


def test_update_index_keeps_the_previous_cache_as_a_backup_before_overwriting(library, tmp_path):
    path = tmp_path / "cache" / "index.npz"
    backup = path.with_name("index.npz.previous")

    update_index(library, PixelEmbedder(), path)
    assert not backup.exists()  # первая сборка: старого индекса ещё нет, резервировать нечего

    update_index(library, PixelEmbedder(), path)
    assert backup.exists() and backup.stat().st_size > 0  # второй раз: прежний файл сохранён как резерв


def test_cancelled_update_saves_nothing(library, tmp_path):
    path = tmp_path / "cache" / "index.npz"

    with pytest.raises(IndexCancelled):
        update_index(library, PixelEmbedder(), path, cancel=lambda: True)

    assert not path.exists()
