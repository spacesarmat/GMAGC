import http.client
import json
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np

from gmagc_common.protocol import MAX_IMAGE_BYTES, ApiError, Health, MatchResponse, Status
from gmagc_desktop.server.api import RequestRecord
from gmagc_desktop.server.runner import PhoneServer
from gmagc_desktop.service.results import Outcome
from gmagc_desktop.service.search_service import SearchService


def test_health_needs_no_code_and_reports_the_index(call):
    status, _, body = call("GET", "/api/health", code=None)

    health = Health.from_dict(body)
    assert status == 200 and health.app == "GMAGC" and health.api == 1
    assert health.indexed is True and health.files == 6


def test_status_requires_the_code_and_reports_progress_fields(call):
    status, _, body = call("GET", "/api/status", code=None)
    assert status == 401 and ApiError.from_dict(body).code == "unauthorized"

    status, _, body = call("GET", "/api/status")
    result = Status.from_dict(body)
    assert status == 200 and result.indexed and result.files == 6 and result.families == 5
    assert result.indexing is False


def test_match_returns_results_with_thumbnails_and_the_projection(call, photo_jpeg, service):
    status, _, body = call("POST", "/api/match", photo_jpeg, headers={"Content-Type": "image/jpeg"})

    response = MatchResponse.from_dict(body)
    assert status == 200 and response.outcome in {"found", "low_confidence"}
    assert len(response.results) == 5 and [item.rank for item in response.results] == [1, 2, 3, 4, 5]
    top = response.results[0]
    assert top.name in {"ell.png", "ell_small.png"} and top.path.startswith(service.settings.library_dir)
    assert top.thumbnail_png.startswith(b"\x89PNG") and response.projection_png.startswith(b"\x89PNG")
    assert 0 < top.score <= 1 and len(response.request_id) == 8


def test_match_honors_the_top_parameter_and_clamps_it(call, photo_jpeg):
    _, _, body = call("POST", "/api/match?top=2", photo_jpeg)
    assert len(MatchResponse.from_dict(body).results) == 2
    _, _, body = call("POST", "/api/match?top=999", photo_jpeg)
    assert len(MatchResponse.from_dict(body).results) == 5  # в библиотеке всего 5 семейств
    _, _, body = call("POST", "/api/match?top=abc", photo_jpeg)
    assert len(MatchResponse.from_dict(body).results) == 5


def test_a_flat_photo_reports_no_projection(call):
    ok, buffer = cv2.imencode(".png", np.full((480, 640, 3), 90, np.uint8))
    status, _, body = call("POST", "/api/match", buffer.tobytes())

    response = MatchResponse.from_dict(body)
    assert status == 200 and response.outcome == "no_projection" and response.results == ()
    assert response.projection_png is None


def test_wrong_or_missing_code_is_401_even_with_a_big_body(call, photo_jpeg):
    for code in ("ABCD2346", "", None):
        status, _, body = call("POST", "/api/match", photo_jpeg * 5, code=code)
        assert status == 401 and ApiError.from_dict(body).code == "unauthorized"


def test_five_wrong_codes_block_the_client_for_a_while(call):
    for _ in range(5):
        assert call("GET", "/api/status", code="ABCD2346")[0] == 401

    status, response, body = call("GET", "/api/status", code="ABCD2346")
    assert status == 429 and ApiError.from_dict(body).code == "rate_limited"
    assert 1 <= int(response.getheader("Retry-After")) <= 30
    assert call("GET", "/api/status")[0] == 429  # верный код тоже ждёт конца блокировки


def test_bad_bodies_are_reported_with_json_errors(call, running):
    status, _, body = call("POST", "/api/match", b"not an image")
    assert status == 400 and ApiError.from_dict(body).code == "bad_image"

    status, _, body = call("POST", "/api/match", b"")
    assert status == 400 and ApiError.from_dict(body).code == "bad_image"

    connection = http.client.HTTPConnection("127.0.0.1", running.port, timeout=20)
    connection.putrequest("POST", "/api/match")
    connection.putheader("Authorization", f"Bearer {running.code}")
    connection.endheaders()  # без Content-Length
    response = connection.getresponse()
    assert response.status == 400 and ApiError.from_dict(json.loads(response.read())).code == "bad_request"
    connection.close()


def test_a_body_over_the_limit_is_413(call):
    status, _, body = call("POST", "/api/match", b"\0" * (MAX_IMAGE_BYTES + 1))

    assert status == 413 and ApiError.from_dict(body).code == "too_large"


def test_unknown_paths_and_methods_answer_json(call):
    status, _, body = call("GET", "/nope")
    assert status == 404 and ApiError.from_dict(body).code == "not_found"

    status, _, body = call("POST", "/api/health", b"x")
    assert status == 404 and body["error"] == "not_found"

    status, response, body = call("PUT", "/api/match", b"x")
    assert status == 501 and body["error"] == "bad_request"
    assert response.getheader("Content-Type").startswith("application/json")


def test_no_index_is_409(tmp_path, photo_jpeg):
    empty = SearchService(tmp_path / "empty")
    empty.load()
    code = empty.ensure_access_code()
    server = PhoneServer(empty, host="127.0.0.1")
    port = server.start(0)
    try:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
        connection.request("POST", "/api/match", body=photo_jpeg, headers={"Authorization": f"Bearer {code}"})
        response = connection.getresponse()
        assert response.status == 409 and ApiError.from_dict(json.loads(response.read())).code == "no_index"
        connection.close()
    finally:
        server.stop()


def test_the_request_callback_gets_the_photo_client_and_outcome(call, running, photo_jpeg):
    status, _, body = call("POST", "/api/match", photo_jpeg)

    assert status == 200 and len(running.records) == 1
    record = running.records[0]
    assert isinstance(record, RequestRecord) and record.request_id == body["request_id"]
    assert record.client == "127.0.0.1" and record.photo == photo_jpeg
    assert record.outcome.kind in {Outcome.FOUND, Outcome.LOW_CONFIDENCE} and record.time > 0


def test_a_failing_callback_does_not_break_the_response(service, photo_jpeg):
    def boom(_record):
        raise RuntimeError("UI упал")

    server = PhoneServer(service, on_request=boom, host="127.0.0.1")
    port = server.start(0)
    try:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
        connection.request(
            "POST", "/api/match", body=photo_jpeg, headers={"Authorization": f"Bearer {service.settings.access_code}"}
        )
        assert connection.getresponse().status == 200
        connection.close()
    finally:
        server.stop()


def test_parallel_requests_all_succeed(call, photo_jpeg):
    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses = list(pool.map(lambda _: call("POST", "/api/match", photo_jpeg)[0], range(6)))

    assert statuses == [200] * 6


def test_the_code_is_read_live_so_a_new_code_takes_effect_at_once(call, service):
    assert call("GET", "/api/status")[0] == 200
    new_code = service.reset_access_code()

    assert call("GET", "/api/status", code=new_code)[0] == 200
    assert call("GET", "/api/status", code="ABCD2346")[0] == 401
