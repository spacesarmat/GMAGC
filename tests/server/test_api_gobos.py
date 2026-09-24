from pathlib import Path

from gmagc_common.fixtures import GOBO_THUMB_BYTES, Gobo, gobo_media_path, gobo_rgba
from gmagc_common.protocol import ApiError, GoboItem, GoboList


def library_files(service):
    return sorted(f.rel_path for f in service._index.files)


def test_searching_by_name_lists_matching_gobos_with_previews_and_slot_thumbnails(call, service):
    name = Path(library_files(service)[0]).stem

    status, _, body = call("GET", f"/api/gobos?q={name}&limit=5")

    result = GoboList.from_dict(body)
    assert status == 200 and 1 <= len(result.items) <= 5 and result.total >= 1
    item = result.items[0]
    assert name.lower() in item.source.lower() and item.name == Path(item.source).stem
    assert item.png.startswith(b"\x89PNG") and item.path == gobo_media_path(item.source)
    assert len(gobo_rgba(Gobo(item.name, item.path, item.thumb))) == GOBO_THUMB_BYTES


def test_all_words_of_the_query_must_match_and_an_empty_query_finds_nothing(call, service):
    status, _, body = call("GET", "/api/gobos?q=zzz_no_such_gobo")
    assert status == 200 and GoboList.from_dict(body).items == () and body["total"] == 0

    status, _, body = call("GET", "/api/gobos?q=")
    assert status == 200 and GoboList.from_dict(body).total == 0


def test_the_limit_is_clamped_and_reported_total_counts_everything(call, service):
    status, _, body = call("GET", "/api/gobos?q=.&limit=2")

    result = GoboList.from_dict(body)
    assert status == 200 and len(result.items) == 2 and result.total == len(library_files(service))


def test_one_gobo_is_found_by_relative_or_full_path(call, service):
    rel = library_files(service)[0]
    full = str(Path(service.settings.library_dir) / rel)

    for path in (rel, full):
        status, _, body = call("GET", "/api/gobo?path=" + path.replace("\\", "/").replace(" ", "%20"))
        assert status == 200 and GoboItem.from_dict(body).source == rel


def test_a_path_outside_the_library_or_unknown_is_not_found(call, service, tmp_path):
    for path in ("nope.png", "../secret.png", str(tmp_path / "other.png"), ""):
        status, _, body = call("GET", "/api/gobo?path=" + path.replace("\\", "/"))
        assert status == 404 and ApiError.from_dict(body).code == "not_found", path


def test_gobo_methods_require_the_access_code(call, service):
    for url in ("/api/gobos?q=a", "/api/gobo?path=a.png"):
        status, _, body = call("GET", url, code="ABCD2346")
        assert status == 401 and ApiError.from_dict(body).code == "unauthorized"


def test_gobo_media_paths_differ_for_the_same_name_in_different_folders():
    a, b = gobo_media_path("Stars/star.png"), gobo_media_path("Other/star.png")

    assert a != b and a.startswith("GMAGC/star_") and a.endswith(".png") and " " not in a
