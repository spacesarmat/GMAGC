import json
from pathlib import Path

import pytest

from gmagc_desktop.scan.engine import LocalScanner, ScanError, ScanUnavailableError, is_pdf
from gmagc_desktop.scan.table import items_from_dict

DATA = Path(__file__).resolve().parents[1] / "data" / "ocr"


def items(name):
    return items_from_dict(json.loads((DATA / f"{name}.json").read_text(encoding="utf-8")))


def fake_ocr(pages):
    """Распознаватель, который по очереди отдаёт заготовленные страницы."""
    queue = list(pages)
    return lambda _image: items(queue.pop(0))


def test_a_photo_gives_a_draft_of_its_table():
    draft = LocalScanner(ocr=fake_ocr(["led_bar_photo_4ch"])).scan(b"\xff\xd8photo")

    assert [m.name for m in draft.modes] == ["4CH"]
    assert [c.template for c in draft.modes[0].channels] == ["red", "green", "blue", "white"]


def test_the_pages_of_a_pdf_are_merged_into_one_draft():
    scanner = LocalScanner(ocr=fake_ocr(["led_bar_scan_p04", "led_bar_scan_p05"]), renderer=lambda _pdf: [b"1", b"2"])

    draft = scanner.scan(b"%PDF-1.7 ...")

    assert [m.name for m in draft.modes] == ["4CH", "9CH"]
    assert len(draft.modes[1].channels[2].ranges) >= 10


def test_a_page_without_a_table_gives_a_warning_only_when_nothing_was_found():
    empty = LocalScanner(ocr=lambda _image: []).scan(b"photo")
    assert empty.modes == () and empty.warnings == ("no_table",)

    scanner = LocalScanner(ocr=fake_ocr(["led_bar_photo_4ch", "led_bar_photo_4ch"]), renderer=lambda _pdf: [b"1", b"2"])
    assert scanner.scan(b"%PDF-1.4").warnings == ()


def test_a_recognizer_failure_is_a_scan_error():
    def broken(_image):
        raise ValueError("не картинка")

    with pytest.raises(ScanError):
        LocalScanner(ocr=broken).scan(b"junk")


def test_a_missing_library_is_reported_as_unavailable(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name.startswith("rapidocr"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    with pytest.raises(ScanUnavailableError):
        LocalScanner().scan(b"photo")


def test_pdf_is_recognised_by_its_signature():
    assert is_pdf(b"%PDF-1.5\n") and is_pdf(b"\n %PDF-1.7") and not is_pdf(b"\x89PNG")
