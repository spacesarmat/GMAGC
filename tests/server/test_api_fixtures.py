import http.client
import json

from gmagc_common.fixtures import Channel, FixtureProfile, Mode, profile_to_dict
from gmagc_common.protocol import MAX_PROFILE_BYTES, ApiError, FixtureUploadResult
from gmagc_desktop.server.runner import PhoneServer
from gmagc_desktop.service.fixture_export import FixtureExporter
from gmagc_desktop.service.settings import Settings

JSON = {"Content-Type": "application/json"}


def ready_profile():
    modes = (
        Mode("Standard", (Channel(1, 8, "Диммер", "dimmer"),)),
        Mode("Extended", (Channel(1, 8, "Диммер", "dimmer"), Channel(2, 8, "Красный", "red"))),
    )
    return FixtureProfile("a" * 32, "SHEHDS", "380W Beam", "", modes)


def body_of(profile):
    return json.dumps(profile_to_dict(profile), ensure_ascii=False).encode("utf-8")


def use_folders(service, tmp_path):
    service.set_fixture_dirs(str(tmp_path / "ma3"), str(tmp_path / "ma2"))
    return tmp_path / "ma3", tmp_path / "ma2"


def test_a_profile_is_stored_for_both_consoles_and_the_reply_lists_the_files(call, service, tmp_path):
    ma3, ma2 = use_folders(service, tmp_path)

    status, _, body = call("POST", "/api/fixtures", body_of(ready_profile()), headers=JSON)

    result = FixtureUploadResult.from_dict(body)
    assert status == 200 and result.skipped == ()
    assert (ma3 / "shehds@380w_beam.xml").exists()
    assert sorted(p.name for p in ma2.glob("*.xml")) == ["shehds@380w_beam@extended.xml", "shehds@380w_beam@standard.xml"]
    assert sorted(target for target, _ in result.written) == ["ma2", "ma2", "ma3", "ma3"]
    assert (ma3 / "shehds@380w_beam.gdtf").exists()


def test_storing_a_profile_requires_the_access_code(call, service, tmp_path):
    use_folders(service, tmp_path)

    status, _, body = call("POST", "/api/fixtures", body_of(ready_profile()), code="ABCD2346", headers=JSON)

    assert status == 401 and ApiError.from_dict(body).code == "unauthorized"
    assert not (tmp_path / "ma3").exists()


def test_a_body_that_is_not_a_profile_is_a_bad_profile_error(call, service, tmp_path):
    use_folders(service, tmp_path)

    for body in (b"{not json", b"[1, 2]", b'{"modes": "x"}', b""):
        status, _, reply = call("POST", "/api/fixtures", body, headers=JSON)
        assert status == 400 and ApiError.from_dict(reply).code == "bad_profile", body


def test_a_profile_that_is_not_ready_is_refused_with_the_reason(call, service, tmp_path):
    use_folders(service, tmp_path)
    broken = FixtureProfile("a" * 32, "", "", "", (Mode("m"),))

    status, _, reply = call("POST", "/api/fixtures", body_of(broken), headers=JSON)

    error = ApiError.from_dict(reply)
    assert status == 400 and error.code == "bad_profile" and "производител" in error.message
    assert not (tmp_path / "ma3").exists()


def test_a_huge_body_is_refused_before_it_is_read(call, service, tmp_path):
    use_folders(service, tmp_path)

    status, _, reply = call("POST", "/api/fixtures", b"x" * (MAX_PROFILE_BYTES + 1), headers=JSON)

    assert status == 413 and ApiError.from_dict(reply).code == "too_large"


def test_a_missing_content_length_is_a_bad_request(running):
    connection = http.client.HTTPConnection("127.0.0.1", running.port, timeout=20)
    try:
        connection.putrequest("POST", "/api/fixtures")
        connection.putheader("Authorization", f"Bearer {running.code}")
        connection.endheaders()
        response = connection.getresponse()
        assert response.status == 400 and json.loads(response.read())["error"] == "bad_request"
    finally:
        connection.close()


def test_without_any_folder_the_reply_is_no_target(service, tmp_path):
    exporter = FixtureExporter(lambda: Settings(), {})  # нет ни настроенных, ни найденных папок
    server = PhoneServer(service, host="127.0.0.1", fixtures=exporter)
    port = server.start(0)
    try:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
        headers = {**JSON, "Authorization": f"Bearer {service.settings.access_code}"}
        connection.request("POST", "/api/fixtures", body=body_of(ready_profile()), headers=headers)
        response = connection.getresponse()
        reply = json.loads(response.read())
        connection.close()
    finally:
        server.stop()

    assert response.status == 409 and reply["error"] == "no_target" and "grandMA3" in reply["message"]


def test_one_console_folder_missing_still_stores_the_other_and_reports_the_skip(service, tmp_path):
    exporter = FixtureExporter(lambda: Settings(ma3_fixture_dir=str(tmp_path / "ma3")), {})
    server = PhoneServer(service, host="127.0.0.1", fixtures=exporter)
    port = server.start(0)
    try:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
        headers = {**JSON, "Authorization": f"Bearer {service.settings.access_code}"}
        connection.request("POST", "/api/fixtures", body=body_of(ready_profile()), headers=headers)
        response = connection.getresponse()
        reply = json.loads(response.read())
        connection.close()
    finally:
        server.stop()

    result = FixtureUploadResult.from_dict(reply)
    assert response.status == 200 and [t for t, _ in result.written] == ["ma3", "ma3"]
    assert result.skipped == ("no_folder:ma2",)
