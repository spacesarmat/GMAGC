from gmagc_common.protocol import build_link
from gmagc_desktop.server.qr import qr_png


def test_qr_is_a_png_and_grows_with_the_scale():
    link = build_link("192.168.1.5", 8765, "ABCD2345")

    small, large = qr_png(link, scale=3), qr_png(link, scale=8)

    assert small.startswith(b"\x89PNG\r\n\x1a\n") and large.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(large) > len(small)


def test_different_links_give_different_images():
    assert qr_png(build_link("192.168.1.5", 8765, "ABCD2345")) != qr_png(build_link("192.168.1.5", 8765, "ABCD2346"))
