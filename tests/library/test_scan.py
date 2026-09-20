from gmagc_desktop.library.scan import LibraryFile, scan_library
from tests.fixtures import write_library


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
