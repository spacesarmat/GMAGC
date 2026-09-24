"""Перенос отмеченных каналов черновика (распознанного по инструкции) в режим профиля."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from gmagc_common.fixtures import (
    TEMPLATES,
    Channel,
    Mode,
    next_free_dmx,
    template_by_id,
    template_ranges,
    template_title,
)
from gmagc_common.scan_draft import DraftChannel

_KNOWN = {template.id for template in TEMPLATES}


def channel_from_draft(draft: DraftChannel, dmx: int) -> Channel:
    """Канал профиля по черновику: неизвестный шаблон — «custom»; без распознанных диапазонов берутся диапазоны шаблона."""
    template_id = draft.template if draft.template in _KNOWN else "custom"
    template = template_by_id(template_id)
    ranges = draft.ranges or template_ranges(template)
    bits = 16 if draft.bits == 16 else 8
    return Channel(dmx, bits, draft.name.strip() or template_title(template), template_id, 0, tuple(ranges))


def add_draft_channels(mode: Mode, chosen: Iterable[DraftChannel]) -> Mode:
    """Добавляет каналы в режим. Адрес из инструкции сохраняется, если он свободен; иначе канал идёт за последним."""
    occupied = {address for channel in mode.channels for address in range(channel.dmx, channel.last + 1)}
    channels = list(mode.channels)
    for draft in sorted(chosen, key=lambda c: c.dmx):
        candidate = channel_from_draft(draft, max(draft.dmx, 1))
        span = set(range(candidate.dmx, candidate.last + 1))
        if draft.dmx < 1 or span & occupied:
            candidate = replace(candidate, dmx=next_free_dmx(replace(mode, channels=tuple(channels))))
            span = set(range(candidate.dmx, candidate.last + 1))
        occupied |= span
        channels.append(candidate)
    return replace(mode, channels=tuple(channels))
