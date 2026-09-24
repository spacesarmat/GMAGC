"""Разбор таблицы DMX по результату распознавания текста (OCR): режимы, каналы, диапазоны значений.

Вход — прямоугольники текста с координатами (любой движок OCR, см. `OcrItem`). Раскладка таблицы восстанавливается
по геометрии, а не по порядку строк: строки таблицы начинаются с метки «Channel N», колонки «функция» и «описание»
отделяются по разрыву между левыми краями текстов. Разбор устойчив к небольшому наклону снимка, но не к сильной
перспективе: неуверенные места помечаются на экране проверки телефона.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from gmagc_common.fixtures import Range
from gmagc_common.scan_draft import (
    ENGINE_LOCAL,
    WARN_NO_TABLE,
    DraftChannel,
    DraftMode,
    ScanDraft,
    fine_base_name,
    guess_template,
    merge_channels,
    parse_range_line,
)

_LABEL = re.compile(r"^\s*ch(?:annel)?\.?\s*(\d{1,3})\s*$", re.IGNORECASE)
_HEADING = re.compile(r"dmx\s*channel\s*[:：]?\s*(\d+)\s*ch", re.IGNORECASE)
_ELLIPSIS = re.compile(r"^[\s.·•…‥:_-]{2,}$")  # строка «......» между каналами: пропущенные каналы такие же
_NAME_NUMBER = re.compile(r"^(\D*?)(\d+)(\D*)$")
_HEADER_WORDS = {"serial", "number", "function", "illustrate", "description", "channel", "value", "serial number"}
ORPHAN = 0  # диапазоны над первой меткой страницы: продолжение последнего канала предыдущей страницы


@dataclass(frozen=True)
class OcrItem:
    """Кусок распознанного текста и его прямоугольник на снимке (в пикселях)."""

    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    score: float = 1.0

    @property
    def yc(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def height(self) -> float:
        return max(self.y1 - self.y0, 1.0)


def items_from_dict(data: dict) -> list[OcrItem]:
    """Элементы из словаря `{"items": [{"box": [[x, y] × 4], "text": …, "score": …}]}` (формат тестовых снимков)."""
    items = []
    for raw in data.get("items", []):
        xs = [point[0] for point in raw["box"]]
        ys = [point[1] for point in raw["box"]]
        items.append(OcrItem(min(xs), min(ys), max(xs), max(ys), str(raw["text"]), float(raw.get("score", 1.0))))
    return items


def items_from_rapidocr(result) -> list[OcrItem]:
    """Элементы из ответа RapidOCR: список `[box, text, score]` (или None, если текста нет)."""
    items = []
    for box, text, score in result or []:
        xs = [point[0] for point in box]
        ys = [point[1] for point in box]
        items.append(OcrItem(float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys)), str(text), float(score)))
    return items


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[len(ordered) // 2] if ordered else 0.0


def _split_sections(items: list[OcrItem]) -> list[tuple[str, list[OcrItem]]]:
    """Делит страницу по заголовкам «N.DMX Channel:9CH»; всё над первым заголовком — страница без заголовка (имя пусто)."""
    headings = sorted(((i.yc, f"{m.group(1)}CH") for i in items if (m := _HEADING.search(i.text))), key=lambda h: h[0])
    ordered = sorted(items, key=lambda i: (i.yc, i.x0))
    if not headings:
        return [("", ordered)]
    sections: list[tuple[str, list[OcrItem]]] = []
    above = [i for i in ordered if i.yc < headings[0][0] - 1]
    if above:
        sections.append(("", above))
    for index, (y, name) in enumerate(headings):
        end = headings[index + 1][0] if index + 1 < len(headings) else float("inf")
        sections.append((name, [i for i in ordered if y - 1 <= i.yc < end and not _HEADING.search(i.text)]))
    return sections


def _parse_section(items: list[OcrItem], require_header: bool = False) -> list[DraftChannel]:
    body = [i for i in items if i.text.strip().lower() not in _HEADER_WORDS]
    labels = sorted(((i, int(m.group(1))) for i in body if (m := _LABEL.match(i.text))), key=lambda p: p[0].yc)
    label_ids = {id(i) for i, _ in labels}
    dots = [i for i in body if id(i) not in label_ids and _ELLIPSIS.match(i.text)]
    dot_ids = {id(i) for i in dots}
    others = [i for i in body if id(i) not in label_ids and id(i) not in dot_ids]
    if not labels and not any(parse_range_line(i.text) for i in others):
        return []
    if require_header and not labels and not any(i.text.strip().lower() in {"illustrate", "function"} for i in items):
        return []
    tolerance = max(0.6 * _median([i.height for i in body]), 4.0)
    label_right = _median([i.x1 for i, _ in labels]) if labels else min((i.x0 for i in others), default=0.0)
    content = [i for i in others if i.x0 > label_right - 4]
    # колонки «функция» и «описание»: самый большой разрыв между левыми краями текстов, не похожих на диапазон
    plain = sorted({round(i.x0) for i in content if parse_range_line(i.text) is None})
    width = max((i.x1 for i in body), default=1.0)
    split = None
    if len(plain) >= 2:
        gap, position = max((b - a, (a + b) / 2) for a, b in zip(plain, plain[1:], strict=False))
        if gap >= 0.04 * width:
            split = position

    bands: list[tuple[int, float, float]] = []  # (номер канала, верх, низ)
    for index, (label, number) in enumerate(labels):
        top = label.yc - tolerance
        bottom = labels[index + 1][0].yc - tolerance if index + 1 < len(labels) else float("inf")
        bands.append((number, top, bottom))
    if labels:
        bands.insert(0, (ORPHAN, float("-inf"), bands[0][1]))
    else:
        bands = [(ORPHAN, float("-inf"), float("inf"))]

    channels: list[DraftChannel] = []
    gaps: set[int] = set()  # каналы, после которых в таблице стоит строка «......»
    for number, top, bottom in bands:
        band = [i for i in content if top <= i.yc < bottom]
        if number != ORPHAN and any(top <= d.yc < bottom for d in dots):
            gaps.add(number)
        label_y = next((lab.yc for lab, n in labels if n == number), None)
        ranges: list[Range] = []
        used: set[int] = set()
        range_items = [(i, parse_range_line(i.text)) for i in band]
        for item, parsed in sorted((p for p in range_items if p[1] is not None), key=lambda p: p[0].yc):
            name = parsed.name
            extras = [
                o
                for o in band
                if id(o) not in used
                and parse_range_line(o.text) is None
                and abs(o.yc - item.yc) <= tolerance
                and o.x0 >= item.x1 - 6
            ]
            for extra in sorted(extras, key=lambda o: o.x0):
                name = f"{name} {extra.text.strip()}".strip()
                used.add(id(extra))
            ranges.append(Range(parsed.start, parsed.end, name))
        text_items = [i for i in band if parse_range_line(i.text) is None and id(i) not in used]
        function_items = [i for i in text_items if split is None or i.x0 < split]
        description_items = [i for i in text_items if split is not None and i.x0 >= split]
        first_line = [i for i in function_items if label_y is None or abs(i.yc - label_y) <= 1.2 * tolerance]
        name = " ".join(i.text.strip() for i in sorted(first_line, key=lambda i: (i.yc, i.x0)))
        rest = [i for i in function_items if i not in first_line] + description_items
        note = " ".join(i.text.strip() for i in sorted(rest, key=lambda i: (i.yc, i.x0)))
        if number == ORPHAN and not ranges:
            continue
        fallback = f"Channel {number}" if number else ""
        channels.append(
            DraftChannel(number, name or fallback, guess_template(name), 8, tuple(ranges), note[:300], 1.0 if name else 0.6)
        )
    merged = list(merge_channels((), tuple(channels)))
    return _fold_fine_channels(_fill_gaps(merged, gaps))


def _numbered_names(first: str, last: str, count: int) -> list[str] | None:
    """«1 Dimming» … «18 Dimming» → названия промежуточных каналов, если число в названиях растёт на единицу."""
    a, b = _NAME_NUMBER.match(first), _NAME_NUMBER.match(last)
    if not a or not b or a.group(1) != b.group(1) or a.group(3) != b.group(3):
        return None
    start, end = int(a.group(2)), int(b.group(2))
    if end - start != count + 1:
        return None
    return [f"{a.group(1)}{start + step}{a.group(3)}" for step in range(1, count + 1)]


def _fill_gaps(channels: list[DraftChannel], gaps: set[int]) -> list[DraftChannel]:
    """Между каналами, разделёнными строкой «......», добавляет пропущенные: они повторяют канал перед строкой."""
    result: list[DraftChannel] = []
    for index, channel in enumerate(channels):
        result.append(channel)
        following = channels[index + 1] if index + 1 < len(channels) else None
        if channel.dmx not in gaps or following is None or following.dmx - channel.dmx < 2:
            continue
        count = following.dmx - channel.dmx - 1
        names = _numbered_names(channel.name, following.name, count) or [channel.name] * count
        for step, name in enumerate(names, start=1):
            result.append(
                replace(
                    channel,
                    dmx=channel.dmx + step,
                    name=name,
                    template=guess_template(name) if name != channel.name else channel.template,
                    note="",
                    # добавлен по строке «......»: на экране проверки помечается «?»
                    confidence=min(channel.confidence, 0.8),
                )
            )
    return result


def _fold_fine_channels(channels: list[DraftChannel]) -> list[DraftChannel]:
    """«Pan» + «Pan fine» → один 16-битный канал «Pan» (адрес второго байта отдельно не описывается)."""
    result: list[DraftChannel] = []
    for channel in channels:
        base = fine_base_name(channel.name)
        previous = result[-1] if result else None
        if base and previous and previous.name.strip().lower() == base.lower() and previous.bits == 8:
            result[-1] = replace(previous, bits=16)
            continue
        result.append(channel)
    return result


def parse_tables(items: list[OcrItem], engine: str = ENGINE_LOCAL) -> ScanDraft:
    """Черновик режимов и каналов по тексту одной страницы."""
    modes = []
    sections = _split_sections(items)
    for index, (name, section) in enumerate(sections):
        # над первым заголовком без таблицы — обычный текст страницы (меню, характеристики), а не продолжение таблицы
        channels = _parse_section(section, require_header=(index == 0 and not name and len(sections) > 1))
        if channels:
            modes.append(DraftMode(name, tuple(channels)))
    if not modes:
        return ScanDraft((), (WARN_NO_TABLE,), engine)
    return ScanDraft(tuple(modes), (), engine)
