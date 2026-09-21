import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import phone_sim  # noqa: E402

from gmagc_common.protocol import build_link  # noqa: E402


def save_bytes(tmp_path, data, name="photo.jpg"):
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_prepare_jpeg_shrinks_big_photos_and_keeps_small_ones(tmp_path):
    big = tmp_path / "big.png"
    cv2.imwrite(str(big), np.full((2000, 3000, 3), 120, np.uint8))
    small = tmp_path / "small.png"
    cv2.imwrite(str(small), np.full((300, 400, 3), 120, np.uint8))

    big_jpeg = cv2.imdecode(np.frombuffer(phone_sim.prepare_jpeg(big), np.uint8), cv2.IMREAD_COLOR)
    small_jpeg = cv2.imdecode(np.frombuffer(phone_sim.prepare_jpeg(small), np.uint8), cv2.IMREAD_COLOR)

    assert max(big_jpeg.shape[:2]) == 1280 and big_jpeg.shape[:2] == (853, 1280)
    assert small_jpeg.shape[:2] == (300, 400)


def test_prepare_jpeg_reads_paths_with_non_ascii_names(tmp_path):
    path = tmp_path / "фото проекции.png"
    ok, buffer = cv2.imencode(".png", np.full((100, 100, 3), 50, np.uint8))
    path.write_bytes(buffer.tobytes())

    assert phone_sim.prepare_jpeg(path).startswith(b"\xff\xd8")


def test_prepare_jpeg_rejects_a_non_image(tmp_path):
    with pytest.raises(ValueError):
        phone_sim.prepare_jpeg(save_bytes(tmp_path, b"not an image", "x.jpg"))


def test_main_with_a_link_prints_the_outcome_and_the_results(tmp_path, running, photo_jpeg, capsys):
    photo = save_bytes(tmp_path, photo_jpeg)
    link = build_link("127.0.0.1", running.port, running.code)

    code = phone_sim.main(["--link", link, str(photo)])

    out = capsys.readouterr().out
    assert code == 0 and "исход:" in out and " 1. " in out and ".png" in out
    assert len(running.records) == 1


def test_main_with_host_port_code_and_top(tmp_path, running, photo_jpeg, capsys):
    photo = save_bytes(tmp_path, photo_jpeg)

    code = phone_sim.main(
        ["--host", "127.0.0.1", "--port", str(running.port), "--code", running.code.lower(), "--top", "2", str(photo)]
    )

    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()[:2] in {"1.", "2.", "3."}]
    assert code == 0 and len(lines) == 2


def test_wrong_code_exits_with_1_and_names_the_error(tmp_path, running, photo_jpeg, capsys):
    photo = save_bytes(tmp_path, photo_jpeg)

    code = phone_sim.main(["--host", "127.0.0.1", "--port", str(running.port), "--code", "ABCD2346", str(photo)])

    assert code == 1 and "unauthorized" in capsys.readouterr().err


def test_a_closed_port_exits_with_2(tmp_path, running, photo_jpeg, capsys):
    photo = save_bytes(tmp_path, photo_jpeg)
    running.server.stop()

    code = phone_sim.main(["--host", "127.0.0.1", "--port", str(running.port), "--code", running.code, str(photo)])

    assert code == 2 and "нет соединения" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        ["photo.jpg"],
        ["--host", "127.0.0.1", "photo.jpg"],
        ["--link", "мусор", "photo.jpg"],
        ["--host", "bad host", "--code", "ABCD2345", "photo.jpg"],
        ["--host", "127.0.0.1", "--code", "BAD", "photo.jpg"],
    ],
)
def test_bad_arguments_exit_with_3(argv, capsys):
    assert phone_sim.main(argv) == 3
    assert capsys.readouterr().err


def test_a_missing_photo_exits_with_3(tmp_path, running, capsys):
    link = build_link("127.0.0.1", running.port, running.code)

    assert phone_sim.main(["--link", link, str(tmp_path / "нет.jpg")]) == 3
    assert "не удалось прочитать фото" in capsys.readouterr().err
