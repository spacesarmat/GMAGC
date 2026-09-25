"""Правит buildozer-часть pyside6-android-deploy перед сборкой: имя пакета, версия, разрешения, значок.

Инструмент сам создаёт buildozer.spec с шаблонными значениями (пакет org.GMAGC.GMAGC, версия 0.1, лишние
разрешения). Нужен тот же идентификатор, что у прежнего приложения (com.spacesarmat.gmagc), чтобы новая версия
ставилась поверх старой. Значения берутся из переменных окружения GMAGC_VERSION, GMAGC_VERSION_CODE, GMAGC_ICON."""

from __future__ import annotations

import sys
from pathlib import Path

import PySide6

TARGET = Path(PySide6.__file__).parent / "scripts" / "deploy_lib" / "android" / "buildozer.py"
MARK = "# --- GMAGC ---"
INSERT = f'''
        {MARK}
        import os
        self.parser.set("app", "package.name", "gmagc")
        self.parser.set("app", "package.domain", "com.spacesarmat")
        self.parser.set("app", "version", os.environ["GMAGC_VERSION"])
        self.parser.set("app", "android.numeric_version", os.environ["GMAGC_VERSION_CODE"])
        self.parser.set("app", "orientation", "portrait")
        self.parser.set("app", "android.permissions", "CAMERA, INTERNET, ACCESS_NETWORK_STATE")
        self.parser.set("app", "icon.filename", os.environ["GMAGC_ICON"])
'''


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    if MARK in text:
        print("уже исправлено")
        return 0
    anchor = "        self.update_config()\n"
    if anchor not in text:
        print("не найдено место вставки в", TARGET, file=sys.stderr)
        return 1
    TARGET.write_text(text.replace(anchor, INSERT + anchor, 1), encoding="utf-8")
    print("исправлено", TARGET)
    return 0


if __name__ == "__main__":
    sys.exit(main())
