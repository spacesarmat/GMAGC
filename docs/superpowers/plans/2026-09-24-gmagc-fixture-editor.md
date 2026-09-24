# Редактор профилей приборов на телефоне: план реализации

> **Для исполнителя:** идти по задачам по порядку, шаги отмечены `- [ ]`. Порядок внутри задачи: сначала падающий тест, потом код, потом зелёный прогон и коммит.

**Цель:** новое окно «Профили приборов» в мобильном приложении: создание с нуля, хранение и редактирование профилей прибора для grandMA2/MA3 (производитель, модель, режимы, каналы, диапазоны).

**Архитектура:** чистая модель профиля с проверкой и JSON лежит в `packages/common/gmagc_common/fixtures.py` (стандартная библиотека, копии в `apps/*/src/gmagc_common` делает `scripts/sync_common.py`). На телефоне: `ProfileStore` поверх SharedPreferences (как `ConnectionStore`) и `ProfileEditor` (`gmagc_mobile/profiles_ui.py`) — свой набор экранов внутри одного вида `profiles` приложения; `MobileApp` только открывает его и передаёт кнопку «Назад».

**Стек:** Python 3.12, Flet 1.0 (Android), pytest (заглушки из `tests/fakes.py`, `tests/fakes_mobile.py`), ruff (строка 125).

**Спецификация:** `docs/superpowers/specs/2026-09-24-gmagc-fixture-editor-design.md`

## Общие ограничения
- Все тексты интерфейса и комментарии по-русски, стиль как в соседнем коде (короткие комментарии «почему»).
- Модель неизменяемая (`frozen=True` + `dataclasses.replace`), правки создают новые объекты.
- Диапазоны и значение по умолчанию хранятся по грубому байту 0–255; перевод в форматы MA2/MA3 — задача экспорта (не здесь).
- Не использовать в нативном Flet-клиенте `Row(alignment=SPACE_BETWEEN)` с вложенными flex-детьми и пустой `Container(expand=True)` (не рендерятся, см. память проекта): вместо них `Text(expand=True)` + кнопка справа.
- Ветка `feat/fixture-editor` (спецификация уже в ней). Каждая задача — отдельный коммит; полный `python -m pytest -q` и `ruff check .` перед PR.
- Запуск на Windows: `.venv\Scripts\python.exe -m pytest ...`.

## Файлы
- Создать: `packages/common/gmagc_common/fixtures.py` (+ копии после sync), `apps/mobile/src/gmagc_mobile/profile_store.py`, `apps/mobile/src/gmagc_mobile/profiles_ui.py`.
- Изменить: `apps/mobile/src/gmagc_mobile/app.py` (вид `profiles`, кнопки входа, «Назад», `build_page`), `README.md`.
- Тесты: `tests/common/test_fixtures.py`, `tests/mobile/test_profile_store.py`, `tests/mobile/test_profiles_ui.py`, дополнение `tests/mobile/test_mobile_back_button.py`.

---

## Задача 1: модель, шаблоны и JSON

**Файлы:** создать `packages/common/gmagc_common/fixtures.py`; тест `tests/common/test_fixtures.py`.

**Интерфейсы (выпускает):**
`Range(start, end, name)`, `Channel(dmx, bits, name, template, default=0, ranges=())` со свойствами `width`, `last`; `Mode(name, channels=())`; `FixtureProfile(id, manufacturer, name, short_name="", modes=())`; `Template(id, title, bits, ranges)`; `TEMPLATES`, `template_by_id(id)`, `channel_from_template(template_id, dmx)`, `next_free_dmx(mode)`, `new_profile()`, `profile_to_dict(p)`, `profile_from_dict(data)`, `ProfileError`, `MAX_DMX = 512`.

- [ ] **Шаг 1: тест `tests/common/test_fixtures.py`**

```python
import pytest

from gmagc_common.fixtures import (
    MAX_DMX,
    TEMPLATES,
    Channel,
    FixtureProfile,
    Mode,
    ProfileError,
    Range,
    channel_from_template,
    new_profile,
    next_free_dmx,
    profile_from_dict,
    profile_to_dict,
    template_by_id,
)


def sample_profile():
    dimmer = Channel(1, 8, "Диммер", "dimmer", 0, (Range(0, 255, "0…100%"),))
    pan = Channel(2, 16, "Pan", "pan", 128, ())
    return FixtureProfile("abc", "SHEHDS", "380W Beam", "380WB", (Mode("19 channel", (dimmer, pan)),))


def test_a_new_profile_has_one_empty_mode_and_a_unique_id():
    first, second = new_profile(), new_profile()

    assert first.id != second.id and len(first.modes) == 1 and first.modes[0].channels == ()


def test_the_json_round_trip_keeps_every_field():
    profile = sample_profile()

    assert profile_from_dict(profile_to_dict(profile)) == profile


def test_a_channel_knows_its_width_and_last_address():
    assert Channel(2, 16, "Pan", "pan").width == 2 and Channel(2, 16, "Pan", "pan").last == 3
    assert Channel(5, 8, "Dim", "dimmer").last == 5


def test_every_template_is_usable_and_ids_are_unique():
    ids = [template.id for template in TEMPLATES]

    assert len(ids) == len(set(ids)) and {"dimmer", "pan", "tilt", "gobo_wheel", "custom"} <= set(ids)
    assert all(template.bits in (8, 16) for template in TEMPLATES)
    assert template_by_id("pan").bits == 16


def test_a_channel_from_a_template_gets_its_bits_name_and_ranges():
    channel = channel_from_template("shutter", 7)

    assert channel.dmx == 7 and channel.template == "shutter" and channel.bits == template_by_id("shutter").bits
    assert channel.name == template_by_id("shutter").title and channel.ranges == template_by_id("shutter").ranges


def test_an_unknown_template_is_rejected_when_asked_for_directly():
    with pytest.raises(ProfileError):
        template_by_id("nope")


def test_the_next_free_address_follows_the_last_used_one():
    mode = Mode("m", (Channel(1, 8, "a", "dimmer"), Channel(2, 16, "b", "pan")))

    assert next_free_dmx(Mode("empty")) == 1
    assert next_free_dmx(mode) == 4
    assert next_free_dmx(Mode("full", (Channel(MAX_DMX, 8, "z", "dimmer"),))) == MAX_DMX + 1


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.pop("modes"),
        lambda d: d.update(modes="x"),
        lambda d: d["modes"][0]["channels"][0].update(bits=12),
        lambda d: d["modes"][0]["channels"][0].update(dmx="1"),
        lambda d: d["modes"][0]["channels"][0].update(dmx=True),
        lambda d: d["modes"][0]["channels"][0]["ranges"].append({"start": 0}),
        lambda d: d.update(name=5),
    ],
)
def test_corrupted_data_raises_profile_error(mutate):
    data = profile_to_dict(sample_profile())
    mutate(data)

    with pytest.raises(ProfileError):
        profile_from_dict(data)


def test_a_non_dict_is_rejected():
    with pytest.raises(ProfileError):
        profile_from_dict([1, 2])


def test_an_unknown_template_in_saved_data_falls_back_to_custom():
    data = profile_to_dict(sample_profile())
    data["modes"][0]["channels"][0]["template"] = "from_the_future"

    assert profile_from_dict(data).modes[0].channels[0].template == "custom"
```

- [ ] **Шаг 2: запустить и убедиться, что падает** (`ModuleNotFoundError: gmagc_common.fixtures`):
`.venv\Scripts\python.exe -m pytest tests/common/test_fixtures.py -q`

- [ ] **Шаг 3: реализация `packages/common/gmagc_common/fixtures.py`**

```python
"""Профиль прибора (fixture type) для grandMA2/MA3: модель, шаблоны каналов, JSON (только стандартная библиотека)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

MAX_DMX = 512
BITS_CHOICES = (8, 16)


class ProfileError(ValueError):
    """Повреждённые или недопустимые данные профиля."""


@dataclass(frozen=True)
class Range:
    start: int
    end: int
    name: str


@dataclass(frozen=True)
class Channel:
    dmx: int  # первый DMX-адрес канала
    bits: int  # 8 или 16; 16 бит занимают dmx и dmx+1
    name: str
    template: str
    default: int = 0  # по грубому байту 0–255
    ranges: tuple[Range, ...] = ()  # по грубому байту 0–255

    @property
    def width(self) -> int:
        return self.bits // 8

    @property
    def last(self) -> int:
        return self.dmx + self.width - 1


@dataclass(frozen=True)
class Mode:
    name: str
    channels: tuple[Channel, ...] = ()


@dataclass(frozen=True)
class FixtureProfile:
    id: str
    manufacturer: str
    name: str
    short_name: str = ""
    modes: tuple[Mode, ...] = ()


@dataclass(frozen=True)
class Template:
    id: str
    title: str
    bits: int
    ranges: tuple[Range, ...] = ()


def _full(label: str) -> tuple[Range, ...]:
    return (Range(0, 255, label),)


# атрибут grandMA2/MA3 для каждого шаблона выбирает экспорт; здесь только нейтральный идентификатор
TEMPLATES = (
    Template("dimmer", "Диммер", 8, _full("0…100%")),
    Template("shutter", "Шаттер / строб", 8, (Range(0, 9, "Закрыт"), Range(10, 127, "Открыт"), Range(128, 255, "Строб"))),
    Template("pan", "Pan", 16, _full("Pan")),
    Template("tilt", "Tilt", 16, _full("Tilt")),
    Template("pan_tilt_speed", "Скорость Pan/Tilt", 8, _full("Быстро…медленно")),
    Template("red", "Красный", 8, _full("0…100%")),
    Template("green", "Зелёный", 8, _full("0…100%")),
    Template("blue", "Синий", 8, _full("0…100%")),
    Template("white", "Белый", 8, _full("0…100%")),
    Template("cto", "CTO", 8, _full("Тёплый…холодный")),
    Template("color_wheel", "Колесо цвета", 8, (Range(0, 9, "Открыто"),)),
    Template("gobo_wheel", "Колесо гобо", 8, (Range(0, 9, "Открыто"),)),
    Template("gobo_rotation", "Вращение гобо", 8, _full("Вращение")),
    Template("prism", "Призма", 8, (Range(0, 9, "Нет"),)),
    Template("focus", "Фокус", 8, _full("Ближе…дальше")),
    Template("zoom", "Зум", 8, _full("Уже…шире")),
    Template("iris", "Ирис", 8, _full("Закрыт…открыт")),
    Template("frost", "Фрост", 8, _full("0…100%")),
    Template("control", "Управление", 8, ()),
    Template("custom", "Свой канал", 8, ()),
)
_BY_ID = {template.id: template for template in TEMPLATES}


def template_by_id(template_id: str) -> Template:
    try:
        return _BY_ID[template_id]
    except KeyError:
        raise ProfileError(f"неизвестный шаблон канала: {template_id}") from None


def channel_from_template(template_id: str, dmx: int) -> Channel:
    template = template_by_id(template_id)
    return Channel(dmx, template.bits, template.title, template.id, 0, template.ranges)


def next_free_dmx(mode: Mode) -> int:
    """Адрес сразу за последним каналом режима (1 в пустом режиме); может выйти за MAX_DMX — это ловит проверка."""
    return max((channel.last for channel in mode.channels), default=0) + 1


def new_profile(manufacturer: str = "", name: str = "") -> FixtureProfile:
    return FixtureProfile(uuid.uuid4().hex, manufacturer, name, "", (Mode("Режим 1"),))


# ---- JSON ------------------------------------------------------------------
def profile_to_dict(profile: FixtureProfile) -> dict:
    return {
        "id": profile.id,
        "manufacturer": profile.manufacturer,
        "name": profile.name,
        "short_name": profile.short_name,
        "modes": [
            {
                "name": mode.name,
                "channels": [
                    {
                        "dmx": channel.dmx,
                        "bits": channel.bits,
                        "name": channel.name,
                        "template": channel.template,
                        "default": channel.default,
                        "ranges": [{"start": r.start, "end": r.end, "name": r.name} for r in channel.ranges],
                    }
                    for channel in mode.channels
                ],
            }
            for mode in profile.modes
        ],
    }


def _text(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ProfileError(f"поле «{field}» должно быть строкой")
    return value


def _int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProfileError(f"поле «{field}» должно быть целым числом")
    return value


def _list(value: object, field: str) -> list:
    if not isinstance(value, list):
        raise ProfileError(f"поле «{field}» должно быть списком")
    return value


def _dict(value: object, field: str) -> dict:
    if not isinstance(value, dict):
        raise ProfileError(f"поле «{field}» должно быть объектом")
    return value


def _range(data: object) -> Range:
    data = _dict(data, "диапазон")
    return Range(_int(data.get("start"), "start"), _int(data.get("end"), "end"), _text(data.get("name"), "name"))


def _channel(data: object) -> Channel:
    data = _dict(data, "канал")
    bits = _int(data.get("bits"), "bits")
    if bits not in BITS_CHOICES:
        raise ProfileError("разрядность канала должна быть 8 или 16")
    template = _text(data.get("template", "custom"), "template")
    return Channel(
        _int(data.get("dmx"), "dmx"),
        bits,
        _text(data.get("name"), "name"),
        template if template in _BY_ID else "custom",  # шаблон из будущей версии не должен ронять загрузку
        _int(data.get("default", 0), "default"),
        tuple(_range(item) for item in _list(data.get("ranges", []), "ranges")),
    )


def profile_from_dict(data: object) -> FixtureProfile:
    data = _dict(data, "профиль")
    modes = tuple(
        Mode(
            _text(_dict(mode, "режим").get("name"), "name"),
            tuple(_channel(item) for item in _list(mode.get("channels", []), "channels")),
        )
        for mode in _list(data.get("modes"), "modes")
    )
    return FixtureProfile(
        _text(data.get("id"), "id"),
        _text(data.get("manufacturer"), "manufacturer"),
        _text(data.get("name"), "name"),
        _text(data.get("short_name", ""), "short_name"),
        modes,
    )
```

- [ ] **Шаг 4:** `python scripts/sync_common.py`, затем `.venv\Scripts\python.exe -m pytest tests/common tests/test_scripts.py -q` — зелёный.
- [ ] **Шаг 5: коммит** `git add packages apps tests && git commit -m "Модель профиля прибора: шаблоны каналов и JSON"`

---

## Задача 2: проверка профиля

**Файлы:** дополнить `packages/common/gmagc_common/fixtures.py` и `tests/common/test_fixtures.py`.
**Интерфейсы:** `Issue(path, message, error)`; `validate_profile(profile) -> list[Issue]` (ошибки `error=True`, предупреждения `error=False`); `has_errors(issues) -> bool`.

- [ ] **Шаг 1: тесты (дописать в `tests/common/test_fixtures.py`)**

```python
from gmagc_common.fixtures import Issue, has_errors, validate_profile


def issues_of(profile):
    return [(issue.path, issue.message, issue.error) for issue in validate_profile(profile)]


def profile_with(*channels, manufacturer="M", name="N", mode_name="Режим"):
    return FixtureProfile("i", manufacturer, name, "", (Mode(mode_name, tuple(channels)),))


def test_a_complete_profile_has_no_issues():
    assert validate_profile(sample_profile()) == []


def test_missing_manufacturer_name_and_modes_are_errors():
    issues = validate_profile(FixtureProfile("i", "", "", "", ()))

    messages = [issue.message for issue in issues]
    assert has_errors(issues) and any("производител" in m for m in messages) and any("название" in m for m in messages)
    assert any("режим" in m for m in messages)


def test_an_empty_mode_and_duplicate_mode_names_are_errors():
    profile = FixtureProfile("i", "M", "N", "", (Mode("A"), Mode("A", (Channel(1, 8, "x", "dimmer"),))))

    messages = [issue.message for issue in validate_profile(profile)]
    assert any("нет каналов" in m for m in messages) and any("повторяется" in m for m in messages)


def test_an_empty_channel_name_is_an_error():
    assert has_errors(validate_profile(profile_with(Channel(1, 8, " ", "dimmer"))))


def test_channels_must_not_overlap_including_the_fine_byte():
    profile = profile_with(Channel(1, 16, "Pan", "pan"), Channel(2, 8, "Tilt", "tilt"))

    assert any("пересека" in issue.message and issue.error for issue in validate_profile(profile))


def test_addresses_must_stay_inside_1_to_512():
    assert has_errors(validate_profile(profile_with(Channel(0, 8, "a", "dimmer"))))
    assert has_errors(validate_profile(profile_with(Channel(MAX_DMX, 16, "a", "pan"))))
    assert not has_errors(validate_profile(profile_with(Channel(MAX_DMX, 8, "a", "dimmer"))))


def test_a_gap_between_channels_is_only_a_warning():
    issues = validate_profile(profile_with(Channel(1, 8, "a", "dimmer"), Channel(5, 8, "b", "red")))

    assert len(issues) == 1 and issues[0].error is False and "пропуск" in issues[0].message


def test_the_default_value_must_be_a_byte():
    assert has_errors(validate_profile(profile_with(Channel(1, 8, "a", "dimmer", 256))))


def test_ranges_must_be_ordered_inside_a_byte_and_not_overlap():
    bad_order = Channel(1, 8, "a", "dimmer", 0, (Range(10, 5, "x"),))
    outside = Channel(1, 8, "a", "dimmer", 0, (Range(0, 300, "x"),))
    overlap = Channel(1, 8, "a", "dimmer", 0, (Range(0, 10, "x"), Range(10, 20, "y")))

    for channel in (bad_order, outside, overlap):
        assert has_errors(validate_profile(profile_with(channel)))


def test_a_hole_between_ranges_is_a_warning_and_the_path_names_the_channel():
    channel = Channel(1, 8, "Гобо", "gobo_wheel", 0, (Range(0, 9, "a"), Range(20, 255, "b")))

    issues = validate_profile(profile_with(channel, mode_name="Стандарт"))

    assert len(issues) == 1 and not issues[0].error and issues[0].path == "Стандарт → Гобо"
```

- [ ] **Шаг 2:** прогон падает (нет `validate_profile`).
- [ ] **Шаг 3: реализация (дописать в `fixtures.py`)**

```python
@dataclass(frozen=True)
class Issue:
    path: str  # «режим → канал» или пусто для профиля целиком
    message: str
    error: bool  # False — предупреждение, сохранению и экспорту не мешает


def has_errors(issues: list[Issue]) -> bool:
    return any(issue.error for issue in issues)


def _check_ranges(channel: Channel, path: str, out: list[Issue]) -> None:
    ordered = sorted(channel.ranges, key=lambda r: (r.start, r.end))
    for r in ordered:
        if not 0 <= r.start <= r.end <= 255:
            out.append(Issue(path, f"диапазон «{r.name}» должен лежать в 0–255 и идти от меньшего к большему", True))
    valid = [r for r in ordered if 0 <= r.start <= r.end <= 255]
    for previous, current in zip(valid, valid[1:], strict=False):
        if current.start <= previous.end:
            out.append(Issue(path, f"диапазоны «{previous.name}» и «{current.name}» пересекаются", True))
        elif current.start > previous.end + 1:
            out.append(Issue(path, f"между диапазонами «{previous.name}» и «{current.name}» есть пропуск", False))


def validate_profile(profile: FixtureProfile) -> list[Issue]:
    issues: list[Issue] = []
    if not profile.manufacturer.strip():
        issues.append(Issue("", "не указан производитель", True))
    if not profile.name.strip():
        issues.append(Issue("", "не указано название прибора", True))
    if not profile.modes:
        issues.append(Issue("", "нет ни одного режима", True))
    seen: set[str] = set()
    for mode in profile.modes:
        if mode.name in seen:
            issues.append(Issue(mode.name, f"название режима «{mode.name}» повторяется", True))
        seen.add(mode.name)
        if not mode.channels:
            issues.append(Issue(mode.name, "в режиме нет каналов", True))
        used: dict[int, str] = {}
        previous_last = 0
        for channel in sorted(mode.channels, key=lambda c: c.dmx):
            path = f"{mode.name} → {channel.name.strip() or '(без названия)'}"
            if not channel.name.strip():
                issues.append(Issue(path, "у канала нет названия", True))
            if channel.dmx < 1 or channel.last > MAX_DMX:
                issues.append(Issue(path, f"адрес должен лежать в 1–{MAX_DMX} (с учётом 16 бит)", True))
            for address in range(channel.dmx, channel.last + 1):
                if address in used:
                    issues.append(Issue(path, f"адрес {address} пересекается с каналом «{used[address]}»", True))
                used[address] = channel.name
            if channel.dmx > previous_last + 1 and 1 <= channel.dmx <= MAX_DMX:
                issues.append(Issue(path, f"пропуск адресов {previous_last + 1}–{channel.dmx - 1}", False))
            previous_last = max(previous_last, channel.last)
            if not 0 <= channel.default <= 255:
                issues.append(Issue(path, "значение по умолчанию должно быть 0–255", True))
            _check_ranges(channel, path, issues)
    return issues
```

- [ ] **Шаг 4:** `python scripts/sync_common.py`; `pytest tests/common -q` зелёный.
- [ ] **Шаг 5: коммит** «Проверка профиля прибора: ошибки и предупреждения».

Примечание: первый тест на пропуск использует адреса 1 и 5, «пропуск адресов 2–4» — ровно одно предупреждение.

---

## Задача 3: хранилище профилей на телефоне

**Файлы:** создать `apps/mobile/src/gmagc_mobile/profile_store.py`; тест `tests/mobile/test_profile_store.py`.
**Интерфейсы:** `ProfileStore(prefs)` с `async list() -> list[FixtureProfile]`, `async save(profile)`, `async delete(profile_id)`; `MemoryPrefs` (замена prefs по умолчанию); ключи `gmagc.profiles.index` и `gmagc.profile.<id>`, значения JSON-строки.

- [ ] **Шаг 1: тест**

```python
import asyncio
import json

from gmagc_common.fixtures import Channel, FixtureProfile, Mode, new_profile, profile_to_dict
from gmagc_mobile.profile_store import INDEX_KEY, ProfileStore, profile_key
from tests.fakes_mobile import FakePrefs


def run(coroutine):
    return asyncio.run(coroutine)


def make_profile(name="A"):
    return FixtureProfile(f"id-{name}", "M", name, "", (Mode("m", (Channel(1, 8, "d", "dimmer"),)),))


def test_saved_profiles_come_back_in_creation_order():
    store = ProfileStore(FakePrefs())

    run(store.save(make_profile("A")))
    run(store.save(make_profile("B")))
    run(store.save(make_profile("A")))  # повторное сохранение не дублирует запись

    assert [p.name for p in run(store.list())] == ["A", "B"]


def test_a_profile_survives_a_reload_from_the_same_prefs():
    prefs = FakePrefs()
    run(ProfileStore(prefs).save(make_profile("A")))

    assert run(ProfileStore(prefs).list())[0] == make_profile("A")


def test_delete_removes_the_profile_and_its_index_entry():
    prefs = FakePrefs()
    store = ProfileStore(prefs)
    run(store.save(make_profile("A")))

    run(store.delete("id-A"))

    assert run(store.list()) == [] and profile_key("id-A") not in prefs.data


def test_a_corrupted_profile_is_skipped_without_breaking_the_list():
    prefs = FakePrefs()
    store = ProfileStore(prefs)
    run(store.save(make_profile("A")))
    run(store.save(make_profile("B")))
    prefs.data[profile_key("id-A")] = "not json"

    assert [p.name for p in run(store.list())] == ["B"]


def test_a_broken_index_gives_an_empty_list_and_unavailable_storage_too():
    assert run(ProfileStore(FakePrefs({INDEX_KEY: "{{"})).list()) == []
    assert run(ProfileStore(FakePrefs(fail=True)).list()) == []


def test_the_stored_value_is_a_json_string():
    prefs = FakePrefs()
    profile = new_profile("M", "N")
    run(ProfileStore(prefs).save(profile))

    assert json.loads(prefs.data[profile_key(profile.id)]) == profile_to_dict(profile)
```

- [ ] **Шаг 2:** падает (нет модуля).
- [ ] **Шаг 3: реализация**

```python
"""Профили приборов на телефоне: JSON в SharedPreferences (индекс + по ключу на профиль)."""

from __future__ import annotations

import json

from gmagc_common.fixtures import FixtureProfile, ProfileError, profile_from_dict, profile_to_dict

INDEX_KEY = "gmagc.profiles.index"


def profile_key(profile_id: str) -> str:
    return f"gmagc.profile.{profile_id}"


class MemoryPrefs:
    """Хранилище в памяти: запасной вариант, когда приложению не передали настоящие prefs."""

    def __init__(self):
        self.data: dict = {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value):
        self.data[key] = value
        return True

    async def remove(self, key):
        return self.data.pop(key, None) is not None


class ProfileStore:
    def __init__(self, prefs):
        self._prefs = prefs

    async def _index(self) -> list[str]:
        try:
            raw = await self._prefs.get(INDEX_KEY)
            ids = json.loads(raw) if isinstance(raw, str) else []
        except Exception:  # noqa: BLE001 - недоступное или повреждённое хранилище = пустой список
            return []
        return [item for item in ids if isinstance(item, str)] if isinstance(ids, list) else []

    async def list(self) -> list[FixtureProfile]:
        profiles = []
        for profile_id in await self._index():
            try:
                raw = await self._prefs.get(profile_key(profile_id))
                profiles.append(profile_from_dict(json.loads(raw)))
            except (ProfileError, TypeError, ValueError):  # повреждённый профиль пропускаем, остальные живут
                continue
            except Exception:  # noqa: BLE001
                continue
        return profiles

    async def save(self, profile: FixtureProfile) -> None:
        await self._prefs.set(profile_key(profile.id), json.dumps(profile_to_dict(profile), ensure_ascii=False))
        index = await self._index()
        if profile.id not in index:
            index.append(profile.id)
            await self._prefs.set(INDEX_KEY, json.dumps(index))

    async def delete(self, profile_id: str) -> None:
        await self._prefs.remove(profile_key(profile_id))
        index = [item for item in await self._index() if item != profile_id]
        await self._prefs.set(INDEX_KEY, json.dumps(index))
```

- [ ] **Шаг 4:** `pytest tests/mobile/test_profile_store.py -q` зелёный; `ruff check .`.
- [ ] **Шаг 5: коммит** «Хранилище профилей приборов на телефоне».

---

## Задача 4: окно «Профили приборов», список профилей и вход из приложения

**Файлы:** создать `apps/mobile/src/gmagc_mobile/profiles_ui.py`; изменить `apps/mobile/src/gmagc_mobile/app.py`; тесты `tests/mobile/test_profiles_ui.py`, `tests/mobile/test_mobile_back_button.py`.

**Интерфейсы (выпускает):** `ProfileEditor(page, store, share, on_exit)` с `.view` (ft.Column), `.screen` (`"list" | "profile" | "mode" | "channel"`), `.profiles`, `.profile`, `async open()`, `go_back() -> bool` (True — шаг назад сделан внутри редактора, False — уже на списке), `async on_new_profile(_)`, `async on_open_profile(profile_id)`, `on_ask_delete(profile_id)`, `async on_confirm_delete(profile_id)`, `on_cancel_delete()`. В `MobileApp`: параметр `profile_store=None`, атрибуты `self.editor`, `self.profiles_view = self.editor.view`, обработчик `on_open_profiles`, значок в нижней навигации экрана подключения и в верхней строке камеры.

- [ ] **Шаг 1: тесты `tests/mobile/test_profiles_ui.py` (список и вход)**

```python
import asyncio
import json

import flet as ft

from gmagc_common.fixtures import FixtureProfile, Mode, new_profile
from gmagc_mobile.profile_store import ProfileStore, profile_key
from gmagc_mobile.profiles_ui import ProfileEditor
from tests.fakes import StubPage, texts
from tests.fakes_mobile import FakePrefs, FakeShare


def run(coroutine):
    return asyncio.run(coroutine)


def make_editor(prefs=None):
    prefs = prefs if prefs is not None else FakePrefs()
    store = ProfileStore(prefs)
    editor = ProfileEditor(StubPage(), store, FakeShare(), on_exit=lambda: None)
    return editor, store, prefs


def shown(editor):
    return " | ".join(t for t in texts(editor.view) if t)


def test_an_empty_list_offers_to_create_the_first_profile():
    editor, _, _ = make_editor()

    run(editor.open())

    assert editor.screen == "list" and "Нет профилей" in shown(editor)


def test_a_new_profile_is_saved_at_once_and_opens_its_screen():
    editor, store, prefs = make_editor()
    run(editor.open())

    run(editor.on_new_profile(None))

    assert editor.screen == "profile" and editor.profile is not None
    assert len(run(store.list())) == 1 and profile_key(editor.profile.id) in prefs.data


def test_the_list_shows_saved_profiles_with_manufacturer_and_mode_count():
    editor, store, _ = make_editor()
    run(store.save(FixtureProfile("1", "SHEHDS", "380W Beam", "", (Mode("a"), Mode("b")))))

    run(editor.open())

    assert "380W Beam" in shown(editor) and "SHEHDS" in shown(editor) and "2" in shown(editor)


def test_opening_a_profile_from_the_list_shows_its_screen():
    editor, store, _ = make_editor()
    run(store.save(new_profile("M", "N")))
    run(editor.open())

    run(editor.on_open_profile(editor.profiles[0].id))

    assert editor.screen == "profile" and editor.profile.name == "N"


def test_deleting_needs_a_second_confirmation():
    editor, store, _ = make_editor()
    run(store.save(new_profile("M", "N")))
    run(editor.open())
    profile_id = editor.profiles[0].id

    editor.on_ask_delete(profile_id)
    assert len(run(store.list())) == 1 and "Удалить" in shown(editor)
    editor.on_cancel_delete()
    assert len(run(store.list())) == 1
    editor.on_ask_delete(profile_id)
    run(editor.on_confirm_delete(profile_id))

    assert run(store.list()) == [] and "Нет профилей" in shown(editor)


def test_back_from_a_profile_returns_to_the_list_and_from_the_list_is_not_handled():
    editor, store, _ = make_editor()
    run(editor.open())
    run(editor.on_new_profile(None))

    assert editor.go_back() is True and editor.screen == "list"
    assert editor.go_back() is False
```

Дополнить `tests/mobile/test_mobile_app.py` (рядом с тестом про Настройки/О программе/Помощь, есть `start()`, `views()`; в `views()` добавить `"profiles"` в кортеж имён):

```python
def test_the_profiles_screen_opens_from_connect_and_returns_there():
    app, _, _, _, _ = start()

    asyncio.run(app.on_open_profiles(None))
    assert views(app) == ["profiles"]
    app.on_close_overlay(None)

    assert views(app) == ["connect"]
```

Дополнить `tests/mobile/test_mobile_back_button.py`:

```python
def test_back_from_the_profiles_list_returns_to_the_screen_it_was_opened_from():
    app, view, _, _ = make()
    asyncio.run(app.on_open_profiles(None))

    press_back(app, view)

    assert app.profiles_view.visible is False and views_shown(app) == ["connect"] and view.decisions == [False]


def test_back_inside_the_profile_editor_goes_one_level_up_first():
    app, view, _, _ = make()
    asyncio.run(app.on_open_profiles(None))
    asyncio.run(app.editor.on_new_profile(None))
    assert app.editor.screen == "profile"

    press_back(app, view)
    assert app.profiles_view.visible and app.editor.screen == "list"
    press_back(app, view)

    assert app.profiles_view.visible is False
```

- [ ] **Шаг 2:** прогон падает (нет `profiles_ui`, `on_open_profiles`).
- [ ] **Шаг 3: `profiles_ui.py` (каркас редактора и экран списка)**

```python
"""Окно «Профили приборов» мобильного приложения: список → профиль → режим → канал (автосохранение)."""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from gmagc_common.fixtures import FixtureProfile, new_profile
from gmagc_mobile.profile_store import ProfileStore

SCREEN_LIST = "list"
SCREEN_PROFILE = "profile"
SCREEN_MODE = "mode"
SCREEN_CHANNEL = "channel"


class ProfileEditor:
    def __init__(self, page: ft.Page, store: ProfileStore, share, on_exit: Callable[[], None] | None = None):
        self.page = page
        self.store = store
        self.share = share
        self.on_exit = on_exit
        self.profiles: list[FixtureProfile] = []
        self.profile: FixtureProfile | None = None
        self.mode_index: int | None = None
        self.channel_index: int | None = None
        self.screen = SCREEN_LIST
        self.pending_delete: str | None = None
        self.message = ""
        self.view = ft.Column(spacing=8, visible=False, expand=True, scroll=ft.ScrollMode.AUTO)

    # ---- навигация ----------------------------------------------------------
    async def open(self) -> None:
        self.profiles = await self.store.list()
        self.profile = None
        self.mode_index = self.channel_index = None
        self.pending_delete = None
        self.screen = SCREEN_LIST
        self.render()

    def go_back(self) -> bool:
        """Шаг назад внутри редактора. False — уже на списке, выходить должно приложение."""
        self.message = ""
        if self.screen == SCREEN_CHANNEL:
            self.channel_index = None
            self.screen = SCREEN_MODE
        elif self.screen == SCREEN_MODE:
            self.mode_index = None
            self.screen = SCREEN_PROFILE
        elif self.screen == SCREEN_PROFILE:
            self.profile = None
            self.screen = SCREEN_LIST
        else:
            return False
        self.render()
        return True

    def _on_back_click(self, _event) -> None:
        if not self.go_back() and self.on_exit:
            self.on_exit()

    # ---- список -------------------------------------------------------------
    async def on_new_profile(self, _event) -> None:
        profile = new_profile()
        await self.store.save(profile)
        self.profiles = await self.store.list()
        self.profile = profile
        self.screen = SCREEN_PROFILE
        self.render()

    async def on_open_profile(self, profile_id: str) -> None:
        self.profile = next((p for p in self.profiles if p.id == profile_id), None)
        if self.profile is not None:
            self.screen = SCREEN_PROFILE
            self.render()

    def on_ask_delete(self, profile_id: str) -> None:
        self.pending_delete = profile_id
        self.render()

    def on_cancel_delete(self) -> None:
        self.pending_delete = None
        self.render()

    async def on_confirm_delete(self, profile_id: str) -> None:
        await self.store.delete(profile_id)
        self.profiles = await self.store.list()
        self.pending_delete = None
        self.render()

    # ---- отрисовка ----------------------------------------------------------
    def _header(self, title: str) -> ft.Row:
        return ft.Row(
            [ft.IconButton(icon=ft.Icons.ARROW_BACK, on_click=self._on_back_click), ft.Text(title, size=20, weight=ft.FontWeight.BOLD)]
        )

    @staticmethod
    def _async_click(handler, *args):
        """Flet принимает async-обработчики: возвращаем корутинную функцию с уже подставленными аргументами."""

        async def click(_event) -> None:
            await handler(*args)

        return click

    def render(self) -> None:
        self.view.controls = getattr(self, f"_render_{self.screen}")()
        self.page.update()

    def _render_list(self) -> list[ft.Control]:
        controls: list[ft.Control] = [self._header("Профили приборов")]
        if not self.profiles:
            controls.append(ft.Text("Нет профилей. Создайте первый.", size=13, color=ft.Colors.GREY_500))
        for profile in self.profiles:
            controls.append(self._profile_card(profile))
        controls.append(ft.Button("Новый профиль", icon=ft.Icons.ADD, on_click=self.on_new_profile))
        return controls

    def _profile_card(self, profile: FixtureProfile) -> ft.Control:
        title = f"{profile.manufacturer or '(без производителя)'} — {profile.name or '(без названия)'}"
        subtitle = f"Режимов: {len(profile.modes)}"
        if self.pending_delete == profile.id:
            return ft.Row(
                [
                    ft.Text(f"Удалить «{title}»?", expand=True),
                    ft.TextButton("Да", on_click=self._async_click(self.on_confirm_delete, profile.id)),
                    ft.TextButton("Нет", on_click=lambda _e: self.on_cancel_delete()),
                ]
            )
        return ft.Container(
            ft.Row(
                [
                    ft.Column([ft.Text(title, weight=ft.FontWeight.BOLD), ft.Text(subtitle, size=12)], expand=True, spacing=2),
                    ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, on_click=lambda _e, pid=profile.id: self.on_ask_delete(pid)),
                ]
            ),
            on_click=self._async_click(self.on_open_profile, profile.id),
            padding=8,
        )

    def _render_profile(self) -> list[ft.Control]:
        return [self._header("Профиль")]  # наполняется в задаче 5

    def _render_mode(self) -> list[ft.Control]:
        return [self._header("Режим")]  # наполняется в задаче 6

    def _render_channel(self) -> list[ft.Control]:
        return [self._header("Канал")]  # наполняется в задаче 7
```

Решение: `page.run_task` не используется; все обработчики Flet-кнопок асинхронные (`_async_click` для аргументов, `async def` для остальных), тесты вызывают методы редактора напрямую через `asyncio.run`.

- [ ] **Шаг 4: интеграция в `MobileApp`**
  - импорты: `from gmagc_mobile.profile_store import MemoryPrefs, ProfileStore`, `from gmagc_mobile.profiles_ui import ProfileEditor`;
  - в `__init__` параметр `profile_store: ProfileStore | None = None`; после `self.share = ...`: `self.editor = ProfileEditor(page, profile_store or ProfileStore(prefs or MemoryPrefs()), self.share, on_exit=lambda: self._show(self._return_view))`; `self.profiles_view = self.editor.view`;
  - `_VIEW_NAMES` добавить `"profiles"`; в `build()` добавить `self.profiles_view` в `ft.Column` после `self.help_view`;
  - `async def on_open_profiles(self, _event) -> None: self._open_overlay("profiles"); await self.editor.open()`;
  - `_handle_back`: перед проверкой `("gallery", "settings", "about", "help")` вставить `if self.profiles_view.visible and self.editor.go_back(): return False`, а `"profiles"` добавить в этот кортеж;
  - вход: пункт `_nav_item(ft.Icons.TUNE, "Профили", self.on_open_profiles)` в нижнюю навигацию экрана подключения и `_camera_icon_button(ft.Icons.TUNE, "Профили приборов", self.on_open_profiles)` в верхнюю строку камеры;
  - `build_page`: `profile_store=ProfileStore(prefs)` в вызове `MobileApp(...)`.
  Тесты вызывают `asyncio.run(app.on_open_profiles(None))` (в примерах шага 1 заменить `app.on_open_profiles(None)` на `asyncio.run(app.on_open_profiles(None))`).
- [ ] **Шаг 5:** `pytest tests/mobile -q` и `ruff check .` — зелёные. Коммит «Окно профилей приборов: список и вход».

---

## Задача 5: экран профиля и режимы

**Файлы:** `profiles_ui.py`, `tests/mobile/test_profiles_ui.py`.
**Интерфейсы:** `async set_profile_text(field, value)` (`field` in `manufacturer|name|short_name`), `async add_mode()`, `async duplicate_mode(index)`, `async delete_mode(index)`, `async rename_mode(index, name)`, `async open_mode(index)`, `async _commit(profile)` (заменяет профиль, пишет в хранилище, обновляет список).

- [ ] **Шаг 1: тесты (дописать)**

```python
def open_new(editor):
    run(editor.open())
    run(editor.on_new_profile(None))


def test_profile_fields_are_saved_as_you_type():
    editor, store, _ = make_editor()
    open_new(editor)

    run(editor.set_profile_text("manufacturer", "SHEHDS"))
    run(editor.set_profile_text("name", "380W Beam"))
    run(editor.set_profile_text("short_name", "380WB"))

    saved = run(store.list())[0]
    assert (saved.manufacturer, saved.name, saved.short_name) == ("SHEHDS", "380W Beam", "380WB")


def test_adding_a_mode_gives_it_a_unique_name_and_saves():
    editor, store, _ = make_editor()
    open_new(editor)

    run(editor.add_mode())

    names = [m.name for m in run(store.list())[0].modes]
    assert names == ["Режим 1", "Режим 2"]


def test_duplicating_a_mode_copies_its_channels_under_a_new_name():
    editor, store, _ = make_editor()
    open_new(editor)
    run(editor.open_mode(0))
    run(editor.add_channel("dimmer"))
    editor.go_back()

    run(editor.duplicate_mode(0))

    modes = run(store.list())[0].modes
    assert len(modes) == 2 and modes[1].name != modes[0].name and modes[1].channels == modes[0].channels


def test_the_last_mode_can_not_be_deleted_but_others_can():
    editor, store, _ = make_editor()
    open_new(editor)

    run(editor.delete_mode(0))
    assert len(run(store.list())[0].modes) == 1

    run(editor.add_mode())
    run(editor.delete_mode(0))
    assert len(run(store.list())[0].modes) == 1


def test_renaming_a_mode_is_saved():
    editor, store, _ = make_editor()
    open_new(editor)

    run(editor.rename_mode(0, "Расширенный"))

    assert run(store.list())[0].modes[0].name == "Расширенный"


def test_the_profile_screen_lists_modes_and_shows_validation_messages():
    editor, _, _ = make_editor()
    open_new(editor)

    text = shown(editor)

    assert "Режим 1" in text and "не указан производитель" in text
```

- [ ] **Шаг 2:** падает.
- [ ] **Шаг 3: реализация (в `profiles_ui.py`)**

```python
from dataclasses import replace

from gmagc_common.fixtures import Mode, channel_from_template, has_errors, next_free_dmx, validate_profile

    async def _commit(self, profile: FixtureProfile) -> None:
        self.profile = profile
        await self.store.save(profile)
        self.profiles = await self.store.list()
        self.render()

    async def set_profile_text(self, field: str, value: str) -> None:
        await self._commit(replace(self.profile, **{field: value}))

    def _unique_mode_name(self, base: str) -> str:
        taken = {mode.name for mode in self.profile.modes}
        if base not in taken:
            return base
        number = 2
        while f"{base} {number}" in taken:
            number += 1
        return f"{base} {number}"

    async def add_mode(self) -> None:
        name = self._unique_mode_name(f"Режим {len(self.profile.modes) + 1}")
        await self._commit(replace(self.profile, modes=(*self.profile.modes, Mode(name))))

    async def duplicate_mode(self, index: int) -> None:
        source = self.profile.modes[index]
        copy = replace(source, name=self._unique_mode_name(f"{source.name} (копия)"))
        modes = (*self.profile.modes[: index + 1], copy, *self.profile.modes[index + 1 :])
        await self._commit(replace(self.profile, modes=modes))

    async def delete_mode(self, index: int) -> None:
        if len(self.profile.modes) <= 1:  # у прибора всегда есть хотя бы один режим
            return
        modes = tuple(m for i, m in enumerate(self.profile.modes) if i != index)
        await self._commit(replace(self.profile, modes=modes))

    async def rename_mode(self, index: int, name: str) -> None:
        modes = tuple(replace(m, name=name) if i == index else m for i, m in enumerate(self.profile.modes))
        await self._commit(replace(self.profile, modes=modes))

    async def open_mode(self, index: int) -> None:
        self.mode_index = index
        self.screen = SCREEN_MODE
        self.render()
```

Экран профиля `_render_profile`: заголовок; три `ft.TextField` (производитель, название, короткое имя) с `on_change` — async-замыкание, вызывающее `set_profile_text(field, e.control.value)`; для каждого режима строка `ft.Text(mode.name, expand=True)` + кнопки «дублировать» и «удалить» (`IconButton`) + нажатие на строку открывает режим; кнопка «Добавить режим»; блок проверки `_issue_controls(validate_profile(self.profile))` — красный текст для ошибок, янтарный для предупреждений, `path: message`. Тот же блок используется на экране режима.

- [ ] **Шаг 4:** `pytest tests/mobile/test_profiles_ui.py -q`, `ruff check .`. Коммит «Профиль прибора: поля и режимы с автосохранением».

---

## Задача 6: экран режима и каналы

**Файлы:** `profiles_ui.py`, `tests/mobile/test_profiles_ui.py`.
**Интерфейсы:** `async add_channel(template_id)`, `async open_channel(index)`, `async delete_channel(index)`, `async move_channel(index, delta)` (только меняет порядок в списке), свойство `mode` (текущий `Mode`).

- [ ] **Шаг 1: тесты (дописать)**

```python
def test_a_channel_added_from_a_template_gets_the_next_free_address():
    editor, store, _ = make_editor()
    open_new(editor)
    run(editor.open_mode(0))

    run(editor.add_channel("dimmer"))
    run(editor.add_channel("pan"))
    run(editor.add_channel("shutter"))

    channels = run(store.list())[0].modes[0].channels
    assert [(c.dmx, c.bits, c.template) for c in channels] == [(1, 8, "dimmer"), (2, 16, "pan"), (4, 8, "shutter")]


def test_deleting_a_channel_keeps_the_others_untouched():
    editor, store, _ = make_editor()
    open_new(editor)
    run(editor.open_mode(0))
    run(editor.add_channel("dimmer"))
    run(editor.add_channel("red"))

    run(editor.delete_channel(0))

    assert [c.template for c in run(store.list())[0].modes[0].channels] == ["red"]


def test_the_mode_screen_shows_channels_in_dmx_order_and_validation_messages():
    editor, _, _ = make_editor()
    open_new(editor)
    run(editor.open_mode(0))
    run(editor.add_channel("dimmer"))
    run(editor.add_channel("pan"))

    text = shown(editor)

    assert "Диммер" in text and "Pan" in text


def test_a_channel_added_beyond_512_is_reported_as_an_error_on_the_screen():
    editor, store, _ = make_editor()
    open_new(editor)
    run(editor.open_mode(0))
    profile = run(store.list())[0]
    from dataclasses import replace

    from gmagc_common.fixtures import Channel

    run(editor._commit(replace(profile, modes=(replace(profile.modes[0], channels=(Channel(512, 8, "z", "dimmer"),)),))))
    run(editor.add_channel("dimmer"))

    assert "адрес должен лежать" in shown(editor)


def test_opening_a_channel_switches_to_the_channel_screen():
    editor, _, _ = make_editor()
    open_new(editor)
    run(editor.open_mode(0))
    run(editor.add_channel("dimmer"))

    run(editor.open_channel(0))

    assert editor.screen == "channel" and editor.go_back() is True and editor.screen == "mode"
```

- [ ] **Шаг 2:** падает.
- [ ] **Шаг 3: реализация**

```python
    @property
    def mode(self) -> Mode:
        return self.profile.modes[self.mode_index]

    async def _commit_mode(self, mode: Mode) -> None:
        modes = tuple(mode if i == self.mode_index else m for i, m in enumerate(self.profile.modes))
        await self._commit(replace(self.profile, modes=modes))

    async def add_channel(self, template_id: str) -> None:
        channel = channel_from_template(template_id, next_free_dmx(self.mode))
        await self._commit_mode(replace(self.mode, channels=(*self.mode.channels, channel)))

    async def delete_channel(self, index: int) -> None:
        channels = tuple(c for i, c in enumerate(self.mode.channels) if i != index)
        await self._commit_mode(replace(self.mode, channels=channels))

    async def open_channel(self, index: int) -> None:
        self.channel_index = index
        self.screen = SCREEN_CHANNEL
        self.render()
```

Экран режима `_render_mode`: заголовок с названием режима; `TextField` названия режима (`rename_mode`); список каналов, отсортированный по `dmx`, строка `Text(f"{c.dmx}{'–' + str(c.last) if c.bits == 16 else ''}  {c.name}", expand=True)` + `IconButton` удаления, нажатие на строку → `open_channel(index_в_исходном_списке)`; блок «Добавить канал» — `ft.Dropdown` шаблонов (`options=[ft.DropdownOption(key=t.id, text=t.title) for t in TEMPLATES]`, `on_select` → `add_channel(value)`), значение после добавления сбрасывается в `None`; блок проверки (только сообщения, относящиеся к этому режиму: `issue.path.startswith(self.mode.name)`).
Важно: индекс в списке отсортированных каналов сопоставлять с индексом в `mode.channels` (хранить пары `(index, channel)`).

- [ ] **Шаг 4:** тесты и `ruff` зелёные; коммит «Экран режима: каналы из шаблонов, автоадрес и проверка».

---

## Задача 7: экран канала и диапазоны

**Файлы:** `profiles_ui.py`, `tests/mobile/test_profiles_ui.py`.
**Интерфейсы:** `async set_channel(**changes)` (`name`, `dmx`, `bits`, `default`, `template` — при смене шаблона подставляются его разрядность и диапазоны, название и адрес остаются), `async add_range()`, `async set_range(index, start=None, end=None, name=None)`, `async delete_range(index)`, `parse_int(text, fallback)` для полей ввода.

- [ ] **Шаг 1: тесты (дописать)**

```python
def open_channel_of(editor, template="gobo_wheel"):
    open_new(editor)
    run(editor.open_mode(0))
    run(editor.add_channel(template))
    run(editor.open_channel(0))


def saved_channel(store):
    return run(store.list())[0].modes[0].channels[0]


def test_channel_fields_are_saved():
    editor, store, _ = make_editor()
    open_channel_of(editor)

    run(editor.set_channel(name="Гобо 1", dmx=9, bits=16, default=10))

    channel = saved_channel(store)
    assert (channel.name, channel.dmx, channel.bits, channel.default) == ("Гобо 1", 9, 16, 10)


def test_changing_the_template_keeps_name_and_address_but_takes_bits_and_ranges():
    editor, store, _ = make_editor()
    open_channel_of(editor, "dimmer")
    run(editor.set_channel(name="Мой канал", dmx=5))

    run(editor.set_channel(template="pan"))

    channel = saved_channel(store)
    assert (channel.name, channel.dmx, channel.template, channel.bits) == ("Мой канал", 5, "pan", 16)


def test_ranges_can_be_added_edited_and_deleted():
    editor, store, _ = make_editor()
    open_channel_of(editor, "control")

    run(editor.add_range())
    run(editor.set_range(0, start=0, end=9, name="Открыто"))
    run(editor.add_range())
    run(editor.set_range(1, start=10, end=255, name="Гобо 1"))
    assert [(r.start, r.end, r.name) for r in saved_channel(store).ranges] == [(0, 9, "Открыто"), (10, 255, "Гобо 1")]

    run(editor.delete_range(0))

    assert [r.name for r in saved_channel(store).ranges] == ["Гобо 1"]


def test_a_new_range_starts_right_after_the_previous_one():
    editor, store, _ = make_editor()
    open_channel_of(editor, "gobo_wheel")  # шаблон даёт диапазон 0–9

    run(editor.add_range())

    added = saved_channel(store).ranges[-1]
    assert (added.start, added.end) == (10, 255)


def test_non_numeric_input_keeps_the_previous_value():
    from gmagc_mobile.profiles_ui import parse_int

    assert parse_int("12", 5) == 12 and parse_int("x", 5) == 5 and parse_int("", 5) == 5


def test_the_channel_screen_shows_range_rows():
    editor, _, _ = make_editor()
    open_channel_of(editor, "gobo_wheel")

    assert "Открыто" in shown(editor)
```

- [ ] **Шаг 2:** падает.
- [ ] **Шаг 3: реализация**

```python
def parse_int(text: str, fallback: int) -> int:
    try:
        return int(str(text).strip())
    except ValueError:
        return fallback

    @property
    def channel(self) -> Channel:
        return self.mode.channels[self.channel_index]

    async def _commit_channel(self, channel: Channel) -> None:
        channels = tuple(channel if i == self.channel_index else c for i, c in enumerate(self.mode.channels))
        await self._commit_mode(replace(self.mode, channels=channels))

    async def set_channel(self, **changes) -> None:
        current = self.channel
        if "template" in changes:  # смена шаблона: разрядность и диапазоны новые, имя и адрес свои
            template = template_by_id(changes.pop("template"))
            current = replace(current, template=template.id, bits=template.bits, ranges=template.ranges)
        await self._commit_channel(replace(current, **changes))

    async def add_range(self) -> None:
        ranges = self.channel.ranges
        start = min(ranges[-1].end + 1, 255) if ranges else 0
        await self._commit_channel(replace(self.channel, ranges=(*ranges, Range(start, 255, "Новый диапазон"))))

    async def set_range(self, index: int, start=None, end=None, name=None) -> None:
        def changed(item: Range) -> Range:
            return Range(item.start if start is None else start, item.end if end is None else end, item.name if name is None else name)

        ranges = tuple(changed(r) if i == index else r for i, r in enumerate(self.channel.ranges))
        await self._commit_channel(replace(self.channel, ranges=ranges))

    async def delete_range(self, index: int) -> None:
        ranges = tuple(r for i, r in enumerate(self.channel.ranges) if i != index)
        await self._commit_channel(replace(self.channel, ranges=ranges))
```
(импорты: `Channel`, `Range`, `template_by_id`, `TEMPLATES`.)

Экран канала `_render_channel`: заголовок с названием; `Dropdown` шаблона (значение `channel.template`, `on_select` → `set_channel(template=...)`); `TextField` названия (`on_change` → `set_channel(name=...)`); `TextField` DMX и по умолчанию (цифровая клавиатура, значение через `parse_int`, `on_change` не дёргает сохранение на каждый символ при пустом вводе — пустая строка оставляет прежнее значение); `SegmentedButton`/два `TextButton` «8 бит»/«16 бит» → `set_channel(bits=...)`; для каждого диапазона строка из трёх полей (от, до, название) + `IconButton` удаления; кнопка «Добавить диапазон»; блок проверки для этого канала (`issue.path.endswith(channel.name)`).

- [ ] **Шаг 4:** тесты и `ruff` зелёные; коммит «Экран канала: поля, шаблон и диапазоны».

---

## Задача 8: «Поделиться профилем», справка, README и финиш

**Файлы:** `profiles_ui.py`, `apps/mobile/src/gmagc_mobile/app.py` (текст помощи), `README.md`, `tests/mobile/test_profiles_ui.py`.

- [ ] **Шаг 1: тест**

```python
def test_sharing_a_profile_sends_its_json_through_the_share_sheet():
    editor, _, _ = make_editor()
    open_new(editor)
    run(editor.set_profile_text("name", "380W Beam"))

    run(editor.on_share(None))

    sent = editor.share.sent[0]
    assert json.loads(sent[0])["name"] == "380W Beam"
```
(Проверить в `tests/fakes_mobile.py` формат записи `FakeShare` — какое поле хранит отправленное (`self.shared`/`self.sent`) и подправить утверждение.)

- [ ] **Шаг 2: реализация**

```python
    async def on_share(self, _event) -> None:
        if self.profile is None:
            return
        text = json.dumps(profile_to_dict(self.profile), ensure_ascii=False, indent=2)
        try:
            await self.share.share_text(text, subject=f"{self.profile.manufacturer} {self.profile.name}".strip())
        except Exception as error:  # noqa: BLE001 - недоступный «Поделиться» не должен ломать редактор
            self.message = f"Не удалось поделиться: {error}"
            self.render()
```
Кнопка «Поделиться профилем» на экране профиля; `self.message` выводится красным текстом вверху экрана.

- [ ] **Шаг 3:** в текст помощи (`help_view` в `app.py`) добавить абзац про «Профили»: создание профиля прибора для grandMA2/MA3, автосохранение, «Поделиться» JSON.
- [ ] **Шаг 4: README** — в раздел про Android-клиент добавить абзац: окно «Профили приборов» (создание с нуля, режимы, каналы из шаблонов, диапазоны, автосохранение, «Поделиться» JSON); отметить, что экспорт в MA2/MA3 XML и отправка на ПК — следующие этапы.
- [ ] **Шаг 5: проверка целиком**
  `.venv\Scripts\python.exe -m pytest -q` — все зелёные (было 785; ожидается заметно больше) и `.venv\Scripts\python.exe -m ruff check .` — чисто.
- [ ] **Шаг 6: ручная проверка в web-режиме** (нативный клиент автоматикой не проверить): `--web`, пройти сценарий «профиль → режим → 3 канала → диапазоны → назад → «Поделиться»» и убедиться, что все экраны отрисовываются; на телефоне это сделает пользователь.
- [ ] **Шаг 7: коммит** «Профили приборов: поделиться, справка, README».
- [ ] **Шаг 8: PR** в `main` (описание по-русски: что сделано, границы этапа, тесты, что не проверено нативно), ждать три проверки CI, спросить пользователя о слиянии, после слияния — релиз (следующая минорная версия 0.7.0: четыре файла версии, строка статуса README, тег, сборки, заметки к релизу).

## Самопроверка плана
- Покрытие спецификации: модель и JSON (з.1), проверка (з.2), хранилище (з.3), окно и список (з.4), режимы (з.5), каналы (з.6), диапазоны (з.7), шаблоны (з.1), автосохранение (все правки идут через `_commit`), «Поделиться» (з.8). Экспорт и отправка на ПК намеренно вне этапа.
- Согласованность имён: `_commit`, `_commit_mode`, `_commit_channel`, `set_channel`, `add_channel`, `go_back` используются одинаково во всех задачах.
- Известные допущения для проверки при реализации: наличие `page.run_task` в `StubPage` (иначе async-обработчики напрямую), формат записи в `FakeShare`, хватит ли SharedPreferences на реальном устройстве (запасной вариант — файл в каталоге данных приложения).
