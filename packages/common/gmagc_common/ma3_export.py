"""Экспорт профиля прибора в файл типа прибора grandMA3 (.xml). Только стандартная библиотека.

Структура и значения сняты с реальных файлов MA3 (`k10test.xml`, `shehds@380w beam.xml`, `generic@moving_head.xml`).
Слоты колёс (`Wheels`) на этом этапе не создаются: диапазоны колёс уходят обычными `ChannelSet`.
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime

from gmagc_common.fixtures import Channel, FixtureProfile, Mode, has_errors, validate_profile
from gmagc_common.i18n import t

DATA_VERSION = "2.5.0.3"
GEOMETRY = "Body"
BLACK = "0.0000000000,0.0000000000,0.0000000000,1.0000000000"
WHITE = "1.0000000000,1.0000000000,1.0000000000,1.0000000000"
RED = "1.0000000000,0.0000000000,0.0000000000,1.0000000000"
GREEN = "0.0000000000,1.0000000000,0.0000000000,1.0000000000"
BLUE = "0.0000000000,0.0000000000,1.0000000000,1.0000000000"


class ExportError(ValueError):
    """Профиль нельзя выгрузить: есть ошибки проверки или неоднозначные шаблоны."""


@dataclass(frozen=True)
class AttrDef:
    name: str
    pretty: str
    feature: str  # «Группа.Функция», как в MA3
    special: str | None = None
    special_index: str = "0"
    activation: str | None = None
    main: str | None = None
    unit: str | None = None
    readout: str = "Percent"
    color: str = BLACK


_STATIC = {
    a.name: a
    for a in (
        AttrDef("Dimmer", "Dim", "Dimmer.Dimmer", "Dimmer", unit="LuminousIntensity"),
        AttrDef("Shutter1", "Sh1", "Beam.Beam", "Shutter", "Shutter"),
        AttrDef("Pan", "P", "Position.PanTilt", "PanTilt", "0", "PanTilt", unit="Angle", readout="Physical"),
        AttrDef("Tilt", "T", "Position.PanTilt", "PanTilt", "1", "PanTilt", unit="Angle", readout="Physical"),
        AttrDef("PositionMSpeed", "Pos MSpeed", "Control.Control"),
        AttrDef("ColorRGB_R", "R", "Color.RGB", "ColorRGB", "0", "ColorRGB", unit="ColorComponent", color=RED),
        AttrDef("ColorRGB_G", "G", "Color.RGB", "ColorRGB", "1", "ColorRGB", unit="ColorComponent", color=GREEN),
        AttrDef("ColorRGB_B", "B", "Color.RGB", "ColorRGB", "2", "ColorRGB", unit="ColorComponent", color=BLUE),
        AttrDef("ColorRGB_W", "W", "Color.RGB", "ColorRGB", "12", "ColorRGB", unit="ColorComponent", color=WHITE),
        AttrDef("CTO", "CTO", "Color.Color"),
        AttrDef("Focus1", "Focus", "Focus.Focus", "Focus"),
        AttrDef("Zoom", "Zoom", "Focus.Focus", "Zoom", unit="Angle", readout="Physical"),
        AttrDef("Iris", "Iris", "Beam.Beam"),
        AttrDef("Frost1", "Frost", "Beam.Beam"),
        AttrDef("Control1", "Ctrl1", "Control.Control"),
        AttrDef("NoFeature", "NoFeature", "Control.Control", "NoFeature"),
    )
}

# шаблон → имя атрибута; «{n}» — номер по порядку появления шаблона в режиме (Gobo1, Gobo2…)
_ATTRIBUTE_OF = {
    "dimmer": "Dimmer",
    "shutter": "Shutter1",
    "pan": "Pan",
    "tilt": "Tilt",
    "pan_tilt_speed": "PositionMSpeed",
    "red": "ColorRGB_R",
    "green": "ColorRGB_G",
    "blue": "ColorRGB_B",
    "white": "ColorRGB_W",
    "cto": "CTO",
    "color_wheel": "Color{n}",
    "gobo_wheel": "Gobo{n}",
    "gobo_rotation": "Gobo{n}PosRotate",
    "prism": "Prism{n}",
    "focus": "Focus1",
    "zoom": "Zoom",
    "iris": "Iris",
    "frost": "Frost1",
    "control": "Control1",
    "custom": "NoFeature",
}
_PHYSICAL = {"Pan": ("-270", "270"), "Tilt": ("-135", "135")}
_NUMBERED = re.compile(r"^(Color|Gobo|Prism)(\d+)(PosRotate|Pos)?$")


def _attribute(name: str) -> AttrDef:
    if name in _STATIC:
        return _STATIC[name]
    match = _NUMBERED.match(name)
    if match is None:
        raise ExportError(t("нет определения атрибута {name}", name=name))
    family, number, suffix = match.group(1), int(match.group(2)), match.group(3)
    index = str(number - 1)
    if family == "Color":
        return AttrDef(name, f"C{number}", "Color.Color", "Color", index, readout="Physical")
    if family == "Prism":
        return AttrDef(name, f"Prism{number}", "Beam.Beam", "Prism", index, "Prism")
    if suffix is None:
        return AttrDef(name, f"G{number}", "Gobo.Gobo", "Gobo", index, f"Gobo{number}", readout="Physical")
    if suffix == "Pos":
        return AttrDef(
            name, f"G{number} <>", "Gobo.Gobo", "GoboPos", index, f"Gobo{number}Pos", unit="Angle", readout="Physical"
        )
    return AttrDef(
        name,
        "Rotate",
        "Gobo.Gobo",
        "GoboPosRotate",
        index,
        f"Gobo{number}Pos",
        main=f"Gobo{number}Pos",
        unit="AngularSpeed",
        readout="Physical",
    )


def _dependencies(name: str) -> list[str]:
    """Атрибут вместе с тем, на который он ссылается (вращение гобо → положение гобо)."""
    attribute = _attribute(name)
    return [attribute.main, name] if attribute.main else [name]


def fixture_guid(profile_id: str) -> str:
    """Guid типа: 16 байт hex через пробелы; из uuid профиля, поэтому повторный экспорт даёт тот же тип."""
    if re.fullmatch(r"[0-9a-fA-F]{32}", profile_id):
        raw = bytes.fromhex(profile_id)
    else:
        raw = hashlib.md5(profile_id.encode("utf-8")).digest()  # только стабильный идентификатор, не защита
    return " ".join(f"{byte:02X}" for byte in raw)


def _hex24(value: int, bits: int) -> str:
    """Грубый байт 0–255 в 24-битное значение MA: 8 бит повторяются («010101»), 16 бит дополняются нулями."""
    byte = f"{value & 0xFF:02X}"
    return byte * 3 if bits == 8 else byte + "0000"


def _resolve_attributes(mode: Mode) -> list[str]:
    """Атрибут каждого канала режима; нумерованные шаблоны считаются по порядку, повторы остальных — ошибка."""
    seen: dict[str, int] = {}
    names = []
    for channel in mode.channels:
        template = _ATTRIBUTE_OF.get(channel.template, _ATTRIBUTE_OF["custom"])
        seen[channel.template] = seen.get(channel.template, 0) + 1
        if "{n}" not in template and seen[channel.template] > 1:
            raise ExportError(
                t(
                    "в режиме «{name}» шаблон «{template}» повторяется: MA3 не различит эти каналы",
                    name=mode.name,
                    template=channel.template,
                )
            )
        names.append(template.format(n=seen[channel.template]))
    return names


def _channel_functions(parent: ET.Element, channel: Channel, attribute: str) -> None:
    logical = ET.SubElement(parent, "LogicalChannel", {"Attribute": attribute})
    function_attributes = {"Attribute": attribute, "Default": _hex24(channel.default, channel.bits)}
    if attribute in _PHYSICAL:
        function_attributes["PhysicalFrom"], function_attributes["PhysicalTo"] = _PHYSICAL[attribute]
    function = ET.SubElement(logical, "ChannelFunction", function_attributes)
    ranges = sorted(channel.ranges, key=lambda r: r.start)
    if ranges and ranges[0].start > 0:
        ET.SubElement(function, "ChannelSet")  # значения ниже первого диапазона: набор с нуля без имени
    for item in ranges:
        set_attributes = {}
        if item.name:
            set_attributes["Name"] = item.name
        if item.start > 0:
            set_attributes["DMXFrom"] = _hex24(item.start, channel.bits)
        ET.SubElement(function, "ChannelSet", set_attributes)


def _dmx_mode(parent: ET.Element, mode: Mode, attributes: list[str]) -> None:
    element = ET.SubElement(parent, "DMXMode", {"Name": mode.name, "Geometry": GEOMETRY, "XYZ": "No", "DiveInto": "Yes"})
    channels = ET.SubElement(element, "DMXChannels")
    for channel, attribute in zip(mode.channels, attributes, strict=True):
        attributes_of_channel = {"Coarse": str(channel.dmx)}
        if channel.bits == 16:
            attributes_of_channel["Fine"] = str(channel.dmx + 1)
        attributes_of_channel["DefaultChannelFunction"] = f"{attribute}.{attribute} 1"
        attributes_of_channel["Geometry"] = GEOMETRY
        dmx_channel = ET.SubElement(channels, "DMXChannel", attributes_of_channel)
        _channel_functions(dmx_channel, channel, attribute)
    for name in ("Relations", "FTMacros", "SoftwareVersions", "FTPresets"):
        ET.SubElement(element, name)


def _attribute_definitions(parent: ET.Element, names: list[str]) -> None:
    definitions = ET.SubElement(parent, "AttributeDefinitions")
    ET.SubElement(definitions, "DeactivationGroups")
    chosen = [_attribute(name) for name in names]
    activation_groups = ET.SubElement(definitions, "ActivationGroups")
    for group in dict.fromkeys(a.activation for a in chosen if a.activation):
        ET.SubElement(activation_groups, "ActivationGroup", {"Name": group})
    feature_groups = ET.SubElement(definitions, "FeatureGroups")
    groups: dict[str, list[str]] = {}
    for attribute in chosen:
        group, feature = attribute.feature.split(".")
        if feature not in groups.setdefault(group, []):
            groups[group].append(feature)
    for group, features in groups.items():
        element = ET.SubElement(feature_groups, "FeatureGroup", {"Name": group})
        for feature in features:
            ET.SubElement(element, "Feature", {"Name": feature})
    attributes = ET.SubElement(definitions, "Attributes")
    for attribute in chosen:
        values = {"Name": attribute.name, "Pretty": attribute.pretty}
        if attribute.main:
            values["MainAttribute"] = attribute.main
        if attribute.activation:
            values["ActivationGroup"] = attribute.activation
        values["Feature"] = attribute.feature
        if attribute.special:
            values["Special"] = attribute.special
        values["SpecialIndex"] = attribute.special_index
        if attribute.unit:
            values["PhysicalUnit"] = attribute.unit
        values["Color"] = attribute.color
        values["NaturalReadout"] = attribute.readout
        values["EncoderResolution"] = "Coarse"
        ET.SubElement(attributes, "Attribute", values)


def export_ma3(profile: FixtureProfile, now: datetime | None = None) -> str:
    """XML типа прибора grandMA3 для профиля; `now` задаёт дату ревизии (для тестов)."""
    issues = validate_profile(profile)
    if has_errors(issues):
        details = "; ".join(f"{i.path}: {i.message}" if i.path else i.message for i in issues if i.error)
        raise ExportError(t("профиль не готов к экспорту: {details}", details=details))
    resolved = [_resolve_attributes(mode) for mode in profile.modes]
    used = list(dict.fromkeys(dep for names in resolved for name in names for dep in _dependencies(name)))

    root = ET.Element("GMA3", {"DataVersion": DATA_VERSION})
    fixture_type = ET.SubElement(
        root,
        "FixtureType",
        {
            "Name": profile.name,
            "Guid": fixture_guid(profile.id),
            "Color": WHITE,
            "Source": "grandMA3",
            "ShortName": profile.short_name or profile.name[:16],
            "Description": t("Создано в GMAGC"),
            "Manufacturer": profile.manufacturer,
        },
    )
    _attribute_definitions(fixture_type, used)
    ET.SubElement(fixture_type, "Wheels")
    physical = ET.SubElement(fixture_type, "PhysicalDescriptions")
    for name in ("Emitters", "CRIs", "FTFilters", "PhysicalProperties", "ColorSpaceCollect", "GamutCollect"):
        ET.SubElement(physical, name)
    models = ET.SubElement(fixture_type, "Models")
    ET.SubElement(models, "Model", {"Name": GEOMETRY, "Length": "0.2000", "Width": "0.2000", "Height": "0.2000"})
    geometries = ET.SubElement(fixture_type, "Geometries")
    ET.SubElement(geometries, "Geometry", {"Name": GEOMETRY, "Model": GEOMETRY})
    modes = ET.SubElement(fixture_type, "DMXModes")
    for mode, attributes in zip(profile.modes, resolved, strict=True):
        _dmx_mode(modes, mode, attributes)
    revisions = ET.SubElement(fixture_type, "Revisions")
    stamp = (now or datetime.now()).strftime("%d.%m.%Y %H:%M:%S")
    ET.SubElement(revisions, "Revision", {"Text": t("Создано в GMAGC"), "Date": stamp, "UserID": "0"})

    ET.indent(root, space="    ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"
