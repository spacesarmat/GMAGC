import pytest

from gmagc_common import protocol
from gmagc_common.protocol import (
    ApiError,
    Connection,
    Health,
    MatchResponse,
    ProtocolError,
    ResultItem,
    Status,
    build_link,
    format_code,
    is_valid_code,
    normalize_code,
    parse_address,
    parse_link,
)


def test_code_helpers_ignore_case_spaces_and_dashes():
    assert normalize_code(" abcd-2345 ") == "ABCD2345"
    assert format_code("abcd2345") == "ABCD-2345"
    assert is_valid_code("ABCD-2345") and is_valid_code("abcd2345")


@pytest.mark.parametrize("bad", ["", "ABCD234", "ABCD23456", "ABCD-234O", "ABCD-2341", "ABCD-23L5", "ЖЖЖЖ2345"])
def test_invalid_codes_are_rejected(bad):
    assert not is_valid_code(bad)


def test_the_alphabet_has_no_lookalikes_and_matches_the_code_length():
    assert not set("0O1IL") & set(protocol.CODE_ALPHABET)
    assert len(set(protocol.CODE_ALPHABET)) == len(protocol.CODE_ALPHABET) == 31
    assert protocol.CODE_LENGTH == 8


def test_link_round_trip():
    link = build_link("192.168.1.5", 8765, "abcd-2345")
    assert link == "gmagc://connect?host=192.168.1.5&port=8765&code=ABCD2345"
    assert parse_link(link) == Connection("192.168.1.5", 8765, "ABCD2345")
    assert parse_link("  " + link + "\n") == Connection("192.168.1.5", 8765, "ABCD2345")


@pytest.mark.parametrize(
    "bad",
    [
        "http://connect?host=1.2.3.4&port=8765&code=ABCD2345",
        "gmagc://other?host=1.2.3.4&port=8765&code=ABCD2345",
        "gmagc://connect?port=8765&code=ABCD2345",
        "gmagc://connect?host=1.2.3.4&port=0&code=ABCD2345",
        "gmagc://connect?host=1.2.3.4&port=70000&code=ABCD2345",
        "gmagc://connect?host=1.2.3.4&port=abc&code=ABCD2345",
        "gmagc://connect?host=1.2.3.4&port=8765&code=BAD",
        "gmagc://connect?host=a/b&port=8765&code=ABCD2345",
        "",
        "мусор",
    ],
)
def test_bad_links_give_none(bad):
    assert parse_link(bad) is None


def test_parse_link_tolerates_non_strings():
    assert parse_link(None) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("192.168.1.5", ("192.168.1.5", 8765)),
        ("192.168.1.5:9000", ("192.168.1.5", 9000)),
        (" http://pc-name.local:8766/ ", ("pc-name.local", 8766)),
        ("192.168.1.5:", None),
        ("192.168.1.5:99999", None),
        ("a:b:c", None),
        ("", None),
        ("bad host", None),
    ],
)
def test_parse_address(text, expected):
    assert parse_address(text) == expected


def sample_response():
    item = ResultItem(1, "a.png", "C:\\lib\\a.png", 0.875, ("C:\\lib2\\a.png",), b"\x89PNGthumb")
    return MatchResponse("abc123", "found", 12.5, (item,), b"\x89PNGproj")


def test_match_response_round_trip_keeps_bytes_and_tuples():
    response = sample_response()
    restored = MatchResponse.from_dict(response.to_dict())
    assert restored == response
    assert isinstance(restored.results[0].copies, tuple)
    assert MatchResponse.from_dict(MatchResponse("x", "no_projection", 1.0, (), None).to_dict()).projection_png is None


def test_health_status_and_error_round_trip():
    health = Health("GMAGC", 1, "0.4.0", True, 11178)
    status = Status(True, 11178, 9396, False, 0, 0)
    error = ApiError("unauthorized", "неверный код доступа")
    assert Health.from_dict(health.to_dict()) == health
    assert Status.from_dict(status.to_dict()) == status
    assert ApiError.from_dict(error.to_dict()) == error


@pytest.mark.parametrize(
    "broken",
    [
        {},
        {"request_id": "x"},
        {"request_id": "x", "outcome": "found", "took_ms": "не число", "results": []},
        {"request_id": "x", "outcome": "found", "took_ms": 1, "results": [{"rank": 1}]},
        {"request_id": "x", "outcome": "found", "took_ms": 1, "results": [], "projection_png": "!!not base64!!"},
        None,
    ],
)
def test_broken_responses_raise_protocol_error(broken):
    with pytest.raises(ProtocolError):
        MatchResponse.from_dict(broken)


def test_every_error_code_has_an_http_status():
    codes = {
        "unauthorized",
        "bad_request",
        "bad_image",
        "not_found",
        "too_large",
        "rate_limited",
        "no_index",
        "bad_profile",
        "no_target",
    }
    codes.add("server_error")
    assert set(protocol.ERROR_STATUS) == codes
    assert protocol.ERROR_STATUS["unauthorized"] == 401 and protocol.ERROR_STATUS["rate_limited"] == 429
    assert protocol.ERROR_STATUS["too_large"] == 413 and protocol.ERROR_STATUS["no_index"] == 409


def test_the_fixture_upload_result_round_trips_and_lists_targets_and_skips():
    result = protocol.FixtureUploadResult(
        written=(("ma3", "C:/lib/a.xml"), ("ma2", "C:/lib/b.xml")), skipped=("grandMA2: папка не найдена",)
    )

    assert protocol.FixtureUploadResult.from_dict(result.to_dict()) == result
    assert result.to_dict()["written"][0] == {"target": "ma3", "path": "C:/lib/a.xml"}


@pytest.mark.parametrize("data", [{}, {"written": "x", "skipped": []}, {"written": [{"target": "ma3"}], "skipped": []}])
def test_a_malformed_fixture_upload_result_is_a_protocol_error(data):
    with pytest.raises(protocol.ProtocolError):
        protocol.FixtureUploadResult.from_dict(data)


def test_the_profile_size_limit_is_smaller_than_the_image_limit():
    assert 0 < protocol.MAX_PROFILE_BYTES <= protocol.MAX_IMAGE_BYTES
