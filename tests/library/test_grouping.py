import numpy as np

from gmagc_desktop.library import grouping
from gmagc_desktop.library.grouping import group_duplicates


def unit(*values):
    vector = np.array(values, dtype=np.float32)
    return vector / np.linalg.norm(vector)


def mask(filled: slice) -> np.ndarray:
    image = np.zeros((8, 8), np.uint8)
    image[filled, :] = 255
    return image


def _duplicated_library() -> tuple[np.ndarray, np.ndarray]:
    """Construct a test library with 6 unique items + 3 duplicates of the first 3."""
    rng = np.random.default_rng(0)
    base = rng.normal(size=(6, 16)).astype(np.float32)
    embeddings = np.concatenate([base, base[:3]])
    embeddings /= np.linalg.norm(embeddings, axis=1, keepdims=True)
    masks = np.stack([mask(slice(i % 4, i % 4 + 3)) for i in range(6)] + [mask(slice(i % 4, i % 4 + 3)) for i in range(3)])
    return embeddings, masks


def test_identical_items_share_a_group_and_others_stay_alone():
    embeddings = np.stack([unit(1, 0, 0), unit(1, 0, 0), unit(0, 1, 0)])
    masks = np.stack([mask(slice(0, 4)), mask(slice(0, 4)), mask(slice(4, 8))])
    assert group_duplicates(embeddings, masks).tolist() == [0, 0, 2]


def test_same_embedding_but_different_mask_is_not_a_duplicate():
    embeddings = np.stack([unit(1, 0, 0), unit(1, 0, 0)])
    masks = np.stack([mask(slice(0, 3)), mask(slice(5, 8))])
    assert group_duplicates(embeddings, masks).tolist() == [0, 1]


def test_groups_are_transitive():
    embeddings = np.stack([unit(1, 0.0, 0), unit(1, 0.15, 0), unit(1, 0.3, 0)])
    masks = np.stack([mask(slice(0, 4))] * 3)
    # cos(0,1)=0.989 и cos(1,2)=0.990 проходят порог, cos(0,2)=0.958 нет: группа собирается цепочкой
    ids = group_duplicates(embeddings, masks, cosine_threshold=0.98)
    assert ids.tolist() == [0, 0, 0]


def test_block_size_does_not_change_result():
    embeddings, masks = _duplicated_library()
    assert group_duplicates(embeddings, masks, block=2).tolist() == group_duplicates(
        embeddings, masks, block=512
    ).tolist()
    assert group_duplicates(embeddings, masks).tolist()[6:] == [0, 1, 2]


def test_pair_chunking_does_not_change_result(monkeypatch):
    embeddings, masks = _duplicated_library()
    baseline = group_duplicates(embeddings, masks)
    monkeypatch.setattr(grouping, "PAIR_BUDGET_BYTES", 1)  # -> one pair per chunk
    assert group_duplicates(embeddings, masks).tolist() == baseline.tolist()


def test_empty_input():
    ids = group_duplicates(np.zeros((0, 0), np.float32), np.zeros((0, 8, 8), np.uint8))
    assert ids.shape == (0,) and ids.dtype == np.int32
