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
