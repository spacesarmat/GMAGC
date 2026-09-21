import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[2] / "apps" / "mobile" / "pyproject.toml"


def load():
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def test_the_camera_permission_is_requested_for_the_android_manifest():
    assert "camera" in load()["tool"]["flet"]["permissions"]


def test_cleartext_http_is_allowed_for_the_local_network():
    application = load()["tool"]["flet"]["android"]["manifest_application"]

    assert application["usesCleartextTraffic"] == "true"


def test_the_qr_and_image_libraries_are_dependencies_and_flet_stays_pinned():
    dependencies = " ".join(load()["project"]["dependencies"])

    assert "pyzbar" in dependencies and "Pillow" in dependencies
    assert "flet==1.0.0" in dependencies and "flet-camera==1.0.0" in dependencies
