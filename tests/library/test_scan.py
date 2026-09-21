from gmagc_desktop.library import scan as scan_module
from gmagc_desktop.library.scan import LibraryFile, scan_library
from tests.fixtures import make_file_vanish_during_walk, make_folder_unlistable, write_library


def test_scan_finds_only_supported_files_sorted_and_posix(tmp_path):
    write_library(tmp_path)
    (tmp_path / "vendor_a" / "question.bmp").write_bytes(b"x")  # не в корне: не игнорируется
    (tmp_path / "vendor_b" / "UPPER.PNG").write_bytes(b"x")

    files = scan_library(tmp_path)

    assert [f.rel_path for f in files] == [
        "blank.png",
        "vendor_a/dots.png",
        "vendor_a/question.bmp",
        "vendor_a/ring.png",
        "vendor_b/UPPER.PNG",
        "vendor_b/ell.png",
        "vendor_b/star.bmp",
        "vendor_c/ell_small.png",
        "vendor_c/gobo.png",
    ]
    assert all(isinstance(f, LibraryFile) and f.size > 0 and f.mtime_ns > 0 for f in files)


def test_library_file_is_hashable_and_compares_by_value():
    a = LibraryFile("a.png", 10, 5)
    assert a == LibraryFile("a.png", 10, 5) and a != LibraryFile("a.png", 11, 5)
    assert len({a, LibraryFile("a.png", 10, 5)}) == 1


def test_missing_root_gives_empty_list(tmp_path):
    assert scan_library(tmp_path / "nope") == []


def test_checked_scan_reports_an_unlistable_directory(tmp_path, monkeypatch):
    write_library(tmp_path)
    make_folder_unlistable(monkeypatch, "vendor_b")

    files, problems = scan_module.scan_library_checked(tmp_path)

    assert len(problems) == 1 and "cannot list directory" in problems[0] and "vendor_b" in problems[0]
    assert "vendor_b/ell.png" not in [f.rel_path for f in files]
    assert "vendor_a/ring.png" in [f.rel_path for f in files]


def test_checked_scan_reports_a_missing_root_as_a_problem(tmp_path):
    files, problems = scan_module.scan_library_checked(tmp_path / "nope")
    assert files == [] and len(problems) == 1 and "nope" in problems[0]


def test_checked_scan_has_no_problems_on_a_healthy_library(tmp_path):
    write_library(tmp_path)
    files, problems = scan_module.scan_library_checked(tmp_path)
    assert problems == [] and files == scan_library(tmp_path)


def test_file_vanishing_between_walk_and_stat_is_skipped_not_a_problem(tmp_path, monkeypatch):
    write_library(tmp_path)
    make_file_vanish_during_walk(monkeypatch, "vendor_a/ring.png")

    files, problems = scan_module.scan_library_checked(tmp_path)

    assert problems == []
    assert "vendor_a/ring.png" not in [f.rel_path for f in files]
    assert "vendor_a/dots.png" in [f.rel_path for f in files]
