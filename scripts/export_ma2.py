r"""Превращает профиль прибора (JSON из кнопки «Поделиться профилем» на телефоне) в типы приборов grandMA2.

  export_ma2.py profile.json                         # файлы по одному на режим появятся рядом
  export_ma2.py profile.json -d "C:\ProgramData\MA Lighting Technologies\grandma\gma2_V_3.9.63\importexport"

В MA2 один файл описывает один режим прибора, поэтому на профиль с несколькими режимами получается несколько файлов.
Коды выхода: 0 успех, 1 профиль не готов к экспорту, 3 файл не прочитан или это не профиль GMAGC.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "desktop" / "src"))

from gmagc_common.fixtures import ProfileError, profile_from_dict  # noqa: E402
from gmagc_common.ma2_export import ExportError, export_ma2_files  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Профиль прибора GMAGC (JSON) → типы приборов grandMA2 (XML)")
    parser.add_argument("profile", type=Path, help="JSON профиля")
    parser.add_argument("-d", "--directory", type=Path, help="куда записать файлы (по умолчанию рядом с JSON)")
    args = parser.parse_args(argv)
    try:
        profile = profile_from_dict(json.loads(args.profile.read_text(encoding="utf-8")))
    except (OSError, ValueError, ProfileError) as error:  # ValueError покрывает и ошибку разбора JSON
        print(f"Не удалось прочитать профиль: {error}", file=sys.stderr)
        return 3
    try:
        files = export_ma2_files(profile)
    except ExportError as error:
        print(error, file=sys.stderr)
        return 1
    target = args.directory or args.profile.parent
    target.mkdir(parents=True, exist_ok=True)
    for name, text in files:
        (target / name).write_text(text, encoding="utf-8")
        print(target / name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
