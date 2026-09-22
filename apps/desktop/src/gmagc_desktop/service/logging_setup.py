"""Диагностический лог-файл: чтобы было что приложить к письму при жалобе на ошибку."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

LOG_FILE_NAME = "gmagc.log"
MAX_BYTES = 1_000_000
BACKUP_COUNT = 1


def setup_logging(data_dir: Path) -> Path:
    """Пишет варнинги и ошибки логгера "gmagc" в файл рядом с настройками; возвращает его путь.

    Повторный вызов (например, второй build_page в тестах) не плодит обработчики — заменяет старый."""
    data_dir.mkdir(parents=True, exist_ok=True)
    log_path = data_dir / LOG_FILE_NAME
    logger = logging.getLogger("gmagc")
    logger.setLevel(logging.INFO)
    for handler in list(logger.handlers):
        if isinstance(handler, logging.handlers.RotatingFileHandler):
            logger.removeHandler(handler)
            handler.close()
    handler = logging.handlers.RotatingFileHandler(log_path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    return log_path
