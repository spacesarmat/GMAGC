import numpy as np
import pytest

from gmagc_desktop.library.grouping import group_duplicates
from gmagc_desktop.matcher.embedder import PixelEmbedder
from gmagc_desktop.matcher.normalize import normalize_gray
from gmagc_desktop.matcher.search import IndexMismatchError, SearchData, Searcher
from gmagc_desktop.matcher.shape import soft_mask
from gmagc_desktop.matcher.variants import rotate_image
from tests.fixtures import shape_images


def angle_error(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


@pytest.fixture(scope="module")
def library():
    images = shape_images()
    names = list(images)
    normalized = [normalize_gray(images[name]) for name in names]
    embedder = PixelEmbedder()
    embeddings = embedder.embed(np.stack(normalized))
    masks = np.stack([soft_mask(n) for n in normalized])
    data = SearchData(embeddings, masks, group_duplicates(embeddings, masks))
    return names, normalized, embedder, data


@pytest.mark.parametrize("w_embed", [0.0, 0.5, 1.0])
def test_rotated_query_finds_its_family_and_reports_members(library, w_embed):
    names, normalized, embedder, data = library
    query = rotate_image(normalized[names.index("ell")], 137.0)

    top = Searcher(data, embedder, w_embed=w_embed).search(query, top_n=3)[0]

    assert {names[i] for i in top.members} == {"ell", "ell_small"}
    assert top.index in top.members and 0.0 <= top.score <= 1.0
    if w_embed < 1.0:
        assert angle_error(top.angle, 223.0) < 3.0 and not top.mirrored


@pytest.mark.parametrize("w", [0.0, 0.3, 0.5, 1.0])
def test_score_is_the_weighted_sum_of_embed_and_shape_scores(library, w):
    names, normalized, embedder, data = library
    query = rotate_image(normalized[names.index("gobo")], 40.0)

    matches = Searcher(data, embedder, w_embed=w).search(query, top_n=10)

    assert len(matches) > 1
    for match in matches:
        assert match.score == pytest.approx(w * max(match.embed_score, 0.0) + (1 - w) * match.shape_score)


def test_mirrored_query_is_flagged_mirrored(library):
    names, normalized, embedder, data = library
    query = rotate_image(np.ascontiguousarray(normalized[names.index("ell")][:, ::-1]), 60.0)

    top = Searcher(data, embedder).search(query, top_n=1)[0]

    assert {names[i] for i in top.members} == {"ell", "ell_small"}
    assert top.mirrored and angle_error(top.angle, 60.0) < 3.0


def test_one_result_per_family_sorted_by_score(library):
    names, normalized, embedder, data = library
    results = Searcher(data, embedder).search(normalized[names.index("gobo")], top_n=10)
    families = [data.group_ids[r.index] for r in results]
    assert len(set(families)) == len(families) == len(set(data.group_ids.tolist()))
    assert [r.score for r in results] == sorted((r.score for r in results), reverse=True)
    assert names[results[0].index] == "gobo"


def test_top_n_limits_results_and_empty_index_is_safe(library):
    names, normalized, embedder, data = library
    assert len(Searcher(data, embedder).search(normalized[0], top_n=2)) == 2
    empty = SearchData(
        np.zeros((0, 0), np.float32), np.zeros((0, 64, 64), np.uint8), np.zeros(0, np.int32)
    )
    assert Searcher(empty, embedder).search(normalized[0]) == []


def test_top_n_above_the_shortlist_extends_the_shortlist_instead_of_capping_the_results(library):
    names, normalized, embedder, data = library
    searcher = Searcher(data, embedder, shortlist=2)

    assert len(searcher.search(normalized[0], top_n=2)) == 2
    assert len(searcher.search(normalized[0], top_n=4)) == 4


def test_embedder_with_other_dimensions_than_the_index_is_rejected_clearly(library):
    names, normalized, embedder, data = library  # индекс построен PixelEmbedder(side=16): 256 измерений
    other = PixelEmbedder(side=8)  # 64 измерения

    with pytest.raises(IndexMismatchError, match="256 dimensions but the embedder produced 64; rebuild the index"):
        Searcher(data, other).search(normalized[0])

    assert isinstance(IndexMismatchError("x"), ValueError)
