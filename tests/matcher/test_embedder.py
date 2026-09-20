import numpy as np
import onnx
from onnx import TensorProto, helper

from gmagc_desktop.matcher.embedder import (
    IMAGENET_MEAN,
    IMAGENET_STD,
    OnnxEmbedder,
    PixelEmbedder,
    l2_normalize,
    pool_output,
)
from tests.helpers import l_shape, sample_gobo


def make_mean_model(path):
    """Крошечная ONNX-модель: среднее по H и W для каждого из 3 каналов."""
    source = helper.make_tensor_value_info("pixel_values", TensorProto.FLOAT, ["N", 3, 224, 224])
    target = helper.make_tensor_value_info("embedding", TensorProto.FLOAT, ["N", 3])
    node = helper.make_node("ReduceMean", ["pixel_values"], ["embedding"], axes=[2, 3], keepdims=0)
    graph = helper.make_graph([node], "mean", [source], [target])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 8
    onnx.save(model, str(path))


def test_l2_normalize_rows():
    out = l2_normalize(np.array([[3.0, 4.0], [0.0, 0.0]]))
    assert np.allclose(out[0], [0.6, 0.8])
    assert np.isfinite(out).all()


def test_pixel_embedder_identical_vs_different():
    embedder = PixelEmbedder()
    a = np.stack([sample_gobo(224), sample_gobo(224), l_shape((224, 224), 0.7)])
    out = embedder.embed(a)
    assert out.shape[0] == 3 and np.allclose(np.linalg.norm(out, axis=1), 1.0, atol=1e-5)
    assert out[0] @ out[1] > 0.999
    assert out[0] @ out[2] < 0.9


def test_onnx_embedder_preprocess_and_output(tmp_path):
    model_path = tmp_path / "tiny.onnx"
    make_mean_model(model_path)
    embedder = OnnxEmbedder(model_path)
    out = embedder.embed(np.full((3, 224, 224), 128, np.uint8))
    expected = (128 / 255 - IMAGENET_MEAN) / IMAGENET_STD
    expected = expected / np.linalg.norm(expected)
    assert out.shape == (3, 3) and out.dtype == np.float32
    assert np.allclose(out[0], expected, atol=1e-5)
    assert embedder.model_id.startswith("onnx-tiny-")


def test_onnx_embedder_handles_many_batches(tmp_path):
    model_path = tmp_path / "tiny.onnx"
    make_mean_model(model_path)
    out = OnnxEmbedder(model_path, batch_size=32).embed(np.zeros((70, 224, 224), np.uint8))
    assert out.shape == (70, 3)


def test_pool_output_concatenates_cls_and_mean_patch():
    tokens = np.arange(2 * 5 * 4, dtype=np.float32).reshape(2, 5, 4)
    out = pool_output(tokens)
    assert out.shape == (2, 8)
    assert np.array_equal(out[:, :4], tokens[:, 0])
    assert np.allclose(out[:, 4:], tokens[:, 1:].mean(axis=1))
