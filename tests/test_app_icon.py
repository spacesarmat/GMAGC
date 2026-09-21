import tomllib
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ICONS = [ROOT / "apps" / "desktop" / "src" / "assets" / "icon.png", ROOT / "apps" / "mobile" / "src" / "assets" / "icon.png"]


def test_both_apps_ship_the_same_square_transparent_icon():
    assert ICONS[0].read_bytes() == ICONS[1].read_bytes()
    with Image.open(ICONS[0]) as icon:
        assert icon.size == (1024, 1024) and icon.mode == "RGBA"
        corners = [icon.getpixel(point)[3] for point in ((0, 0), (1023, 0), (0, 1023), (1023, 1023))]
        assert corners == [0, 0, 0, 0]
        assert icon.getpixel((512, 512))[3] >= 250  # рисунок почти непрозрачный (альфа 253-254)


def test_the_original_artwork_is_kept_next_to_the_docs():
    assert (ROOT / "docs" / "branding" / "icon.png").is_file()


def test_the_icon_background_matches_the_artwork_in_both_builds():
    for app in ("desktop", "mobile"):
        config = tomllib.loads((ROOT / "apps" / app / "pyproject.toml").read_text(encoding="utf-8"))
        assert config["tool"]["flet"]["icon_background"] == "#040c1f"
