import pytest

from gmagc_common import i18n


@pytest.fixture(autouse=True)
def restore_language():
    yield
    i18n.set_language("ru")
    i18n.reset_catalogs()


def test_the_default_language_is_russian_and_text_is_returned_as_is():
    assert i18n.current_language() == "ru"
    assert i18n.t("Настройки") == "Настройки"


def test_an_english_catalog_translates_only_after_the_language_is_switched():
    i18n.register("en", {"Настройки": "Settings"})

    assert i18n.t("Настройки") == "Настройки"
    i18n.set_language("en")
    assert i18n.t("Настройки") == "Settings"


def test_an_untranslated_text_falls_back_to_the_russian_source():
    i18n.set_language("en")

    assert i18n.t("Нет такого перевода") == "Нет такого перевода"


def test_parameters_are_substituted_after_the_translation():
    i18n.register("en", {"Найдено файлов: {count}": "Files found: {count}"})

    assert i18n.t("Найдено файлов: {count}", count=3) == "Найдено файлов: 3"
    i18n.set_language("en")
    assert i18n.t("Найдено файлов: {count}", count=3) == "Files found: 3"


def test_a_broken_template_does_not_raise():
    assert i18n.t("Файл {name}", other=1) == "Файл {name}"


def test_registering_twice_merges_catalogs():
    i18n.register("en", {"а": "a"})
    i18n.register("en", {"б": "b"})
    i18n.set_language("en")

    assert (i18n.t("а"), i18n.t("б")) == ("a", "b")


@pytest.mark.parametrize(
    ("locale_name", "expected"),
    [
        ("ru_RU", "ru"),
        ("ru-RU", "ru"),
        ("Russian_Russia", "ru"),
        ("RU", "ru"),
        ("en_US", "en"),
        ("en-GB", "en"),
        ("English_United States", "en"),
        ("de_DE", "en"),
        ("C", "en"),
        ("", "ru"),
        (None, "ru"),
    ],
)
def test_the_system_language_is_russian_for_russian_locales_english_for_others_and_russian_when_unknown(
    locale_name, expected
):
    assert i18n.detect_system_language(locale_name) == expected


def test_auto_follows_the_given_system_locale():
    assert i18n.set_language("auto", system_locale="en_US") == "en"
    assert i18n.current_language() == "en"
    assert i18n.set_language("auto", system_locale="ru_RU") == "ru"


def test_an_unknown_choice_is_treated_as_auto():
    assert i18n.normalize_choice("klingon") == "auto"
    assert i18n.normalize_choice("EN") == "en"
    assert i18n.normalize_choice(None) == "auto"
    assert i18n.set_language("klingon", system_locale="en_US") == "en"


def test_plural_picks_the_russian_form_by_the_number_and_the_english_one_by_the_language():
    forms = {"ru": ("файл", "файла", "файлов"), "en": ("file", "files")}

    assert [i18n.plural(n, **forms) for n in (1, 2, 5, 11, 21, 22, 25, 111, 0)] == [
        "файл",
        "файла",
        "файлов",
        "файлов",
        "файл",
        "файла",
        "файлов",
        "файлов",
        "файлов",
    ]
    i18n.set_language("en")
    assert [i18n.plural(n, **forms) for n in (0, 1, 2, 21)] == ["files", "file", "files", "files"]


def test_language_names_are_shown_in_their_own_language():
    assert i18n.language_name("ru") == "Русский" and i18n.language_name("en") == "English"
    assert i18n.language_name("auto").startswith("Авто") or i18n.language_name("auto").startswith("Auto")
