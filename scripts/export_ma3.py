r"""Превращает профиль прибора (JSON из кнопки «Поделиться профилем» на телефоне) в тип прибора grandMA3.

  export_ma3.py profile.json                    # рядом появится profile.xml
  export_ma3.py profile.json -o "C:\ProgramData\MALightingTechnology\gma3_library\fixturetypes\мой прибор.xml"

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
from gmagc_common.ma3_export import ExportError, export_ma3  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Профиль прибора GMAGC (JSON) → тип прибора grandMA3 (XML)")
    parser.add_argument("profile", type=Path, help="JSON профиля")
    parser.add_argument("-o", "--output", type=Path, help="куда записать XML (по умолчанию рядом с JSON)")
    args = parser.parse_args(argv)
    try:
        profile = profile_from_dict(json.loads(args.profile.read_text(encoding="utf-8")))
    except (OSError, ValueError, ProfileError) as error:  # ValueError покрывает и ошибку разбора JSON
        print(f"Не удалось прочитать профиль: {error}", file=sys.stderr)
        return 3
    try:
        text = export_ma3(profile)
    except ExportError as error:
        print(error, file=sys.stderr)
        return 1
    target = args.output or args.profile.with_suffix(".xml")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
