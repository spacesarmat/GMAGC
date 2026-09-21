from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "packages" / "common" / "gmagc_common"
TARGETS = [
    ROOT / "apps" / "desktop" / "src" / "gmagc_common",
    ROOT / "apps" / "mobile" / "src" / "gmagc_common",
]


def test_app_copies_match_the_canonical_package():
    names = sorted(path.name for path in SOURCE.glob("*.py"))
    assert "protocol.py" in names
    for target in TARGETS:
        assert sorted(path.name for path in target.glob("*.py")) == names, f"{target}: набор файлов отличается"
        for name in names:
            assert (target / name).read_bytes() == (SOURCE / name).read_bytes(), (
                f"{target / name} расходится с оригиналом: запустите python scripts/sync_common.py"
            )
