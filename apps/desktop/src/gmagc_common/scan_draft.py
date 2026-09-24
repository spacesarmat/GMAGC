"""Черновик каналов, распознанный на странице инструкции: модель, правила угадывания шаблона и диапазонов.

Только стандартная библиотека: пакет без изменений копируется в приложения (scripts/sync_common.py).
Черновик ничего не меняет в профиле: телефон показывает его на экране проверки, пользователь выбирает, что добавить.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from gmagc_common.fixtures import Range

ENGINE_LOCAL = "local"
ENGINE_CLOUD = "cloud"

_DASH = "-–—‒~"
_RANGE = re.compile(rf"^\s*(\d{{1,3}})\s*[{_DASH}]+\s*(\d{{1,3}})\s*[:：;.]?\s*(.*)$")
_FINE = re.compile(r"^(.*?)\s*[\(\[]?\s*(?:fine|lsb|16\s*-?\s*bit)\s*[\)\]]?\s*$", re.IGNORECASE)
_RGBW = {"r": "red", "g": "green", "b": "blue", "w": "white"}
_RGBW_LETTER = re.compile(r"^([rgbw])\s*(?:dimm|dim\b|intens|$)")
_RGBW_WORD = re.compile(r"^(red|green|blue|white)\b")


def parse_range_line(text: str) -> Range | None:
    """Строка вида «0--5:null;» или «18--21: effect 4» как диапазон значений DMX; обычный текст — None."""
    match = _RANGE.match(text or "")
    if match is None:
        return None
    start, end = int(match.group(1)), int(match.group(2))
    if not 0 <= start <= end <= 255:
        return None
    return Range(start, end, match.group(3).strip(" ;.,"))


def guess_template(name: str) -> str:
    """Шаблон канала по его названию в инструкции (не угадали — «custom»)."""
    text = (name or "").strip().lower()
    if not text:
        return "custom"
    letter = _RGBW_LETTER.match(text)
    if letter:
        return _RGBW[letter.group(1)]
    word = _RGBW_WORD.match(text)
    if word:
        return word.group(1)
    checks = (
        (r"(pan|tilt).*(speed|time)|(speed|time).*(pan|tilt)", "pan_tilt_speed"),
        (r"gobo.*(rot|index|spin)", "gobo_rotation"),
        (r"gobo", "gobo_wheel"),
        (r"colou?r\s*wheel|wheel.*colou?r", "color_wheel"),
        (r"prism", "prism"),
        (r"\biris\b", "iris"),
        (r"frost", "frost"),
        (r"zoom", "zoom"),
        (r"focus", "focus"),
        (r"\bcto\b|colou?r\s*temp", "cto"),
        (r"\bpan\b", "pan"),
        (r"\btilt\b", "tilt"),
        (r"strob|shutter", "shutter"),
        (r"dimm|intens|brightness|master", "dimmer"),
        (r"macro|program|auto|speed|reset|function|mode|control", "control"),
    )
    for pattern, template in checks:
        if re.search(pattern, text):
            return template
    return "custom"


def fine_base_name(name: str) -> str | None:
    """«Pan fine» → «Pan»: название основного канала, если это тонкий байт 16-битного канала; иначе None."""
    match = _FINE.match((name or "").strip())
    if match is None or not match.group(1).strip():
        return None
    return match.group(1).strip()


@dataclass(frozen=True)
class DraftChannel:
    dmx: int
    name: str
    template: str
    bits: int = 8
    ranges: tuple[Range, ...] = ()
    note: str = ""  # пояснение из инструкции, которое не удалось превратить в диапазоны
    confidence: float = 1.0

    def to_dict(self) -> dict:
        return {
            "dmx": self.dmx,
            "name": self.name,
            "template": self.template,
            "bits": self.bits,
            "ranges": [{"start": r.start, "end": r.end, "name": r.name} for r in self.ranges],
            "note": self.note,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: dict) -> DraftChannel:
        try:
            return cls(
                int(data["dmx"]),
                str(data["name"]),
                str(data.get("template", "custom")),
                int(data.get("bits", 8)),
                tuple(Range(int(r["start"]), int(r["end"]), str(r["name"])) for r in data.get("ranges", [])),
                str(data.get("note", "")),
                float(data.get("confidence", 1.0)),
            )
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise ValueError(f"неверный канал черновика: {error!r}") from error


@dataclass(frozen=True)
class DraftMode:
    name: str  # например «9CH»; пустое имя — страница без заголовка (продолжение предыдущей)
    channels: tuple[DraftChannel, ...] = ()


@dataclass(frozen=True)
class ScanDraft:
    modes: tuple[DraftMode, ...] = ()
    warnings: tuple[str, ...] = ()
    engine: str = ENGINE_LOCAL

    def to_dict(self) -> dict:
        return {
            "modes": [{"name": m.name, "channels": [c.to_dict() for c in m.channels]} for m in self.modes],
            "warnings": list(self.warnings),
            "engine": self.engine,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ScanDraft:
        try:
            modes = data["modes"]
            if not isinstance(modes, list):
                raise TypeError("ожидался список режимов")
            return cls(
                tuple(
                    DraftMode(str(m["name"]), tuple(DraftChannel.from_dict(c) for c in m.get("channels", []))) for m in modes
                ),
                tuple(str(w) for w in data.get("warnings", [])),
                str(data.get("engine", ENGINE_LOCAL)),
            )
        except (KeyError, TypeError, AttributeError) as error:
            raise ValueError(f"неверный черновик: {error!r}") from error


def _merge_channels(existing: tuple[DraftChannel, ...], extra: tuple[DraftChannel, ...]) -> tuple[DraftChannel, ...]:
    by_dmx = {c.dmx: c for c in existing}
    for channel in extra:
        known = by_dmx.get(channel.dmx)
        if known is None:
            by_dmx[channel.dmx] = channel
            continue
        ranges = sorted(
            {(r.start, r.end, r.name): r for r in (*known.ranges, *channel.ranges)}.values(), key=lambda r: (r.start, r.end)
        )
        by_dmx[channel.dmx] = replace(
            known,
            name=known.name or channel.name,
            ranges=tuple(ranges),
            note=known.note or channel.note,
            confidence=min(known.confidence, channel.confidence),
        )
    return tuple(by_dmx[dmx] for dmx in sorted(by_dmx))


def merge_drafts(first: ScanDraft, second: ScanDraft) -> ScanDraft:
    """Склеивает черновики соседних страниц: тот же режим и канал дополняются.

    Страница без заголовка режима (имя пустое) продолжает последний режим."""
    modes = list(first.modes)
    for mode in second.modes:
        if mode.name:
            target = next((i for i, m in enumerate(modes) if m.name == mode.name), None)
        else:
            target = len(modes) - 1 if modes else None
        if target is None:
            modes.append(mode)
        else:
            modes[target] = DraftMode(modes[target].name, _merge_channels(modes[target].channels, mode.channels))
    return ScanDraft(tuple(modes), first.warnings + second.warnings, first.engine or second.engine)
