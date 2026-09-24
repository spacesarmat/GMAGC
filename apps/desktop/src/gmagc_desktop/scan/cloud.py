"""Облачное распознавание инструкции: Claude читает фото или PDF и отвечает черновиком каналов по JSON-схеме.

Запускается только по явной просьбе телефона (`engine=cloud`, пользователь подтвердил отправку) и только с ключом,
введённым в настройках ПК. Ключ на телефон не попадает. Библиотека `anthropic` подключается при первом использовании.
"""

from __future__ import annotations

import base64
import io
import json
import logging
from collections.abc import Callable

from gmagc_common.fixtures import TEMPLATES, Range
from gmagc_common.scan_draft import ENGINE_CLOUD, WARN_NO_TABLE, DraftChannel, DraftMode, ScanDraft
from gmagc_desktop.scan.engine import ScanError, ScanUnavailableError, is_pdf

log = logging.getLogger(__name__)

MODEL = "claude-opus-5"
MAX_OUTPUT_TOKENS = 32000
MAX_IMAGE_SIDE = 2000  # длинная сторона фото после сжатия: таблица читается, файл укладывается в лимит API
IMAGE_BYTES_LIMIT = 3_500_000  # API принимает картинку до 5 МБ в base64: ~3,7 МБ исходных байт, берём с запасом

_TEMPLATE_IDS = [template.id for template in TEMPLATES]

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["modes"],
    "properties": {
        "modes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "channels"],
                "properties": {
                    "name": {"type": "string"},
                    "channels": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["dmx", "name", "template", "bits", "ranges"],
                            "properties": {
                                "dmx": {"type": "integer"},
                                "name": {"type": "string"},
                                "template": {"type": "string", "enum": _TEMPLATE_IDS},
                                "bits": {"type": "integer", "enum": [8, 16]},
                                "ranges": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "required": ["start", "end", "name"],
                                        "properties": {
                                            "start": {"type": "integer"},
                                            "end": {"type": "integer"},
                                            "name": {"type": "string"},
                                        },
                                    },
                                },
                            },
                        },
                    },
                },
            },
        }
    },
}

PROMPT = (
    "This is a page (or several pages) of a lighting fixture manual. Extract the DMX channel tables.\n"
    "- One entry in `modes` per DMX mode (for example '9CH', 'Standard'); use an empty name if a table has no heading.\n"
    "- A page can contain several tables and several channels; a table can continue on the next page: "
    "then keep the same mode and channel numbers.\n"
    "- `dmx` is the first DMX address of the channel (1-512). A 16-bit channel occupies two addresses "
    "(coarse and fine): report it once with bits=16 and do not list the fine channel separately.\n"
    "- `name` is the channel function as written in the manual (keep the manual's language).\n"
    "- `template` is the closest of the allowed values; use 'custom' when nothing fits and 'control' for "
    "macro, program, speed, reset and mode channels.\n"
    "- `ranges` are the DMX value ranges of the channel (0-255) with their meaning, exactly as in the manual; "
    "an empty list when the manual gives none.\n"
    "Do not invent channels or ranges that are not in the document."
)


def prepare_image(data: bytes) -> tuple[bytes, str]:
    """Байты и тип картинки для API: большое фото сжимается, PNG/JPEG/WEBP/GIF нужного размера уходят как есть."""
    from PIL import Image, UnidentifiedImageError

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise ScanError("не удалось прочитать изображение") from error
    fmt = (image.format or "").upper()
    media = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp", "GIF": "image/gif"}.get(fmt)
    if media and len(data) <= IMAGE_BYTES_LIMIT and max(image.size) <= 4000:
        return data, media
    image = image.convert("RGB")
    image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=88)
    return buffer.getvalue(), "image/jpeg"


def _clean_channel(raw: dict) -> DraftChannel | None:
    try:
        dmx = int(raw["dmx"])
        name = str(raw["name"]).strip()
        bits = 16 if int(raw.get("bits", 8)) == 16 else 8
        ranges = []
        for item in raw.get("ranges", []):
            start, end = int(item["start"]), int(item["end"])
            label = str(item["name"]).strip()
            if 0 <= start <= end <= 255 and label:
                ranges.append(Range(start, end, label))
    except (KeyError, TypeError, ValueError):
        return None
    if not 1 <= dmx <= 512 or not name:
        return None
    template = str(raw.get("template", "custom"))
    return DraftChannel(dmx, name, template if template in _TEMPLATE_IDS else "custom", bits, tuple(ranges))


def draft_from_reply(text: str) -> ScanDraft:
    """Черновик из JSON-ответа модели; испорченные каналы отбрасываются, а не ломают весь ответ."""
    try:
        data = json.loads(text)
        raw_modes = data["modes"]
        if not isinstance(raw_modes, list):
            raise TypeError("modes")
    except (ValueError, KeyError, TypeError) as error:
        raise ScanError("облако вернуло ответ неожиданного вида") from error
    modes = []
    for raw in raw_modes:
        try:
            channels = [c for c in (_clean_channel(item) for item in raw.get("channels", [])) if c]
            name = str(raw.get("name", "")).strip()
        except (AttributeError, TypeError):
            continue
        if channels:
            by_dmx = {c.dmx: c for c in channels}  # повтор одного адреса: остаётся последний
            modes.append(DraftMode(name, tuple(by_dmx[d] for d in sorted(by_dmx))))
    if not modes:
        return ScanDraft((), (WARN_NO_TABLE,), ENGINE_CLOUD)
    return ScanDraft(tuple(modes), (), ENGINE_CLOUD)


def _default_client(api_key: str):
    try:
        import anthropic
    except ImportError as error:
        raise ScanUnavailableError("не установлен модуль облака (anthropic)") from error
    return anthropic.Anthropic(api_key=api_key)


class CloudScanner:
    def __init__(self, api_key: Callable[[], str], client_factory: Callable[[str], object] | None = None):
        self._api_key = api_key
        self._client_factory = client_factory or _default_client

    def scan(self, data: bytes) -> ScanDraft:
        key = (self._api_key() or "").strip()
        if not key:
            raise ScanUnavailableError("на ПК не введён ключ Anthropic: укажите его в настройках ПК-приложения")
        if is_pdf(data):
            block = {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": base64.standard_b64encode(data).decode(),
                },
            }
        else:
            image, media = prepare_image(data)
            block = {
                "type": "image",
                "source": {"type": "base64", "media_type": media, "data": base64.standard_b64encode(image).decode()},
            }
        client = self._client_factory(key)
        try:
            with client.messages.stream(
                model=MODEL,
                max_tokens=MAX_OUTPUT_TOKENS,
                output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
                messages=[{"role": "user", "content": [block, {"type": "text", "text": PROMPT}]}],
            ) as stream:
                message = stream.get_final_message()
        except ScanError:
            raise
        except Exception as error:  # noqa: BLE001 - типы ошибок SDK разбираем по имени, чтобы не требовать его при импорте
            raise self._translate(error) from error
        if getattr(message, "stop_reason", None) == "refusal":
            raise ScanError("облако отказалось обработать этот файл")
        if getattr(message, "stop_reason", None) == "max_tokens":
            raise ScanError("таблица слишком большая для одного запроса: отправьте меньше страниц")
        text = next((b.text for b in message.content if getattr(b, "type", "") == "text"), "")
        return draft_from_reply(text)

    @staticmethod
    def _translate(error: Exception) -> ScanError:
        name = type(error).__name__
        if name in {"AuthenticationError", "PermissionDeniedError"}:
            return ScanUnavailableError("облако отклонило ключ Anthropic: проверьте его в настройках ПК-приложения")
        if name == "RateLimitError":
            return ScanError("облако просит подождать (лимит запросов): повторите позже")
        if name in {"APIConnectionError", "APITimeoutError"}:
            return ScanError("нет связи с облаком: проверьте интернет на ПК")
        if name == "BadRequestError":
            return ScanError("облако не приняло файл: он слишком большой или повреждён")
        log.exception("ошибка облачного распознавания")
        return ScanError("облако вернуло ошибку")
