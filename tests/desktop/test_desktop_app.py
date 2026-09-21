import flet as ft

from gmagc_desktop.about import AUTHOR, NAME, VERSION
from gmagc_desktop.app import build_page


class StubPage:
    """Минимальная замена ft.Page: запоминает, что на неё добавили."""

    def __init__(self):
        self.title = ""
        self.added = []
        self.updates = 0

    def add(self, *controls):
        self.added.extend(controls)

    def update(self):
        self.updates += 1


def texts(control):
    """Все строки Text внутри дерева контролов."""
    found = []
    for attribute in ("content", "controls"):
        value = getattr(control, attribute, None)
        for child in value if isinstance(value, list) else [value] if value is not None else []:
            found.extend(texts(child))
    if isinstance(control, ft.Text):
        found.append(control.value)
    return found


def find_button(control):
    if isinstance(control, ft.Button):
        return control
    for attribute in ("content", "controls"):
        value = getattr(control, attribute, None)
        for child in value if isinstance(value, list) else [value] if value is not None else []:
            button = find_button(child)
            if button is not None:
                return button
    return None


def test_page_shows_name_version_and_author():
    page = StubPage()

    build_page(page)

    assert page.title == f"{NAME} {VERSION}"
    shown = " ".join(texts(page.added[0]))
    assert NAME in shown and VERSION in shown and AUTHOR in shown


def test_button_runs_the_core_check_and_shows_the_result():
    page = StubPage()
    result = build_page(page, check=lambda: {"ok": True, "shape": (224, 224), "versions": {"numpy": "9.9"}})

    find_button(page.added[0]).on_click(None)

    assert "ОК" in result.value and "numpy: 9.9" in result.value
    assert page.updates == 1


def test_failed_check_is_reported_as_an_error():
    page = StubPage()
    result = build_page(page, check=lambda: {"ok": False, "shape": None, "versions": {}})

    find_button(page.added[0]).on_click(None)

    assert "ОШИБКА" in result.value
