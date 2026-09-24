"""Распознавание инструкции на ПК: фото или PDF → черновик каналов (`ScanDraft`).

Тяжёлые библиотеки (RapidOCR, pypdfium2) подключаются при первом использовании: без них приложение работает,
а запрос автозаполнения получает понятную ошибку. Распознаватель и «рисовалка» страниц PDF подменяются в тестах.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Callable

from gmagc_common.scan_draft import ENGINE_LOCAL, ScanDraft, merge_drafts
from gmagc_desktop.scan.table import OcrItem, items_from_rapidocr, parse_tables

log = logging.getLogger(__name__)

MAX_PAGES = 30  # страниц PDF за один запрос: больше — это уже не одна таблица каналов
PDF_SCALE = 2.0  # масштаб отрисовки страницы PDF (≈144 dpi): текст мелкий, OCR любит крупнее

OcrFunction = Callable[[bytes], list[OcrItem]]  # байты картинки → куски текста с координатами
PageRenderer = Callable[[bytes], list[bytes]]  # байты PDF → PNG каждой страницы


class ScanError(Exception):
    """Файл не удалось прочитать как фото или PDF."""


class ScanUnavailableError(ScanError):
    """Не установлены библиотеки распознавания."""


def is_pdf(data: bytes) -> bool:
    return data[:1024].lstrip().startswith(b"%PDF")


def _rapidocr_function() -> OcrFunction:
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as error:
        raise ScanUnavailableError("не установлен модуль распознавания текста (rapidocr-onnxruntime)") from error
    engine = RapidOCR()

    def recognize(image: bytes) -> list[OcrItem]:
        result, _ = engine(image)
        return items_from_rapidocr(result)

    return recognize


def render_pdf_pages(data: bytes) -> list[bytes]:
    try:
        import pypdfium2
    except ImportError as error:
        raise ScanUnavailableError("не установлен модуль чтения PDF (pypdfium2)") from error
    try:
        document = pypdfium2.PdfDocument(data)
    except Exception as error:  # noqa: BLE001 - библиотека бросает собственные типы ошибок
        raise ScanError("не удалось прочитать PDF") from error
    pages = []
    try:
        for index in range(min(len(document), MAX_PAGES)):
            image = document[index].render(scale=PDF_SCALE).to_pil()
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            pages.append(buffer.getvalue())
    finally:
        document.close()
    return pages


class LocalScanner:
    def __init__(self, ocr: OcrFunction | None = None, renderer: PageRenderer | None = None):
        self._ocr = ocr
        self._renderer = renderer or render_pdf_pages

    def scan(self, data: bytes) -> ScanDraft:
        pages = self._renderer(data) if is_pdf(data) else [data]
        if not pages:
            raise ScanError("в файле нет страниц")
        if self._ocr is None:
            self._ocr = _rapidocr_function()
        draft = ScanDraft((), (), ENGINE_LOCAL)
        for number, page in enumerate(pages, 1):
            try:
                items = self._ocr(page)
            except ScanError:
                raise
            except Exception as error:  # noqa: BLE001 - битая картинка и сбой модели различаются слабо
                log.exception("не удалось распознать страницу %d", number)
                raise ScanError("не удалось распознать изображение") from error
            page_draft = parse_tables(items, ENGINE_LOCAL)
            draft = merge_drafts(draft, page_draft)
        # предупреждение «нет таблицы» имеет смысл только если не нашлось ни одного режима
        warnings = draft.warnings if not draft.modes else ()
        return ScanDraft(draft.modes, tuple(dict.fromkeys(warnings)), ENGINE_LOCAL)
