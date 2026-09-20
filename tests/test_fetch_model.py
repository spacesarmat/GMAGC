import hashlib
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


class FakeResponse:
    def __init__(self, chunks, content_length=None, fail_after=None):
        self._chunks = list(chunks)
        self._sent = 0
        self._fail_after = fail_after
        self.headers = {} if content_length is None else {"Content-Length": str(content_length)}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, size):
        if self._fail_after is not None and self._sent >= self._fail_after:
            raise ConnectionResetError("boom")
        if not self._chunks:
            return b""
        self._sent += 1
        return self._chunks.pop(0)


def fake_urlopen(response):
    return lambda url, timeout=None: response


def test_download_writes_target_returns_sha256_and_leaves_no_part(tmp_path, monkeypatch):
    module = load_script()
    chunks = [b"a" * 1000, b"b" * 500]
    content_length = 1500
    response = FakeResponse(chunks, content_length=content_length)
    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen(response))

    target = tmp_path / "dinov2.onnx"
    checksum = module.download("http://example.com/model.onnx", target)

    # Verify target content
    expected_content = b"a" * 1000 + b"b" * 500
    assert target.read_bytes() == expected_content

    # Verify checksum
    expected_hash = hashlib.sha256(expected_content).hexdigest()
    assert checksum == expected_hash

    # Verify .part file does not exist
    part = target.with_name(target.name + ".part")
    assert not part.exists()


def test_short_download_keeps_the_existing_model(tmp_path, monkeypatch):
    module = load_script()
    target = tmp_path / "dinov2.onnx"
    target.write_bytes(b"good")

    chunks = [b"x" * 10]
    response = FakeResponse(chunks, content_length=100)
    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen(response))

    with pytest.raises(OSError, match="incomplete"):
        module.download("http://example.com/model.onnx", target)

    # Verify target still has original content
    assert target.read_bytes() == b"good"

    # Verify .part file does not exist
    part = target.with_name(target.name + ".part")
    assert not part.exists()


def test_interrupted_download_leaves_neither_target_nor_part(tmp_path, monkeypatch):
    module = load_script()
    chunks = [b"x" * 10, b"y" * 10]
    response = FakeResponse(chunks, fail_after=1)
    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen(response))

    target = tmp_path / "dinov2.onnx"

    with pytest.raises(ConnectionResetError):
        module.download("http://example.com/model.onnx", target)

    # Verify target does not exist
    assert not target.exists()

    # Verify .part file does not exist
    part = target.with_name(target.name + ".part")
    assert not part.exists()


def test_main_skips_an_existing_model_without_force(tmp_path, monkeypatch):
    module = load_script()
    target = tmp_path / "dinov2-small-fp32.onnx"
    target.write_bytes(b"existing")

    # Monkeypatch download to raise if called
    def mock_download(*args, **kwargs):
        raise AssertionError("must not download")

    monkeypatch.setattr(module, "download", mock_download)

    result = module.main(["--out", str(tmp_path)])

    assert result == 0
    # File should be unchanged
    assert target.read_bytes() == b"existing"


def test_main_force_redownloads_and_writes_checksum_last(tmp_path, monkeypatch):
    module = load_script()
    target = tmp_path / "dinov2-small-fp32.onnx"
    target.write_bytes(b"old")

    # Monkeypatch download to write new content and return checksum
    def mock_download(url, target_path, timeout=60.0):
        target_path.write_bytes(b"new")
        return "abc123"

    monkeypatch.setattr(module, "download", mock_download)

    result = module.main(["--out", str(tmp_path), "--force"])

    assert result == 0
    # Target should have new content
    assert target.read_bytes() == b"new"
    # Checksum file should exist and have correct format
    sha_file = tmp_path / "dinov2-small-fp32.onnx.sha256"
    assert sha_file.read_text(encoding="utf-8") == "abc123  dinov2-small-fp32.onnx\n"
