"""Копирует packages/common/gmagc_common в приложения: python scripts/sync_common.py"""

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "packages" / "common" / "gmagc_common"
TARGETS = [ROOT / "apps" / "desktop" / "src" / "gmagc_common", ROOT / "apps" / "mobile" / "src" / "gmagc_common"]


def sync() -> list[Path]:
    written = []
    for target in TARGETS:
        target.mkdir(parents=True, exist_ok=True)
        for source in sorted(SOURCE.glob("*.py")):
            shutil.copyfile(source, target / source.name)
            written.append(target / source.name)
    return written


if __name__ == "__main__":
    for path in sync():
        print(path.relative_to(ROOT))
