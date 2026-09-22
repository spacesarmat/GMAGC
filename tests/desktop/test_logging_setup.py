import logging

from gmagc_desktop.service.logging_setup import setup_logging


def test_setup_logging_creates_the_file_and_writes_to_it(tmp_path):
    log_path = setup_logging(tmp_path / "data")

    assert log_path == tmp_path / "data" / "gmagc.log"
    logging.getLogger("gmagc").error("что-то пошло не так")

    assert "что-то пошло не так" in log_path.read_text(encoding="utf-8")


def test_calling_it_twice_does_not_duplicate_handlers_or_log_lines(tmp_path):
    setup_logging(tmp_path / "data")
    log_path = setup_logging(tmp_path / "data")

    logging.getLogger("gmagc").warning("одна строка")

    lines = [line for line in log_path.read_text(encoding="utf-8").splitlines() if "одна строка" in line]
    assert len(lines) == 1
