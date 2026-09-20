import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "fetch_model.py"


def load_script():
    spec = importlib.util.spec_from_file_location("fetch_model", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_variant_urls():
    module = load_script()
    base = "https://huggingface.co/onnx-community/dinov2-small/resolve/main/onnx/"
    assert module.variant_url("fp32") == base + "model.onnx"
    assert module.variant_url("int8") == base + "model_int8.onnx"
    assert module.variant_url("fp16") == base + "model_fp16.onnx"


def test_unknown_variant_is_rejected():
    with pytest.raises(KeyError):
        load_script().variant_url("q4")
