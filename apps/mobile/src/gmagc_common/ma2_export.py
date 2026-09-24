"""Экспорт режима профиля прибора в файл типа прибора grandMA2 (.xml). Только стандартная библиотека.

Структура и значения сняты с реальных файлов MA2 (`ape_labs@mobilight_4@12_channel.xml`,
`shehds@380w_beam@19_channel.xml`). В MA2 один файл описывает один режим прибора.
Слоты колёс (`Wheels`) на этом этапе не создаются.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime

from gmagc_common.fixtures import Channel, FixtureProfile, Mode, file_part, has_errors, validate_profile
from gmagc_common.i18n import t
from gmagc_common.ma3_export import ExportError

MA_NAMESPACE = "http://schemas.malighting.de/grandma2/xml/MA"
SCHEMA = "http://schemas.malighting.de/grandma2/xml/2.8.123/MA.xsd"
MODULE = "Main Module"
FULL_24 = "16777215"


@dataclass(frozen=True)
class Ma2Attr:
    attribute: str
    feature: str
    preset: str
    subattribute: str | None = None  # по умолчанию совпадает с атрибутом
    highlight: str | None = None
    snap: bool = False

    @property
    def sub(self) -> str:
        return self.subattribute or self.attribute


_DUMMY = Ma2Attr("DUMMY", "CONTROL", "CONTROL", "NOFEATURE")

# шаблон → атрибут MA2; «{n}» — номер по порядку появления шаблона в режиме. Только атрибуты, подтверждённые
# образцами MA2; остальные шаблоны выгружаются пустым каналом DUMMY, пока нет образца с их атрибутом
_ATTRIBUTES: dict[str, Ma2Attr] = {
    "dimmer": Ma2Attr("DIM", "DIMMER", "DIMMER", highlight="100"),
    "shutter": Ma2Attr("SHUTTER", "SHUTTER", "BEAM", highlight="0"),
    "pan": Ma2Attr("PAN", "POSITION", "POSITION"),
    "tilt": Ma2Attr("TILT", "POSITION", "POSITION"),
    "pan_tilt_speed": Ma2Attr("POSITIONMSPEED", "MSPEED", "CONTROL"),
    "red": Ma2Attr("COLORRGB1", "COLORRGB", "COLOR", highlight="100"),
    "green": Ma2Attr("COLORRGB2", "COLORRGB", "COLOR", highlight="100"),
    "blue": Ma2Attr("COLORRGB3", "COLORRGB", "COLOR", highlight="100"),
    "white": Ma2Attr("COLORRGB5", "COLORRGB", "COLOR", highlight="100"),
    "color_wheel": Ma2Attr("COLOR{n}", "COLOR{n}", "COLOR", highlight="0", snap=True),
    "gobo_wheel": Ma2Attr("GOBO{n}", "GOBO{n}", "GOBO", highlight="0", snap=True),
    "gobo_rotation": Ma2Attr("GOBO{n}_POS", "GOBO{n}", "GOBO"),
    "prism": Ma2Attr("PRISMA{n}", "BEAM{n}", "BEAM"),
    "zoom": Ma2Attr("ZOOM", "FOCUS", "FOCUS"),
    "focus": Ma2Attr("FOCUS", "FOCUS", "FOCUS"),
}
_PHYSICAL = {"PAN": ("-270", "270"), "TILT": ("-135", "135")}


def _spec(template: str, number: int) -> Ma2Attr:
    found = _ATTRIBUTES.get(template)
    if found is None:
        return _DUMMY
    return Ma2Attr(
        found.attribute.format(n=number),
        found.feature.format(n=number),
        found.preset,
        found.subattribute,
        found.highlight,
        found.snap,
    )


def _resolve(mode: Mode) -> list[Ma2Attr]:
    """Атрибут каждого канала режима; нумерованные шаблоны считаются по порядку, повтор остальных подтверждённых — ошибка."""
    seen: dict[str, int] = {}
    specs = []
    for channel in mode.channels:
        seen[channel.template] = seen.get(channel.template, 0) + 1
        found = _ATTRIBUTES.get(channel.template)
        if found is not None and "{n}" not in found.attribute and seen[channel.template] > 1:
            raise ExportError(
                t(
                    "в режиме «{name}» шаблон «{template}» повторяется: MA2 не различит эти каналы",
                    name=mode.name,
                    template=channel.template,
                )
            )
        specs.append(_spec(channel.template, seen[channel.template]))
    return specs


def ma2_file_name(profile: FixtureProfile, mode: Mode) -> str:
    """Имя файла по правилу библиотеки MA: производитель@модель@режим.xml, нижний регистр, всё лишнее — «_»."""

    return f"{file_part(profile.manufacturer)}@{file_part(profile.name)}@{file_part(mode.name)}.xml"


def _sets(function: ET.Element, channel: Channel, spec: Ma2Attr) -> None:
    top = 65535 if channel.bits == 16 else 255
    scale = 256 if channel.bits == 16 else 1
    if channel.ranges:
        for number, item in enumerate(sorted(channel.ranges, key=lambda r: r.start), start=1):
            ET.SubElement(
                function,
                "ChannelSet",
                {
                    "name": item.name or t("Диапазон {number}", number=number),
                    "from_dmx": str(item.start * scale),
                    "to_dmx": str(item.end * scale + (scale - 1)),
                },
            )
        return
    points = [("min", 0)]
    if spec.attribute in _PHYSICAL:
        points.append(("center", top // 2 + 1))
    points.append(("max", top))
    for name, value in points:
        ET.SubElement(function, "ChannelSet", {"name": name, "from_dmx": str(value), "to_dmx": str(value)})


def _channel_type(module: ET.Element, channel: Channel, spec: Ma2Attr) -> None:
    values = {"attribute": spec.attribute, "feature": spec.feature, "preset": spec.preset, "coarse": str(channel.dmx)}
    if channel.bits == 16:
        values["fine"] = str(channel.dmx + 1)
    default = channel.default * (256 if channel.bits == 16 else 1)
    if default:
        values["default"] = str(default)
    if spec.highlight is not None:
        values["highlight_value"] = spec.highlight
    if spec.snap:
        values["snap"] = "true"
    channel_type = ET.SubElement(module, "ChannelType", values)
    low, high = _PHYSICAL.get(spec.attribute, ("0", "1"))
    function = ET.SubElement(
        channel_type,
        "ChannelFunction",
        {
            "from": low if spec.attribute in _PHYSICAL else "0",
            "to": high if spec.attribute in _PHYSICAL else "100",
            "min_dmx_24": "0",
            "max_dmx_24": FULL_24,
            "physfrom": low,
            "physto": high,
            "subattribute": spec.sub,
            "attribute": spec.attribute,
            "feature": spec.feature,
            "preset": spec.preset,
        },
    )
    _sets(function, channel, spec)


def export_ma2(profile: FixtureProfile, mode_index: int = 0, now: datetime | None = None) -> str:
    """XML типа прибора grandMA2 для одного режима профиля; `now` задаёт дату ревизии (для тестов)."""
    issues = validate_profile(profile)
    if has_errors(issues):
        details = "; ".join(f"{i.path}: {i.message}" if i.path else i.message for i in issues if i.error)
        raise ExportError(t("профиль не готов к экспорту: {details}", details=details))
    if not 0 <= mode_index < len(profile.modes):
        raise ExportError(t("нет режима с номером {mode_index}", mode_index=mode_index))
    mode = profile.modes[mode_index]
    specs = _resolve(mode)

    root = ET.Element(
        "MA",
        {
            "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
            "xsi:schemaLocation": f"{MA_NAMESPACE} {SCHEMA}",
            "major_vers": "2",
            "minor_vers": "8",
            "stream_vers": "123",
            "xmlns": MA_NAMESPACE,
        },
    )
    fixture_type = ET.SubElement(root, "FixtureType", {"name": profile.name, "mode": mode.name})
    info = ET.SubElement(fixture_type, "InfoItems")
    stamp = (now or datetime.now()).strftime("%Y-%m-%d")
    ET.SubElement(info, "Info", {"type": "Revision", "date": stamp}).text = t("Создано в GMAGC")
    ET.SubElement(fixture_type, "short_name").text = profile.short_name or profile.name[:16]
    ET.SubElement(fixture_type, "manufacturer").text = profile.manufacturer
    ET.SubElement(fixture_type, "short_manufacturer").text = profile.manufacturer
    modules = ET.SubElement(fixture_type, "Modules")
    moving = any(spec.attribute in ("PAN", "TILT") for spec in specs)
    module = ET.SubElement(
        modules,
        "Module",
        {
            "name": MODULE,
            "class": "Headmover" if moving else "LED",
            "beamtype": "Spot" if moving else "Wash",
            "beam_angle": "25",
            "beam_intensity": "10000",
        },
    )
    body = ET.SubElement(module, "Body")
    ET.SubElement(body, "Size", {"x": "0.2", "y": "0.2", "z": "0.2"})
    for channel, spec in zip(mode.channels, specs, strict=True):
        _channel_type(module, channel, spec)
    instances = ET.SubElement(fixture_type, "Instances")
    ET.SubElement(instances, "Instance", {"module_index": "0", "patch": "1", "locked": "true"})
    ET.SubElement(fixture_type, "Wheels")

    ET.indent(root, space="\t")
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def export_ma2_files(profile: FixtureProfile, now: datetime | None = None) -> list[tuple[str, str]]:
    """Файлы MA2 для всех режимов профиля: (имя файла, XML)."""
    return [(ma2_file_name(profile, mode), export_ma2(profile, index, now)) for index, mode in enumerate(profile.modes)]
