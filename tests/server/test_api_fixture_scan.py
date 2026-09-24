import json
from pathlib import Path

from gmagc_common.protocol import MAX_SCAN_BYTES, ApiError
from gmagc_common.scan_draft import ScanDraft
from gmagc_desktop.scan.engine import LocalScanner, ScanUnavailableError
from gmagc_desktop.scan.table import items_from_dict

DATA = Path(__file__).resolve().parents[1] / "data" / "ocr"


def use_photo(running, name="led_bar_photo_4ch"):
    items = items_from_dict(json.loads((DATA / f"{name}.json").read_text(encoding="utf-8")))
    running.server._context.scanner = LocalScanner(ocr=lambda _image: items)


def test_a_photo_of_the_table_gives_a_draft(call, running):
    use_photo(running)

    status, _, body = call("POST", "/api/fixture-scan", b"\xff\xd8photo")

    draft = ScanDraft.from_dict(body)
    assert status == 200 and [m.name for m in draft.modes] == ["4CH"]
    assert [c.template for c in draft.modes[0].channels] == ["red", "green", "blue", "white"]


def test_scanning_requires_the_access_code(call, running):
    use_photo(running)

    status, _, body = call("POST", "/api/fixture-scan", b"photo", code="ABCD2346")

    assert status == 401 and ApiError.from_dict(body).code == "unauthorized"


def test_an_empty_or_huge_file_is_refused(call, running):
    use_photo(running)

    status, _, body = call("POST", "/api/fixture-scan", b"")
    assert status == 400 and ApiError.from_dict(body).code == "bad_scan"

    status, _, body = call("POST", "/api/fixture-scan", b"x" * (MAX_SCAN_BYTES + 1))
    assert status == 413 and ApiError.from_dict(body).code == "too_large"


def test_an_unknown_engine_is_a_bad_request(call, running):
    use_photo(running)

    status, _, body = call("POST", "/api/fixture-scan?engine=magic", b"photo")

    assert status == 400 and ApiError.from_dict(body).code == "bad_request"


def test_the_cloud_engine_without_a_key_says_where_to_enter_it(call, running):
    use_photo(running)

    status, _, body = call("POST", "/api/fixture-scan?engine=cloud", b"photo")

    error = ApiError.from_dict(body)
    assert status == 409 and error.code == "scan_unavailable" and "ключ" in error.message


def test_the_cloud_engine_answers_with_its_own_draft(call, running):
    from gmagc_common.scan_draft import DraftChannel, DraftMode
    from gmagc_desktop.scan.cloud import CloudScanner

    class Cloud(CloudScanner):
        def scan(self, data):
            return ScanDraft((DraftMode("9CH", (DraftChannel(1, "Dimmer", "dimmer"),)),), (), "cloud")

    running.server._context.cloud = Cloud(lambda: "key")

    status, _, body = call("POST", "/api/fixture-scan?engine=cloud", b"photo")

    draft = ScanDraft.from_dict(body)
    assert status == 200 and draft.engine == "cloud" and draft.modes[0].name == "9CH"


def test_missing_recognition_libraries_are_a_conflict(call, running):
    def unavailable(_image):
        raise ScanUnavailableError("нет модуля")

    running.server._context.scanner = LocalScanner(ocr=unavailable)

    status, _, body = call("POST", "/api/fixture-scan", b"photo")

    assert status == 409 and ApiError.from_dict(body).code == "scan_unavailable"
