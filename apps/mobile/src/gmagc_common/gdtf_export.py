"""Экспорт профиля прибора в GDTF (.gdtf): основной формат обмена для grandMA3 (только стандартная библиотека).

Файл — ZIP: `description.xml` (DataVersion 1.2, все режимы профиля) и `wheels/*.png` с картинками гобо. Атрибуты и признаки
берутся из стандартного списка GDTF; каналы без подходящего атрибута (управление, свой канал) получают `Control(n)`.
Слот колеса — по диапазону канала «колесо гобо», как и в экспорте MA2/MA3.
"""

from __future__ import annotations

import io
import re
import uuid
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from gmagc_common.fixtures import (
    GOBO_THUMB_SIDE,
    Channel,
    FixtureProfile,
    Mode,
    ProfileError,
    file_part,
    gobo_rgba,
    has_errors,
    has_gobo_wheel,
    validate_profile,
)
from gmagc_common.i18n import t
from gmagc_common.ma3_export import ExportError
from gmagc_common.png_lite import rgba_to_png

DATA_VERSION = "1.2"
BODY = "Body"
_FORBIDDEN = re.compile(r"[^ \"#%'()*+\-/0-9:;<=>@A-Z_`a-z\u0080-\U0010ffff]")  # приложение C спецификации: допустимые знаки


@dataclass(frozen=True)
class Attr:
    name: str
    pretty: str
    feature: str  # «Группа.Признак»
    unit: str = ""
    group: str = ""  # группа активации


_ATTRIBUTES: dict[str, Attr] = {
    "dimmer": Attr("Dimmer", "Dim", "Dimmer.Dimmer", "LuminousIntensity"),
    "shutter": Attr("Shutter{n}", "Sh{n}", "Beam.Beam"),
    "pan": Attr("Pan", "P", "Position.PanTilt", "Angle", "PanTilt"),
    "tilt": Attr("Tilt", "T", "Position.PanTilt", "Angle", "PanTilt"),
    "pan_tilt_speed": Attr("PositionMSpeed", "Pos MSpeed", "Control.Control"),
    "red": Attr("ColorAdd_R", "R", "Color.RGB", "ColorComponent", "ColorRGB"),
    "green": Attr("ColorAdd_G", "G", "Color.RGB", "ColorComponent", "ColorRGB"),
    "blue": Attr("ColorAdd_B", "B", "Color.RGB", "ColorComponent", "ColorRGB"),
    "white": Attr("ColorAdd_W", "White", "Color.RGB", "ColorComponent", "ColorRGB"),
    "cto": Attr("CTO", "CTO", "Color.Color", "Temperature"),
    "color_wheel": Attr("Color{n}", "C{n}", "Color.Color", "", "ColorRGB"),
    "gobo_wheel": Attr("Gobo{n}", "G{n}", "Gobo.Gobo", "", "Gobo{n}"),
    "gobo_rotation": Attr("Gobo{n}Pos", "G{n} <>", "Gobo.Gobo", "Angle", "Gobo{n}Pos"),
    "prism": Attr("Prism{n}", "Prism{n}", "Beam.Beam", "", "Prism"),
    "focus": Attr("Focus{n}", "Focus{n}", "Focus.Focus"),
    "zoom": Attr("Zoom", "Zoom", "Focus.Focus", "Angle"),
    "iris": Attr("Iris", "Iris", "Beam.Beam"),
    "frost": Attr("Frost{n}", "Frost{n}", "Beam.Beam"),
    "control": Attr("Control{n}", "Ctrl{n}", "Control.Control"),
}
_PHYSICAL = {"Pan": ("-270", "270"), "Tilt": ("-135", "135")}


def gdtf_file_name(profile: FixtureProfile) -> str:
    """Имя файла по правилу GDTF: Производитель@Модель.gdtf (нижний регистр, лишнее — «_»)."""
    return f"{file_part(profile.manufacturer)}@{file_part(profile.name)}.gdtf"


def _name(text: str, fallback: str = "") -> str:
    """Значение типа Name: запрещённые знаки первых 128 символов (точка, запятая, скобки [] и др.) заменяются на «_»."""
    cleaned = _FORBIDDEN.sub("_", text).strip()
    return cleaned or fallback


def fixture_type_id(profile_id: str) -> str:
    """GUID типа (8-4-4-4-12): из uuid профиля, поэтому повторный экспорт даёт тот же тип."""
    try:
        return str(uuid.UUID(profile_id)).upper()
    except ValueError:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, "gmagc:" + profile_id)).upper()


def _resolve(mode: Mode) -> list[Attr]:
    """Атрибут GDTF каждого канала режима; нумерованные считаются по порядку, повтор остальных — ошибка."""
    seen: dict[str, int] = {}
    result = []
    for channel in mode.channels:
        template = channel.template if channel.template in _ATTRIBUTES else "control"
        family = template
        seen[family] = seen.get(family, 0) + 1
        found = _ATTRIBUTES[template]
        if "{n}" not in found.name and seen[family] > 1:
            raise ExportError(
                t(
                    "в режиме «{name}» шаблон «{template}» повторяется: GDTF не различит эти каналы",
                    name=mode.name,
                    template=channel.template,
                )
            )
        number = seen[family]
        result.append(
            Attr(
                found.name.format(n=number),
                found.pretty.format(n=number),
                found.feature,
                found.unit,
                found.group.format(n=number),
            )
        )
    return result


def _dmx(value: int, width: int) -> str:
    return f"{value}/{width}"


def _wheel_definitions(
    profile: FixtureProfile, resolved: list[list[Attr]]
) -> tuple[dict[str, Channel], dict[tuple[int, int], str]]:
    """Колёса типа (имя → канал-образец) и имя колеса каждого канала «колесо гобо»; одинаковые колёса режимов — одно."""
    definitions: dict[str, Channel] = {}
    keys: dict[tuple, str] = {}
    names: dict[tuple[int, int], str] = {}
    for mode_index, (mode, attributes) in enumerate(zip(profile.modes, resolved, strict=True)):
        for channel_index, (channel, attribute) in enumerate(zip(mode.channels, attributes, strict=True)):
            if not has_gobo_wheel(channel):
                continue
            key = tuple((r.name, r.gobo.path if r.gobo else "") for r in sorted(channel.ranges, key=lambda r: r.start))
            if key not in keys:
                name, number = attribute.name, 1
                while name in definitions:
                    number += 1
                    name = f"{attribute.name}_{number}"
                keys[key] = name
                definitions[name] = channel
            names[(mode_index, channel_index)] = keys[key]
    return definitions, names


def _media_stem(path: str) -> str:
    return path.rsplit("/", 1)[-1].rsplit(".", 1)[0]


def _picture(gobo, pictures: Mapping[str, bytes] | None) -> bytes | None:
    """PNG слота: картинка с ПК (крупнее) или миниатюра из профиля; None — картинки нет."""
    if pictures and gobo.path in pictures:
        return pictures[gobo.path]
    try:
        rgba = gobo_rgba(gobo)
    except ProfileError as error:
        raise ExportError(str(error)) from error
    return None if rgba is None else rgba_to_png(GOBO_THUMB_SIDE, GOBO_THUMB_SIDE, rgba, circle=True)


def _feature_groups(parent: ET.Element, attributes: list[Attr]) -> None:
    groups: dict[str, list[str]] = {}
    for attribute in attributes:
        group, _, feature = attribute.feature.partition(".")
        features = groups.setdefault(group, [])
        if feature not in features:
            features.append(feature)
    element = ET.SubElement(parent, "FeatureGroups")
    for group, features in groups.items():
        node = ET.SubElement(element, "FeatureGroup", {"Name": group, "Pretty": group})
        for feature in features:
            ET.SubElement(node, "Feature", {"Name": feature})


def _attribute_definitions(parent: ET.Element, attributes: list[Attr]) -> None:
    definitions = ET.SubElement(parent, "AttributeDefinitions")  # порядок детей задан спецификацией
    groups = list(dict.fromkeys(a.group for a in attributes if a.group))
    activation = ET.SubElement(definitions, "ActivationGroups")
    for group in groups:
        ET.SubElement(activation, "ActivationGroup", {"Name": group})
    _feature_groups(definitions, attributes)
    element = ET.SubElement(definitions, "Attributes")
    for attribute in attributes:
        values = {"Name": attribute.name, "Pretty": attribute.pretty}
        if attribute.group:
            values["ActivationGroup"] = attribute.group
        values["Feature"] = attribute.feature
        if attribute.unit:
            values["PhysicalUnit"] = attribute.unit
        ET.SubElement(element, "Attribute", values)


def _wheels(
    parent: ET.Element, definitions: dict[str, Channel], external: Mapping[str, bytes] | None, files: dict[str, bytes]
) -> None:
    """Колёса гобо: слот на каждый диапазон; картинка слота — файл в `wheels/`, в XML имя без расширения."""
    wheels = ET.SubElement(parent, "Wheels")
    for wheel_name, channel in definitions.items():
        wheel = ET.SubElement(wheels, "Wheel", {"Name": wheel_name})
        for number, item in enumerate(sorted(channel.ranges, key=lambda r: r.start), start=1):
            values = {"Name": _name(item.name or (item.gobo.name if item.gobo else ""), f"Slot {number}")}
            if item.gobo is not None:
                stem = _media_stem(item.gobo.path)
                png = _picture(item.gobo, external)
                if png is not None:
                    files[stem] = png
                    values["MediaFileName"] = stem
            ET.SubElement(wheel, "Slot", values)


def _channel(parent: ET.Element, channel: Channel, attribute: Attr, wheel: str) -> None:
    width = 2 if channel.bits == 16 else 1
    scale = 256 if channel.bits == 16 else 1
    offsets = ",".join(str(channel.dmx + step) for step in range(width))
    dmx_channel = ET.SubElement(parent, "DMXChannel", {"Offset": offsets, "Geometry": BODY})
    logical = ET.SubElement(dmx_channel, "LogicalChannel", {"Attribute": attribute.name})
    values = {"Attribute": attribute.name, "DMXFrom": _dmx(0, width)}
    if channel.default:
        values["Default"] = _dmx(channel.default * scale, width)
    if attribute.name in _PHYSICAL:
        values["PhysicalFrom"], values["PhysicalTo"] = _PHYSICAL[attribute.name]
    if wheel:
        values["Wheel"] = wheel
    function = ET.SubElement(logical, "ChannelFunction", values)
    ranges = sorted(channel.ranges, key=lambda r: r.start)
    if ranges and ranges[0].start > 0 and not wheel:
        ET.SubElement(function, "ChannelSet", {"DMXFrom": _dmx(0, width)})  # значения ниже первого диапазона
    for number, item in enumerate(ranges, start=1):
        start = 0 if wheel and number == 1 else item.start  # у колеса слот 1 покрывает и значения ниже первого диапазона
        set_values = {}
        name = _name(item.name or (item.gobo.name if item.gobo else ""), "")
        if name:
            set_values["Name"] = name
        set_values["DMXFrom"] = _dmx(start * scale, width)
        if wheel:
            set_values["WheelSlotIndex"] = str(number)
        ET.SubElement(function, "ChannelSet", set_values)


def export_gdtf(profile: FixtureProfile, now: datetime | None = None, pictures: Mapping[str, bytes] | None = None) -> bytes:
    """Файл .gdtf (ZIP) для профиля; `pictures` — PNG слотов по `Gobo.path` (с ПК, крупнее миниатюр), `now` — для тестов."""
    issues = validate_profile(profile)
    if has_errors(issues):
        details = "; ".join(f"{i.path}: {i.message}" if i.path else i.message for i in issues if i.error)
        raise ExportError(t("профиль не готов к экспорту: {details}", details=details))
    resolved = [_resolve(mode) for mode in profile.modes]
    used = list({a.name: a for attributes in resolved for a in attributes}.values())
    definitions, wheel_names = _wheel_definitions(profile, resolved)
    stamp = now or datetime.now()

    root = ET.Element("GDTF", {"DataVersion": DATA_VERSION})
    fixture_type = ET.SubElement(
        root,
        "FixtureType",
        {
            "Name": _name(profile.name, "Fixture"),
            "ShortName": profile.short_name or profile.name[:16],
            "LongName": profile.name,
            "Manufacturer": profile.manufacturer,
            "Description": t("Создано в GMAGC"),
            "FixtureTypeID": fixture_type_id(profile.id),
            "CanHaveChildren": "No",
        },
    )
    _attribute_definitions(fixture_type, used)
    files: dict[str, bytes] = {}
    _wheels(fixture_type, definitions, pictures, files)
    models = ET.SubElement(fixture_type, "Models")
    ET.SubElement(models, "Model", {"Name": BODY, "Length": "0.2", "Width": "0.2", "Height": "0.2", "PrimitiveType": "Cube"})
    geometries = ET.SubElement(fixture_type, "Geometries")
    body = ET.SubElement(geometries, "Geometry", {"Name": BODY, "Model": BODY})
    moving = any(a.name in ("Pan", "Tilt") for attributes in resolved for a in attributes)
    ET.SubElement(body, "Beam", {"Name": "Beam", "Model": BODY, "BeamType": "Spot" if moving else "Wash"})
    modes = ET.SubElement(fixture_type, "DMXModes")
    for mode_index, (mode, attributes) in enumerate(zip(profile.modes, resolved, strict=True)):
        element = ET.SubElement(modes, "DMXMode", {"Name": _name(mode.name, f"Mode {mode_index + 1}"), "Geometry": BODY})
        channels = ET.SubElement(element, "DMXChannels")
        for channel_index, (channel, attribute) in enumerate(zip(mode.channels, attributes, strict=True)):
            _channel(channels, channel, attribute, wheel_names.get((mode_index, channel_index), ""))
        ET.SubElement(element, "Relations")
    revisions = ET.SubElement(fixture_type, "Revisions")
    ET.SubElement(
        revisions, "Revision", {"Text": t("Создано в GMAGC"), "Date": stamp.strftime("%Y-%m-%dT%H:%M:%S"), "UserID": "0"}
    )

    ET.indent(root, space="    ")
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n").encode("utf-8")
    buffer = io.BytesIO()
    moment = (max(stamp.year, 1980), stamp.month, stamp.day, stamp.hour, stamp.minute, stamp.second)
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in [("description.xml", xml), *((f"wheels/{stem}.png", png) for stem, png in files.items())]:
            info = zipfile.ZipInfo(name, moment)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return buffer.getvalue()
