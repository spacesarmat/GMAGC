# GMAGC: ПК-приложение с поиском (этап 3). План реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ПК-приложение Flet: выбрать папку библиотеки, построить индекс, выбрать фото или вставить из буфера, увидеть результаты с превью, кликабельными путями и предупреждением о низкой оценке.

**Architecture:** Слой сервиса без Flet (`gmagc_desktop/service/`: настройки, `SearchService`, результаты, показ файла в проводнике) над ядром; тонкий экран (`gmagc_desktop/ui/`) на заглушках страницы тестируется pytest. Сначала закрываются отложенные исправления ядра (они нужны сервису).

**Tech Stack:** Python 3.12, Flet 1.0.0, ядро v0.1.0 (numpy, OpenCV), pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-09-21-gmagc-desktop-search-design.md`

## Global Constraints

- Flet закреплён на 1.0.0; в приложении `requires-python = ">=3.12,<3.13"`; `[tool.flet.compile] packages = false` остаётся (OpenCV читает `config.py`).
- Слой `service/` не импортирует Flet; `ui/` не содержит бизнес-логики.
- Порог «нет совпадения»: `LOW_CONFIDENCE_SCORE = 0.72` (результаты не скрываются); оценка в интерфейсе не больше 100%.
- Настройки и кэш: `%LOCALAPPDATA%\@ANDY_BUM\GMAGC\` (macOS `~/Library/Application Support/GMAGC`, иначе `~/.local/share/gmagc`), переопределение `GMAGC_DATA_DIR`.
- Индексация и поиск идут в фоновом потоке (`page.run_thread`); ошибки показываются в окне, не traceback.
- Тесты используют только синтетические данные (`tests/fixtures.py`); `gobos/`, `photo/`, `models/` не читаются и не коммитятся.
- Автор `@ANDY_BUM` остаётся на экране приложения. Комментарии и строки интерфейса на русском.
- Коммиты: `git commit -m "<тип>: <описание>" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"`. Работа на ветке `feat/desktop-search`, в `main` только через Pull Request с зелёными проверками.
- Запуск тестов: `.venv\Scripts\python.exe -m pytest -q`, линтер: `.venv\Scripts\python.exe -m ruff check .`.

---

### Task 1: Исправления ядра и общая миниатюра

**Files:**
- Modify: `apps/desktop/src/gmagc_desktop/library/index.py`, `scripts/_thumbs.py`, `scripts/benchmark.py`
- Create: `apps/desktop/src/gmagc_desktop/library/cache.py`, `apps/desktop/src/gmagc_desktop/matcher/thumbnail.py`
- Test: `tests/library/test_index_hardening.py`, `tests/library/test_cache.py`, `tests/matcher/test_thumbnail.py`

**Interfaces:**
- Produces: `library.cache.update_index(root, embedder, index_path, progress=None, cancel=None) -> LibraryIndex` (загрузить кэш, дособрать, сохранить); `matcher.thumbnail.square_pad(gray) -> ndarray`, `matcher.thumbnail.thumbnail_png(gray, size=96) -> bytes` (PNG квадрата с чёрными полями); `load_index` возвращает `None` для кэша с небезопасными `rel_path`; обрезанные PNG/BMP попадают в `skipped`, а не в `transient`.

- [ ] **Step 1: Write the failing tests**

```python
# path: tests/library/test_index_hardening.py
import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from gmagc_desktop.library import index as index_module
from gmagc_desktop.library.index import LibraryIndex, build_index, load_index, save_index
from gmagc_desktop.library.scan import LibraryFile
from gmagc_desktop.matcher.embedder import PixelEmbedder
from tests.fixtures import shape_images, write_library


def _truncated_png(path: Path) -> None:
    buffer = io.BytesIO()
    Image.fromarray(shape_images()["dots"], "L").save(buffer, format="PNG")
    data = buffer.getvalue()
    path.write_bytes(data[: len(data) // 2])


def _one_file_index(rel_path: str) -> LibraryIndex:
    return LibraryIndex(
        "pixels-16",
        [LibraryFile(rel_path, 10, 5)],
        np.zeros((1, 4), np.float32),
        np.zeros((1, 64, 64), np.uint8),
        np.zeros(1, np.int32),
    )


def test_truncated_png_is_a_permanent_skip_not_a_transient_failure(tmp_path, monkeypatch):
    library = tmp_path / "lib"
    library.mkdir()
    write_library(library)
    _truncated_png(library / "vendor_a" / "cut.png")

    first = build_index(library, PixelEmbedder())

    assert "vendor_a/cut.png" in [f.rel_path for f in first.skipped]
    assert first.transient == []

    opened = []
    real = index_module.load_library_gray
    monkeypatch.setattr(index_module, "load_library_gray", lambda path: opened.append(Path(path).name) or real(path))
    build_index(library, PixelEmbedder(), existing=first)
    assert "cut.png" not in opened  # окончательно испорченный файл повторно не открывается


@pytest.mark.parametrize("bad", ["../evil.png", "/abs/evil.png", "C:/evil.png", "a/../../evil.png", "..\\evil.png"])
def test_load_index_rejects_unsafe_relative_paths(tmp_path, bad):
    target = tmp_path / "index.npz"
    save_index(_one_file_index(bad), target)

    assert load_index(target) is None


def test_load_index_accepts_nested_relative_paths(tmp_path):
    target = tmp_path / "index.npz"
    save_index(_one_file_index("vendor/sub dir/a.png"), target)

    loaded = load_index(target)

    assert loaded is not None and loaded.files[0].rel_path == "vendor/sub dir/a.png"


def test_save_index_leaves_no_temp_files_and_keeps_the_old_index_on_failure(tmp_path, monkeypatch):
    library = tmp_path / "lib"
    library.mkdir()
    write_library(library)
    index = build_index(library, PixelEmbedder())
    target = tmp_path / "cache" / "index.npz"

    save_index(index, target)
    assert [p.name for p in target.parent.iterdir()] == ["index.npz"]
    before = target.read_bytes()

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(np, "savez_compressed", boom)
    with pytest.raises(OSError, match="disk full"):
        save_index(index, target)

    assert target.read_bytes() == before
    assert [p.name for p in target.parent.iterdir()] == ["index.npz"]
```

```python
# path: tests/library/test_cache.py
import pytest

from gmagc_desktop.library.cache import update_index
from gmagc_desktop.library.index import IndexCancelled
from gmagc_desktop.matcher.embedder import PixelEmbedder
from tests.fixtures import write_library


@pytest.fixture()
def library(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    write_library(root)
    return root


def test_update_index_builds_saves_and_reuses_the_cache(library, tmp_path):
    path = tmp_path / "cache" / "index.npz"
    calls = []

    first = update_index(library, PixelEmbedder(), path, progress=lambda done, total: calls.append((done, total)))

    assert path.exists() and len(first) == 6
    assert calls and calls[-1][0] == calls[-1][1]

    second = update_index(library, PixelEmbedder(), path)

    assert len(second) == 6 and second.model_id == first.model_id


def test_cancelled_update_saves_nothing(library, tmp_path):
    path = tmp_path / "cache" / "index.npz"

    with pytest.raises(IndexCancelled):
        update_index(library, PixelEmbedder(), path, cancel=lambda: True)

    assert not path.exists()
```

```python
# path: tests/matcher/test_thumbnail.py
import cv2
import numpy as np

from gmagc_desktop.matcher.thumbnail import square_pad, thumbnail_png


def test_thumbnail_png_is_a_square_png_of_the_requested_size():
    data = thumbnail_png(np.full((10, 20), 200, np.uint8), 32)

    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
    assert data.startswith(b"\x89PNG") and image.shape == (32, 32)


def test_square_pad_centres_a_tall_image():
    padded = square_pad(np.full((20, 10), 100, np.uint8))

    assert padded.shape == (20, 20)
    assert np.all(padded[:, :5] == 0) and np.all(padded[:, 15:] == 0) and np.all(padded[:, 5:15] == 100)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/library/test_index_hardening.py tests/library/test_cache.py tests/matcher/test_thumbnail.py -q`
Expected: FAIL (нет `cache.py` и `thumbnail.py`; обрезанный PNG попадает в `transient`; небезопасные пути загружаются).

- [ ] **Step 3: Implementation**

```python
# path: apps/desktop/src/gmagc_desktop/matcher/thumbnail.py
"""Миниатюры гобо для интерфейса и отчётов."""

from __future__ import annotations

import cv2
import numpy as np


def square_pad(gray: np.ndarray) -> np.ndarray:
    """Дополняет изображение чёрным до квадрата, оригинал по центру."""
    side = max(gray.shape)
    square = np.zeros((side, side), np.uint8)
    y, x = (side - gray.shape[0]) // 2, (side - gray.shape[1]) // 2
    square[y : y + gray.shape[0], x : x + gray.shape[1]] = gray
    return square


def thumbnail_png(gray: np.ndarray, size: int = 96) -> bytes:
    """PNG-миниатюра size x size: изображение вписано в квадрат с чёрными полями."""
    small = cv2.resize(square_pad(gray), (size, size), interpolation=cv2.INTER_AREA)
    ok, buffer = cv2.imencode(".png", small)
    if not ok:
        raise ValueError("не удалось закодировать миниатюру")
    return buffer.tobytes()
```

```python
# path: apps/desktop/src/gmagc_desktop/library/cache.py
"""Кэш индекса на диске: загрузить, дособрать, сохранить."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from gmagc_desktop.library.index import LibraryIndex, ProgressCallback, build_index, load_index, save_index
from gmagc_desktop.matcher.embedder import Embedder


def update_index(
    root: str | Path,
    embedder: Embedder,
    index_path: str | Path,
    progress: ProgressCallback | None = None,
    cancel: Callable[[], bool] | None = None,
) -> LibraryIndex:
    """Дособирает индекс поверх кэша (новые и изменённые файлы) и сохраняет его.

    Исключения build_index (LibraryNotFound, LibraryScanError, IndexCancelled) пробрасываются, кэш при этом не трогается.
    """
    index = build_index(root, embedder, existing=load_index(index_path), progress=progress, cancel=cancel)
    save_index(index, index_path)
    return index
```

Правки `apps/desktop/src/gmagc_desktop/library/index.py` (применить скриптом; тексты замен точные):

```python
# path: .gmagc-cache/patch_index.py
from pathlib import Path
import re

path = Path("apps/desktop/src/gmagc_desktop/library/index.py")
text = path.read_text(encoding="utf-8")

# 1) обрезанные файлы: окончательный пропуск
old = '''    except OSError as error:
        logger.warning("library file %s cannot be read right now, will retry next time: %s", path, error)
        raise _TransientReadError(str(error)) from error
'''
new = '''    except OSError as error:
        if _is_corrupt_file_error(error):
            logger.warning("skipping corrupt library file %s: %s", path, error)
            return None
        logger.warning("library file %s cannot be read right now, will retry next time: %s", path, error)
        raise _TransientReadError(str(error)) from error
'''
assert text.count(old) == 1
text = text.replace(old, new)

helper = '''# Сообщения PIL об окончательно повреждённых (обрезанных) файлах: у них errno нет, а у сбоев ОС он есть.
_CORRUPT_MARKERS = ("truncated", "broken data stream", "decoder error")


def _is_corrupt_file_error(error: OSError) -> bool:
    return error.errno is None and any(marker in str(error).lower() for marker in _CORRUPT_MARKERS)


'''
anchor = "def _load_normalized("
assert text.count(anchor) == 1
text = text.replace(anchor, helper + anchor)

# 2) save_index через уникальный временный файл
start = text.index("def save_index(")
end = text.index("def _files(")
save = '''def save_index(index: LibraryIndex, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            np.savez_compressed(
                handle,
                format_version=np.array(FORMAT_VERSION),
                model_id=np.array(index.model_id),
                rel_paths=np.array([f.rel_path for f in index.files], dtype=str),
                sizes=np.array([f.size for f in index.files], dtype=np.int64),
                mtimes=np.array([f.mtime_ns for f in index.files], dtype=np.int64),
                embeddings=index.embeddings.astype(np.float16),
                masks=index.masks,
                group_ids=index.group_ids.astype(np.int32),
                skipped_paths=np.array([f.rel_path for f in index.skipped], dtype=str),
                skipped_sizes=np.array([f.size for f in index.skipped], dtype=np.int64),
                skipped_mtimes=np.array([f.mtime_ns for f in index.skipped], dtype=np.int64),
            )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


'''
text = text[:start] + save + text[end:]
text = text.replace("import tokenize\n", "import tempfile\nimport tokenize\n", 1)
text = text.replace("from pathlib import Path\n", "from pathlib import Path, PurePosixPath, PureWindowsPath\n", 1)

# 3) load_index отвергает небезопасные rel_path
safe = '''def _is_safe_rel_path(rel_path: str) -> bool:
    """Относительный путь внутри библиотеки: без диска, абсолютного начала и `..`."""
    normalized = rel_path.replace("\\\\", "/")
    posix = PurePosixPath(normalized)
    return bool(normalized) and not posix.is_absolute() and not PureWindowsPath(normalized).drive and ".." not in posix.parts


'''
assert text.count("def load_index(") == 1
text = text.replace("def load_index(", safe + "def load_index(")
old_ret = '''            return LibraryIndex(
                model_id=str(data["model_id"]),
                files=_files(data["rel_paths"], data["sizes"], data["mtimes"]),
                embeddings=data["embeddings"].astype(np.float32),
                masks=data["masks"],
                group_ids=data["group_ids"],
                skipped=_files(data["skipped_paths"], data["skipped_sizes"], data["skipped_mtimes"]),
            )
'''
new_ret = '''            files = _files(data["rel_paths"], data["sizes"], data["mtimes"])
            skipped = _files(data["skipped_paths"], data["skipped_sizes"], data["skipped_mtimes"])
            if not all(_is_safe_rel_path(f.rel_path) for f in files + skipped):
                return None  # кэш с путями за пределами библиотеки не используем: индекс построится заново
            return LibraryIndex(
                model_id=str(data["model_id"]),
                files=files,
                embeddings=data["embeddings"].astype(np.float32),
                masks=data["masks"],
                group_ids=data["group_ids"],
                skipped=skipped,
            )
'''
assert text.count(old_ret) == 1
text = text.replace(old_ret, new_ret)
path.write_text(text, encoding="utf-8", newline="\n")
print("index.py patched")
```

Run: `mkdir -p .gmagc-cache && .venv\Scripts\python.exe .gmagc-cache\patch_index.py`

Миниатюра в скриптах и бенчмарк: `scripts/_thumbs.py` заменить целиком, в `scripts/benchmark.py` тело `load_or_build` заменить и добавить импорт.

```python
# path: scripts/_thumbs.py
"""Общий помощник миниатюр: реализация живёт в пакете."""

from gmagc_desktop.matcher.thumbnail import square_pad  # noqa: F401
```

В `scripts/benchmark.py`: заменить
```python
def load_or_build(root: Path, embedder, index_path: Path) -> LibraryIndex:
    index = build_index(root, embedder, existing=load_index(index_path), progress=_progress)
    print(file=sys.stderr)
    save_index(index, index_path)
    return index
```
на
```python
def load_or_build(root: Path, embedder, index_path: Path) -> LibraryIndex:
    index = update_index(root, embedder, index_path, progress=_progress)
    print(file=sys.stderr)
    return index
```
добавить `from gmagc_desktop.library.cache import update_index  # noqa: E402` рядом с остальными импортами `gmagc_desktop` и убрать ставшие неиспользуемыми `build_index`, `load_index`, `save_index` из импорта `gmagc_desktop.library.index`: `.venv\Scripts\python.exe -m ruff check scripts/benchmark.py --select F401 --fix`.

- [ ] **Step 4: Run all tests and ruff**

Run: `.venv\Scripts\python.exe -m pytest -q` и `.venv\Scripts\python.exe -m ruff check .`
Expected: 157 + 12 новых тестов проходят (169), ruff чист; `tests/test_scripts.py` и `tests/test_thumbs.py` зелёные без правок.

- [ ] **Step 5: Commit**

```bash
git add -A apps scripts tests
git commit -m "fix: treat truncated files as corrupt, validate cached paths, add update_index and shared thumbnails" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: Настройки и результаты сервиса

**Files:**
- Create: `apps/desktop/src/gmagc_desktop/service/__init__.py` (пустой), `apps/desktop/src/gmagc_desktop/service/settings.py`, `apps/desktop/src/gmagc_desktop/service/results.py`
- Test: `tests/desktop/test_settings.py`

**Interfaces:**
- Produces: `data_dir() -> Path`; `Settings(library_dir: str = "", top_n: int = 10)`; `load_settings(path) -> Settings`; `save_settings(settings, path) -> None`; `Outcome` (`FOUND`, `LOW_CONFIDENCE`, `NO_PROJECTION`); `LOW_CONFIDENCE_SCORE = 0.72`; `Result(rank, name, rel_path, full_path, score, copies, thumbnail_png)`; `SearchOutcome(kind, results=(), projection_png=None, took_ms=0.0)`; `IndexStatus(files, families, skipped, transient)`.

- [ ] **Step 1: Write the failing tests**

```python
# path: tests/desktop/test_settings.py
import sys

from gmagc_desktop.service.settings import Settings, data_dir, load_settings, save_settings


def test_missing_and_corrupt_files_give_defaults(tmp_path):
    assert load_settings(tmp_path / "nope.json") == Settings()

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert load_settings(broken) == Settings()

    listing = tmp_path / "list.json"
    listing.write_text("[1, 2]", encoding="utf-8")
    assert load_settings(listing) == Settings()


def test_roundtrip_keeps_a_cyrillic_library_path(tmp_path):
    target = tmp_path / "data" / "settings.json"

    save_settings(Settings(library_dir="D:\\Библиотека гобо", top_n=15), target)

    assert load_settings(target) == Settings(library_dir="D:\\Библиотека гобо", top_n=15)


def test_invalid_values_fall_back_to_defaults(tmp_path):
    target = tmp_path / "settings.json"
    target.write_text('{"library_dir": 5, "top_n": 999}', encoding="utf-8")

    assert load_settings(target) == Settings(library_dir="", top_n=10)


def test_data_dir_can_be_overridden_and_follows_the_platform(monkeypatch, tmp_path):
    monkeypatch.setenv("GMAGC_DATA_DIR", str(tmp_path / "custom"))
    assert data_dir() == tmp_path / "custom"

    monkeypatch.delenv("GMAGC_DATA_DIR")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    assert data_dir().parts[-2:] == ("@ANDY_BUM", "GMAGC")
    assert str(data_dir()).startswith(str(tmp_path / "local"))

    monkeypatch.setattr(sys, "platform", "darwin")
    assert data_dir().parts[-3:] == ("Library", "Application Support", "GMAGC")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/desktop/test_settings.py -q`
Expected: FAIL (`ModuleNotFoundError: gmagc_desktop.service`).

- [ ] **Step 3: Implementation**

```python
# path: apps/desktop/src/gmagc_desktop/service/settings.py
"""Настройки приложения и каталог данных пользователя."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

APP_FOLDER = "GMAGC"
MAX_TOP_N = 50


def data_dir() -> Path:
    """Каталог настроек и кэша индекса (переопределяется переменной GMAGC_DATA_DIR)."""
    override = os.environ.get("GMAGC_DATA_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "@ANDY_BUM" / APP_FOLDER
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_FOLDER
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "gmagc"


@dataclass
class Settings:
    library_dir: str = ""
    top_n: int = 10


def load_settings(path: str | Path) -> Settings:
    """Настройки из файла; отсутствующий, повреждённый или неверный файл даёт значения по умолчанию."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    if not isinstance(raw, dict):
        return Settings()
    library_dir = raw.get("library_dir", "")
    top_n = raw.get("top_n", 10)
    return Settings(
        library_dir=library_dir if isinstance(library_dir, str) else "",
        top_n=top_n if isinstance(top_n, int) and not isinstance(top_n, bool) and 1 <= top_n <= MAX_TOP_N else 10,
    )


def save_settings(settings: Settings, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")
```

```python
# path: apps/desktop/src/gmagc_desktop/service/results.py
"""Типы результатов поиска для интерфейса (и будущего сервера)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# Верные попадания на реальных фото имели оценку не ниже 70,5%, ложные не выше 71,3%: порог нестрогий.
LOW_CONFIDENCE_SCORE = 0.72


class Outcome(Enum):
    FOUND = "found"
    LOW_CONFIDENCE = "low_confidence"
    NO_PROJECTION = "no_projection"


@dataclass(frozen=True)
class Result:
    rank: int
    name: str
    rel_path: str
    full_path: str
    score: float  # доля от 0 до 1
    copies: tuple[str, ...]  # полные пути остальных файлов семейства
    thumbnail_png: bytes


@dataclass(frozen=True)
class SearchOutcome:
    kind: Outcome
    results: tuple[Result, ...] = ()
    projection_png: bytes | None = None
    took_ms: float = 0.0


@dataclass(frozen=True)
class IndexStatus:
    files: int
    families: int
    skipped: int
    transient: int
```

Пустой `apps/desktop/src/gmagc_desktop/service/__init__.py` создаётся отдельно (`touch`).

- [ ] **Step 4: Run tests and ruff**

Run: `.venv\Scripts\python.exe -m pytest -q` и `.venv\Scripts\python.exe -m ruff check .`
Expected: 173 passed (4 новых), ruff чист.

- [ ] **Step 5: Commit**

```bash
git add apps/desktop/src/gmagc_desktop/service tests/desktop/test_settings.py
git commit -m "feat: add app settings and search result types" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: SearchService

**Files:**
- Create: `apps/desktop/src/gmagc_desktop/service/search_service.py`
- Test: `tests/desktop/test_search_service.py`

**Interfaces:**
- Consumes: `update_index`, `load_index` (Task 1), `Settings`, `load_settings`, `save_settings`, `Outcome`, `Result`, `SearchOutcome`, `IndexStatus`, `LOW_CONFIDENCE_SCORE` (Task 2), `thumbnail_png` (Task 1), `Searcher`, `DEFAULT_W_EMBED`, `normalize_photo`, `load_photo_bgr`, `load_library_gray`, `PixelEmbedder`.
- Produces: `SearchService(data_dir, embedder=None)` с атрибутом `settings`; методы `load() -> IndexStatus | None`, `set_library(path) -> None`, `build_index(progress=None, cancel=None) -> IndexStatus`, `status() -> IndexStatus | None`, `search_photo(photo_bgr, top_n=None) -> SearchOutcome`, `search_file(path) -> SearchOutcome`, `search_image_bytes(data) -> SearchOutcome`; исключения `PhotoError(ValueError)`, `NoIndexError(RuntimeError)`; константа `BLANK_THUMBNAIL: bytes`. Исключения ядра `IndexCancelled`, `LibraryNotFound`, `LibraryScanError` пробрасываются из `build_index`.

- [ ] **Step 1: Write the failing tests**

```python
# path: tests/desktop/test_search_service.py
import cv2
import numpy as np
import pytest

from gmagc_desktop.library.index import IndexCancelled, LibraryNotFound
from gmagc_desktop.matcher.synthetic import simulate_photo
from gmagc_desktop.service import search_service
from gmagc_desktop.service.results import Outcome
from gmagc_desktop.service.search_service import NoIndexError, PhotoError, SearchService
from tests.fixtures import shape_images, write_library


@pytest.fixture()
def library(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    write_library(root)
    return root


@pytest.fixture()
def service(tmp_path, library):
    instance = SearchService(tmp_path / "data")
    instance.load()
    instance.set_library(library)
    instance.build_index()
    return instance


def ell_photo(seed=5):
    return simulate_photo(shape_images()["ell"], np.random.default_rng(seed))


def test_build_index_reports_status_and_progress(tmp_path, library):
    service = SearchService(tmp_path / "data")
    service.load()
    service.set_library(library)
    calls = []

    status = service.build_index(progress=lambda done, total: calls.append((done, total)))

    assert (status.files, status.families, status.skipped, status.transient) == (6, 5, 1, 0)
    assert calls and calls[-1][0] == calls[-1][1]


def test_search_returns_families_with_copies_thumbnails_and_projection(service, library):
    outcome = service.search_photo(ell_photo())

    assert len(outcome.results) == 5  # по одной карточке на семейство
    top = outcome.results[0]
    assert top.name in {"ell.png", "ell_small.png"} and len(top.copies) == 1
    assert top.full_path.startswith(str(library)) and all(c.startswith(str(library)) for c in top.copies)
    assert top.thumbnail_png.startswith(b"\x89PNG") and outcome.projection_png.startswith(b"\x89PNG")
    assert 0.0 < top.score <= 1.0 and outcome.took_ms > 0
    assert [r.rank for r in outcome.results] == [1, 2, 3, 4, 5]
    assert [r.score for r in outcome.results] == sorted((r.score for r in outcome.results), reverse=True)


def test_low_confidence_threshold_decides_the_outcome_kind(service, monkeypatch):
    monkeypatch.setattr(search_service, "LOW_CONFIDENCE_SCORE", 2.0)
    assert service.search_photo(ell_photo()).kind is Outcome.LOW_CONFIDENCE

    monkeypatch.setattr(search_service, "LOW_CONFIDENCE_SCORE", 0.0)
    assert service.search_photo(ell_photo()).kind is Outcome.FOUND


def test_flat_photo_has_no_projection(service):
    outcome = service.search_photo(np.full((480, 640, 3), 90, np.uint8))

    assert outcome.kind is Outcome.NO_PROJECTION and outcome.results == ()


def test_search_without_an_index_raises(tmp_path):
    service = SearchService(tmp_path / "data")
    service.load()

    with pytest.raises(NoIndexError):
        service.search_photo(ell_photo())
    with pytest.raises(NoIndexError, match="папка библиотеки не выбрана"):
        service.build_index()


def test_unreadable_photos_raise_photo_error(service, tmp_path):
    with pytest.raises(PhotoError):
        service.search_file(tmp_path / "missing.png")
    with pytest.raises(PhotoError):
        service.search_image_bytes(b"junk")
    with pytest.raises(PhotoError):
        service.search_image_bytes(b"")


def test_file_and_bytes_searches_agree(service, tmp_path):
    ok, buffer = cv2.imencode(".png", ell_photo())
    path = tmp_path / "photo.png"
    path.write_bytes(buffer.tobytes())

    from_file = service.search_file(path)
    from_bytes = service.search_image_bytes(buffer.tobytes())

    assert [r.rel_path for r in from_file.results] == [r.rel_path for r in from_bytes.results]


def test_load_restores_settings_and_index_from_the_cache(tmp_path, service, library):
    fresh = SearchService(tmp_path / "data")

    status = fresh.load()

    assert status == service.status() and fresh.settings.library_dir == str(library)
    assert fresh.search_photo(ell_photo()).results


def test_cancelled_build_leaves_no_index(tmp_path, library):
    service = SearchService(tmp_path / "data")
    service.load()
    service.set_library(library)

    with pytest.raises(IndexCancelled):
        service.build_index(cancel=lambda: True)

    assert service.status() is None and not (tmp_path / "data" / "index.npz").exists()


def test_changing_the_library_drops_the_old_index_and_cache(service, tmp_path):
    other = tmp_path / "other"
    other.mkdir()

    service.set_library(other)

    assert service.status() is None
    assert not (tmp_path / "data" / "index.npz").exists()
    with pytest.raises(NoIndexError):
        service.search_photo(ell_photo())


def test_missing_library_folder_is_reported(tmp_path):
    service = SearchService(tmp_path / "data")
    service.load()
    service.set_library(tmp_path / "nope")

    with pytest.raises(LibraryNotFound):
        service.build_index()


def test_a_vanished_library_file_gets_a_blank_thumbnail(service, library):
    (library / "vendor_c" / "gobo.png").unlink()

    outcome = service.search_photo(simulate_photo(shape_images()["gobo"], np.random.default_rng(3)))

    assert any(r.name == "gobo.png" and r.thumbnail_png == search_service.BLANK_THUMBNAIL for r in outcome.results)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/desktop/test_search_service.py -q`
Expected: FAIL (`ModuleNotFoundError: gmagc_desktop.service.search_service`).

- [ ] **Step 3: Implementation**

```python
# path: apps/desktop/src/gmagc_desktop/service/search_service.py
"""Сервис поиска: настройки, индекс библиотеки и поиск по фото (без Flet)."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np

from gmagc_desktop.library.cache import update_index
from gmagc_desktop.library.index import LibraryIndex, ProgressCallback, load_index
from gmagc_desktop.matcher.embedder import Embedder, PixelEmbedder
from gmagc_desktop.matcher.imageio import load_library_gray, load_photo_bgr
from gmagc_desktop.matcher.pipeline import normalize_photo
from gmagc_desktop.matcher.search import DEFAULT_W_EMBED, Match, Searcher
from gmagc_desktop.matcher.thumbnail import thumbnail_png
from gmagc_desktop.service.results import LOW_CONFIDENCE_SCORE, IndexStatus, Outcome, Result, SearchOutcome
from gmagc_desktop.service.settings import Settings, load_settings, save_settings

THUMBNAIL_SIZE = 96
PROJECTION_SIZE = 160
BLANK_THUMBNAIL = thumbnail_png(np.zeros((1, 1), np.uint8), THUMBNAIL_SIZE)


class PhotoError(ValueError):
    """Фото нельзя прочитать или декодировать."""


class NoIndexError(RuntimeError):
    """Индекса нет: библиотека не выбрана или индекс не построен."""


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0


class SearchService:
    def __init__(self, data_dir: str | Path, embedder: Embedder | None = None):
        self._data_dir = Path(data_dir)
        self._embedder = embedder or PixelEmbedder()
        self._settings_path = self._data_dir / "settings.json"
        self._index_path = self._data_dir / "index.npz"
        self.settings = Settings()
        self._index: LibraryIndex | None = None
        self._searcher: Searcher | None = None

    def _use(self, index: LibraryIndex | None) -> None:
        self._index = index
        self._searcher = None if index is None else Searcher(index.search_data(), self._embedder, w_embed=DEFAULT_W_EMBED)

    def load(self) -> IndexStatus | None:
        """Читает настройки и кэш индекса (если библиотека выбрана и кэш совместим)."""
        self.settings = load_settings(self._settings_path)
        index = load_index(self._index_path) if self.settings.library_dir else None
        if index is not None and index.model_id != self._embedder.model_id:
            index = None
        self._use(index)
        return self.status()

    def set_library(self, path: str | Path) -> None:
        """Запоминает папку библиотеки; индекс другой папки сбрасывается вместе с кэшем."""
        path = str(path)
        if path != self.settings.library_dir:
            self._use(None)
            self._index_path.unlink(missing_ok=True)
        self.settings = replace(self.settings, library_dir=path)
        save_settings(self.settings, self._settings_path)

    def build_index(
        self, progress: ProgressCallback | None = None, cancel: Callable[[], bool] | None = None
    ) -> IndexStatus:
        """Строит или дособирает индекс. LibraryNotFound, LibraryScanError, IndexCancelled пробрасываются."""
        if not self.settings.library_dir:
            raise NoIndexError("папка библиотеки не выбрана")
        self._use(update_index(self.settings.library_dir, self._embedder, self._index_path, progress, cancel))
        return self.status()

    def status(self) -> IndexStatus | None:
        index = self._index
        if index is None:
            return None
        return IndexStatus(
            files=len(index),
            families=len(set(index.group_ids.tolist())),
            skipped=len(index.skipped),
            transient=len(index.transient),
        )

    def search_photo(self, photo_bgr: np.ndarray, top_n: int | None = None) -> SearchOutcome:
        searcher, index = self._searcher, self._index
        if searcher is None or index is None:
            raise NoIndexError("индекс не построен")
        started = time.perf_counter()
        normalized = normalize_photo(photo_bgr)
        if normalized is None:
            return SearchOutcome(Outcome.NO_PROJECTION, took_ms=_elapsed_ms(started))
        matches = searcher.search(normalized, top_n=top_n or self.settings.top_n)
        results = tuple(self._result(index, rank, match) for rank, match in enumerate(matches, start=1))
        confident = bool(results) and results[0].score >= LOW_CONFIDENCE_SCORE
        return SearchOutcome(
            Outcome.FOUND if confident else Outcome.LOW_CONFIDENCE,
            results,
            thumbnail_png(normalized, PROJECTION_SIZE),
            _elapsed_ms(started),
        )

    def search_file(self, path: str | Path) -> SearchOutcome:
        try:
            photo = load_photo_bgr(path)
        except (OSError, ValueError) as error:
            raise PhotoError(str(error)) from error
        return self.search_photo(photo)

    def search_image_bytes(self, data: bytes) -> SearchOutcome:
        photo = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR) if data else None
        if photo is None:
            raise PhotoError("не удалось прочитать изображение")
        return self.search_photo(photo)

    def _result(self, index: LibraryIndex, rank: int, match: Match) -> Result:
        rel_path = index.files[match.index].rel_path
        full_path = self._full_path(rel_path)
        copies = tuple(self._full_path(index.files[i].rel_path) for i in match.members if i != match.index)
        return Result(
            rank, Path(rel_path).name, rel_path, full_path, min(match.score, 1.0), copies, self._thumbnail(full_path)
        )

    def _full_path(self, rel_path: str) -> str:
        root = Path(self.settings.library_dir)
        path = root / rel_path
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"путь вне библиотеки: {rel_path}")
        return str(path)

    @staticmethod
    def _thumbnail(full_path: str) -> bytes:
        try:
            return thumbnail_png(load_library_gray(full_path), THUMBNAIL_SIZE)
        except (OSError, ValueError, SyntaxError):  # файл исчез или испортился после индексации
            return BLANK_THUMBNAIL
```

- [ ] **Step 4: Run tests and ruff**

Run: `.venv\Scripts\python.exe -m pytest -q` и `.venv\Scripts\python.exe -m ruff check .`
Expected: 185 passed (12 новых), ruff чист. Если `test_search_returns_families...` ждёт 5 результатов, а вернулось меньше, проверить `shortlist` (по умолчанию 20 семейств, в тестовой библиотеке 5); тест не ослаблять.

- [ ] **Step 5: Commit**

```bash
git add apps/desktop/src/gmagc_desktop/service tests/desktop/test_search_service.py
git commit -m "feat: add the search service (index, search, results)" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: Показ файла в проводнике

**Files:**
- Create: `apps/desktop/src/gmagc_desktop/service/reveal.py`
- Test: `tests/desktop/test_reveal.py`

**Interfaces:**
- Produces: `reveal_in_file_manager(path: str | Path) -> bool`: Windows `explorer /select,"<путь>"`, macOS `open -R <путь>`, иначе `xdg-open <папка>`; `True`, если команда запущена, `False` при `OSError`.

- [ ] **Step 1: Write the failing tests**

```python
# path: tests/desktop/test_reveal.py
import subprocess
import sys

import pytest

from gmagc_desktop.service.reveal import reveal_in_file_manager


@pytest.fixture()
def launched(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda command, **kwargs: calls.append(command))
    return calls


def test_windows_selects_the_file_in_explorer(monkeypatch, launched):
    monkeypatch.setattr(sys, "platform", "win32")

    assert reveal_in_file_manager("D:\\Гобо\\a b\\ell.png") is True

    assert launched == ['explorer /select,"D:\\Гобо\\a b\\ell.png"']


def test_macos_reveals_the_file_in_finder(monkeypatch, launched):
    monkeypatch.setattr(sys, "platform", "darwin")

    assert reveal_in_file_manager("/lib/ell.png") is True

    assert launched == [["open", "-R", "/lib/ell.png"]]


def test_other_systems_open_the_containing_folder(monkeypatch, launched):
    monkeypatch.setattr(sys, "platform", "linux")

    assert reveal_in_file_manager("/lib/sub/ell.png") is True

    assert launched == [["xdg-open", "/lib/sub"]]


def test_launch_failure_returns_false(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")

    def boom(command, **kwargs):
        raise FileNotFoundError("xdg-open")

    monkeypatch.setattr(subprocess, "Popen", boom)

    assert reveal_in_file_manager("/lib/ell.png") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/desktop/test_reveal.py -q`
Expected: FAIL (`ModuleNotFoundError: gmagc_desktop.service.reveal`).

- [ ] **Step 3: Implementation**

```python
# path: apps/desktop/src/gmagc_desktop/service/reveal.py
"""Показ файла в файловом менеджере ОС."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def reveal_in_file_manager(path: str | Path) -> bool:
    """Показывает файл в Проводнике / Finder (на других ОС открывает папку). True, если команда запущена."""
    target = Path(path)
    try:
        if sys.platform == "win32":
            # Проводник разбирает `/select,"путь"` сам: список аргументов заключил бы в кавычки и ключ
            subprocess.Popen(f'explorer /select,"{target}"')
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target.parent)])
    except OSError:
        return False
    return True
```

- [ ] **Step 4: Run tests and ruff**

Run: `.venv\Scripts\python.exe -m pytest -q` и `.venv\Scripts\python.exe -m ruff check .`
Expected: 189 passed (4 новых), ruff чист.

- [ ] **Step 5: Commit**

```bash
git add apps/desktop/src/gmagc_desktop/service/reveal.py tests/desktop/test_reveal.py
git commit -m "feat: reveal a result file in the OS file manager" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: Экран приложения

**Files:**
- Create: `apps/desktop/src/gmagc_desktop/ui/__init__.py` (пустой), `apps/desktop/src/gmagc_desktop/ui/texts.py`, `apps/desktop/src/gmagc_desktop/ui/app.py`
- Modify: `apps/desktop/src/main.py`, `apps/desktop/src/gmagc_desktop/about.py`, `apps/mobile/src/gmagc_mobile/about.py` (версия `0.3.0`), `apps/desktop/pyproject.toml`, `apps/mobile/pyproject.toml` (`version = "0.3.0"`)
- Delete: `apps/desktop/src/gmagc_desktop/app.py` (каркас v0.2), `tests/desktop/test_desktop_app.py`
- Test: `tests/desktop/test_texts.py`, `tests/desktop/test_desktop_ui.py`

**Interfaces:**
- Consumes: `SearchService`, `PhotoError`, `NoIndexError`, `Outcome`, `Result`, `SearchOutcome`, `IndexStatus`, `LOW_CONFIDENCE_SCORE`, `reveal_in_file_manager`, `run_core_check`, `data_dir`.
- Produces: `ui.texts.status_text(status) -> str`, `score_text(score) -> str`, `outcome_message(kind) -> str | None`; `ui.app.DesktopApp(page, service, picker=None, clipboard=None, reveal=reveal_in_file_manager, check=run_core_check)` с обработчиками `on_choose_folder`, `on_rebuild`, `on_pick_photo`, `on_paste` (async), `on_cancel`, `on_check` (sync) и методом `build()`; `ui.app.build_page(page, service=None, **services) -> DesktopApp`. Переменные окружения `GMAGC_DEMO_LIBRARY` и `GMAGC_DEMO_PHOTO` (отладка): при старте выбирают папку, индексируют и ищут по фото.

- [ ] **Step 1: Write the failing tests**

```python
# path: tests/desktop/test_texts.py
from gmagc_desktop.service.results import IndexStatus, Outcome
from gmagc_desktop.ui.texts import outcome_message, score_text, status_text


def test_status_text_for_missing_and_built_indexes():
    assert status_text(None) == "Индекс не построен"
    assert status_text(IndexStatus(11178, 9396, 0, 0)) == "11\u00a0178 файлов, 9\u00a0396 семейств"
    assert status_text(IndexStatus(6, 5, 1, 2)) == (
        "6 файлов, 5 семейств, пропущено 1, нечитаемо сейчас 2 (повторю при обновлении)"
    )


def test_score_is_a_clamped_percentage():
    assert score_text(0.873) == "87.3%"
    assert score_text(1.0004) == "100.0%"
    assert score_text(-0.1) == "0.0%"


def test_outcome_messages():
    assert outcome_message(Outcome.FOUND) is None
    assert "ниже 72%" in outcome_message(Outcome.LOW_CONFIDENCE)
    assert "переснимите" in outcome_message(Outcome.NO_PROJECTION)
```

```python
# path: tests/desktop/test_desktop_ui.py
import asyncio
from types import SimpleNamespace

import cv2
import flet as ft
import numpy as np
import pytest

from gmagc_desktop.about import AUTHOR, NAME, VERSION
from gmagc_desktop.library.index import IndexCancelled
from gmagc_desktop.matcher.synthetic import simulate_photo
from gmagc_desktop.service.search_service import SearchService
from gmagc_desktop.ui.app import build_page
from tests.fixtures import shape_images, write_library


class StubPage:
    """Минимальная замена ft.Page: запоминает добавленное, поток выполняет сразу."""

    def __init__(self):
        self.title = ""
        self.added = []
        self.services = []
        self.updates = 0

    def add(self, *controls):
        self.added.extend(controls)

    def update(self):
        self.updates += 1

    def run_thread(self, handler, *args, **kwargs):
        handler(*args, **kwargs)


class FakePicker:
    def __init__(self, folder=None, files=()):
        self.folder = folder
        self.files = list(files)

    async def get_directory_path(self, dialog_title=None, initial_directory=None):
        return self.folder

    async def pick_files(self, **kwargs):
        return [SimpleNamespace(path=path) for path in self.files]


class FakeClipboard:
    def __init__(self, image=None, files=()):
        self.image = image
        self.files = list(files)

    async def get_image(self):
        return self.image

    async def get_files(self):
        return list(self.files)


def walk(control):
    yield control
    for attribute in ("content", "controls"):
        value = getattr(control, attribute, None)
        for child in value if isinstance(value, list) else [value] if value is not None else []:
            if isinstance(child, ft.Control):
                yield from walk(child)


def texts(control):
    return [c.value for c in walk(control) if isinstance(c, ft.Text)]


@pytest.fixture()
def library(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    write_library(root)
    return root


def make_app(tmp_path, **services):
    page = StubPage()
    app = build_page(page, service=SearchService(tmp_path / "data"), **services)
    return app, page


def save_photo(path, image):
    ok, buffer = cv2.imencode(".png", image)
    path.write_bytes(buffer.tobytes())
    return path


def ell_photo():
    return simulate_photo(shape_images()["ell"], np.random.default_rng(5))


def indexed_app(tmp_path, library, **services):
    app, page = make_app(tmp_path, picker=FakePicker(folder=str(library)), **services)
    asyncio.run(app.on_choose_folder(None))
    return app, page


def test_initial_screen_shows_name_version_author_and_empty_state(tmp_path):
    app, page = make_app(tmp_path)

    shown = " ".join(t for t in texts(page.added[0]) if t)
    assert page.title == f"{NAME} {VERSION}"
    assert NAME in shown and VERSION in shown and AUTHOR in shown
    assert "не выбрана" in shown and "Индекс не построен" in shown
    assert len(page.services) == 2


def test_choosing_a_folder_builds_the_index_and_restores_the_controls(tmp_path, library):
    app, _ = indexed_app(tmp_path, library)

    assert app.status_label.value.startswith("6 файлов, 5 семейств")
    assert app.library_text.value == str(library)
    assert not app.progress.visible and not app.cancel_button.visible and not app.banner.visible
    assert not app.choose_folder_button.disabled and not app.pick_photo_button.disabled


def test_missing_folder_is_reported_in_the_banner(tmp_path):
    app, _ = make_app(tmp_path, picker=FakePicker(folder=str(tmp_path / "nope")))

    asyncio.run(app.on_choose_folder(None))

    assert app.banner.visible and "library folder not found" in app.banner_text.value
    assert app.status_label.value == "Индекс не построен"
    assert not app.choose_folder_button.disabled


def test_rebuild_without_a_library_and_photo_without_an_index_ask_for_a_folder(tmp_path):
    photo = save_photo(tmp_path / "p.png", ell_photo())
    app, _ = make_app(tmp_path, picker=FakePicker(files=[str(photo)]))

    asyncio.run(app.on_rebuild(None))
    assert app.banner.visible and "Сначала выберите папку" in app.banner_text.value

    asyncio.run(app.on_pick_photo(None))
    assert "Сначала выберите папку" in app.banner_text.value


def test_indexing_errors_and_cancel_are_shown_not_raised(tmp_path, library, monkeypatch):
    app, _ = indexed_app(tmp_path, library)

    def cancelled(progress=None, cancel=None):
        raise IndexCancelled()

    monkeypatch.setattr(app.service, "build_index", cancelled)
    asyncio.run(app.on_rebuild(None))
    assert "Индексация отменена" in app.banner_text.value and not app.cancel_button.visible

    def boom(progress=None, cancel=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(app.service, "build_index", boom)
    asyncio.run(app.on_rebuild(None))
    assert "Ошибка индексации: boom" in app.banner_text.value and not app.choose_folder_button.disabled


def test_picked_photo_shows_the_photo_the_projection_and_result_cards(tmp_path, library):
    photo = save_photo(tmp_path / "p.png", ell_photo())
    app, _ = indexed_app(tmp_path, library, picker=None)
    app.picker.files = [str(photo)]

    asyncio.run(app.on_pick_photo(None))

    assert app.photo_holder.visible and app.projection_holder.visible
    assert len(app.results_column.controls) == 5
    first = texts(app.results_column.controls[0])
    assert any(t.endswith(".png") and "ell" in t for t in first) and any(t.endswith("%") for t in first)
    assert not app.pick_photo_button.disabled


def test_flat_photo_shows_the_no_projection_message(tmp_path, library):
    photo = save_photo(tmp_path / "flat.png", np.full((480, 640, 3), 90, np.uint8))
    app, _ = indexed_app(tmp_path, library)
    app.picker.files = [str(photo)]

    asyncio.run(app.on_pick_photo(None))

    assert "Проекция на фото не найдена" in app.banner_text.value and app.results_column.controls == []


def test_clicking_a_result_path_reveals_the_file(tmp_path, library):
    revealed = []
    photo = save_photo(tmp_path / "p.png", ell_photo())
    app, _ = indexed_app(tmp_path, library, reveal=revealed.append)
    app.picker.files = [str(photo)]
    asyncio.run(app.on_pick_photo(None))

    button = next(c for c in walk(app.results_column.controls[0]) if isinstance(c, ft.TextButton))
    button.on_click(None)

    assert len(revealed) == 1 and revealed[0].startswith(str(library)) and revealed[0].endswith(".png")


def test_paste_prefers_an_image_then_a_copied_file_then_reports_an_empty_clipboard(tmp_path, library):
    photo = save_photo(tmp_path / "p.png", ell_photo())
    app, _ = indexed_app(tmp_path, library, clipboard=FakeClipboard(image=photo.read_bytes()))
    asyncio.run(app.on_paste(None))
    assert len(app.results_column.controls) == 5

    app.results_column.controls = []
    app.clipboard.image = None
    app.clipboard.files = [str(tmp_path / "notes.txt"), str(photo)]
    asyncio.run(app.on_paste(None))
    assert len(app.results_column.controls) == 5

    app.results_column.controls = []
    app.clipboard.files = []
    asyncio.run(app.on_paste(None))
    assert "В буфере обмена" in app.banner_text.value and app.results_column.controls == []


def test_core_check_button_shows_the_result(tmp_path):
    app, page = make_app(tmp_path, check=lambda: {"ok": True, "shape": (224, 224), "versions": {"numpy": "9.9"}})

    button = next(c for c in walk(page.added[0]) if isinstance(c, ft.TextButton) and c.content.value == "Проверить ядро")
    button.on_click(None)

    assert "ОК" in app.check_label.value and "numpy: 9.9" in app.check_label.value


def test_demo_variables_run_indexing_and_a_search_at_startup(tmp_path, library, monkeypatch):
    photo = save_photo(tmp_path / "demo.png", ell_photo())
    monkeypatch.setenv("GMAGC_DEMO_LIBRARY", str(library))
    monkeypatch.setenv("GMAGC_DEMO_PHOTO", str(photo))

    app, _ = make_app(tmp_path)

    assert app.status_label.value.startswith("6 файлов") and len(app.results_column.controls) == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/desktop/test_texts.py tests/desktop/test_desktop_ui.py -q`
Expected: FAIL (`ModuleNotFoundError: gmagc_desktop.ui`).

- [ ] **Step 3: Implementation**

```python
# path: apps/desktop/src/gmagc_desktop/ui/texts.py
"""Тексты интерфейса, которые можно проверить без окна."""

from __future__ import annotations

from gmagc_desktop.service.results import LOW_CONFIDENCE_SCORE, IndexStatus, Outcome


def _number(value: int) -> str:
    return f"{value:,}".replace(",", "\u00a0")


def status_text(status: IndexStatus | None) -> str:
    if status is None:
        return "Индекс не построен"
    text = f"{_number(status.files)} файлов, {_number(status.families)} семейств"
    if status.skipped:
        text += f", пропущено {_number(status.skipped)}"
    if status.transient:
        text += f", нечитаемо сейчас {_number(status.transient)} (повторю при обновлении)"
    return text


def score_text(score: float) -> str:
    return f"{min(max(score, 0.0), 1.0) * 100:.1f}%"


def outcome_message(kind: Outcome) -> str | None:
    if kind is Outcome.LOW_CONFIDENCE:
        return f"Оценка ниже {int(LOW_CONFIDENCE_SCORE * 100)}%: похоже, такого гобо в библиотеке нет. Ниже самые близкие."
    if kind is Outcome.NO_PROJECTION:
        return "Проекция на фото не найдена: переснимите ближе, затемните фон."
    return None
```

```python
# path: apps/desktop/src/gmagc_desktop/ui/app.py
"""Экран ПК-приложения: библиотека, индекс, поиск по фото."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import flet as ft

from gmagc_desktop.about import AUTHOR, NAME, VERSION
from gmagc_desktop.library.index import IndexCancelled, LibraryNotFound, LibraryScanError
from gmagc_desktop.selfcheck import run_core_check
from gmagc_desktop.service.results import Outcome, Result, SearchOutcome
from gmagc_desktop.service.reveal import reveal_in_file_manager
from gmagc_desktop.service.search_service import NoIndexError, PhotoError, SearchService
from gmagc_desktop.service.settings import data_dir
from gmagc_desktop.ui.texts import outcome_message, score_text, status_text

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
NO_LIBRARY_HINT = "Сначала выберите папку библиотеки и постройте индекс"


class DesktopApp:
    def __init__(
        self,
        page: ft.Page,
        service: SearchService,
        picker=None,
        clipboard=None,
        reveal: Callable[[str], bool] = reveal_in_file_manager,
        check: Callable[[], dict] = run_core_check,
    ):
        self.page = page
        self.service = service
        self.picker = picker or ft.FilePicker()
        self.clipboard = clipboard or ft.Clipboard()
        self.reveal = reveal
        self.check = check
        self._busy = False
        self._cancel = False

        self.library_text = ft.Text("не выбрана", selectable=True)
        self.status_label = ft.Text("Индекс не построен")
        self.progress = ft.ProgressBar(value=0, visible=False)
        self.progress_label = ft.Text(visible=False)
        self.choose_folder_button = ft.Button("Выбрать папку…", on_click=self.on_choose_folder)
        self.rebuild_button = ft.Button("Обновить индекс", on_click=self.on_rebuild)
        self.cancel_button = ft.Button("Отмена", on_click=self.on_cancel, visible=False)
        self.pick_photo_button = ft.Button("Выбрать фото…", on_click=self.on_pick_photo)
        self.paste_button = ft.Button("Вставить из буфера", on_click=self.on_paste)
        self.banner_text = ft.Text(color=ft.Colors.BLACK)
        self.banner = ft.Container(self.banner_text, padding=10, border_radius=6, visible=False)
        self.photo_holder = ft.Column(visible=False, spacing=4)
        self.projection_holder = ft.Column(visible=False, spacing=4)
        self.results_column = ft.Column(spacing=8)
        self.check_label = ft.Text("")

    # ---- построение экрана -------------------------------------------------
    def build(self) -> None:
        status = self.service.load()
        self.library_text.value = self.service.settings.library_dir or "не выбрана"
        self.status_label.value = status_text(status)
        self.page.services.extend([self.picker, self.clipboard])

        left = ft.Column(
            [
                ft.Text("Библиотека", size=18, weight=ft.FontWeight.BOLD),
                self.library_text,
                self.choose_folder_button,
                self.rebuild_button,
                self.status_label,
                self.progress,
                self.progress_label,
                self.cancel_button,
            ],
            spacing=8,
            width=320,
        )
        right = ft.Column(
            [
                ft.Row([self.pick_photo_button, self.paste_button], spacing=8),
                self.banner,
                ft.Row([self.photo_holder, self.projection_holder], spacing=16, vertical_alignment=ft.CrossAxisAlignment.START),
                ft.Text("Результаты", size=18, weight=ft.FontWeight.BOLD),
                self.results_column,
            ],
            spacing=10,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        )
        footer = ft.Row(
            [
                ft.Text(f"{NAME} {VERSION} · Автор: {AUTHOR}", size=12),
                ft.TextButton(content=ft.Text("Проверить ядро", size=12), on_click=self.on_check),
                self.check_label,
            ],
            spacing=12,
        )
        self.page.add(
            ft.SafeArea(
                ft.Column(
                    [
                        ft.Row([left, ft.VerticalDivider(), right], expand=True, vertical_alignment=ft.CrossAxisAlignment.START),
                        footer,
                    ],
                    expand=True,
                ),
                expand=True,
            )
        )
        demo_photo = os.environ.get("GMAGC_DEMO_PHOTO")
        if demo_photo:
            self.page.run_thread(lambda: self._run_demo(os.environ.get("GMAGC_DEMO_LIBRARY", ""), demo_photo))

    # ---- состояние ---------------------------------------------------------
    def _set_busy(self, busy: bool, *, indexing: bool = False) -> None:
        self._busy = busy
        for button in (self.choose_folder_button, self.rebuild_button, self.pick_photo_button, self.paste_button):
            button.disabled = busy
        self.progress.visible = busy and indexing
        self.progress_label.visible = busy and indexing
        self.cancel_button.visible = busy and indexing
        if not busy or not indexing:
            self.progress.value = 0
        self.page.update()

    def _show_banner(self, text: str, *, error: bool) -> None:
        self.banner_text.value = text
        self.banner.bgcolor = ft.Colors.RED_100 if error else ft.Colors.AMBER_100
        self.banner.visible = True
        self.page.update()

    def _hide_banner(self) -> None:
        self.banner.visible = False

    # ---- индексация --------------------------------------------------------
    async def on_choose_folder(self, _event) -> None:
        folder = await self.picker.get_directory_path(dialog_title="Папка библиотеки гобо")
        if not folder:
            return
        self.service.set_library(folder)
        self.library_text.value = folder
        self.status_label.value = status_text(self.service.status())
        self._start_index()

    async def on_rebuild(self, _event) -> None:
        self._start_index()

    def on_cancel(self, _event) -> None:
        self._cancel = True

    def _start_index(self) -> None:
        if self._busy:
            return
        if not self.service.settings.library_dir:
            self._show_banner(NO_LIBRARY_HINT, error=True)
            return
        self._cancel = False
        self._hide_banner()
        self._set_busy(True, indexing=True)
        self.page.run_thread(self._index_worker)

    def _index_worker(self) -> None:
        try:
            self.service.build_index(progress=self._on_progress, cancel=lambda: self._cancel)
        except IndexCancelled:
            self._show_banner("Индексация отменена", error=False)
        except (LibraryNotFound, LibraryScanError) as error:
            self._show_banner(str(error), error=True)
        except Exception as error:  # noqa: BLE001 - рабочий поток обязан показать причину, а не пропасть
            self._show_banner(f"Ошибка индексации: {error}", error=True)
        finally:
            self.status_label.value = status_text(self.service.status())
            self._set_busy(False)

    def _on_progress(self, done: int, total: int) -> None:
        self.progress.value = done / total if total else 0
        self.progress_label.value = f"Индексация: {done} из {total}"
        self.page.update()

    # ---- поиск -------------------------------------------------------------
    async def on_pick_photo(self, _event) -> None:
        files = await self.picker.pick_files(dialog_title="Фото проекции", file_type=ft.FilePickerFileType.IMAGE)
        if files and files[0].path:
            self._search_bytes_from(Path(files[0].path))

    async def on_paste(self, _event) -> None:
        data = await self.clipboard.get_image()
        if data:
            self._start_search(data)
            return
        for name in await self.clipboard.get_files():
            if Path(name).suffix.lower() in IMAGE_SUFFIXES:
                self._search_bytes_from(Path(name))
                return
        self._show_banner("В буфере обмена нет картинки или файла-изображения", error=True)

    def _search_bytes_from(self, path: Path) -> None:
        try:
            data = path.read_bytes()
        except OSError as error:
            self._show_banner(f"Не удалось прочитать файл: {error}", error=True)
            return
        self._start_search(data)

    def _start_search(self, data: bytes) -> None:
        if self._busy:
            return
        if self.service.status() is None:
            self._show_banner(NO_LIBRARY_HINT, error=True)
            return
        self._hide_banner()
        self._show_photo(data)
        self._set_busy(True)
        self.page.run_thread(lambda: self._search_worker(data))

    def _search_worker(self, data: bytes) -> None:
        try:
            outcome = self.service.search_image_bytes(data)
        except NoIndexError:
            self._show_banner(NO_LIBRARY_HINT, error=True)
        except PhotoError as error:
            self._show_banner(f"Не удалось прочитать фото: {error}", error=True)
        except Exception as error:  # noqa: BLE001 - рабочий поток обязан показать причину, а не пропасть
            self._show_banner(f"Ошибка поиска: {error}", error=True)
        else:
            self._show_outcome(outcome)
        finally:
            self._set_busy(False)

    def _show_photo(self, data: bytes) -> None:
        self.photo_holder.controls = [
            ft.Text("Фото"),
            ft.Image(src=data, width=260, height=200, fit=ft.BoxFit.CONTAIN),
        ]
        self.photo_holder.visible = True
        self.projection_holder.visible = False
        self.results_column.controls = []
        self.page.update()

    def _show_outcome(self, outcome: SearchOutcome) -> None:
        message = outcome_message(outcome.kind)
        if message:
            self._show_banner(message, error=outcome.kind is Outcome.NO_PROJECTION)
        if outcome.projection_png:
            self.projection_holder.controls = [
                ft.Text("Найденная проекция"),
                ft.Image(src=outcome.projection_png, width=160, height=160, fit=ft.BoxFit.CONTAIN),
            ]
        self.projection_holder.visible = bool(outcome.projection_png)
        self.results_column.controls = [self._result_card(result) for result in outcome.results]
        self.page.update()

    def _result_card(self, result: Result) -> ft.Card:
        details: list[ft.Control] = [
            ft.Text(result.name, weight=ft.FontWeight.BOLD),
            ft.TextButton(
                content=ft.Text(result.full_path, size=12),
                tooltip="Показать в папке",
                on_click=lambda _event, path=result.full_path: self.reveal(path),
            ),
            ft.Text(score_text(result.score)),
        ]
        if result.copies:
            details.append(ft.Text(f"ещё {len(result.copies)} файлов", tooltip="\n".join(result.copies)))
        return ft.Card(
            ft.Container(
                ft.Row(
                    [
                        ft.Image(src=result.thumbnail_png, width=96, height=96, fit=ft.BoxFit.CONTAIN),
                        ft.Column(details, spacing=2, expand=True),
                    ],
                    spacing=12,
                ),
                padding=10,
            )
        )

    # ---- прочее ------------------------------------------------------------
    def on_check(self, _event) -> None:
        info = self.check()
        head = "ОК: ядро работает" if info["ok"] else "ОШИБКА: ядро не сработало"
        self.check_label.value = head + ", " + ", ".join(f"{name}: {value}" for name, value in info["versions"].items())
        self.page.update()

    def _run_demo(self, library: str, photo: str) -> None:
        """Отладка: GMAGC_DEMO_LIBRARY / GMAGC_DEMO_PHOTO запускают индексацию и поиск при старте."""
        self._set_busy(True, indexing=True)
        if library:
            self.service.set_library(library)
            self.library_text.value = library
        self._index_worker()
        self._set_busy(True)
        data = Path(photo).read_bytes()
        self._show_photo(data)
        self._search_worker(data)


def build_page(page: ft.Page, service: SearchService | None = None, **services) -> DesktopApp:
    page.title = f"{NAME} {VERSION}"
    window = getattr(page, "window", None)
    if window is not None:
        window.width, window.height = 1100, 760
    app = DesktopApp(page, service or SearchService(data_dir()), **services)
    app.build()
    return app
```

```python
# path: apps/desktop/src/main.py
"""Точка входа ПК-приложения для `flet build`."""

import flet as ft

from gmagc_desktop.ui.app import build_page

ft.run(build_page)
```

Пустой `apps/desktop/src/gmagc_desktop/ui/__init__.py` создаётся отдельно (`touch`). Версия `0.3.0`:

```bash
sed -i 's/VERSION = "0.2.1"/VERSION = "0.3.0"/' apps/desktop/src/gmagc_desktop/about.py apps/mobile/src/gmagc_mobile/about.py
sed -i 's/^version = "0.2.1"/version = "0.3.0"/' apps/desktop/pyproject.toml apps/mobile/pyproject.toml
git rm -q apps/desktop/src/gmagc_desktop/app.py tests/desktop/test_desktop_app.py
```

- [ ] **Step 4: Run tests and ruff**

Run: `.venv\Scripts\python.exe -m pytest -q` и `.venv\Scripts\python.exe -m ruff check .`
Expected: все тесты проходят (189 минус 3 удалённых теста каркаса плюс 14 новых), ruff чист. Если тест на заглушке падает из-за конструктора элемента Flet, поправить код по сообщению об ошибке, не ослабляя проверку.

- [ ] **Step 5: Commit**

```bash
git add -A apps tests
git commit -m "feat: desktop screen with library, indexing and photo search" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6: Проверка сборкой и снимком окна, релиз v0.3.0

**Files:**
- Create: `scripts/capture_window.ps1`
- Modify: `README.md`

- [ ] **Step 1: Помощник «снимок окна»**

```powershell
# path: scripts/capture_window.ps1
# Снимок окна процесса (только область его окна): .\scripts\capture_window.ps1 -Process gmagc-desktop -Out window.png
param([string]$Process = "gmagc-desktop", [string]$Out = "window.png")

Add-Type -AssemblyName System.Drawing
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class GmagcWin32 {
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int cmd);
}
"@

$p = Get-Process $Process -ErrorAction Stop | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $p) { throw "Окно процесса $Process не найдено" }
[GmagcWin32]::ShowWindow($p.MainWindowHandle, 9) | Out-Null
[GmagcWin32]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
Start-Sleep -Milliseconds 700
$r = New-Object GmagcWin32+RECT
[GmagcWin32]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
$width = $r.Right - $r.Left
$height = $r.Bottom - $r.Top
$bitmap = New-Object System.Drawing.Bitmap $width, $height
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($r.Left, $r.Top, 0, 0, $bitmap.Size)
$bitmap.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$graphics.Dispose()
$bitmap.Dispose()
Write-Host "Снимок окна: $Out ($width x $height)"
```

Windows PowerShell 5.1 читает файл без BOM как ANSI: сохранить с BOM (`.venv\Scripts\python.exe -c "from pathlib import Path; p=Path('scripts/capture_window.ps1'); p.write_text(p.read_text(encoding='utf-8'), encoding='utf-8-sig', newline='\r\n')"`).

- [ ] **Step 2: Локальная сборка и проверка на реальных данных**

Сборка: `.\scripts\build_windows.ps1` (окружение `.venv312`, ~30 с). Запуск собранного приложения с отладочными переменными и изолированными настройками (реальные настройки пользователя не трогаются):

```powershell
$env:GMAGC_DATA_DIR = "$env:TEMP\gmagc_demo"
$env:GMAGC_DEMO_LIBRARY = "C:\Users\ANDYBUM\GMAGC\gobos"
$env:GMAGC_DEMO_PHOTO = (Get-ChildItem C:\Users\ANDYBUM\GMAGC\photo -Filter "photo_13*.jpg").FullName
Start-Process .\apps\desktop\build\windows\gmagc-desktop.exe
# индексация 11 тыс. файлов около минуты; затем снимок только окна приложения
Start-Sleep -Seconds 90
.\scripts\capture_window.ps1 -Out .gmagc-cache\window.png
```
Посмотреть `.gmagc-cache\window.png`: слева папка и статус индекса, справа исходное фото, найденная проекция и список результатов с превью и путями; при расхождении с ожидаемым видом исправить `ui/app.py` (правка, `build_windows.ps1`, снимок) до приемлемого вида. Проверить, что во время индексации прогресс обновлялся (обновление из рабочего потока работает), в `%LOCALAPPDATA%\@ANDY_BUM\GMAGC\console.log` нет `Traceback`.

- [ ] **Step 3: README, Pull Request, релиз**

В `README.md` обновить статус (ПК-приложение с поиском, v0.3.0), описание раздела «Сборки» (что делает приложение) и раздел «Локальная разработка» (`capture_window.ps1`, переменные `GMAGC_DEMO_LIBRARY` / `GMAGC_DEMO_PHOTO`, `GMAGC_DATA_DIR`). Затем:

```bash
git add -A README.md scripts docs apps tests
git commit -m "docs: describe the desktop search app and add the window capture helper" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
git push -u origin feat/desktop-search
gh pr create --base main --head feat/desktop-search --title "ПК-приложение с поиском по фото (этап 3)" --body "Слой сервиса и экран Flet: выбор библиотеки, индексация с прогрессом, поиск по фото или из буфера, результаты с превью и кликабельными путями. Автор: @ANDY_BUM."
```

Ожидание `gh run list --branch feat/desktop-search`: `ci.yml` (3 ОС) и три сборки (с дымовой проверкой запуска) зелёные. Слияние `gh pr merge --squash --delete-branch`, затем `git switch main && git pull`, тег `git tag -a v0.3.0 -m "GMAGC v0.3.0: desktop app with photo search"` и `git push origin v0.3.0`. После зелёных сборок по тегу: `gh release view v0.3.0` (три файла и три `.sha256`), скачать, сверить суммы, запустить Windows-архив, заменить автоописание релиза (что нового, как запустить, ограничения) через `gh release edit v0.3.0 --notes-file`.

---

## Самопроверка плана

**Покрытие спецификации:** слой сервиса (настройки, результаты, сервис, показ файла) → Tasks 2–4; отложенные исправления ядра (обрезанные PNG, проверка путей, `update_index`, уникальный временный файл) и общая миниатюра → Task 1; экран, порог 72%, предупреждения, ошибки, кнопки выбора/вставки, клик по пути → Task 5; проверка сборкой, снимок окна и релиз → Task 6. Не входят по спецификации: сервер и лента телефона, QR, перетаскивание из ОС, число результатов в интерфейсе.
**Согласованность имён:** `update_index`, `thumbnail_png`, `square_pad`, `SearchService.{load,set_library,build_index,status,search_photo,search_file,search_image_bytes}`, `PhotoError`, `NoIndexError`, `Outcome`, `Result`, `SearchOutcome`, `IndexStatus`, `LOW_CONFIDENCE_SCORE`, `DesktopApp.{on_choose_folder,on_rebuild,on_cancel,on_pick_photo,on_paste,on_check,build}`, `build_page(page, service=None, **services)` совпадают между тестами и кодом.
