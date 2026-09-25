"""Полнота переводов: каждый t("…") в коде приложения имеет английский вариант с теми же подстановками."""

import ast
import re
from pathlib import Path

import pytest

from gmagc_common.fixtures import TEMPLATES
from gmagc_common.lang_en import EN as COMMON_EN
from gmagc_desktop.lang_en import EN as DESKTOP_EN
from gmagc_phone.lang_en import EN as PHONE_EN

ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDER = re.compile(r"\{(\w+)(?::[^}]*)?\}")


def used_keys(pattern: str) -> set[str]:
    keys = template_texts() if pattern.startswith("packages/common") else set()
    for path in sorted(ROOT.glob(pattern)):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            is_t = isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "t"
            if is_t and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                keys.add(node.args[0].value)
    return keys


CATALOGS = [
    ("телефон", "apps/mobile/src/gmagc_phone/**/*.py", PHONE_EN),
    ("ПК", "apps/desktop/src/gmagc_desktop/**/*.py", DESKTOP_EN),
    ("общее", "packages/common/gmagc_common/*.py", COMMON_EN),
]


def template_texts() -> set[str]:
    """Названия шаблонов каналов и их диапазонов: задаются данными, а не вызовами t(\"…\")."""
    texts = set()
    for template in TEMPLATES:
        texts.add(template.title)
        texts.update(item.name for item in template.ranges)
    return {text for text in texts if re.search("[А-Яа-яЁё]", text)}


@pytest.mark.parametrize(("name", "pattern", "catalog"), CATALOGS, ids=[c[0] for c in CATALOGS])
def test_every_translated_text_has_an_english_translation(name, pattern, catalog):
    missing = sorted(key for key in used_keys(pattern) if key not in catalog)

    assert not missing, f"нет английского перевода ({name}): {missing}"


@pytest.mark.parametrize(("name", "pattern", "catalog"), CATALOGS, ids=[c[0] for c in CATALOGS])
def test_the_catalog_has_no_leftover_entries(name, pattern, catalog):
    leftover = sorted(key for key in catalog if key not in used_keys(pattern))

    assert not leftover, f"перевод без места использования ({name}): {leftover}"


@pytest.mark.parametrize(("name", "pattern", "catalog"), CATALOGS, ids=[c[0] for c in CATALOGS])
def test_a_translation_keeps_the_same_placeholders_as_the_source(name, pattern, catalog):
    broken = [
        key for key, value in catalog.items() if set(PLACEHOLDER.findall(key)) != set(PLACEHOLDER.findall(value))
    ]

    assert not broken, f"подстановки не совпадают ({name}): {broken}"
