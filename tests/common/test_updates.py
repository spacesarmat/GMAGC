import json
import socket

import pytest

from gmagc_common import updates
from gmagc_common.updates import (
    Asset,
    ReleaseInfo,
    UpdateCheckError,
    check_due,
    fetch_latest,
    is_allowed_url,
    is_newer,
    open_url,
    parse_sha256,
    parse_version,
    pick_assets,
    update_source,
)
from tests.updates_stub import release_json, stub_server

SHA = "a" * 64


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("v0.5.1", (0, 5, 1)),
        ("0.10.0", (0, 10, 0)),
        (" v1.2.3 ", (1, 2, 3)),
        ("1.2", None),
        ("1.2.3.4", None),
        ("v1.2.3-rc1", None),
        ("latest", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_version(text, expected):
    assert parse_version(text) == expected


def test_versions_compare_numerically_not_as_text():
    assert is_newer("0.10.0", "0.9.9") and is_newer("v1.0.0", "0.99.99")
    assert not is_newer("0.5.1", "0.5.1") and not is_newer("0.5.0", "0.5.1")
    assert not is_newer("garbage", "0.5.1") and not is_newer("0.6.0", "garbage")


def test_a_release_is_read_from_the_api_reply():
    release = ReleaseInfo.from_api(release_json("0.6.0", "https://example.invalid"))

    assert release.version == "0.6.0" and release.tag == "v0.6.0"
    assert release.notes == "Что нового в 0.6.0" and release.page_url.endswith("/releases/tag/v0.6.0")
    assert len(release.assets) == 6 and release.assets[0] == Asset(
        "GMAGC-desktop-windows-0.6.0.zip", "https://example.invalid/GMAGC-desktop-windows-0.6.0.zip", 1000
    )


@pytest.mark.parametrize(
    "broken",
    [
        {**release_json("0.6.0", "x"), "draft": True},
        {**release_json("0.6.0", "x"), "prerelease": True},
        {**release_json("0.6.0", "x"), "tag_name": "nightly"},
        {"assets": []},
        [],
        None,
    ],
)
def test_drafts_prereleases_and_foreign_replies_are_not_releases(broken):
    assert ReleaseInfo.from_api(broken) is None


def test_broken_assets_are_skipped_and_a_missing_body_is_empty():
    data = release_json("0.6.0", "https://example.invalid")
    data["assets"] = [{"name": "no-url"}, "junk", {"name": "ok.zip", "browser_download_url": "https://x/ok.zip"}]
    data["body"] = None

    release = ReleaseInfo.from_api(data)

    assert [a.name for a in release.assets] == ["ok.zip"] and release.assets[0].size == 0 and release.notes == ""


@pytest.mark.parametrize(
    ("platform", "name"),
    [
        ("windows", "GMAGC-desktop-windows-0.6.0.zip"),
        ("macos", "GMAGC-desktop-macos-0.6.0.zip"),
        ("android", "GMAGC-android-0.6.0.apk"),
    ],
)
def test_the_file_and_its_checksum_are_picked_by_platform(platform, name):
    release = ReleaseInfo.from_api(release_json("0.6.0", "https://example.invalid"))

    asset, checksum = pick_assets(release, platform)

    assert asset.name == name and checksum.name == name + ".sha256"


def test_a_missing_file_checksum_or_platform_is_reported_as_none():
    release = ReleaseInfo.from_api(release_json("0.6.0", "https://example.invalid", platforms=("windows",)))
    assert pick_assets(release, "macos") is None and pick_assets(release, "linux") is None

    release = ReleaseInfo.from_api(release_json("0.6.0", "https://example.invalid"))
    kept = tuple(a for a in release.assets if not a.name.endswith(".sha256"))
    without_sum = ReleaseInfo(release.version, release.tag, release.notes, release.page_url, kept)
    asset, checksum = pick_assets(without_sum, "android")
    assert asset.name.endswith(".apk") and checksum is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (f"{SHA}  GMAGC-android-0.6.0.apk\n", SHA),
        (f"{SHA.upper()} *file.zip", SHA),
        (f"\n  {SHA}\n", SHA),
        ("not a hash  file.zip", None),
        ("abc123  file.zip", None),
        ("", None),
    ],
)
def test_parse_sha256(text, expected):
    assert parse_sha256(text) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://api.github.com/repos/spacesarmat/GMAGC/releases/latest",
        "https://github.com/spacesarmat/GMAGC/releases/download/v0.6.0/GMAGC-android-0.6.0.apk",
        "https://objects.githubusercontent.com/github-production-release-asset/abc",
        "https://release-assets.githubusercontent.com/x",
    ],
)
def test_github_addresses_are_allowed(url):
    assert is_allowed_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/x",
        "https://evil.example/x",
        "https://github.com.evil.example/x",
        "https://evilgithub.com/x",
        "https://githubusercontent.com.evil.example/x",
        "https://notgithubusercontent.com/x",
        "ftp://github.com/x",
        "file:///C:/x",
        "http://127.0.0.1:8000/x",
        "",
        "not a url",
    ],
)
def test_other_addresses_are_refused(url):
    assert not is_allowed_url(url)


def test_a_local_address_is_allowed_only_on_request_and_only_over_loopback():
    assert is_allowed_url("http://127.0.0.1:8000/x", allow_local=True)
    assert is_allowed_url("http://localhost:8000/x", allow_local=True)
    assert not is_allowed_url("http://192.168.1.5:8000/x", allow_local=True)
    assert not is_allowed_url("http://example.com/x", allow_local=True)


def test_the_update_source_is_github_unless_a_loopback_override_is_set(monkeypatch):
    monkeypatch.delenv(updates.UPDATE_URL_ENV, raising=False)
    assert update_source() == (updates.RELEASES_API, False)

    monkeypatch.setenv(updates.UPDATE_URL_ENV, "http://127.0.0.1:9999/latest")
    assert update_source() == ("http://127.0.0.1:9999/latest", True)

    monkeypatch.setenv(updates.UPDATE_URL_ENV, "https://evil.example/latest")
    assert update_source() == (updates.RELEASES_API, False)
    monkeypatch.setenv(updates.UPDATE_URL_ENV, "http://192.168.1.5/latest")
    assert update_source() == (updates.RELEASES_API, False)


def test_the_check_is_due_once_a_day_and_when_the_clock_went_back():
    day = updates.CHECK_INTERVAL_SECONDS
    assert check_due(0, 1_000_000) and check_due(1_000_000 - day, 1_000_000)
    assert not check_due(1_000_000 - day + 1, 1_000_000)
    assert check_due(2_000_000, 1_000_000)


def test_a_newer_release_is_returned_and_an_equal_or_older_one_is_not():
    routes = {}
    with stub_server(routes) as base:
        routes["/latest"] = {"body": json.dumps(release_json("0.6.0", base)).encode()}
        newer = fetch_latest("0.5.1", url=f"{base}/latest", allow_local=True)
        same = fetch_latest("0.6.0", url=f"{base}/latest", allow_local=True)
        older = fetch_latest("0.7.0", url=f"{base}/latest", allow_local=True)

    assert newer.version == "0.6.0" and same is None and older is None


@pytest.mark.parametrize(
    ("status", "fragment"),
    [(404, "не найдены"), (403, "ограничил"), (429, "ограничил"), (500, "ошибкой 500")],
)
def test_http_errors_are_reported_in_words(status, fragment):
    with stub_server({"/latest": {"status": status, "body": b"{}"}}) as base:
        with pytest.raises(UpdateCheckError) as error:
            fetch_latest("0.5.1", url=f"{base}/latest", allow_local=True)

    assert fragment in str(error.value)


def test_replies_that_are_not_a_release_are_errors():
    cases = [b"<html>captive portal</html>", b'{"hello": "world"}', b"[1, 2]", b'{"tag_name": "v1.0.0", "draft": true}']
    for body in cases:
        with stub_server({"/latest": {"body": body}}) as base:
            with pytest.raises(UpdateCheckError):
                fetch_latest("0.5.1", url=f"{base}/latest", allow_local=True)


def test_an_oversized_reply_is_refused(monkeypatch):
    monkeypatch.setattr(updates, "MAX_RESPONSE_BYTES", 100)
    with stub_server({"/latest": {"body": b"x" * 500}}) as base:
        with pytest.raises(UpdateCheckError) as error:
            fetch_latest("0.5.1", url=f"{base}/latest", allow_local=True)

    assert "большой" in str(error.value)


def test_no_connection_and_a_slow_server_are_reported_as_no_connection():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]
    with pytest.raises(UpdateCheckError) as error:
        fetch_latest("0.5.1", url=f"http://127.0.0.1:{closed_port}/latest", allow_local=True)
    assert "Нет связи" in str(error.value)

    with stub_server({"/latest": {"body": b"{}", "delay": 1.5}}) as base:
        with pytest.raises(UpdateCheckError) as error:
            fetch_latest("0.5.1", timeout=0.3, url=f"{base}/latest", allow_local=True)
    assert "Нет связи" in str(error.value)


def test_a_redirect_to_a_foreign_host_is_refused():
    routes = {"/latest": {"status": 302, "headers": {"Location": "https://evil.example/latest"}}}
    with stub_server(routes) as base:
        with pytest.raises(UpdateCheckError) as error:
            fetch_latest("0.5.1", url=f"{base}/latest", allow_local=True)

    assert "недопустим" in str(error.value)


def test_a_redirect_within_the_allowed_scope_is_followed():
    routes = {}
    with stub_server(routes) as base:
        routes["/old"] = {"status": 302, "headers": {"Location": f"{base}/latest"}}
        routes["/latest"] = {"body": json.dumps(release_json("0.6.0", base)).encode()}

        release = fetch_latest("0.5.1", url=f"{base}/old", allow_local=True)

    assert release.version == "0.6.0"


def test_open_url_refuses_a_disallowed_address_before_connecting():
    with pytest.raises(UpdateCheckError):
        open_url("https://evil.example/x")
    with pytest.raises(UpdateCheckError):
        open_url("http://127.0.0.1:1/x")  # локальный адрес без allow_local
