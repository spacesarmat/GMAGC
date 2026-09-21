# GMAGC Core: распознавание, индекс библиотеки, бенчмарк и CLI. План реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Автономное ядро: по фото проекции найти похожие гобо в папке-библиотеке (индексация, поиск, бенчмарк, CLI). Без UI и сервера.

**Architecture:** Пайплайн `фото → сегментация проекции → нормализация 224×224 → 48 вариантов запроса (24 поворота × зеркало) → эмбеддинги (ONNX или пиксельный baseline) → косинусный поиск по индексу → мягкое сравнение формы для top-20 → группировка дублей`. Ядро не знает про UI и HTTP. Эмбеддер и индекс сменные.

**Tech Stack:** Python (dev на установленном 3.14, код совместим с ≥3.12), numpy, opencv-python-headless, onnxruntime, Pillow; pytest, ruff, onnx (только тесты).

**Spec:** `docs/superpowers/specs/2026-09-19-gmagc-gobo-recognizer-design.md` (разделы 4, 6, 9, 12 этап 1–2). Серверу, UI, мобильному клиенту и CI посвящены отдельные планы, они пишутся после первых замеров из этого плана.

## Global Constraints

- Полностью офлайн: ни индексация, ни поиск не обращаются к интернету (интернет допустим только в dev-скрипте загрузки модели).
- Рантайм-зависимости только: numpy, opencv-python-headless, onnxruntime, Pillow. PyTorch в рантайме не используется.
- Библиотека `gobos/` (11 192 файла, PNG+BMP) и фото `photo/` **не коммитятся** (`.gitignore`); тесты и CI используют только синтетические данные.
- Формат библиотеки: PNG и BMP; у ~80% PNG прозрачный фон, композитим на **чёрный**; служебные файлы игнорируются (`question.bmp`).
- Нормализация обеих сторон: сдвиг по центроиду яркой области, масштаб по 99,5-му перцентилю расстояний от центроида (близко к описанной окружности, но устойчиво к шуму), квадрат **224×224**, серые уровни сохраняются, вне области чёрный.
- Повороты и зеркало применяются к **запросу**: 24 поворота × зеркало = 48 вариантов. В индексе один вектор на файл, кэш `float16`.
- Уточнение формы для top-K (по умолчанию **20**), выдача top-N (по умолчанию **10**).
- Фото перед сегментацией уменьшается до ~1024 px по длинной стороне.
- Правильный результат считается по «семейству» дублей, а не по конкретному файлу.
- Коммиты: `git commit -m "<тип>: <описание>" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"`.

---

## Структура файлов

```
pyproject.toml                         конфиг pytest/ruff (без сборки)
requirements-dev.txt
apps/desktop/gmagc_desktop/
  __init__.py
  cli.py                               index / search
  matcher/
    __init__.py
    imageio.py                         загрузка файлов библиотеки и фото
    normalize.py                       нормализация 224×224
    synthetic.py                       симулятор «фото проекции» (тесты, бенчмарк)
    segment.py                         поиск проекции на фото
    variants.py                        повороты и зеркало
    embedder.py                        PixelEmbedder, OnnxEmbedder
    shape.py                           soft_mask, ShapeMatcher
    search.py                          SearchData, Searcher
  library/
    __init__.py
    scan.py                            обход папки
    grouping.py                        группировка дублей
    index.py                           LibraryIndex: сборка, кэш, дозапись
scripts/
  fetch_model.py                       скачивание ONNX-модели (dev)
  benchmark.py                         замер top-1/top-5
  report_photos.py                     HTML-отчёт по реальным фото
tests/
  helpers.py
  matcher/test_*.py   library/test_*.py   test_cli.py
docs/benchmarks/                       результаты замеров
```

---

### Task 1: Окружение, каркас и загрузка изображений

**Files:**
- Create: `pyproject.toml`, `requirements-dev.txt`, `apps/desktop/gmagc_desktop/__init__.py`, `apps/desktop/gmagc_desktop/matcher/__init__.py`, `apps/desktop/gmagc_desktop/library/__init__.py`, `apps/desktop/gmagc_desktop/matcher/imageio.py`
- Test: `tests/matcher/test_imageio.py`

**Interfaces:**
- Produces:
  - `LIBRARY_EXTENSIONS: frozenset[str]` (`{".png", ".bmp"}`), `IGNORED_LIBRARY_NAMES: frozenset[str]` (`{"question.bmp"}`)
  - `load_library_gray(path: str | Path) -> np.ndarray` (uint8, 2D, прозрачность на чёрном)
  - `load_photo_bgr(path: str | Path) -> np.ndarray` (uint8, HxWx3, BGR; работает с не-ASCII путями, применяет EXIF-ориентацию) Пустой файл даёт `ValueError` (а не `cv2.error`).

- [ ] **Step 1: Каркас и зависимости**

`pyproject.toml`:

```toml
[tool.pytest.ini_options]
pythonpath = ["apps/desktop", "."]
testpaths = ["tests"]

[tool.ruff]
line-length = 125
target-version = "py312"
src = ["apps/desktop", "."]

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP"]

[tool.ruff.lint.per-file-ignores]
"scripts/*.py" = ["E402", "I001"]  # sys.path подменяется до импортов намеренно
"tests/test_scripts.py" = ["E402", "I001"]
"tests/test_thumbs.py" = ["E402", "I001"]
```

`requirements-dev.txt`:

```
numpy
opencv-python-headless
onnxruntime
onnx
Pillow
pytest
ruff
```

Три пустых `__init__.py` (`gmagc_desktop`, `matcher`, `library`) создаются пустыми файлами. Установка в существующий пустой `.venv`:

Run: `.venv\Scripts\python.exe -m pip install -r requirements-dev.txt`
Expected: установка без ошибок.

- [ ] **Step 2: Write the failing test**

```python
# path: tests/matcher/test_imageio.py
import numpy as np
import pytest
from PIL import Image

from gmagc_desktop.matcher.imageio import load_library_gray, load_photo_bgr


def test_transparent_background_becomes_black_even_if_rgb_is_white(tmp_path):
    image = Image.new("RGBA", (32, 32), (255, 255, 255, 0))
    for x in range(10, 20):
        for y in range(10, 20):
            image.putpixel((x, y), (255, 255, 255, 255))
    path = tmp_path / "g.png"
    image.save(path)

    gray = load_library_gray(path)

    assert gray.dtype == np.uint8 and gray.shape == (32, 32)
    assert gray[0, 0] == 0
    assert gray[15, 15] == 255


def test_palette_png_with_transparency(tmp_path):
    image = Image.new("P", (16, 16), 0)
    image.putpalette([255, 255, 255] + [0, 0, 0] * 255)
    image.info["transparency"] = 0
    path = tmp_path / "p.png"
    image.save(path, transparency=0)

    gray = load_library_gray(path)

    assert gray.shape == (16, 16)
    assert gray.max() == 0


def test_bmp_and_grayscale_modes(tmp_path):
    Image.new("RGB", (8, 8), (200, 200, 200)).save(tmp_path / "a.bmp")
    Image.new("L", (8, 8), 90).save(tmp_path / "b.png")

    assert load_library_gray(tmp_path / "a.bmp")[0, 0] == 200
    assert load_library_gray(tmp_path / "b.png")[0, 0] == 90


def test_photo_is_bgr_and_non_ascii_path_works(tmp_path):
    path = tmp_path / "фото.png"
    Image.new("RGB", (10, 6), (255, 0, 0)).save(path)  # красный в RGB

    bgr = load_photo_bgr(path)

    assert bgr.shape == (6, 10, 3)
    assert tuple(bgr[0, 0]) == (0, 0, 255)  # красный в BGR


def test_empty_photo_file_raises_value_error(tmp_path):
    path = tmp_path / "empty.jpg"
    path.write_bytes(b"")
    with pytest.raises(ValueError):
        load_photo_bgr(path)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/matcher/test_imageio.py -v`
Expected: FAIL (`ModuleNotFoundError: gmagc_desktop.matcher.imageio`).

- [ ] **Step 4: Write minimal implementation**

```python
# path: apps/desktop/gmagc_desktop/matcher/imageio.py
"""Загрузка файлов библиотеки и фото в numpy-массивы."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image

LIBRARY_EXTENSIONS = frozenset({".png", ".bmp"})
IGNORED_LIBRARY_NAMES = frozenset({"question.bmp"})


def load_library_gray(path: str | Path) -> np.ndarray:
    """Файл гобо -> uint8 2D. Прозрачность композитится на чёрный."""
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
    canvas = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
    canvas.alpha_composite(rgba)
    return np.array(canvas.convert("L"), dtype=np.uint8)


def load_photo_bgr(path: str | Path) -> np.ndarray:
    """Фото -> uint8 HxWx3 BGR (с учётом EXIF-ориентации, поддерживает не-ASCII пути)."""
    data = np.fromfile(str(path), dtype=np.uint8)
    if data.size == 0:
        raise ValueError(f"cannot decode image: {path}")
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"cannot decode image: {path}")
    return image
```

- [ ] **Step 5: Run test to verify it passes, commit**

Run: `.venv\Scripts\python.exe -m pytest tests/matcher/test_imageio.py -v`
Expected: 5 passed.

```bash
git add pyproject.toml requirements-dev.txt apps tests
git commit -m "feat: scaffold core package and image loading" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: Нормализация 224×224

**Files:**
- Create: `apps/desktop/gmagc_desktop/matcher/normalize.py`, `tests/helpers.py`
- Test: `tests/matcher/test_normalize.py`

**Interfaces:**
- Consumes: ничего.
- Produces:
  - `NORM_SIZE = 224`
  - `normalize_gray(gray: np.ndarray, size: int = 224, fill: float = 0.45) -> np.ndarray | None`: uint8 `(size, size)`; `None`, если яркой области нет.
  - (`tests/helpers.py`) `l_shape(canvas: tuple[int, int], scale: float, offset: tuple[int, int]) -> np.ndarray`, `sample_gobo(size: int = 256) -> np.ndarray`, `iou(a, b) -> float`.

- [ ] **Step 1: Write the failing test и общие хелперы тестов**

```python
# path: tests/helpers.py
"""Синтетические фигуры для тестов."""

import cv2
import numpy as np

_L_POINTS = np.array([(50, 50), (90, 50), (90, 180), (200, 180), (200, 220), (50, 220)])


def l_shape(canvas=(300, 300), scale=1.0, offset=(0, 0)) -> np.ndarray:
    """Белая асимметричная L-фигура на чёрном (canvas = (высота, ширина))."""
    image = np.zeros(canvas, np.uint8)
    points = (_L_POINTS * scale + np.array(offset)).astype(np.int32)
    cv2.fillPoly(image, [points], 255)
    return image


def sample_gobo(size=256) -> np.ndarray:
    """Асимметричное «гобо»: кольцо, точки и сектор на чёрном диске."""
    image = np.zeros((size, size), np.uint8)
    c = size // 2
    cv2.circle(image, (c, c), int(size * 0.40), 255, max(2, size // 20))
    cv2.circle(image, (c + size // 5, c - size // 8), size // 12, 255, -1)
    cv2.circle(image, (c - size // 4, c + size // 6), size // 20, 255, -1)
    cv2.ellipse(image, (c, c), (size // 6, size // 12), 30, 0, 200, 255, -1)
    return image


def iou(a: np.ndarray, b: np.ndarray, threshold: int = 127) -> float:
    a, b = a > threshold, b > threshold
    union = np.logical_or(a, b).sum()
    return float(np.logical_and(a, b).sum() / union) if union else 0.0
```

```python
# path: tests/matcher/test_normalize.py
import numpy as np

from gmagc_desktop.matcher.normalize import NORM_SIZE, normalize_gray
from tests.helpers import iou, l_shape


def test_output_shape_and_dtype():
    out = normalize_gray(l_shape())
    assert out.shape == (NORM_SIZE, NORM_SIZE) and out.dtype == np.uint8


def test_invariant_to_shift_and_scale():
    a = normalize_gray(l_shape((300, 300), 1.0, (0, 0)))
    b = normalize_gray(l_shape((200, 260), 0.5, (20, 15)))
    assert iou(a, b) > 0.9


def test_blank_image_returns_none():
    assert normalize_gray(np.zeros((64, 64), np.uint8)) is None


def test_shape_fits_into_canvas():
    out = normalize_gray(l_shape())
    ys, xs = np.nonzero(out > 127)
    assert xs.min() > 0 and ys.min() > 0
    assert xs.max() < NORM_SIZE - 1 and ys.max() < NORM_SIZE - 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/matcher/test_normalize.py -v`
Expected: FAIL (`ModuleNotFoundError: gmagc_desktop.matcher.normalize`).

- [ ] **Step 3: Write minimal implementation**

```python
# path: apps/desktop/gmagc_desktop/matcher/normalize.py
"""Приведение изображения к канонической форме: центр, масштаб, размер."""

from __future__ import annotations

import cv2
import numpy as np

NORM_SIZE = 224
FILL = 0.45
MIN_THRESHOLD = 40
MIN_BRIGHT_PIXELS = 20
MIN_RADIUS = 2.0


def bright_mask(gray: np.ndarray) -> np.ndarray:
    """Булева маска «светлой» области (Otsu, но не ниже MIN_THRESHOLD)."""
    threshold, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return gray > max(threshold, MIN_THRESHOLD)


def normalize_gray(
    gray: np.ndarray, size: int = NORM_SIZE, fill: float = FILL
) -> np.ndarray | None:
    """Центр по центроиду яркой области, радиус 99.5-го перцентиля = fill*size.

    Серые уровни сохраняются, пустое место чёрное. None, если яркой области нет.
    """
    ys, xs = np.nonzero(bright_mask(gray))
    if xs.size < MIN_BRIGHT_PIXELS:
        return None
    cx, cy = float(xs.mean()), float(ys.mean())
    radius = float(np.percentile(np.hypot(xs - cx, ys - cy), 99.5))
    if radius < MIN_RADIUS:
        return None
    scale = fill * size / radius
    matrix = np.array(
        [[scale, 0.0, size / 2 - scale * cx], [0.0, scale, size / 2 - scale * cy]],
        dtype=np.float32,
    )
    return cv2.warpAffine(gray, matrix, (size, size), flags=cv2.INTER_LINEAR, borderValue=0)
```

- [ ] **Step 4: Run test to verify it passes, commit**

Run: `.venv\Scripts\python.exe -m pytest tests/matcher/test_normalize.py -v`
Expected: 4 passed.

```bash
git add apps tests
git commit -m "feat: add gray-level normalization to 224x224" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: Симулятор фото и сегментация проекции

**Files:**
- Create: `apps/desktop/gmagc_desktop/matcher/synthetic.py`, `apps/desktop/gmagc_desktop/matcher/segment.py`
- Test: `tests/matcher/test_segment.py`

**Interfaces:**
- Consumes: `tests.helpers.sample_gobo`.
- Produces:
  - `simulate_photo(gobo_gray: np.ndarray, rng: np.random.Generator, width: int = 1280, height: int = 960) -> np.ndarray`: BGR uint8 «фото проекции» (стена, шум, потолочные окна, луч света, поворот/зеркало/перспектива/размытие, оранжевый блик).
  - `extract_projection(bgr: np.ndarray) -> np.ndarray | None`: uint8 gray, обрезка по найденной проекции, вне неё чёрный; `None`, если проекции нет.

Параметры сегментации проверены на 17 реальных фото из `photo/` (прототип): порог = `max(Otsu, 0.75 × p99.5 яркости)`, насыщенность < 110, слияние пятен дилатацией ~6% стороны, выбор кластера по «яркостному весу».

- [ ] **Step 1: Write the failing test**

```python
# path: tests/matcher/test_segment.py
import cv2
import numpy as np

from gmagc_desktop.matcher.segment import extract_projection
from gmagc_desktop.matcher.synthetic import simulate_photo
from tests.helpers import sample_gobo


def test_finds_projection_on_cluttered_wall():
    photo = simulate_photo(sample_gobo(), np.random.default_rng(1))
    crop = extract_projection(photo)
    assert crop is not None
    assert 120 < max(crop.shape) < 420  # ~30-40% высоты кадра после уменьшения до 1024 px
    assert (crop > 0).mean() > 0.05


def test_many_seeds_never_pick_the_background():
    for seed in range(12):
        photo = simulate_photo(sample_gobo(), np.random.default_rng(seed))
        crop = extract_projection(photo)
        assert crop is not None, seed
        assert 120 < max(crop.shape) < 420, seed


def test_returns_none_for_flat_photo():
    flat = np.full((480, 640, 3), 90, np.uint8)
    assert extract_projection(flat) is None


def test_close_up_projection_filling_the_frame_is_still_found():
    image = np.zeros((480, 640, 3), np.uint8)
    cv2.circle(image, (320, 240), 230, (255, 240, 220), 40)
    assert extract_projection(image) is not None


def _two_blobs(edge_gap: int) -> np.ndarray:
    """Two equal bright discs (radius 60) whose facing edges are `edge_gap` px apart on a 1024x768 frame."""
    image = np.full((768, 1024, 3), 60, np.uint8)
    color = (255, 245, 235)
    cv2.circle(image, (300, 384), 60, color, -1)
    cv2.circle(image, (300 + 120 + edge_gap, 384), 60, color, -1)
    return image


def test_nearby_blobs_are_merged_into_one_crop():
    crop = extract_projection(_two_blobs(edge_gap=20))  # 20 px < merge kernel (6% of 1024 = 61 px)
    assert crop is not None
    assert crop.shape[1] >= 250  # spans both discs (about 260 px wide)


def test_distant_blobs_are_not_merged():
    crop = extract_projection(_two_blobs(edge_gap=200))  # 200 px > merge kernel
    assert crop is not None
    assert crop.shape[1] < 150  # only one disc (about 120 px wide)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/matcher/test_segment.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Write the simulator**

```python
# path: apps/desktop/gmagc_desktop/matcher/synthetic.py
"""Симулятор фото проекции гобо на стене (для тестов и бенчмарка)."""

from __future__ import annotations

import cv2
import numpy as np

TINT_BGR = np.array([1.0, 0.96, 0.85], dtype=np.float32)  # голубовато-белый свет
WALL_BGR = np.array([0.95, 1.0, 1.02], dtype=np.float32)


def _wall(rng: np.random.Generator, width: int, height: int) -> np.ndarray:
    gradient = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None]
    base = 80.0 + 30.0 * gradient + rng.normal(0.0, 5.0, (height, width)).astype(np.float32)
    base = cv2.GaussianBlur(base, (0, 0), 2.0)
    photo = base[:, :, None] * WALL_BGR
    for x in range(0, width, 64):  # потолочные окна: светлые, но темнее проекции
        photo[int(0.03 * height) : int(0.15 * height), x : x + 40] += 55.0
    xs = np.arange(width, dtype=np.float32)[None, :]
    ys = np.linspace(1.0, 0.0, int(0.45 * height), dtype=np.float32)[:, None]
    shaft = 45.0 * np.exp(-(((xs - width * 0.47) / (width * 0.02)) ** 2)) * ys  # луч света
    photo[: shaft.shape[0]] += shaft[:, :, None]
    return photo


def simulate_photo(
    gobo_gray: np.ndarray, rng: np.random.Generator, width: int = 1280, height: int = 960
) -> np.ndarray:
    """BGR uint8 «фото» гобо: поворот, зеркало, перспектива, размытие, шум, блик."""
    photo = _wall(rng, width, height)

    side = int(rng.uniform(0.28, 0.40) * height)
    gh, gw = gobo_gray.shape
    fit = side / max(gh, gw)
    patch = cv2.resize(
        gobo_gray,
        (max(1, round(gw * fit)), max(1, round(gh * fit))),
        interpolation=cv2.INTER_AREA,
    )
    canvas = np.zeros((side, side), np.uint8)
    y0, x0 = (side - patch.shape[0]) // 2, (side - patch.shape[1]) // 2
    canvas[y0 : y0 + patch.shape[0], x0 : x0 + patch.shape[1]] = patch
    if rng.random() < 0.5:
        canvas = np.ascontiguousarray(canvas[:, ::-1])

    angle = np.deg2rad(rng.uniform(0.0, 360.0))
    rotation = np.array(
        [[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]], dtype=np.float32
    )
    centre = np.array(
        [
            width * 0.5 + rng.uniform(-0.08, 0.08) * width,
            height * 0.45 + rng.uniform(-0.05, 0.05) * height,
        ],
        dtype=np.float32,
    )
    corners = np.array([(-1, -1), (1, -1), (1, 1), (-1, 1)], dtype=np.float32) * (side / 2)
    dst = centre + corners @ rotation.T + rng.uniform(-0.03, 0.03, (4, 2)) * side
    src = np.array([(0, 0), (side, 0), (side, side), (0, side)], dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(src, dst.astype(np.float32))
    layer = cv2.warpPerspective(canvas, matrix, (width, height), flags=cv2.INTER_LINEAR)
    layer = cv2.GaussianBlur(layer.astype(np.float32) / 255.0, (0, 0), rng.uniform(0.8, 2.0))

    photo += rng.uniform(150.0, 200.0) * layer[:, :, None] * TINT_BGR
    photo += rng.normal(0.0, 3.0, photo.shape).astype(np.float32)
    photo = np.clip(photo, 0, 255).astype(np.uint8)

    if rng.random() < 0.5:  # оранжевый блик у нижнего края проекции
        centre_x = int(centre[0] + rng.uniform(-0.1, 0.1) * side)
        cv2.ellipse(
            photo,
            (centre_x, int(centre[1] + 0.5 * side)),
            (int(0.18 * side), int(0.05 * side)),
            0,
            0,
            360,
            (40, 130, 230),
            -1,
        )
    return photo
```

- [ ] **Step 4: Write the segmentation**

```python
# path: apps/desktop/gmagc_desktop/matcher/segment.py
"""Поиск проекции гобо на фото: яркая малонасыщенная область, пятна сливаются в один кластер."""

from __future__ import annotations

import cv2
import numpy as np

MAX_SIDE = 1024
MAX_SATURATION = 110
P995_FRACTION = 0.75
MIN_AREA_FRACTION = 0.002
MERGE_FRACTION = 0.06
MIN_MERGE_KERNEL = 9
MIN_DYNAMIC_RANGE = 40  # p99.5 - p5 яркости; меньше значит «в кадре нет проекции»


def extract_projection(bgr: np.ndarray) -> np.ndarray | None:
    """Вырезка проекции (gray, вне найденной области чёрный) или None."""
    height, width = bgr.shape[:2]
    scale = MAX_SIDE / max(height, width)
    if scale < 1.0:
        bgr = cv2.resize(
            bgr, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA
        )
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    value = cv2.GaussianBlur(hsv[:, :, 2], (0, 0), 1.5)

    low, high = np.percentile(value, [5.0, 99.5])
    if high - low < MIN_DYNAMIC_RANGE:
        return None
    otsu, _ = cv2.threshold(value, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    threshold = max(float(otsu), P995_FRACTION * float(high))
    mask = ((value > threshold) & (saturation < MAX_SATURATION)).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    if not mask.any():
        return None

    kernel = max(MIN_MERGE_KERNEL, int(MERGE_FRACTION * max(mask.shape)))
    merged = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel, kernel)))
    count, labels, _, _ = cv2.connectedComponentsWithStats(merged, connectivity=8)

    foreground = mask > 0
    weight = np.clip(value.astype(np.float32) - threshold, 0.0, None)
    scores = np.bincount(labels[foreground], weights=weight[foreground], minlength=count)
    scores[0] = 0.0
    best = int(scores.argmax())
    if scores[best] <= 0.0:
        return None

    selected = (labels == best) & foreground
    if selected.sum() < MIN_AREA_FRACTION * selected.size:
        return None
    ys, xs = np.nonzero(selected)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    return np.where(selected[y0:y1, x0:x1], gray[y0:y1, x0:x1], 0).astype(np.uint8)
```

- [ ] **Step 5: Run tests, commit**

Run: `.venv\Scripts\python.exe -m pytest tests/matcher/test_segment.py -v`
Expected: 6 passed. Если `test_many_seeds...` падает на конкретном seed, отладить симулятор/пороги на этом seed (не ослаблять диапазон размеров).

```bash
git add apps tests
git commit -m "feat: add photo simulator and projection segmentation" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: Повороты и зеркало запроса

**Files:**
- Create: `apps/desktop/gmagc_desktop/matcher/variants.py`
- Test: `tests/matcher/test_variants.py`

**Interfaces:**
- Consumes: ничего.
- Produces:
  - `DEFAULT_ROTATIONS = 24`
  - `rotate_image(image: np.ndarray, angle_degrees: float) -> np.ndarray`: поворот вокруг центра `((w-1)/2, (h-1)/2)`, положительный угол против часовой стрелки, чёрные поля.
  - `query_variants(image: np.ndarray, n_rotations: int = 24, mirror: bool = True) -> np.ndarray`: форма `(V, H, W)`; сначала `n_rotations` поворотов оригинала (индекс 0 это оригинал), затем столько же для зеркала (отражение по горизонтали).
  - `variant_pose(index: int, n_rotations: int = 24) -> tuple[float, bool]`: `(угол, зеркало)` для индекса варианта.

- [ ] **Step 1: Write the failing test**

```python
# path: tests/matcher/test_variants.py
import numpy as np

from gmagc_desktop.matcher.variants import query_variants, rotate_image, variant_pose
from tests.helpers import l_shape


def test_variant_count_and_shape():
    image = l_shape((64, 64), 0.2, (0, 0))
    assert query_variants(image).shape == (48, 64, 64)
    assert query_variants(image, n_rotations=12, mirror=False).shape == (12, 64, 64)


def test_first_variant_is_original_and_second_block_is_mirrored():
    image = l_shape((64, 64), 0.2, (0, 0))
    variants = query_variants(image)
    assert np.array_equal(variants[0], image)
    assert np.array_equal(variants[24], image[:, ::-1])


def test_rotate_90_matches_numpy_rot90():
    image = l_shape((300, 300))
    diff = np.abs(rotate_image(image, 90).astype(int) - np.rot90(image, 1).astype(int))
    assert diff.mean() < 2


def test_variant_pose_maps_index_to_angle_and_mirror():
    assert variant_pose(0) == (0.0, False)
    assert variant_pose(1) == (15.0, False)
    assert variant_pose(24) == (0.0, True)
    assert variant_pose(25) == (15.0, True)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/matcher/test_variants.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Write minimal implementation**

```python
# path: apps/desktop/gmagc_desktop/matcher/variants.py
"""Повороты и зеркало запроса: гобо вращается и проецируется зеркально."""

from __future__ import annotations

import cv2
import numpy as np

DEFAULT_ROTATIONS = 24


def rotate_image(image: np.ndarray, angle_degrees: float) -> np.ndarray:
    """Поворот вокруг центра, положительный угол против часовой стрелки."""
    height, width = image.shape[:2]
    matrix = cv2.getRotationMatrix2D(
        ((width - 1) / 2.0, (height - 1) / 2.0), float(angle_degrees), 1.0
    )
    return cv2.warpAffine(image, matrix, (width, height), flags=cv2.INTER_LINEAR, borderValue=0)


def query_variants(
    image: np.ndarray, n_rotations: int = DEFAULT_ROTATIONS, mirror: bool = True
) -> np.ndarray:
    """Все повороты оригинала, затем (если mirror) все повороты зеркального отражения."""
    bases = [image]
    if mirror:
        bases.append(np.ascontiguousarray(image[:, ::-1]))
    variants = []
    for base in bases:
        for k in range(n_rotations):
            variants.append(base if k == 0 else rotate_image(base, k * 360.0 / n_rotations))
    return np.stack(variants)


def variant_pose(index: int, n_rotations: int = DEFAULT_ROTATIONS) -> tuple[float, bool]:
    """(угол, зеркало) для индекса из query_variants."""
    mirrored, k = divmod(index, n_rotations)
    return k * 360.0 / n_rotations, bool(mirrored)
```

- [ ] **Step 4: Run test to verify it passes, commit**

Run: `.venv\Scripts\python.exe -m pytest tests/matcher/test_variants.py -v`
Expected: 4 passed.

```bash
git add apps tests
git commit -m "feat: add rotation and mirror variants" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: Эмбеддеры (пиксельный baseline и ONNX)

**Files:**
- Create: `apps/desktop/gmagc_desktop/matcher/embedder.py`
- Test: `tests/matcher/test_embedder.py`

**Interfaces:**
- Consumes: ничего.
- Produces:
  - `class Embedder(Protocol)`: атрибут `model_id: str`, метод `embed(images: np.ndarray) -> np.ndarray`: вход `(N, H, W)` uint8 (нормализованные 224×224), выход `(N, D)` float32, каждая строка L2-нормализована.
  - `l2_normalize(vectors: np.ndarray) -> np.ndarray`
  - `PixelEmbedder(side: int = 16)`: baseline без модели (`model_id = "pixels-16"`).
  - `pool_output(output: np.ndarray) -> np.ndarray`: `(N, D)` остаётся как есть; `(N, T, D)` превращается в `concat(токен 0, среднее остальных)`, то есть `(N, 2D)`.
  - `OnnxEmbedder(model_path: str | Path, batch_size: int = 32, providers: list[str] | None = None)`: вход `pixel_values` `(N, 3, H, W)`, серое изображение дублируется в 3 канала и нормализуется ImageNet-статистикой; `model_id = "onnx-<имя файла без расширения>-<размер файла в байтах>"`. Ошибки загрузки модели onnxruntime (`InvalidProtobuf`, `Fail` наследуются напрямую от `Exception`) переводятся на границе в `ValueError("cannot load ONNX model ...")` с сохранением причины; несуществующий файл даёт `FileNotFoundError`.

- [ ] **Step 1: Write the failing test**

```python
# path: tests/matcher/test_embedder.py
import numpy as np
import onnx
import pytest
from onnx import TensorProto, helper

from gmagc_desktop.matcher.embedder import (
    IMAGENET_MEAN,
    IMAGENET_STD,
    OnnxEmbedder,
    PixelEmbedder,
    l2_normalize,
    pool_output,
)
from tests.helpers import l_shape, sample_gobo


def make_mean_model(path):
    """Крошечная ONNX-модель: среднее по H и W для каждого из 3 каналов."""
    source = helper.make_tensor_value_info("pixel_values", TensorProto.FLOAT, ["N", 3, 224, 224])
    target = helper.make_tensor_value_info("embedding", TensorProto.FLOAT, ["N", 3])
    node = helper.make_node("ReduceMean", ["pixel_values"], ["embedding"], axes=[2, 3], keepdims=0)
    graph = helper.make_graph([node], "mean", [source], [target])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 8
    onnx.save(model, str(path))


def test_l2_normalize_rows():
    out = l2_normalize(np.array([[3.0, 4.0], [0.0, 0.0]]))
    assert np.allclose(out[0], [0.6, 0.8])
    assert np.isfinite(out).all()


def test_pixel_embedder_identical_vs_different():
    embedder = PixelEmbedder()
    a = np.stack([sample_gobo(224), sample_gobo(224), l_shape((224, 224), 0.7)])
    out = embedder.embed(a)
    assert out.shape[0] == 3 and np.allclose(np.linalg.norm(out, axis=1), 1.0, atol=1e-5)
    assert out[0] @ out[1] > 0.999
    assert out[0] @ out[2] < 0.9


def test_onnx_embedder_preprocess_and_output(tmp_path):
    model_path = tmp_path / "tiny.onnx"
    make_mean_model(model_path)
    embedder = OnnxEmbedder(model_path)
    out = embedder.embed(np.full((3, 224, 224), 128, np.uint8))
    expected = (128 / 255 - IMAGENET_MEAN) / IMAGENET_STD
    expected = expected / np.linalg.norm(expected)
    assert out.shape == (3, 3) and out.dtype == np.float32
    assert np.allclose(out[0], expected, atol=1e-5)
    assert embedder.model_id.startswith("onnx-tiny-")


def test_onnx_embedder_handles_many_batches_and_keeps_order(tmp_path):
    model_path = tmp_path / "tiny.onnx"
    make_mean_model(model_path)
    embedder = OnnxEmbedder(model_path, batch_size=32)
    # Каждое изображение — своя константа, поэтому перепутанный порядок батчей заметен
    images = np.stack([np.full((224, 224), 10 + 3 * i, np.uint8) for i in range(70)])

    out = embedder.embed(images)

    assert out.shape == (70, 3)
    assert len({tuple(np.round(row, 5)) for row in out}) == 70  # строки различимы: проверка не пустая
    for i in (0, 1, 31, 32, 33, 63, 64, 69):  # границы батчей по 32
        assert np.allclose(out[i], embedder.embed(images[i : i + 1])[0], atol=1e-6)


def test_pixel_embedder_empty_batch_returns_an_empty_matrix_like_onnx(tmp_path):
    out = PixelEmbedder().embed(np.zeros((0, 224, 224), np.uint8))
    assert out.shape == (0, 0) and out.dtype == np.float32


def test_pool_output_concatenates_cls_and_mean_patch():
    tokens = np.arange(2 * 5 * 4, dtype=np.float32).reshape(2, 5, 4)
    out = pool_output(tokens)
    assert out.shape == (2, 8)
    assert np.array_equal(out[:, :4], tokens[:, 0])
    assert np.allclose(out[:, 4:], tokens[:, 1:].mean(axis=1))


def test_onnx_embedder_rejects_garbage_empty_and_directory_models(tmp_path):
    garbage = tmp_path / "garbage.onnx"
    garbage.write_bytes(b"this is not an onnx model")
    empty = tmp_path / "empty.onnx"
    empty.write_bytes(b"")
    folder = tmp_path / "folder.onnx"
    folder.mkdir()
    for bad in (garbage, empty, folder):
        with pytest.raises(ValueError, match="cannot load ONNX model"):
            OnnxEmbedder(bad)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/matcher/test_embedder.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Write minimal implementation**

```python
# path: apps/desktop/gmagc_desktop/matcher/embedder.py
"""Эмбеддеры: признаки для поиска похожих нормализованных изображений."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


class Embedder(Protocol):
    model_id: str

    def embed(self, images: np.ndarray) -> np.ndarray:
        """(N, H, W) uint8 -> (N, D) float32 с L2-нормой 1."""
        ...


def l2_normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return (vectors / np.maximum(norms, 1e-12)).astype(np.float32)


class PixelEmbedder:
    """Baseline: уменьшенное изображение без среднего. Не требует модели."""

    def __init__(self, side: int = 16):
        self.side = side
        self.model_id = f"pixels-{side}"

    def embed(self, images: np.ndarray) -> np.ndarray:
        if len(images) == 0:
            return np.zeros((0, 0), dtype=np.float32)
        small = np.stack(
            [
                cv2.resize(image, (self.side, self.side), interpolation=cv2.INTER_AREA)
                for image in images
            ]
        ).astype(np.float32)
        small -= small.mean(axis=(1, 2), keepdims=True)
        return l2_normalize(small.reshape(len(images), -1))


def pool_output(output: np.ndarray) -> np.ndarray:
    """(N, D) без изменений; (N, T, D) -> concat(токен 0, среднее остальных токенов)."""
    if output.ndim == 2:
        return output
    if output.ndim == 3:
        return np.concatenate([output[:, 0], output[:, 1:].mean(axis=1)], axis=1)
    raise ValueError(f"unsupported model output rank: {output.ndim}")


class OnnxEmbedder:
    """Энкодер изображений в формате ONNX (например, DINOv2-small), офлайн через onnxruntime."""

    def __init__(
        self,
        model_path: str | Path,
        batch_size: int = 32,
        providers: list[str] | None = None,
    ):
        import onnxruntime as ort

        path = Path(model_path)
        self.model_id = f"onnx-{path.stem}-{path.stat().st_size}"
        self._batch_size = batch_size
        try:
            self._session = ort.InferenceSession(
                str(path), providers=providers or ["CPUExecutionProvider"]
            )
        except Exception as error:  # onnxruntime-исключения наследуются от Exception: переводим в ValueError на границе
            raise ValueError(f"cannot load ONNX model {path}: {error}") from error
        self._input_name = self._session.get_inputs()[0].name

    @staticmethod
    def _prepare(images: np.ndarray) -> np.ndarray:
        gray = images.astype(np.float32) / 255.0
        rgb = np.repeat(gray[:, None, :, :], 3, axis=1)
        rgb = (rgb - IMAGENET_MEAN[None, :, None, None]) / IMAGENET_STD[None, :, None, None]
        return rgb.astype(np.float32)

    def embed(self, images: np.ndarray) -> np.ndarray:
        if len(images) == 0:
            return np.zeros((0, 0), dtype=np.float32)
        chunks = []
        for start in range(0, len(images), self._batch_size):
            batch = self._prepare(images[start : start + self._batch_size])
            output = self._session.run(None, {self._input_name: batch})[0]
            chunks.append(pool_output(output))
        return l2_normalize(np.concatenate(chunks, axis=0))
```

- [ ] **Step 4: Run test to verify it passes, commit**

Run: `.venv\Scripts\python.exe -m pytest tests/matcher/test_embedder.py -v`
Expected: 7 passed.

```bash
git add apps tests
git commit -m "feat: add pixel and ONNX embedders" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6: Мягкое сравнение формы

**Files:**
- Create: `apps/desktop/gmagc_desktop/matcher/shape.py`
- Test: `tests/matcher/test_shape.py`

**Interfaces:**
- Consumes: `rotate_image` из `variants.py`.
- Produces:
  - `MASK_SIZE = 64`
  - `soft_mask(normalized: np.ndarray, size: int = 64) -> np.ndarray`: уменьшенная копия нормализованного 224×224, uint8 `(size, size)` (именно такие маски хранятся в индексе).
  - `ShapeMatch(score: float, angle: float, mirrored: bool)` (frozen dataclass).
  - `ShapeMatcher(query_mask: np.ndarray, coarse_step: float = 5.0, fine_radius: float = 4.0, fine_step: float = 1.0)`; `.score(candidate_mask: np.ndarray) -> ShapeMatch`. Метрика: мягкий IoU размытых масок, `sum(min(a, b)) / sum(max(a, b))`. Найденная поза значит: `candidate ≈ rotate_image(mirror(query) if mirrored else query, angle)`, `angle` в `[0, 360)`.

- [ ] **Step 1: Write the failing test**

```python
# path: tests/matcher/test_shape.py
import numpy as np

from gmagc_desktop.matcher.normalize import normalize_gray
from gmagc_desktop.matcher.shape import MASK_SIZE, ShapeMatcher, soft_mask
from gmagc_desktop.matcher.variants import rotate_image
from tests.helpers import l_shape, sample_gobo


def angle_error(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def query_mask() -> np.ndarray:
    return soft_mask(normalize_gray(l_shape()))


def test_soft_mask_shape_and_dtype():
    mask = query_mask()
    assert mask.shape == (MASK_SIZE, MASK_SIZE) and mask.dtype == np.uint8


def test_identical_shape_scores_high_with_zero_angle():
    query = query_mask()
    match = ShapeMatcher(query).score(query)
    assert match.score > 0.95
    assert angle_error(match.angle, 0.0) < 1.5 and not match.mirrored


def test_rotated_shape_recovers_angle():
    query = query_mask()
    match = ShapeMatcher(query).score(rotate_image(query, 47.0))
    assert match.score > 0.9
    assert angle_error(match.angle, 47.0) < 2.0 and not match.mirrored


def test_mirrored_and_rotated_shape_is_flagged_mirrored():
    query = query_mask()
    candidate = rotate_image(np.ascontiguousarray(query[:, ::-1]), 40.0)
    match = ShapeMatcher(query).score(candidate)
    assert match.score > 0.9 and match.mirrored
    assert angle_error(match.angle, 40.0) < 2.0


def test_different_shape_scores_clearly_lower():
    query = query_mask()
    other = soft_mask(normalize_gray(sample_gobo()))
    matcher = ShapeMatcher(query)
    assert matcher.score(other).score < 0.6 < matcher.score(rotate_image(query, 30.0)).score
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/matcher/test_shape.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Write minimal implementation**

```python
# path: apps/desktop/gmagc_desktop/matcher/shape.py
"""Мягкое сравнение формы: размытые маски, перебор поворота и зеркала."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from gmagc_desktop.matcher.variants import rotate_image

MASK_SIZE = 64
BLUR_SIGMA = 1.2


@dataclass(frozen=True)
class ShapeMatch:
    score: float
    angle: float
    mirrored: bool


def soft_mask(normalized: np.ndarray, size: int = MASK_SIZE) -> np.ndarray:
    """Нормализованное 224x224 -> uint8 (size, size). Такие маски хранятся в индексе."""
    return cv2.resize(normalized, (size, size), interpolation=cv2.INTER_AREA)


def _blurred(mask: np.ndarray) -> np.ndarray:
    return cv2.GaussianBlur(mask.astype(np.float32) / 255.0, (0, 0), BLUR_SIGMA)


def _soft_iou(stack: np.ndarray, target: np.ndarray) -> np.ndarray:
    inter = np.minimum(stack, target).sum(axis=(1, 2))
    union = np.maximum(stack, target).sum(axis=(1, 2))
    return inter / np.maximum(union, 1e-6)


class ShapeMatcher:
    """Сравнивает один запрос со многими кандидатами, кэшируя повороты запроса."""

    def __init__(
        self,
        query_mask: np.ndarray,
        coarse_step: float = 5.0,
        fine_radius: float = 4.0,
        fine_step: float = 1.0,
    ):
        plain = _blurred(query_mask)
        self._bases = {False: plain, True: np.ascontiguousarray(plain[:, ::-1])}
        self._poses = [
            (float(angle), mirrored)
            for mirrored in (False, True)
            for angle in np.arange(0.0, 360.0, coarse_step)
        ]
        self._coarse = np.stack(
            [rotate_image(self._bases[m], a) for a, m in self._poses]
        )
        self._fine_offsets = np.arange(-fine_radius, fine_radius + 1e-6, fine_step)

    def score(self, candidate_mask: np.ndarray) -> ShapeMatch:
        target = _blurred(candidate_mask)
        best = int(np.argmax(_soft_iou(self._coarse, target)))
        angle0, mirrored = self._poses[best]
        angles = angle0 + self._fine_offsets
        fine = np.stack([rotate_image(self._bases[mirrored], a) for a in angles])
        scores = _soft_iou(fine, target)
        j = int(np.argmax(scores))
        return ShapeMatch(float(scores[j]), float(angles[j] % 360.0), mirrored)
```

- [ ] **Step 4: Run test to verify it passes, commit**

Run: `.venv\Scripts\python.exe -m pytest tests/matcher/test_shape.py -v`
Expected: 5 passed.

```bash
git add apps tests
git commit -m "feat: add soft shape matcher with rotation and mirror search" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 7: Обход библиотеки и тестовая библиотека

**Files:**
- Create: `apps/desktop/gmagc_desktop/library/scan.py`, `tests/fixtures.py`
- Test: `tests/library/test_scan.py`

**Interfaces:**
- Consumes: `LIBRARY_EXTENSIONS`, `IGNORED_LIBRARY_NAMES` из `matcher/imageio.py`; `tests.helpers.l_shape`, `sample_gobo`.
- Produces:
  - `LibraryFile(rel_path: str, size: int, mtime_ns: int)`: frozen dataclass (хешируемый), `rel_path` в POSIX-виде относительно корня библиотеки.
  - `scan_library(root: str | Path) -> list[LibraryFile]`: рекурсивно, только `.png`/`.bmp` (регистр не важен), отсортировано по `rel_path`; `question.bmp` игнорируется **только в корне**.
  - (`tests/fixtures.py`) `shape_images() -> dict[str, np.ndarray]` (ключи `ring`, `dots`, `star`, `ell`, `ell_small`, `gobo`; `ell_small` это то же гобо, что `ell`, в другом разрешении); `write_library(root: Path) -> None` создаёт 7 файлов-изображений + `question.bmp` + `notes.txt`.

Состав тестовой библиотеки (`write_library`): `vendor_a/ring.png` (RGB), `vendor_a/dots.png` (RGBA, белый RGB и прозрачный фон), `vendor_b/star.bmp` (RGB), `vendor_b/ell.png` (режим L), `vendor_c/ell_small.png` (128×128), `vendor_c/gobo.png`, `blank.png` (чёрный), `question.bmp` (в корне, игнорируется), `notes.txt`.

- [ ] **Step 1: Write the failing test и фикстуры**

```python
# path: tests/fixtures.py
"""Маленькая синтетическая библиотека гобо для тестов индекса, поиска и CLI."""

import os
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
from PIL import Image

from gmagc_desktop.library import scan
from tests.helpers import l_shape, sample_gobo


def _ring(size: int = 256) -> np.ndarray:
    image = np.zeros((size, size), np.uint8)
    cv2.circle(image, (size // 2, size // 2), int(size * 0.38), 255, size // 12)
    return image


def _dots(size: int = 256) -> np.ndarray:
    image = np.zeros((size, size), np.uint8)
    for i in range(5):
        for j in range(5):
            if (i * 7 + j * 3) % 4 != 0:
                cv2.circle(image, (40 + i * 44, 40 + j * 44), 12 if (i + j) % 2 else 7, 255, -1)
    return image


def _star(size: int = 256) -> np.ndarray:
    points = []
    for k in range(10):
        radius = 110 if k % 2 == 0 else 45
        angle = k * np.pi / 5 - np.pi / 2
        points.append((size // 2 + radius * np.cos(angle), size // 2 + radius * np.sin(angle)))
    image = np.zeros((size, size), np.uint8)
    cv2.fillPoly(image, [np.array(points, np.int32)], 255)
    return image


def shape_images() -> dict[str, np.ndarray]:
    return {
        "ring": _ring(),
        "dots": _dots(),
        "star": _star(),
        "ell": l_shape((256, 256)),
        "ell_small": l_shape((128, 128), 0.5),
        "gobo": sample_gobo(256),
    }


def write_library(root: Path) -> None:
    images = shape_images()
    for folder in ("vendor_a", "vendor_b", "vendor_c"):
        (root / folder).mkdir(parents=True, exist_ok=True)

    Image.fromarray(images["ring"]).convert("RGB").save(root / "vendor_a" / "ring.png")
    alpha = images["dots"]
    rgba = np.dstack([np.full_like(alpha, 255)] * 3 + [alpha])  # белый RGB, фон прозрачный
    Image.fromarray(rgba, "RGBA").save(root / "vendor_a" / "dots.png")
    Image.fromarray(images["star"]).convert("RGB").save(root / "vendor_b" / "star.bmp")
    Image.fromarray(images["ell"], "L").save(root / "vendor_b" / "ell.png")
    Image.fromarray(images["ell_small"], "L").save(root / "vendor_c" / "ell_small.png")
    Image.fromarray(images["gobo"], "L").save(root / "vendor_c" / "gobo.png")
    Image.fromarray(np.zeros((64, 64), np.uint8), "L").save(root / "blank.png")
    Image.fromarray(images["ring"]).convert("RGB").save(root / "question.bmp")
    (root / "notes.txt").write_text("not an image", encoding="utf-8")


def make_folder_unlistable(monkeypatch, folder_name: str) -> None:
    """Подменяет os.walk в scan: папку folder_name «нельзя прочитать» (вызывается onerror), остальные обходятся как есть."""
    real_walk = os.walk

    def fake_walk(top, topdown=True, onerror=None, followlinks=False):
        for dirpath, dirnames, filenames in real_walk(top, topdown, None, followlinks):
            if Path(dirpath).name == folder_name:
                if onerror is not None:
                    onerror(PermissionError(13, "Access is denied", dirpath))
                continue
            yield dirpath, dirnames, filenames

    monkeypatch.setattr(scan, "os", SimpleNamespace(walk=fake_walk))


def make_file_vanish_during_walk(monkeypatch, rel_path: str) -> None:
    """Подменяет os.walk в scan: файл rel_path удаляется уже после того, как обход его перечислил (до stat())."""
    real_walk = os.walk

    def fake_walk(top, topdown=True, onerror=None, followlinks=False):
        target = Path(top) / rel_path
        for dirpath, dirnames, filenames in real_walk(top, topdown, onerror, followlinks):
            if Path(dirpath) == target.parent and target.exists():
                target.unlink()
            yield dirpath, dirnames, filenames

    monkeypatch.setattr(scan, "os", SimpleNamespace(walk=fake_walk))
```

```python
# path: tests/library/test_scan.py
from gmagc_desktop.library import scan as scan_module
from gmagc_desktop.library.scan import LibraryFile, scan_library
from tests.fixtures import make_file_vanish_during_walk, make_folder_unlistable, write_library


def test_scan_finds_only_supported_files_sorted_and_posix(tmp_path):
    write_library(tmp_path)
    (tmp_path / "vendor_a" / "question.bmp").write_bytes(b"x")  # не в корне: не игнорируется
    (tmp_path / "vendor_b" / "UPPER.PNG").write_bytes(b"x")

    files = scan_library(tmp_path)

    assert [f.rel_path for f in files] == [
        "blank.png",
        "vendor_a/dots.png",
        "vendor_a/question.bmp",
        "vendor_a/ring.png",
        "vendor_b/UPPER.PNG",
        "vendor_b/ell.png",
        "vendor_b/star.bmp",
        "vendor_c/ell_small.png",
        "vendor_c/gobo.png",
    ]
    assert all(isinstance(f, LibraryFile) and f.size > 0 and f.mtime_ns > 0 for f in files)


def test_library_file_is_hashable_and_compares_by_value():
    a = LibraryFile("a.png", 10, 5)
    assert a == LibraryFile("a.png", 10, 5) and a != LibraryFile("a.png", 11, 5)
    assert len({a, LibraryFile("a.png", 10, 5)}) == 1


def test_missing_root_gives_empty_list(tmp_path):
    assert scan_library(tmp_path / "nope") == []


def test_checked_scan_reports_an_unlistable_directory(tmp_path, monkeypatch):
    write_library(tmp_path)
    make_folder_unlistable(monkeypatch, "vendor_b")

    files, problems = scan_module.scan_library_checked(tmp_path)

    assert len(problems) == 1 and "cannot list directory" in problems[0] and "vendor_b" in problems[0]
    assert "vendor_b/ell.png" not in [f.rel_path for f in files]
    assert "vendor_a/ring.png" in [f.rel_path for f in files]


def test_checked_scan_reports_a_missing_root_as_a_problem(tmp_path):
    files, problems = scan_module.scan_library_checked(tmp_path / "nope")
    assert files == [] and len(problems) == 1 and "nope" in problems[0]


def test_checked_scan_has_no_problems_on_a_healthy_library(tmp_path):
    write_library(tmp_path)
    files, problems = scan_module.scan_library_checked(tmp_path)
    assert problems == [] and files == scan_library(tmp_path)


def test_file_vanishing_between_walk_and_stat_is_skipped_not_a_problem(tmp_path, monkeypatch):
    write_library(tmp_path)
    make_file_vanish_during_walk(monkeypatch, "vendor_a/ring.png")

    files, problems = scan_module.scan_library_checked(tmp_path)

    assert problems == []
    assert "vendor_a/ring.png" not in [f.rel_path for f in files]
    assert "vendor_a/dots.png" in [f.rel_path for f in files]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/library/test_scan.py -v`
Expected: FAIL (`ModuleNotFoundError: gmagc_desktop.library.scan`).

- [ ] **Step 3: Write minimal implementation**

```python
# path: apps/desktop/gmagc_desktop/library/scan.py
"""Обход папки библиотеки гобо."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from gmagc_desktop.matcher.imageio import IGNORED_LIBRARY_NAMES, LIBRARY_EXTENSIONS


@dataclass(frozen=True)
class LibraryFile:
    rel_path: str  # POSIX-вид, относительно корня библиотеки
    size: int
    mtime_ns: int


def scan_library_checked(root: str | Path) -> tuple[list[LibraryFile], list[str]]:
    """Файлы библиотеки (отсортированы по rel_path) и список проблем обхода.

    Непрочитанная папка (нет доступа, отключённый диск и т. п.) попадает в problems, а не молча пропускается.
    Файл, исчезнувший между обходом и stat(), просто пропускается: его уже нет, это не проблема.
    """
    root = Path(root)
    found: list[LibraryFile] = []
    problems: list[str] = []

    def on_error(error: OSError) -> None:
        problems.append(f"cannot list directory {error.filename}: {error}")

    for dirpath, _dirnames, names in os.walk(root, onerror=on_error):
        directory = Path(dirpath)
        for name in names:
            if Path(name).suffix.lower() not in LIBRARY_EXTENSIONS:
                continue
            if directory == root and name.lower() in IGNORED_LIBRARY_NAMES:
                continue
            try:
                stat = (directory / name).stat()
            except FileNotFoundError:
                continue
            rel = (directory / name).relative_to(root).as_posix()
            found.append(LibraryFile(rel, stat.st_size, stat.st_mtime_ns))
    found.sort(key=lambda f: f.rel_path)
    return found, problems


def scan_library(root: str | Path) -> list[LibraryFile]:
    """Все поддерживаемые файлы библиотеки, отсортированные по rel_path (без сведений о проблемах обхода)."""
    return scan_library_checked(root)[0]
```

- [ ] **Step 4: Run test to verify it passes, commit**

Run: `.venv\Scripts\python.exe -m pytest tests/library/test_scan.py -v`
Expected: 7 passed.

```bash
git add apps tests
git commit -m "feat: add library scanning and synthetic test library" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 8: Группировка дублей

**Files:**
- Create: `apps/desktop/gmagc_desktop/library/grouping.py`
- Test: `tests/library/test_grouping.py`

**Interfaces:**
- Consumes: ничего (только numpy).
- Produces: `group_duplicates(embeddings: np.ndarray, masks: np.ndarray, cosine_threshold: float = 0.97, iou_threshold: float = 0.85, block: int = 512) -> np.ndarray`: `int32` `(N,)`, идентификатор семейства = наименьший индекс участника. Два файла объединяются, если косинус эмбеддингов ≥ порога **и** мягкий IoU масок (без поворота) ≥ порога; объединение транзитивно. Пары проверяются порциями с бюджетом `PAIR_BUDGET_BYTES` (32 МБ на собранный массив масок), а не по числу пар: при масках 64×64 порция в 100 000 пар заняла бы ~1,6 ГБ.

- [ ] **Step 1: Write the failing test**

```python
# path: tests/library/test_grouping.py
import numpy as np

from gmagc_desktop.library import grouping
from gmagc_desktop.library.grouping import group_duplicates


def unit(*values):
    vector = np.array(values, dtype=np.float32)
    return vector / np.linalg.norm(vector)


def mask(filled: slice) -> np.ndarray:
    image = np.zeros((8, 8), np.uint8)
    image[filled, :] = 255
    return image


def _duplicated_library() -> tuple[np.ndarray, np.ndarray]:
    """Construct a test library with 6 unique items + 3 duplicates of the first 3."""
    rng = np.random.default_rng(0)
    base = rng.normal(size=(6, 16)).astype(np.float32)
    embeddings = np.concatenate([base, base[:3]])
    embeddings /= np.linalg.norm(embeddings, axis=1, keepdims=True)
    masks = np.stack([mask(slice(i % 4, i % 4 + 3)) for i in range(6)] + [mask(slice(i % 4, i % 4 + 3)) for i in range(3)])
    return embeddings, masks


def test_identical_items_share_a_group_and_others_stay_alone():
    embeddings = np.stack([unit(1, 0, 0), unit(1, 0, 0), unit(0, 1, 0)])
    masks = np.stack([mask(slice(0, 4)), mask(slice(0, 4)), mask(slice(4, 8))])
    assert group_duplicates(embeddings, masks).tolist() == [0, 0, 2]


def test_same_embedding_but_different_mask_is_not_a_duplicate():
    embeddings = np.stack([unit(1, 0, 0), unit(1, 0, 0)])
    masks = np.stack([mask(slice(0, 3)), mask(slice(5, 8))])
    assert group_duplicates(embeddings, masks).tolist() == [0, 1]


def test_groups_are_transitive():
    embeddings = np.stack([unit(1, 0.0, 0), unit(1, 0.15, 0), unit(1, 0.3, 0)])
    masks = np.stack([mask(slice(0, 4))] * 3)
    # cos(0,1)=0.989 и cos(1,2)=0.990 проходят порог, cos(0,2)=0.958 нет: группа собирается цепочкой
    ids = group_duplicates(embeddings, masks, cosine_threshold=0.98)
    assert ids.tolist() == [0, 0, 0]


def test_block_size_does_not_change_result():
    embeddings, masks = _duplicated_library()
    assert group_duplicates(embeddings, masks, block=2).tolist() == group_duplicates(
        embeddings, masks, block=512
    ).tolist()
    assert group_duplicates(embeddings, masks).tolist()[6:] == [0, 1, 2]


def test_pair_chunking_does_not_change_result(monkeypatch):
    embeddings, masks = _duplicated_library()
    baseline = group_duplicates(embeddings, masks)
    monkeypatch.setattr(grouping, "PAIR_BUDGET_BYTES", 1)  # -> one pair per chunk
    assert group_duplicates(embeddings, masks).tolist() == baseline.tolist()


def test_empty_input():
    ids = group_duplicates(np.zeros((0, 0), np.float32), np.zeros((0, 8, 8), np.uint8))
    assert ids.shape == (0,) and ids.dtype == np.int32
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/library/test_grouping.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Write minimal implementation**

```python
# path: apps/desktop/gmagc_desktop/library/grouping.py
"""Группировка визуальных дублей (одно гобо у разных производителей)."""

from __future__ import annotations

import numpy as np

PAIR_BUDGET_BYTES = 32 * 1024 * 1024  # размер одного собранного массива масок при проверке пар


def _find(parent: np.ndarray, item: int) -> int:
    root = item
    while parent[root] != root:
        root = parent[root]
    while parent[item] != root:
        parent[item], item = root, parent[item]
    return int(root)


def _soft_iou_pairs(flat_masks: np.ndarray, left: np.ndarray, right: np.ndarray) -> np.ndarray:
    first = flat_masks[left]
    second = flat_masks[right]
    inter = np.minimum(first, second).sum(axis=1)
    union = np.maximum(first, second).sum(axis=1)
    return inter / np.maximum(union, 1e-6)


def group_duplicates(
    embeddings: np.ndarray,
    masks: np.ndarray,
    cosine_threshold: float = 0.97,
    iou_threshold: float = 0.85,
    block: int = 512,
) -> np.ndarray:
    """Идентификаторы семейств: наименьший индекс участника. Объединение транзитивно."""
    count = len(embeddings)
    parent = np.arange(count, dtype=np.int64)
    if count == 0:
        return parent.astype(np.int32)
    vectors = embeddings.astype(np.float32)
    flat = masks.reshape(count, -1).astype(np.float32) / 255.0
    pair_chunk = max(1, PAIR_BUDGET_BYTES // (flat.shape[1] * flat.itemsize))

    for start in range(0, count, block):
        similarity = vectors[start : start + block] @ vectors.T
        rows, cols = np.nonzero(similarity >= cosine_threshold)
        rows = rows + start
        keep = cols > rows
        rows, cols = rows[keep], cols[keep]
        for chunk in range(0, len(rows), pair_chunk):
            left = rows[chunk : chunk + pair_chunk]
            right = cols[chunk : chunk + pair_chunk]
            similar = _soft_iou_pairs(flat, left, right) >= iou_threshold
            for a, b in zip(left[similar], right[similar], strict=True):
                root_a, root_b = _find(parent, int(a)), _find(parent, int(b))
                if root_a != root_b:
                    parent[max(root_a, root_b)] = min(root_a, root_b)

    return np.array([_find(parent, i) for i in range(count)], dtype=np.int32)
```

- [ ] **Step 4: Run test to verify it passes, commit**

Run: `.venv\Scripts\python.exe -m pytest tests/library/test_grouping.py -v`
Expected: 6 passed.

```bash
git add apps tests
git commit -m "feat: add duplicate grouping" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 9: Поиск (эмбеддинги + уточнение формы + семейства)

**Files:**
- Create: `apps/desktop/gmagc_desktop/matcher/search.py`
- Test: `tests/matcher/test_search.py`

**Interfaces:**
- Consumes: `Embedder` (Task 5), `query_variants` (Task 4), `ShapeMatcher`, `soft_mask` (Task 6), `group_duplicates` (Task 8, только в тестах).
- Produces:
  - `SearchData(embeddings: np.ndarray, masks: np.ndarray, group_ids: np.ndarray)`: frozen dataclass; `(N, D)` float32 L2-нормализованные, `(N, 64, 64)` uint8, `(N,)` int32.
  - `Match(index: int, score: float, embed_score: float, shape_score: float, angle: float, mirrored: bool, members: tuple[int, ...])`: frozen dataclass; `index` это лучший (по эмбеддингу) файл семейства, `members` все индексы семейства (включая `index`).
  - `Searcher(data: SearchData, embedder: Embedder, n_rotations: int = 24, shortlist: int = 20, w_embed: float = 0.5)`; `.search(normalized_query: np.ndarray, top_n: int = 10) -> list[Match]`: `score = w_embed * max(embed_score, 0) + (1 - w_embed) * shape_score`, сортировка по убыванию, одна запись на семейство.

- [ ] **Step 1: Write the failing test**

```python
# path: tests/matcher/test_search.py
import numpy as np
import pytest

from gmagc_desktop.library.grouping import group_duplicates
from gmagc_desktop.matcher.embedder import PixelEmbedder
from gmagc_desktop.matcher.normalize import normalize_gray
from gmagc_desktop.matcher.search import IndexMismatchError, SearchData, Searcher
from gmagc_desktop.matcher.shape import soft_mask
from gmagc_desktop.matcher.variants import rotate_image
from tests.fixtures import shape_images


def angle_error(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


@pytest.fixture(scope="module")
def library():
    images = shape_images()
    names = list(images)
    normalized = [normalize_gray(images[name]) for name in names]
    embedder = PixelEmbedder()
    embeddings = embedder.embed(np.stack(normalized))
    masks = np.stack([soft_mask(n) for n in normalized])
    data = SearchData(embeddings, masks, group_duplicates(embeddings, masks))
    return names, normalized, embedder, data


@pytest.mark.parametrize("w_embed", [0.0, 0.5, 1.0])
def test_rotated_query_finds_its_family_and_reports_members(library, w_embed):
    names, normalized, embedder, data = library
    query = rotate_image(normalized[names.index("ell")], 137.0)

    top = Searcher(data, embedder, w_embed=w_embed).search(query, top_n=3)[0]

    assert {names[i] for i in top.members} == {"ell", "ell_small"}
    assert top.index in top.members and 0.0 <= top.score <= 1.0
    if w_embed < 1.0:
        assert angle_error(top.angle, 223.0) < 3.0 and not top.mirrored


@pytest.mark.parametrize("w", [0.0, 0.3, 0.5, 1.0])
def test_score_is_the_weighted_sum_of_embed_and_shape_scores(library, w):
    names, normalized, embedder, data = library
    query = rotate_image(normalized[names.index("gobo")], 40.0)

    matches = Searcher(data, embedder, w_embed=w).search(query, top_n=10)

    assert len(matches) > 1
    for match in matches:
        assert match.score == pytest.approx(w * max(match.embed_score, 0.0) + (1 - w) * match.shape_score)


def test_mirrored_query_is_flagged_mirrored(library):
    names, normalized, embedder, data = library
    query = rotate_image(np.ascontiguousarray(normalized[names.index("ell")][:, ::-1]), 60.0)

    top = Searcher(data, embedder).search(query, top_n=1)[0]

    assert {names[i] for i in top.members} == {"ell", "ell_small"}
    assert top.mirrored and angle_error(top.angle, 60.0) < 3.0


def test_one_result_per_family_sorted_by_score(library):
    names, normalized, embedder, data = library
    results = Searcher(data, embedder).search(normalized[names.index("gobo")], top_n=10)
    families = [data.group_ids[r.index] for r in results]
    assert len(set(families)) == len(families) == len(set(data.group_ids.tolist()))
    assert [r.score for r in results] == sorted((r.score for r in results), reverse=True)
    assert names[results[0].index] == "gobo"


def test_top_n_limits_results_and_empty_index_is_safe(library):
    names, normalized, embedder, data = library
    assert len(Searcher(data, embedder).search(normalized[0], top_n=2)) == 2
    empty = SearchData(
        np.zeros((0, 0), np.float32), np.zeros((0, 64, 64), np.uint8), np.zeros(0, np.int32)
    )
    assert Searcher(empty, embedder).search(normalized[0]) == []


def test_embedder_with_other_dimensions_than_the_index_is_rejected_clearly(library):
    names, normalized, embedder, data = library  # индекс построен PixelEmbedder(side=16): 256 измерений
    other = PixelEmbedder(side=8)  # 64 измерения

    with pytest.raises(IndexMismatchError, match="256 dimensions but the embedder produced 64; rebuild the index"):
        Searcher(data, other).search(normalized[0])

    assert isinstance(IndexMismatchError("x"), ValueError)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/matcher/test_search.py -v`
Expected: FAIL (`ModuleNotFoundError: gmagc_desktop.matcher.search`).

- [ ] **Step 3: Write minimal implementation**

```python
# path: apps/desktop/gmagc_desktop/matcher/search.py
"""Поиск: эмбеддинги по 48 вариантам запроса -> shortlist -> уточнение формы -> семейства."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from gmagc_desktop.matcher.embedder import Embedder
from gmagc_desktop.matcher.shape import ShapeMatcher, soft_mask
from gmagc_desktop.matcher.variants import DEFAULT_ROTATIONS, query_variants

DEFAULT_W_EMBED = 0.5  # вес эмбеддинга в итоговой оценке (остальное — форма); единый по умолчанию для всех входов


class IndexMismatchError(ValueError):
    """Размерность векторов индекса не совпадает с размерностью эмбеддера: индекс построен другой моделью."""


@dataclass(frozen=True)
class SearchData:
    embeddings: np.ndarray  # (N, D) float32, L2-нормализованные
    masks: np.ndarray  # (N, 64, 64) uint8
    group_ids: np.ndarray  # (N,) int32


@dataclass(frozen=True)
class Match:
    index: int  # лучший (по эмбеддингу) файл семейства
    score: float
    embed_score: float
    shape_score: float
    angle: float
    mirrored: bool
    members: tuple[int, ...]  # все файлы семейства, включая index


class Searcher:
    def __init__(
        self,
        data: SearchData,
        embedder: Embedder,
        n_rotations: int = DEFAULT_ROTATIONS,
        shortlist: int = 20,
        w_embed: float = DEFAULT_W_EMBED,
    ):
        self._data = data
        self._embedder = embedder
        self._n_rotations = n_rotations
        self._shortlist = shortlist
        self._w_embed = w_embed
        self._members: dict[int, list[int]] = defaultdict(list)
        for index, group in enumerate(data.group_ids.tolist()):
            self._members[group].append(index)

    def search(self, normalized_query: np.ndarray, top_n: int = 10) -> list[Match]:
        data = self._data
        if len(data.embeddings) == 0:
            return []

        variants = query_variants(normalized_query, self._n_rotations, mirror=True)
        query_vectors = self._embedder.embed(variants)  # (V, D)
        if query_vectors.shape[1] != data.embeddings.shape[1]:
            raise IndexMismatchError(
                f"index vectors have {data.embeddings.shape[1]} dimensions "
                f"but the embedder produced {query_vectors.shape[1]}; rebuild the index"
            )
        best_embed = (data.embeddings @ query_vectors.T).max(axis=1)  # (N,)

        candidates: list[int] = []
        seen_groups: set[int] = set()
        for index in np.argsort(-best_embed):
            group = int(data.group_ids[index])
            if group in seen_groups:
                continue
            seen_groups.add(group)
            candidates.append(int(index))
            if len(candidates) >= self._shortlist:
                break

        shape = ShapeMatcher(soft_mask(normalized_query))
        matches = []
        for index in candidates:
            found = shape.score(data.masks[index])
            embed_score = float(best_embed[index])
            score = self._w_embed * max(embed_score, 0.0) + (1.0 - self._w_embed) * found.score
            matches.append(
                Match(
                    index=index,
                    score=score,
                    embed_score=embed_score,
                    shape_score=found.score,
                    angle=found.angle,
                    mirrored=found.mirrored,
                    members=tuple(self._members[int(data.group_ids[index])]),
                )
            )
        matches.sort(key=lambda m: m.score, reverse=True)
        return matches[:top_n]
```

- [ ] **Step 4: Run test to verify it passes, commit**

Run: `.venv\Scripts\python.exe -m pytest tests/matcher/test_search.py -v`
Expected: 11 passed.

```bash
git add apps tests
git commit -m "feat: add searcher combining embeddings, shape rerank and families" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 10: Индекс библиотеки (сборка, кэш, дозапись)

**Files:**
- Create: `apps/desktop/gmagc_desktop/library/index.py`
- Test: `tests/library/test_index.py`

**Interfaces:**
- Consumes: `scan_library`/`LibraryFile` (Task 7), `group_duplicates` (Task 8), `SearchData` (Task 9), `load_library_gray`, `normalize_gray`, `soft_mask`, `Embedder`.
- Produces:
  - `FORMAT_VERSION = 1`; `class IndexCancelled(Exception)`; `ProgressCallback = Callable[[int, int], None]` (`done, total` по новым/изменённым файлам).
  - `LibraryIndex(model_id: str, files: list[LibraryFile], embeddings: np.ndarray, masks: np.ndarray, group_ids: np.ndarray, skipped: list[LibraryFile])`: `__len__`, `search_data() -> SearchData`.
  - `build_index(root, embedder, existing: LibraryIndex | None = None, progress: ProgressCallback | None = None, batch_size: int = 64, cancel: Callable[[], bool] | None = None) -> LibraryIndex`: повторно использует строки `existing`, если совпали `model_id` и `(rel_path, size, mtime_ns)`; нечитаемые и пустые файлы попадают в `skipped` и не обрабатываются повторно, пока не изменятся; `cancel()` возвращает True между пакетами -> `IndexCancelled`. Если `root` не каталог, поднимает `FileNotFoundError` (иначе пустой индекс затёр бы кэш). Нечитаемые файлы (`OSError`, `ValueError`, `SyntaxError`, `cv2.error`, `DecompressionBombError`) пропускаются с предупреждением в лог; `PermissionError` и ошибки программы не глотаются.
  - `save_index(index, path) -> None` (атомарно через временный файл, эмбеддинги в `float16`), `load_index(path) -> LibraryIndex | None` (`None`, если файла нет, он повреждён или другая версия формата). Перехватывается также `zlib.error`, `EOFError` и `NotImplementedError` из разбора повреждённого архива.

- [ ] **Step 1: Write the failing test**

```python
# path: tests/library/test_index.py
import os
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image, UnidentifiedImageError

from gmagc_desktop.library.index import (
    IndexCancelled,
    LibraryNotFound,
    LibraryScanError,
    build_index,
    load_index,
    save_index,
)
from gmagc_desktop.matcher.embedder import PixelEmbedder
from tests.fixtures import make_file_vanish_during_walk, make_folder_unlistable, write_library


class CountingEmbedder(PixelEmbedder):
    def __init__(self, tag: str = "pixels-16"):
        super().__init__()
        self.model_id = tag
        self.count = 0

    def embed(self, images):
        self.count += len(images)
        return super().embed(images)


@pytest.fixture()
def library(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    write_library(root)
    return root


def test_build_indexes_valid_files_skips_blank_and_groups_duplicates(library):
    index = build_index(library, CountingEmbedder())

    paths = [f.rel_path for f in index.files]
    assert paths == [
        "vendor_a/dots.png",
        "vendor_a/ring.png",
        "vendor_b/ell.png",
        "vendor_b/star.bmp",
        "vendor_c/ell_small.png",
        "vendor_c/gobo.png",
    ]
    assert [f.rel_path for f in index.skipped] == ["blank.png"]
    assert index.embeddings.shape[0] == index.masks.shape[0] == len(index) == 6
    groups = dict(zip(paths, index.group_ids.tolist(), strict=True))
    assert groups["vendor_b/ell.png"] == groups["vendor_c/ell_small.png"]
    assert len(set(groups.values())) == 5


def test_progress_reports_totals(library):
    calls = []
    build_index(library, CountingEmbedder(), progress=lambda done, total: calls.append((done, total)), batch_size=2)
    assert calls[-1] == (7, 7) and calls[0][1] == 7 and len(calls) == 4


def test_save_and_load_roundtrip(library, tmp_path):
    index = build_index(library, CountingEmbedder())
    target = tmp_path / "cache" / "index.npz"

    save_index(index, target)
    loaded = load_index(target)

    assert loaded.model_id == index.model_id
    assert loaded.files == index.files and loaded.skipped == index.skipped
    assert np.allclose(loaded.embeddings, index.embeddings, atol=1e-3)
    assert np.array_equal(loaded.masks, index.masks)
    assert np.array_equal(loaded.group_ids, index.group_ids)
    assert loaded.embeddings.dtype == np.float32


def test_incremental_build_embeds_only_new_files(library, tmp_path):
    first = CountingEmbedder()
    index = build_index(library, first)
    assert first.count == 6

    from PIL import Image

    Image.fromarray(np.eye(64, dtype=np.uint8) * 255, "L").save(library / "vendor_c" / "diag.png")
    second = CountingEmbedder()
    updated = build_index(library, second, existing=index)

    assert second.count == 1  # blank.png и старые файлы не пересчитываются
    assert len(updated) == 7 and "vendor_c/diag.png" in [f.rel_path for f in updated.files]


def test_changed_file_is_recomputed_and_removed_file_disappears(library):
    index = build_index(library, CountingEmbedder())
    (library / "vendor_a" / "ring.png").unlink()
    star = library / "vendor_b" / "star.bmp"
    os.utime(star, ns=(1_000_000_000, 1_000_000_000))  # другой mtime -> другая сигнатура

    embedder = CountingEmbedder()
    updated = build_index(library, embedder, existing=index)

    assert embedder.count == 1
    assert "vendor_a/ring.png" not in [f.rel_path for f in updated.files]


def test_model_change_forces_full_rebuild(library):
    index = build_index(library, CountingEmbedder("pixels-16"))
    other = CountingEmbedder("another-model")
    build_index(library, other, existing=index)
    assert other.count == 6


def test_cancel_stops_between_batches(library):
    with pytest.raises(IndexCancelled):
        build_index(library, CountingEmbedder(), batch_size=2, cancel=lambda: True)


def test_load_returns_none_for_missing_or_corrupt_file(tmp_path):
    assert load_index(tmp_path / "missing.npz") is None
    broken = tmp_path / "broken.npz"
    broken.write_bytes(b"not a zip")
    assert load_index(broken) is None


def test_load_returns_none_when_the_npy_header_is_cut_off(tmp_path):
    """Оборванный заголовок .npy внутри npz: numpy бросает tokenize.TokenError, а не ValueError."""
    import struct
    import zipfile

    header = b"{'descr': '<i8', 'fortran_order': False, 'shape': (1,"
    header += b" " * ((64 - (10 + len(header) + 1) % 64) % 64) + b"\n"
    npy = b"\x93NUMPY\x01\x00" + struct.pack("<H", len(header)) + header + b"\x00" * 8
    damaged = tmp_path / "cut_header.npz"
    with zipfile.ZipFile(damaged, "w") as archive:
        archive.writestr("format_version.npy", npy)

    assert load_index(damaged) is None


def test_load_never_raises_on_damaged_cache(library, tmp_path):
    target = tmp_path / "index.npz"
    save_index(build_index(library, CountingEmbedder()), target)
    data = target.read_bytes()
    damaged = tmp_path / "damaged.npz"

    damaged.write_bytes(data[: len(data) // 2])
    assert load_index(damaged) is None

    for offset in range(64, len(data) - 64, max(1, len(data) // 40)):
        broken = bytearray(data)
        for i in range(offset, offset + 8):
            broken[i] ^= 0xFF
        damaged.write_bytes(bytes(broken))
        load_index(damaged)  # None или индекс допустимы, исключения быть не должно


def test_missing_library_root_raises_instead_of_returning_an_empty_index(tmp_path):
    with pytest.raises(FileNotFoundError):
        build_index(tmp_path / "unplugged", CountingEmbedder())


def test_skipped_files_are_not_reopened_until_they_change(library, monkeypatch):
    from gmagc_desktop.library import index as index_module

    opened = []
    real = index_module.load_library_gray
    monkeypatch.setattr(index_module, "load_library_gray", lambda path: opened.append(Path(path).name) or real(path))

    first = build_index(library, CountingEmbedder())
    assert "blank.png" in opened
    opened.clear()

    second = build_index(library, CountingEmbedder(), existing=first)
    assert opened == []  # ни один файл не открывался: строки и «пропущенные» взяты из кэша

    os.utime(library / "blank.png", ns=(2_000_000_000, 2_000_000_000))
    build_index(library, CountingEmbedder(), existing=second)
    assert opened == ["blank.png"]  # изменившийся пропущенный файл пробуем снова


def test_permission_and_program_errors_are_not_swallowed(library, monkeypatch):
    from gmagc_desktop.library import index as index_module

    def failing(error):
        def loader(path):
            raise error

        return loader

    monkeypatch.setattr(index_module, "load_library_gray", failing(PermissionError("locked")))
    with pytest.raises(PermissionError):
        build_index(library, CountingEmbedder())

    monkeypatch.setattr(index_module, "load_library_gray", failing(TypeError("bug")))
    with pytest.raises(TypeError):
        build_index(library, CountingEmbedder())


def test_corrupt_image_is_skipped_with_a_warning(library, caplog):
    (library / "vendor_a" / "broken.png").write_bytes(b"not a png")
    with caplog.at_level("WARNING"):
        index = build_index(library, CountingEmbedder())
    assert "vendor_a/broken.png" in [f.rel_path for f in index.skipped]
    assert "broken.png" in caplog.text


def test_missing_library_root_raises_library_not_found_with_the_path(tmp_path):
    with pytest.raises(LibraryNotFound, match="library folder not found") as caught:
        build_index(tmp_path / "unplugged", CountingEmbedder())
    assert isinstance(caught.value, FileNotFoundError) and "unplugged" in str(caught.value)


def test_unlistable_directory_aborts_instead_of_building_a_partial_index(library, monkeypatch):
    make_folder_unlistable(monkeypatch, "vendor_b")
    embedder = CountingEmbedder()

    with pytest.raises(LibraryScanError, match="refusing to build a partial index") as caught:
        build_index(library, embedder)

    assert "cannot list directory" in str(caught.value) and "vendor_b" in str(caught.value)
    assert "1 problem" in str(caught.value)
    assert embedder.count == 0  # ничего не встраивалось: индекс не строился


def test_empty_library_folder_raises_instead_of_returning_an_empty_index(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "notes.txt").write_text("not an image", encoding="utf-8")
    with pytest.raises(LibraryScanError, match="no PNG/BMP files found"):
        build_index(empty, CountingEmbedder())


def test_library_of_only_unreadable_files_raises(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    (root / "broken.png").write_bytes(b"not a png")
    (root / "also_broken.bmp").write_bytes(b"not a bmp")
    with pytest.raises(LibraryScanError, match=r"none of the 2 library files could be read"):
        build_index(root, CountingEmbedder())


def test_file_vanishing_between_walk_and_stat_is_skipped_by_the_build(library, monkeypatch):
    make_file_vanish_during_walk(monkeypatch, "vendor_a/ring.png")

    index = build_index(library, CountingEmbedder())

    paths = [f.rel_path for f in index.files]
    assert "vendor_a/ring.png" not in paths and "vendor_a/dots.png" in paths
    assert len(index) == 5 and [f.rel_path for f in index.skipped] == ["blank.png"]


def _fail_on(monkeypatch, name, error_factory):
    """Подменяет загрузчик: файл с именем name падает с error_factory() (пока флаг не сброшен)."""
    from gmagc_desktop.library import index as index_module

    real = index_module.load_library_gray
    state = {"failing": True, "opened": []}

    def loader(path):
        state["opened"].append(Path(path).name)
        if state["failing"] and Path(path).name == name:
            raise error_factory()
        return real(path)

    monkeypatch.setattr(index_module, "load_library_gray", loader)
    return state


def test_transient_read_failure_is_retried_and_never_persisted(library, tmp_path, monkeypatch, caplog):
    state = _fail_on(monkeypatch, "ring.png", lambda: OSError("device not ready"))

    with caplog.at_level("WARNING"):
        first = build_index(library, CountingEmbedder())

    assert [f.rel_path for f in first.transient] == ["vendor_a/ring.png"]
    assert "vendor_a/ring.png" not in [f.rel_path for f in first.skipped]
    assert "vendor_a/ring.png" not in [f.rel_path for f in first.files]
    assert "ring.png" in caplog.text and "device not ready" in caplog.text

    target = tmp_path / "cache" / "index.npz"
    save_index(first, target)
    with np.load(target) as data:
        persisted = set(data["rel_paths"].tolist()) | set(data["skipped_paths"].tolist())
    assert "vendor_a/ring.png" not in persisted
    loaded = load_index(target)
    assert loaded.transient == []

    state["failing"] = False
    embedder = CountingEmbedder()
    second = build_index(library, embedder, existing=loaded)

    assert embedder.count == 1  # пересчитан только файл, который раньше не удалось прочитать
    assert "vendor_a/ring.png" in [f.rel_path for f in second.files]
    assert second.transient == [] and [f.rel_path for f in second.skipped] == ["blank.png"]


@pytest.mark.parametrize(
    "make_error",
    [
        lambda: UnidentifiedImageError("cannot identify image file"),
        lambda: ValueError("bad value"),
        lambda: SyntaxError("broken PNG file"),
        lambda: cv2.error("bad image"),
        lambda: Image.DecompressionBombError("too large"),
    ],
    ids=["unidentified", "value", "syntax", "cv2", "bomb"],
)
def test_definitive_decode_failures_are_skipped_and_persisted(library, tmp_path, monkeypatch, make_error):
    _fail_on(monkeypatch, "ring.png", make_error)

    index = build_index(library, CountingEmbedder())

    assert "vendor_a/ring.png" in [f.rel_path for f in index.skipped]
    assert index.transient == []
    target = tmp_path / "index.npz"
    save_index(index, target)
    assert "vendor_a/ring.png" in [f.rel_path for f in load_index(target).skipped]


def test_corrupt_png_stays_skipped_and_is_not_reopened(library, monkeypatch):
    (library / "vendor_a" / "broken.png").write_bytes(b"not a png")
    first = build_index(library, CountingEmbedder())
    assert "vendor_a/broken.png" in [f.rel_path for f in first.skipped] and first.transient == []

    state = _fail_on(monkeypatch, "nothing.png", RuntimeError)  # только для учёта открытых файлов
    second = build_index(library, CountingEmbedder(), existing=first)

    assert state["opened"] == []
    assert "vendor_a/broken.png" in [f.rel_path for f in second.skipped]


def test_library_where_every_read_is_transient_raises_none_could_be_read(library, monkeypatch):
    from gmagc_desktop.library import index as index_module

    def unplugged(path):
        raise OSError("device not ready")

    monkeypatch.setattr(index_module, "load_library_gray", unplugged)
    with pytest.raises(LibraryScanError, match=r"none of the 7 library files could be read"):
        build_index(library, CountingEmbedder())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/library/test_index.py -v`
Expected: FAIL (`ModuleNotFoundError: gmagc_desktop.library.index`).

- [ ] **Step 3: Write minimal implementation**

```python
# path: apps/desktop/gmagc_desktop/library/index.py
"""Индекс библиотеки: эмбеддинги, маски формы, семейства дублей; кэш на диске."""

from __future__ import annotations

import logging
import os
import tokenize
import zipfile
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError

from gmagc_desktop.library.grouping import group_duplicates
from gmagc_desktop.library.scan import LibraryFile, scan_library_checked
from gmagc_desktop.matcher.embedder import Embedder
from gmagc_desktop.matcher.imageio import load_library_gray
from gmagc_desktop.matcher.normalize import normalize_gray
from gmagc_desktop.matcher.search import SearchData
from gmagc_desktop.matcher.shape import soft_mask

logger = logging.getLogger(__name__)

FORMAT_VERSION = 1
ProgressCallback = Callable[[int, int], None]


class IndexCancelled(Exception):
    """Индексация прервана по запросу пользователя."""


class LibraryNotFound(FileNotFoundError):
    """Папка библиотеки не существует (например, отключён диск)."""


class LibraryScanError(RuntimeError):
    """Библиотеку нельзя надёжно проиндексировать: частичный или пустой результат не сохраняем."""


@dataclass
class LibraryIndex:
    model_id: str
    files: list[LibraryFile]
    embeddings: np.ndarray  # (N, D) float32
    masks: np.ndarray  # (N, 64, 64) uint8
    group_ids: np.ndarray  # (N,) int32
    skipped: list[LibraryFile] = field(default_factory=list)
    # Не удалось прочитать сейчас (временный сбой). В кэш не сохраняется: следующая сборка попробует снова.
    transient: list[LibraryFile] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.files)

    def search_data(self) -> SearchData:
        return SearchData(self.embeddings, self.masks, self.group_ids)


# Окончательные сбои декодирования: файл испорчен, повторное открытие ничего не изменит.
# UnidentifiedImageError — подкласс OSError, поэтому перехватывается раньше общего OSError.
_DEFINITIVE = (UnidentifiedImageError, ValueError, SyntaxError, cv2.error, Image.DecompressionBombError)


class _TransientReadError(Exception):
    """Временный сбой чтения (устройство не готово, сетевой сбой, блокировка): файл повторят при следующей сборке."""


def _load_normalized(path: Path) -> np.ndarray | None:
    """Нормализованное изображение или None, если файл окончательно нечитаем (испорчен или пустой).

    Прочие OSError — временный сбой: _TransientReadError. PermissionError и ошибки программы не глотаются.
    """
    try:
        normalized = normalize_gray(load_library_gray(path))
    except PermissionError:
        raise
    except _DEFINITIVE as error:
        logger.warning("skipping unreadable library file %s: %s", path, error)
        return None
    except OSError as error:
        logger.warning("library file %s cannot be read right now, will retry next time: %s", path, error)
        raise _TransientReadError(str(error)) from error
    return normalized


def build_index(
    root: str | Path,
    embedder: Embedder,
    existing: LibraryIndex | None = None,
    progress: ProgressCallback | None = None,
    batch_size: int = 64,
    cancel: Callable[[], bool] | None = None,
) -> LibraryIndex:
    root = Path(root)
    if not root.is_dir():
        raise LibraryNotFound(f"library folder not found: {root}")
    scanned, problems = scan_library_checked(root)
    if problems:
        raise LibraryScanError(
            f"{len(problems)} problem(s) while scanning {root}: {'; '.join(problems[:3])}; "
            "refusing to build a partial index"
        )
    if not scanned:
        raise LibraryScanError(f"no PNG/BMP files found in {root}")

    reusable: dict[LibraryFile, int] = {}
    known_skipped: set[LibraryFile] = set()
    if existing is not None and existing.model_id == embedder.model_id:
        reusable = {file: i for i, file in enumerate(existing.files)}
        known_skipped = set(existing.skipped)

    todo = [f for f in scanned if f not in reusable and f not in known_skipped]
    skipped = [f for f in scanned if f in known_skipped]
    transient: list[LibraryFile] = []
    fresh: dict[LibraryFile, tuple[np.ndarray, np.ndarray]] = {}

    for start in range(0, len(todo), batch_size):
        if cancel is not None and cancel():
            raise IndexCancelled()
        loaded: list[tuple[LibraryFile, np.ndarray]] = []
        for file in todo[start : start + batch_size]:
            try:
                normalized = _load_normalized(root / file.rel_path)
            except _TransientReadError:
                transient.append(file)
                continue
            if normalized is None:
                skipped.append(file)
            else:
                loaded.append((file, normalized))
        if loaded:
            vectors = embedder.embed(np.stack([normalized for _, normalized in loaded]))
            for (file, normalized), vector in zip(loaded, vectors, strict=True):
                fresh[file] = (soft_mask(normalized), vector)
        if progress is not None:
            progress(min(start + batch_size, len(todo)), len(todo))

    skipped.sort(key=lambda f: f.rel_path)
    files = [f for f in scanned if f in reusable or f in fresh]
    if not files:
        raise LibraryScanError(f"none of the {len(scanned)} library files could be read")

    embeddings = np.stack(
        [existing.embeddings[reusable[f]] if f in reusable else fresh[f][1] for f in files]
    ).astype(np.float32)
    masks = np.stack([existing.masks[reusable[f]] if f in reusable else fresh[f][0] for f in files])
    return LibraryIndex(
        embedder.model_id, files, embeddings, masks, group_duplicates(embeddings, masks), skipped, transient
    )


def save_index(index: LibraryIndex, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with open(temporary, "wb") as handle:
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


def _files(paths: np.ndarray, sizes: np.ndarray, mtimes: np.ndarray) -> list[LibraryFile]:
    return [
        LibraryFile(str(p), int(s), int(m)) for p, s, m in zip(paths, sizes, mtimes, strict=True)
    ]


def load_index(path: str | Path) -> LibraryIndex | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        with np.load(path, allow_pickle=False) as data:
            if int(data["format_version"]) != FORMAT_VERSION:
                return None
            return LibraryIndex(
                model_id=str(data["model_id"]),
                files=_files(data["rel_paths"], data["sizes"], data["mtimes"]),
                embeddings=data["embeddings"].astype(np.float32),
                masks=data["masks"],
                group_ids=data["group_ids"],
                skipped=_files(data["skipped_paths"], data["skipped_sizes"], data["skipped_mtimes"]),
            )
    except (
        OSError,
        KeyError,
        ValueError,
        EOFError,
        NotImplementedError,
        zipfile.BadZipFile,
        zlib.error,
        tokenize.TokenError,  # numpy разбирает заголовок .npy токенайзером
    ):
        return None
```

- [ ] **Step 4: Run test to verify it passes, commit**

Run: `.venv\Scripts\python.exe -m pytest tests/library/test_index.py -v`
Expected: 27 passed. Если `test_build_indexes_valid_files...` падает на числе семейств (две разные фикстурные фигуры склеились), подправить фигуру в `tests/fixtures.py`, а не порог группировки.

```bash
git add apps tests
git commit -m "feat: add library index with incremental build and disk cache" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 11: Конвейер «фото → нормализованный вид» и CLI

**Files:**
- Create: `apps/desktop/gmagc_desktop/matcher/pipeline.py`, `apps/desktop/gmagc_desktop/cli.py`
- Test: `tests/matcher/test_pipeline.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `extract_projection` (Task 3), `normalize_gray` (Task 2), `build_index`/`load_index`/`save_index` (Task 10), `Searcher` (Task 9), `OnnxEmbedder`/`PixelEmbedder` (Task 5), `write_library`/`shape_images` (Task 7).
- Produces:
  - `normalize_photo(bgr: np.ndarray) -> np.ndarray | None`: `extract_projection` + `normalize_gray`; `None`, если проекция не найдена.
  - `make_embedder(model: str | None) -> Embedder` (`OnnxEmbedder`, если задан путь, иначе `PixelEmbedder`), `main(argv: list[str] | None = None) -> int`.
  - Команды: `index LIBRARY --index FILE [--model ONNX]` печатает `N files indexed (K unique), S skipped`, код 0; `search PHOTO --index FILE [--model ONNX] [--library DIR] [--top 10] [--w-embed 0.5]` печатает строки `" 1.  87.3%  vendor_b/ell.png  (+1 copies)"`; коды выхода: 0 успех, 1 нет/несовместимый индекс или нет папки библиотеки, 2 проекция не найдена, 3 нечитаемый входной файл (фото или модель; одна строка в stderr, без traceback). Порядок в `search`: индекс → фото → эмбеддер → совпадение `model_id` → проекция.

- [ ] **Step 1: Write the failing tests**

```python
# path: tests/matcher/test_pipeline.py
import numpy as np

from gmagc_desktop.matcher.normalize import NORM_SIZE
from gmagc_desktop.matcher.pipeline import normalize_photo
from gmagc_desktop.matcher.synthetic import simulate_photo
from tests.helpers import sample_gobo


def test_simulated_photo_gives_normalized_image():
    out = normalize_photo(simulate_photo(sample_gobo(), np.random.default_rng(2)))
    assert out is not None and out.shape == (NORM_SIZE, NORM_SIZE)


def test_flat_photo_gives_none():
    assert normalize_photo(np.full((480, 640, 3), 90, np.uint8)) is None
```

```python
# path: tests/test_cli.py
import cv2
import numpy as np
import pytest

from gmagc_desktop import cli
from gmagc_desktop.library.index import LibraryIndex, save_index
from gmagc_desktop.matcher.embedder import PixelEmbedder
from gmagc_desktop.matcher.synthetic import simulate_photo
from tests.fixtures import make_folder_unlistable, shape_images, write_library


@pytest.fixture()
def indexed(tmp_path, capsys):
    library = tmp_path / "lib"
    library.mkdir()
    write_library(library)
    index_path = tmp_path / "index.npz"
    assert cli.main(["index", str(library), "--index", str(index_path)]) == 0
    capsys.readouterr()
    return library, index_path, tmp_path


def save_photo(directory, name, image):
    path = directory / name
    cv2.imencode(".png", image)[1].tofile(str(path))
    return path


def test_index_reports_counts(tmp_path, capsys):
    library = tmp_path / "lib"
    library.mkdir()
    write_library(library)
    assert cli.main(["index", str(library), "--index", str(tmp_path / "i.npz")]) == 0
    assert "6 files indexed (5 unique), 1 skipped" in capsys.readouterr().out


def test_index_reports_files_that_are_unreadable_right_now_and_writes_no_trace_of_them(tmp_path, monkeypatch, capsys):
    from gmagc_desktop.library import index as index_module

    library = tmp_path / "lib"
    library.mkdir()
    write_library(library)
    real = index_module.load_library_gray

    def loader(path):
        if path.name == "ring.png":
            raise OSError("device not ready")
        return real(path)

    monkeypatch.setattr(index_module, "load_library_gray", loader)
    target = tmp_path / "i.npz"

    assert cli.main(["index", str(library), "--index", str(target)]) == 0

    out = capsys.readouterr().out
    assert "5 files indexed (4 unique), 1 skipped, 1 unreadable now (will be retried)" in out
    with np.load(target) as data:
        assert "vendor_a/ring.png" not in data["rel_paths"].tolist() + data["skipped_paths"].tolist()


def test_index_of_missing_library_returns_3_and_writes_nothing(tmp_path, capsys):
    target = tmp_path / "i.npz"
    assert cli.main(["index", str(tmp_path / "nope"), "--index", str(target)]) == 3
    assert "library folder not found" in capsys.readouterr().err
    assert not target.exists()


def test_search_finds_the_right_gobo(indexed, capsys):
    library, index_path, tmp = indexed
    photo = save_photo(tmp, "p.png", simulate_photo(shape_images()["ell"], np.random.default_rng(5)))

    code = cli.main(["search", str(photo), "--index", str(index_path), "--top", "3"])

    first = capsys.readouterr().out.splitlines()[0]
    assert code == 0 and first.startswith(" 1.") and "ell" in first and "(+1 copies)" in first


def test_search_prints_full_paths_when_library_given(indexed, capsys):
    library, index_path, tmp = indexed
    photo = save_photo(tmp, "p.png", simulate_photo(shape_images()["ring"], np.random.default_rng(6)))
    cli.main(["search", str(photo), "--index", str(index_path), "--library", str(library)])
    assert str(library) in capsys.readouterr().out.splitlines()[0]


def test_search_without_projection_returns_2(indexed, capsys):
    library, index_path, tmp = indexed
    flat = save_photo(tmp, "flat.png", np.full((480, 640, 3), 90, np.uint8))
    assert cli.main(["search", str(flat), "--index", str(index_path)]) == 2
    assert "projection not found" in capsys.readouterr().err


def test_search_without_index_returns_1(tmp_path, capsys):
    photo = save_photo(tmp_path, "p.png", np.full((32, 32, 3), 90, np.uint8))
    assert cli.main(["search", str(photo), "--index", str(tmp_path / "nope.npz")]) == 1
    assert "index not found" in capsys.readouterr().err


def test_search_with_other_model_than_index_returns_1(indexed, monkeypatch, capsys):
    library, index_path, tmp = indexed
    photo = save_photo(tmp, "p.png", simulate_photo(shape_images()["ell"], np.random.default_rng(5)))
    monkeypatch.setattr(cli, "make_embedder", lambda model: PixelEmbedder(side=8))
    assert cli.main(["search", str(photo), "--index", str(index_path)]) == 1
    assert "index was built with" in capsys.readouterr().err


def test_search_with_embedder_of_other_dimensions_returns_1_and_asks_to_rebuild(indexed, monkeypatch, capsys):
    library, index_path, tmp = indexed
    photo = save_photo(tmp, "p.png", simulate_photo(shape_images()["ell"], np.random.default_rng(5)))
    other = PixelEmbedder(side=8)
    other.model_id = "pixels-16"  # тот же model_id, что в индексе, но другая размерность векторов
    monkeypatch.setattr(cli, "make_embedder", lambda model: other)

    code = cli.main(["search", str(photo), "--index", str(index_path)])

    out, err = capsys.readouterr()
    assert code == 1 and "rebuild the index" in err and "Traceback" not in err
    assert out == ""


def test_search_with_missing_photo_returns_3(indexed, monkeypatch, capsys):
    library, index_path, tmp = indexed
    msg = "model must not be built before photo is read"
    monkeypatch.setattr(cli, "make_embedder", lambda model: (_ for _ in ()).throw(AssertionError(msg)))
    code = cli.main(["search", str(tmp / "nope.png"), "--index", str(index_path)])
    out, err = capsys.readouterr()
    assert code == 3
    assert "cannot read photo" in err
    assert "Traceback" not in err


def test_search_with_zero_byte_photo_returns_3(indexed, capsys):
    library, index_path, tmp = indexed
    path = tmp / "empty.jpg"
    path.write_bytes(b"")
    code = cli.main(["search", str(path), "--index", str(index_path)])
    out, err = capsys.readouterr()
    assert code == 3
    assert "cannot read photo" in err


def test_search_with_non_image_photo_returns_3(indexed, capsys):
    library, index_path, tmp = indexed
    path = tmp / "text.png"
    path.write_bytes(b"not an image")
    code = cli.main(["search", str(path), "--index", str(index_path)])
    out, err = capsys.readouterr()
    assert code == 3
    assert "cannot read photo" in err


def test_search_with_missing_model_returns_3(indexed, capsys):
    library, index_path, tmp = indexed
    photo = save_photo(tmp, "p.png", simulate_photo(shape_images()["ell"], np.random.default_rng(5)))
    code = cli.main(["search", str(photo), "--index", str(index_path), "--model", str(tmp / "nope.onnx")])
    out, err = capsys.readouterr()
    assert code == 3
    assert "cannot load model" in err


def test_index_with_missing_model_returns_3(tmp_path, capsys):
    library = tmp_path / "lib"
    library.mkdir()
    write_library(library)
    target = tmp_path / "x.npz"
    code = cli.main(["index", str(library), "--index", str(target), "--model", str(tmp_path / "nope.onnx")])
    out, err = capsys.readouterr()
    assert code == 3
    assert not target.exists()


def test_search_with_corrupt_model_returns_3(indexed, capsys):
    library, index_path, tmp = indexed
    garbage = tmp / "garbage.onnx"
    garbage.write_bytes(b"not an onnx model")
    photo = save_photo(tmp, "p.png", simulate_photo(shape_images()["ell"], np.random.default_rng(5)))
    code = cli.main(["search", str(photo), "--index", str(index_path), "--model", str(garbage)])
    out, err = capsys.readouterr()
    assert code == 3
    assert "cannot load model" in err
    assert "Traceback" not in err


def test_index_with_corrupt_model_returns_3(tmp_path, capsys):
    library = tmp_path / "lib"
    library.mkdir()
    write_library(library)
    garbage = tmp_path / "garbage.onnx"
    garbage.write_bytes(b"not an onnx model")
    target = tmp_path / "y.npz"
    code = cli.main(["index", str(library), "--index", str(target), "--model", str(garbage)])
    out, err = capsys.readouterr()
    assert code == 3
    assert "cannot load model" in err
    assert not target.exists()


def test_index_with_an_unlistable_folder_returns_3_and_keeps_the_existing_index(indexed, monkeypatch, capsys):
    library, index_path, tmp = indexed
    before = index_path.read_bytes()
    make_folder_unlistable(monkeypatch, "vendor_b")

    code = cli.main(["index", str(library), "--index", str(index_path)])

    err = capsys.readouterr().err
    assert code == 3
    assert "cannot list directory" in err and "refusing to build a partial index" in err
    assert index_path.read_bytes() == before


def test_index_of_an_empty_library_returns_3_and_keeps_the_existing_index(indexed, capsys):
    library, index_path, tmp = indexed
    before = index_path.read_bytes()
    empty = tmp / "empty_lib"
    empty.mkdir()

    code = cli.main(["index", str(empty), "--index", str(index_path)])

    assert code == 3 and "no PNG/BMP files found" in capsys.readouterr().err
    assert index_path.read_bytes() == before


def test_index_of_an_empty_library_writes_no_index_file(tmp_path, capsys):
    empty = tmp_path / "empty_lib"
    empty.mkdir()
    target = tmp_path / "fresh.npz"

    assert cli.main(["index", str(empty), "--index", str(target)]) == 3
    assert not target.exists()


def test_search_on_an_empty_index_returns_1_with_a_hint(tmp_path, capsys):
    empty_index = LibraryIndex(
        "pixels-16",
        [],
        np.zeros((0, 0), np.float32),
        np.zeros((0, 64, 64), np.uint8),
        np.zeros(0, np.int32),
    )
    index_path = tmp_path / "empty.npz"
    save_index(empty_index, index_path)
    photo = save_photo(tmp_path, "p.png", simulate_photo(shape_images()["ell"], np.random.default_rng(5)))

    code = cli.main(["search", str(photo), "--index", str(index_path)])

    assert code == 1
    assert "index is empty; rebuild it with the 'index' command" in capsys.readouterr().err


def test_read_photo_and_build_embedder_are_public_and_report_to_stderr(tmp_path, capsys):
    assert cli.read_photo(tmp_path / "nope.png") is None
    assert "cannot read photo" in capsys.readouterr().err
    assert cli.build_embedder(str(tmp_path / "nope.onnx")) is None
    assert "cannot load model" in capsys.readouterr().err
    assert isinstance(cli.build_embedder(None), PixelEmbedder)


def test_w_embed_default_is_defined_once(tmp_path):
    import inspect

    from gmagc_desktop.matcher.search import DEFAULT_W_EMBED, Searcher

    assert DEFAULT_W_EMBED == 0.5
    assert inspect.signature(Searcher).parameters["w_embed"].default == DEFAULT_W_EMBED
    args = cli.build_parser().parse_args(["search", "p.png", "--index", "i.npz"])
    assert args.w_embed == DEFAULT_W_EMBED
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/matcher/test_pipeline.py tests/test_cli.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Write minimal implementation**

```python
# path: apps/desktop/gmagc_desktop/matcher/pipeline.py
"""Фото -> нормализованное изображение, готовое к поиску."""

from __future__ import annotations

import numpy as np

from gmagc_desktop.matcher.normalize import normalize_gray
from gmagc_desktop.matcher.segment import extract_projection


def normalize_photo(bgr: np.ndarray) -> np.ndarray | None:
    """Сегментация проекции + нормализация 224x224; None, если проекция не найдена."""
    crop = extract_projection(bgr)
    return None if crop is None else normalize_gray(crop)
```

```python
# path: apps/desktop/gmagc_desktop/cli.py
"""Командная строка ядра: index и search.

Коды возврата:
0 - успех;
1 - индекс отсутствует, несовместим (другая модель или размерность) или пуст;
2 - проекция на фото не найдена;
3 - вход нечитаем (фото, модель, папка библиотеки).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from gmagc_desktop.library.index import LibraryNotFound, LibraryScanError, build_index, load_index, save_index
from gmagc_desktop.matcher.embedder import Embedder, OnnxEmbedder, PixelEmbedder
from gmagc_desktop.matcher.imageio import load_photo_bgr
from gmagc_desktop.matcher.pipeline import normalize_photo
from gmagc_desktop.matcher.search import DEFAULT_W_EMBED, IndexMismatchError, Searcher


def make_embedder(model: str | None) -> Embedder:
    return OnnxEmbedder(model) if model else PixelEmbedder()


def read_photo(path: str | Path) -> np.ndarray | None:
    """Load photo from path; return None after printing error message to stderr."""
    try:
        return load_photo_bgr(path)
    except (OSError, ValueError) as error:
        print(f"cannot read photo {path}: {error}", file=sys.stderr)
        return None


def build_embedder(model: str | None) -> Embedder | None:
    """Build embedder; return None after printing error message to stderr."""
    try:
        return make_embedder(model)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"cannot load model {model}: {error}", file=sys.stderr)
        return None


def _progress(done: int, total: int) -> None:
    print(f"\rindexing {done}/{total}", end="", file=sys.stderr, flush=True)


def _cmd_index(args: argparse.Namespace) -> int:
    embedder = build_embedder(args.model)
    if embedder is None:
        return 3
    try:
        index = build_index(
            args.library, embedder, existing=load_index(args.index), progress=_progress
        )
    except (LibraryNotFound, LibraryScanError) as error:
        print(file=sys.stderr)
        print(error, file=sys.stderr)
        return 3
    print(file=sys.stderr)
    save_index(index, args.index)
    unique = len(set(index.group_ids.tolist()))
    retry = f", {len(index.transient)} unreadable now (will be retried)" if index.transient else ""
    print(f"{len(index)} files indexed ({unique} unique), {len(index.skipped)} skipped{retry}")
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    index = load_index(args.index)
    if index is None:
        print("index not found or unreadable; run 'index' first", file=sys.stderr)
        return 1
    if len(index) == 0:
        print("index is empty; rebuild it with the 'index' command", file=sys.stderr)
        return 1
    photo = read_photo(args.photo)
    if photo is None:
        return 3
    embedder = build_embedder(args.model)
    if embedder is None:
        return 3
    if index.model_id != embedder.model_id:
        print(
            f"index was built with '{index.model_id}', search uses '{embedder.model_id}'",
            file=sys.stderr,
        )
        return 1
    normalized = normalize_photo(photo)
    if normalized is None:
        print("projection not found on the photo", file=sys.stderr)
        return 2
    searcher = Searcher(index.search_data(), embedder, w_embed=args.w_embed)
    root = Path(args.library) if args.library else None
    try:
        matches = searcher.search(normalized, top_n=args.top)
    except IndexMismatchError as error:
        print(error, file=sys.stderr)
        return 1
    for rank, match in enumerate(matches, start=1):
        rel = index.files[match.index].rel_path
        shown = str(root / rel) if root else rel
        extra = f"  (+{len(match.members) - 1} copies)" if len(match.members) > 1 else ""
        print(f"{rank:2d}. {match.score * 100:5.1f}%  {shown}{extra}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gmagc", description=__doc__)
    commands = parser.add_subparsers(required=True)

    index = commands.add_parser("index", help="построить или обновить индекс библиотеки")
    index.add_argument("library", type=Path)
    index.add_argument("--index", type=Path, required=True)
    index.add_argument("--model", default=None, help="путь к ONNX-модели (иначе пиксельный baseline)")
    index.set_defaults(handler=_cmd_index)

    search = commands.add_parser("search", help="найти гобо по фото")
    search.add_argument("photo", type=Path)
    search.add_argument("--index", type=Path, required=True)
    search.add_argument("--model", default=None)
    search.add_argument("--library", type=Path, default=None, help="печатать полные пути")
    search.add_argument("--top", type=int, default=10)
    search.add_argument("--w-embed", type=float, default=DEFAULT_W_EMBED)
    search.set_defaults(handler=_cmd_search)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass, commit**

Run: `.venv\Scripts\python.exe -m pytest tests/matcher/test_pipeline.py tests/test_cli.py -v`
Expected: 24 passed. Если `test_search_finds_the_right_gobo` даёт не тот файл, выяснить причину (сегментация симулятора или baseline); тест не ослаблять, а подобрать другой фиксированный seed только если проблема в конкретной случайной перспективе.

```bash
git add apps tests
git commit -m "feat: add photo pipeline and index/search CLI" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 12: Скрипт загрузки ONNX-модели (dev)

**Files:**
- Create: `scripts/fetch_model.py`
- Modify: `.gitignore` (добавить строки в конец)
- Test: `tests/test_fetch_model.py`

**Interfaces:**
- Produces: `scripts/fetch_model.py --variant {fp32,int8,fp16} [--out models]` скачивает `onnx-community/dinov2-small` (`onnx/model.onnx`, `onnx/model_int8.onnx`, `onnx/model_fp16.onnx`) в `models/dinov2-small-<variant>.onnx`, печатает и сохраняет SHA-256 рядом (`*.onnx.sha256`). Единственное место, которому нужен интернет. Функция `variant_url(variant: str) -> str`. Скачивание идёт через `download(url, target, timeout=60.0) -> str`: временный файл `*.part`, сверка с `Content-Length`, `os.replace` только после полной загрузки, `.sha256` пишется последним; существующий файл пропускается без `--force`.
- На карточке Hugging Face у `onnx-community/dinov2-small` лицензия не указана. Перед включением модели в сборку проверить лицензию исходной модели `facebook/dinov2-small` и записать вывод в `docs/benchmarks/` (Task 15).

- [ ] **Step 1: Write the failing test**

```python
# path: tests/test_fetch_model.py
import hashlib
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "fetch_model.py"


def load_script():
    spec = importlib.util.spec_from_file_location("fetch_model", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_variant_urls():
    module = load_script()
    base = "https://huggingface.co/onnx-community/dinov2-small/resolve/main/onnx/"
    assert module.variant_url("fp32") == base + "model.onnx"
    assert module.variant_url("int8") == base + "model_int8.onnx"
    assert module.variant_url("fp16") == base + "model_fp16.onnx"


def test_unknown_variant_is_rejected():
    with pytest.raises(KeyError):
        load_script().variant_url("q4")


class FakeResponse:
    def __init__(self, chunks, content_length=None, fail_after=None):
        self._chunks = list(chunks)
        self._sent = 0
        self._fail_after = fail_after
        self.headers = {} if content_length is None else {"Content-Length": str(content_length)}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, size):
        if self._fail_after is not None and self._sent >= self._fail_after:
            raise ConnectionResetError("boom")
        if not self._chunks:
            return b""
        self._sent += 1
        return self._chunks.pop(0)


def fake_urlopen(response):
    return lambda url, timeout=None: response


def test_download_writes_target_returns_sha256_and_leaves_no_part(tmp_path, monkeypatch):
    module = load_script()
    chunks = [b"a" * 1000, b"b" * 500]
    content_length = 1500
    response = FakeResponse(chunks, content_length=content_length)
    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen(response))

    target = tmp_path / "dinov2.onnx"
    checksum = module.download("http://example.com/model.onnx", target)

    # Verify target content
    expected_content = b"a" * 1000 + b"b" * 500
    assert target.read_bytes() == expected_content

    # Verify checksum
    expected_hash = hashlib.sha256(expected_content).hexdigest()
    assert checksum == expected_hash

    # Verify .part file does not exist
    part = target.with_name(target.name + ".part")
    assert not part.exists()


def test_short_download_keeps_the_existing_model(tmp_path, monkeypatch):
    module = load_script()
    target = tmp_path / "dinov2.onnx"
    target.write_bytes(b"good")

    chunks = [b"x" * 10]
    response = FakeResponse(chunks, content_length=100)
    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen(response))

    with pytest.raises(OSError, match="incomplete"):
        module.download("http://example.com/model.onnx", target)

    # Verify target still has original content
    assert target.read_bytes() == b"good"

    # Verify .part file does not exist
    part = target.with_name(target.name + ".part")
    assert not part.exists()


def test_interrupted_download_leaves_neither_target_nor_part(tmp_path, monkeypatch):
    module = load_script()
    chunks = [b"x" * 10, b"y" * 10]
    response = FakeResponse(chunks, fail_after=1)
    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen(response))

    target = tmp_path / "dinov2.onnx"

    with pytest.raises(ConnectionResetError):
        module.download("http://example.com/model.onnx", target)

    # Verify target does not exist
    assert not target.exists()

    # Verify .part file does not exist
    part = target.with_name(target.name + ".part")
    assert not part.exists()


def test_main_skips_an_existing_model_without_force(tmp_path, monkeypatch):
    module = load_script()
    target = tmp_path / "dinov2-small-fp32.onnx"
    target.write_bytes(b"existing")

    # Monkeypatch download to raise if called
    def mock_download(*args, **kwargs):
        raise AssertionError("must not download")

    monkeypatch.setattr(module, "download", mock_download)

    result = module.main(["--out", str(tmp_path)])

    assert result == 0
    # File should be unchanged
    assert target.read_bytes() == b"existing"


def test_main_force_redownloads_and_writes_checksum_last(tmp_path, monkeypatch):
    module = load_script()
    target = tmp_path / "dinov2-small-fp32.onnx"
    target.write_bytes(b"old")

    # Monkeypatch download to write new content and return checksum
    def mock_download(url, target_path, timeout=60.0):
        target_path.write_bytes(b"new")
        return "abc123"

    monkeypatch.setattr(module, "download", mock_download)

    result = module.main(["--out", str(tmp_path), "--force"])

    assert result == 0
    # Target should have new content
    assert target.read_bytes() == b"new"
    # Checksum file should exist and have correct format
    sha_file = tmp_path / "dinov2-small-fp32.onnx.sha256"
    assert sha_file.read_text(encoding="utf-8") == "abc123  dinov2-small-fp32.onnx\n"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_fetch_model.py -v`
Expected: FAIL (`FileNotFoundError` / нет скрипта).

- [ ] **Step 3: Write minimal implementation**

```python
# path: scripts/fetch_model.py
"""Скачивание ONNX-модели эмбеддингов (dev-инструмент; единственное место, где нужен интернет)."""

from __future__ import annotations

import argparse
import hashlib
import os
import urllib.request
from pathlib import Path

BASE_URL = "https://huggingface.co/onnx-community/dinov2-small/resolve/main/onnx/"
VARIANTS = {"fp32": "model.onnx", "int8": "model_int8.onnx", "fp16": "model_fp16.onnx"}


def variant_url(variant: str) -> str:
    return BASE_URL + VARIANTS[variant]


def download(url: str, target: Path, timeout: float = 60.0) -> str:
    """Скачивает url через временный файл и возвращает SHA-256. target появляется только после полной загрузки."""
    part = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    written = 0
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response, open(part, "wb") as handle:
            expected = response.headers.get("Content-Length")
            while chunk := response.read(1 << 20):
                handle.write(chunk)
                digest.update(chunk)
                written += len(chunk)
        if expected is not None and written != int(expected):
            raise OSError(f"incomplete download: got {written} of {expected} bytes")
        os.replace(part, target)
    finally:
        part.unlink(missing_ok=True)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=sorted(VARIANTS), default="fp32")
    parser.add_argument("--out", type=Path, default=Path("models"))
    parser.add_argument("--force", action="store_true", help="скачать заново, даже если файл уже есть")
    args = parser.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / f"dinov2-small-{args.variant}.onnx"

    if target.exists() and not args.force:
        print(f"{target} already exists; use --force to download it again")
        return 0

    url = variant_url(args.variant)
    print(f"downloading {url}")
    checksum = download(url, target)
    (args.out / f"{target.name}.sha256").write_text(f"{checksum}  {target.name}\n", encoding="utf-8")
    print(f"saved {target} sha256={checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Добавить в конец `.gitignore`:

```
# Скачанные модели (загружаются scripts/fetch_model.py, в git не хранятся)
models/*.onnx
```

- [ ] **Step 4: Run test to verify it passes, commit**

Run: `.venv\Scripts\python.exe -m pytest tests/test_fetch_model.py -v`
Expected: 7 passed.

```bash
git add scripts tests .gitignore
git commit -m "feat: add ONNX model fetch script" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 13: Бенчмарк качества

**Files:**
- Create: `scripts/benchmark.py`
- Test: `tests/test_scripts.py` (создаётся здесь, дополняется в Task 14)

**Interfaces:**
- Consumes: `build_index`/`load_index`/`save_index`, `Searcher`, `normalize_photo`, `simulate_photo`, `OnnxEmbedder`/`PixelEmbedder`, `load_library_gray`, `load_photo_bgr`.
- Produces (`scripts/benchmark.py`):
  - `PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png"}`
  - `load_or_build(root: Path, embedder, index_path: Path) -> LibraryIndex`: кэш индекса на диске, дозапись при повторном запуске.
  - `synthetic_eval(index, root, searcher, samples, seed) -> dict` с ключами `samples, top1, top5, segmentation_failed, median_ms`. Берётся по одному представителю каждого семейства, из него `simulate_photo`, затем полный пайплайн; попадание считается по семейству.
  - `real_eval(index, searcher, photos_dir, labels_path) -> dict | None`: ключи `rows, labeled, top1, top5`; `None`, если папки нет. Формат `labels.json`: `{"<имя фото>": ["<rel_path файла>", ...] | null}` (`null` значит «этого гобо нет в библиотеке»). Семантика: сбой сегментации на размеченном фото это промах (остаётся в знаменателе); нечитаемое фото и ошибка разметки (пустой список, неизвестный путь, неверный тип) не входят в метрики и считаются в `unreadable` / `label_errors`; слэши в путях разметки нормализуются; битый `labels.json` даёт `LabelsError` (в `main` код выхода 3); печатаемые проценты не превышают 100.
  - `main(argv) -> int`: `--library DIR` (обязателен), `--model ONNX`, `--index FILE` (по умолчанию `.gmagc-cache/index-<model_id>.npz`), `--samples 300`, `--seed 0`, `--w-embed 0.5`, `--photos DIR` (по умолчанию `photo/`), `--labels FILE` (по умолчанию `<photos>/labels.json`).

- [ ] **Step 1: Write the failing test**

```python
# path: tests/test_scripts.py
import json
import re
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import benchmark  # noqa: E402

from gmagc_desktop import cli  # noqa: E402
from gmagc_desktop.matcher.search import Searcher  # noqa: E402
from gmagc_desktop.matcher.synthetic import simulate_photo  # noqa: E402
from tests.fixtures import shape_images, write_library  # noqa: E402


def make_library(tmp_path):
    library = tmp_path / "lib"
    library.mkdir()
    write_library(library)
    return library


def save_photo(directory, name, gobo, seed):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    cv2.imencode(".png", simulate_photo(gobo, np.random.default_rng(seed)))[1].tofile(str(path))
    return path


def build_searcher(tmp_path):
    library = make_library(tmp_path)
    embedder = cli.make_embedder(None)
    index = benchmark.load_or_build(library, embedder, tmp_path / "idx.npz")
    return index, Searcher(index.search_data(), embedder)


def write_labels(photos, mapping):
    photos.mkdir(parents=True, exist_ok=True)
    (photos / "labels.json").write_text(json.dumps(mapping), encoding="utf-8")


def test_benchmark_synthetic_smoke(tmp_path, capsys):
    library = make_library(tmp_path)
    code = benchmark.main(
        [
            "--library", str(library),
            "--samples", "4",
            "--index", str(tmp_path / "idx.npz"),
            "--photos", str(tmp_path / "no_photos"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "synthetic (n=4)" in out and "top-1" in out and "top-5" in out
    assert "no real photos" in out
    # With 5 families, samples=4, all segmentable -> top-5 should be 100%
    match = re.search(r"top-1 ([\d.]+)%.*top-5 ([\d.]+)%", out)
    assert match, "synthetic line missing top-1/top-5 percentages"
    top1, top5 = float(match.group(1)), float(match.group(2))
    assert 0 <= top1 <= top5 <= 100, f"top-1={top1}% should be <= top-5={top5}%"
    assert top5 == 100.0, f"top-5 should be 100.0% with 5 families and 4 samples, got {top5}%"


def test_benchmark_real_photos_with_labels(tmp_path, capsys):
    library = make_library(tmp_path)
    photos = tmp_path / "photos"
    save_photo(photos, "a.png", shape_images()["ell"], 5)
    save_photo(photos, "b.png", shape_images()["ring"], 6)
    (photos / "labels.json").write_text(
        '{"a.png": ["vendor_c/ell_small.png"], "b.png": null}', encoding="utf-8"
    )
    code = benchmark.main(
        [
            "--library", str(library),
            "--samples", "2",
            "--index", str(tmp_path / "idx.npz"),
            "--photos", str(photos),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "real photos: labeled=1" in out
    assert "a.png:" in out and "b.png:" in out and "(not in library)" in out
    assert "OK top-1" in out
    assert "top-1 100.0%" in out


def test_load_or_build_reuses_cache(tmp_path):
    from PIL import Image
    from gmagc_desktop.matcher.embedder import PixelEmbedder

    class CountingEmbedder(PixelEmbedder):
        """PixelEmbedder, который считает, сколько СТРОК (изображений) он получил."""

        def __init__(self):
            super().__init__()
            self.rows_embedded = 0

        def embed(self, images):
            self.rows_embedded += len(images)
            return super().embed(images)

    library = make_library(tmp_path)
    embedder = CountingEmbedder()
    path = tmp_path / "cache" / "idx.npz"

    # First call: builds index, embeds 6 valid library files
    first = benchmark.load_or_build(library, embedder, path)
    assert embedder.rows_embedded == 6, f"first call should embed 6 files, got {embedder.rows_embedded}"
    assert len(first) == 6, "index should have 6 files"

    # Second call: reuses cache, should not embed anything new
    second = benchmark.load_or_build(library, embedder, path)
    assert embedder.rows_embedded == 6, (
        f"second call should reuse cache, rows should still be 6, got {embedder.rows_embedded}"
    )
    assert len(second) == 6, "cached index should still have 6 files"

    # Add ONE new image to library (create a real image so it can be embedded)
    new_photo = library / "vendor_c"
    Image.fromarray(np.eye(64, dtype=np.uint8) * 255, "L").save(new_photo / "diag.png")

    # Third call: incremental build, should embed the new file
    third = benchmark.load_or_build(library, embedder, path)
    assert embedder.rows_embedded == 7, f"third call should embed 1 new file, rows should be 7, got {embedder.rows_embedded}"
    assert len(third) == 7, "index should now have 7 files"


def test_real_eval_counts_a_family_hit(tmp_path):
    """Photo labeled with a family member -> top1==1.0, labeled==1."""
    index, searcher = build_searcher(tmp_path)
    photos = tmp_path / "photos"
    save_photo(photos, "a.png", shape_images()["ell"], 5)
    write_labels(photos, {"a.png": ["vendor_c/ell_small.png"]})

    result = benchmark.real_eval(index, searcher, photos, photos / "labels.json")
    assert result is not None
    assert result["labeled"] == 1
    assert result["top1"] == 1.0, f"expected 100% top1 for family hit, got {result['top1'] * 100}%"
    assert "OK top-1" in result["rows"][0]


def test_real_eval_distinguishes_top1_from_top5(tmp_path):
    """Photo labeled with a different family (in top-5) -> top1==0.0, top5==1.0."""
    index, searcher = build_searcher(tmp_path)
    photos = tmp_path / "photos"
    save_photo(photos, "a.png", shape_images()["ell"], 5)
    write_labels(photos, {"a.png": ["vendor_b/star.bmp"]})

    result = benchmark.real_eval(index, searcher, photos, photos / "labels.json")
    assert result is not None
    assert result["labeled"] == 1
    assert result["top1"] == 0.0, "should not match top-1 for different family"
    assert result["top5"] == 1.0, "should match in top-5 (only 5 families)"
    assert "OK top-5" in result["rows"][0]


def test_real_eval_counts_a_missing_projection_as_a_miss(tmp_path):
    """Labeled flat photo with no projection -> labeled==1, top1==0.0, row contains MISS."""
    index, searcher = build_searcher(tmp_path)
    photos = tmp_path / "photos"
    # Create a flat photo (no gobo, will fail to project)
    flat = np.full((480, 640, 3), 90, dtype=np.uint8)
    photos.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(photos / "flat.png"), flat)
    write_labels(photos, {"flat.png": ["vendor_c/ell_small.png"]})

    result = benchmark.real_eval(index, searcher, photos, photos / "labels.json")
    assert result is not None
    assert result["labeled"] == 1, "missing projection should count as labeled (it's a miss, not an omission)"
    assert result["top1"] == 0.0
    assert "projection not found  MISS" in result["rows"][0]


def test_real_eval_reports_unreadable_photos_without_aborting(tmp_path):
    """Unreadable photo + good labeled photo -> unreadable==1, labeled==1, run continues."""
    index, searcher = build_searcher(tmp_path)
    photos = tmp_path / "photos"
    photos.mkdir(parents=True, exist_ok=True)
    # Create an unreadable file
    (photos / "bad.png").write_bytes(b"junk")
    # Create a good labeled photo
    save_photo(photos, "good.png", shape_images()["ell"], 5)
    write_labels(photos, {"bad.png": None, "good.png": ["vendor_c/ell_small.png"]})

    result = benchmark.real_eval(index, searcher, photos, photos / "labels.json")
    assert result is not None
    assert result["unreadable"] == 1, "should report unreadable file"
    assert result["labeled"] == 1, "good photo should be labeled"
    assert result["top1"] == 1.0, "good photo should hit"
    assert any("bad.png" in row and "cannot read photo" in row for row in result["rows"])
    assert any("good.png" in row and "OK top-1" in row for row in result["rows"])


def test_real_eval_flags_label_errors_and_normalises_backslashes(tmp_path):
    """Labels with backslashes, missing paths, empty lists, wrong types -> flagged as errors."""
    index, searcher = build_searcher(tmp_path)
    photos = tmp_path / "photos"
    save_photo(photos, "a.png", shape_images()["ell"], 5)
    save_photo(photos, "b.png", shape_images()["ring"], 6)
    save_photo(photos, "c.png", shape_images()["ell"], 7)
    save_photo(photos, "d.png", shape_images()["ring"], 8)

    # a.png: backslash in path (should be normalized and hit)
    # b.png: non-existent path (should error)
    # c.png: empty list (should error)
    # d.png: string instead of list (should error)
    write_labels(
        photos,
        {
            "a.png": ["vendor_c\\ell_small.png"],
            "b.png": ["vendor_x/none.png"],
            "c.png": [],
            "d.png": "vendor_a/ring.bmp",
        },
    )

    result = benchmark.real_eval(index, searcher, photos, photos / "labels.json")
    assert result is not None
    assert result["label_errors"] == 3, f"expected 3 label errors, got {result['label_errors']}"
    assert result["labeled"] == 1, "only a.png should be labeled"
    assert result["top1"] == 1.0, "a.png (ell) should hit vendor_c/ell_small.png"
    assert any("LABEL ERROR" in row for row in result["rows"])


def test_real_eval_null_label_is_not_measured(tmp_path):
    """Photo labeled null (not in library) -> labeled==0, row has (not in library)."""
    index, searcher = build_searcher(tmp_path)
    photos = tmp_path / "photos"
    save_photo(photos, "a.png", shape_images()["ell"], 5)
    write_labels(photos, {"a.png": None})

    result = benchmark.real_eval(index, searcher, photos, photos / "labels.json")
    assert result is not None
    assert result["labeled"] == 0, "null label should not count as labeled"
    assert "(not in library)" in result["rows"][0]


def test_real_eval_raises_labels_error_for_malformed_json_and_main_returns_3(tmp_path, capsys):
    """Malformed JSON or missing --labels file -> LabelsError or exit code 3."""
    # Test 1: invalid JSON
    index, searcher = build_searcher(tmp_path)
    photos = tmp_path / "test1_photos"
    save_photo(photos, "a.png", shape_images()["ell"], 5)
    (photos / "labels.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(benchmark.LabelsError):
        benchmark.real_eval(index, searcher, photos, photos / "labels.json")

    # Test 2: JSON list instead of object
    (photos / "labels.json").write_text("[]", encoding="utf-8")
    with pytest.raises(benchmark.LabelsError):
        benchmark.real_eval(index, searcher, photos, photos / "labels.json")

    # Test 3: main returns 3 for cannot read labels
    lib_path = tmp_path / "lib3"
    lib_path.mkdir()
    write_library(lib_path)
    photos3 = tmp_path / "test3_photos"
    save_photo(photos3, "a.png", shape_images()["ell"], 5)
    (photos3 / "labels.json").write_text("{not json", encoding="utf-8")
    code = benchmark.main(
        [
            "--library", str(lib_path),
            "--samples", "2",
            "--index", str(tmp_path / "idx3.npz"),
            "--photos", str(photos3),
        ]
    )
    err = capsys.readouterr().err
    assert code == 3, "should return exit code 3 for malformed labels"
    assert "cannot read labels file" in err

    # Test 4: main returns 3 for missing --labels file
    lib_path4 = tmp_path / "lib4"
    lib_path4.mkdir()
    write_library(lib_path4)
    photos4 = tmp_path / "test4_photos"
    save_photo(photos4, "a.png", shape_images()["ell"], 5)
    capsys.readouterr()  # clear
    missing_labels = tmp_path / "missing_labels.json"
    code = benchmark.main(
        [
            "--library", str(lib_path4),
            "--samples", "2",
            "--index", str(tmp_path / "idx4.npz"),
            "--photos", str(photos4),
            "--labels", str(missing_labels),
        ]
    )
    err = capsys.readouterr().err
    assert code == 3, "should return exit code 3 for missing labels file"
    assert "labels file not found" in err


def test_synthetic_eval_is_deterministic_and_sane(tmp_path):
    """Synthetic eval with same seed produces same metrics; 5 families guarantee top-5 hit."""
    index, searcher = build_searcher(tmp_path)
    library = tmp_path / "lib"  # Already created by build_searcher via make_library

    # With samples=3, seed=3
    result1 = benchmark.synthetic_eval(index, library, searcher, samples=3, seed=3)
    result2 = benchmark.synthetic_eval(index, library, searcher, samples=3, seed=3)

    # Should have same metrics (ignore median_ms, which may differ slightly)
    assert result1["samples"] == result2["samples"] == 3
    assert result1["top1"] == result2["top1"], "same seed should produce same top1"
    assert result1["top5"] == result2["top5"], "same seed should produce same top5"
    seg_fail1, seg_fail2 = result1["segmentation_failed"], result2["segmentation_failed"]
    assert seg_fail1 == seg_fail2, "same seed should produce same segmentation_failed"

    # With 5 families, all fit in top-5, so real searcher should guarantee top5==1.0
    assert result1["top5"] == 1.0, f"with 5 families and pixel embedder, top5 should be 1.0, got {result1['top5']}"
    assert result1["segmentation_failed"] == 0.0, f"shapes should always segment, got {result1['segmentation_failed']}"

    # Sanity checks
    assert 0.0 <= result1["top1"] <= result1["top5"] <= 1.0
    assert 0.0 <= result1["segmentation_failed"] <= 1.0


def test_synthetic_eval_counts_misses_when_the_search_is_wrong(tmp_path):
    """Synthetic eval with an empty-result searcher should give top1==0.0, top5==0.0."""
    index, _ = build_searcher(tmp_path)
    library = tmp_path / "lib"

    class StubSearcher:
        def search(self, normalized, top_n=10):
            return []

    stub_searcher = StubSearcher()
    result = benchmark.synthetic_eval(index, library, stub_searcher, samples=3, seed=5)

    # Stub searcher returns no matches, so all should be misses
    assert result["top1"] == 0.0, f"no matches should give top1==0.0, got {result['top1']}"
    assert result["top5"] == 0.0, f"no matches should give top5==0.0, got {result['top5']}"
    assert result["samples"] == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_scripts.py -v`
Expected: FAIL (`ModuleNotFoundError: benchmark`).

- [ ] **Step 3: Write minimal implementation**

```python
# path: scripts/benchmark.py
"""Замер качества: синтетические «плохие фото» из библиотеки и реальные фото с разметкой."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "desktop"))

from gmagc_desktop.cli import build_embedder  # noqa: E402
from gmagc_desktop.library.index import (  # noqa: E402
    LibraryIndex,
    LibraryNotFound,
    LibraryScanError,
    build_index,
    load_index,
    save_index,
)
from gmagc_desktop.matcher.imageio import load_library_gray, load_photo_bgr  # noqa: E402
from gmagc_desktop.matcher.pipeline import normalize_photo  # noqa: E402
from gmagc_desktop.matcher.search import DEFAULT_W_EMBED, Searcher  # noqa: E402
from gmagc_desktop.matcher.synthetic import simulate_photo  # noqa: E402

PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png"}
_MISSING = object()  # у фото нет записи в labels.json (настоящее значение метки с ним не совпадёт)


class LabelsError(ValueError):
    """labels.json нельзя прочитать или у него неверный формат."""


def load_labels(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        labels = json.loads(path.read_text(encoding="utf-8-sig"))  # BOM: так пишет Windows PowerShell
    except (OSError, ValueError) as error:
        raise LabelsError(f"cannot read labels file {path}: {error}") from error
    if not isinstance(labels, dict):
        raise LabelsError(f"labels file {path} must contain a JSON object")
    return labels


def _progress(done: int, total: int) -> None:
    print(f"\rindexing {done}/{total}", end="", file=sys.stderr, flush=True)


def load_or_build(root: Path, embedder, index_path: Path) -> LibraryIndex:
    index = build_index(root, embedder, existing=load_index(index_path), progress=_progress)
    print(file=sys.stderr)
    save_index(index, index_path)
    return index


def synthetic_eval(index: LibraryIndex, root: Path, searcher: Searcher, samples: int, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    representatives: dict[int, int] = {}
    for position, group in enumerate(index.group_ids.tolist()):
        representatives.setdefault(group, position)
    if not representatives:
        raise SystemExit("library is empty")
    chosen = rng.choice(
        list(representatives.values()), size=min(samples, len(representatives)), replace=False
    )
    hits1 = hits5 = failed = 0
    milliseconds: list[float] = []
    for position in chosen:
        gray = load_library_gray(root / index.files[int(position)].rel_path)
        photo = simulate_photo(gray, rng)
        started = time.perf_counter()
        normalized = normalize_photo(photo)
        if normalized is None:
            failed += 1
            continue
        matches = searcher.search(normalized, top_n=5)
        milliseconds.append((time.perf_counter() - started) * 1000.0)
        target = int(index.group_ids[int(position)])
        found = [int(index.group_ids[m.index]) for m in matches]
        hits1 += bool(found) and found[0] == target
        hits5 += target in found
    total = len(chosen)
    return {
        "samples": total,
        "top1": hits1 / total,
        "top5": hits5 / total,
        "segmentation_failed": failed / total,
        "median_ms": statistics.median(milliseconds) if milliseconds else float("nan"),
    }


def real_eval(index: LibraryIndex, searcher: Searcher, photos_dir: Path, labels_path: Path) -> dict | None:
    if not photos_dir.is_dir():
        return None
    labels = load_labels(labels_path)
    by_path = {file.rel_path: i for i, file in enumerate(index.files)}
    rows: list[str] = []
    labeled = hits1 = hits5 = unreadable = label_errors = 0
    hit_scores: list[float] = []  # оценка top-1 у фото, найденного верно
    null_scores: list[float] = []  # оценка top-1 у фото с меткой null (в библиотеке его нет)
    photo_paths = sorted(p for p in photos_dir.iterdir() if p.is_file() and p.suffix.lower() in PHOTO_SUFFIXES)
    for photo_path in photo_paths:
        name = photo_path.name
        try:
            photo = load_photo_bgr(photo_path)
        except (OSError, ValueError) as error:
            unreadable += 1
            rows.append(f"{name}: cannot read photo ({error})")
            continue

        expected = labels.get(name, _MISSING)
        wanted: set[int] | None = None
        if isinstance(expected, list):
            paths = [p.replace("\\", "/") for p in expected if isinstance(p, str)]
            unknown = [p for p in paths if p not in by_path]
            if not paths or len(paths) != len(expected) or unknown:
                label_errors += 1
                rows.append(f"{name}: LABEL ERROR (empty list or unknown path: {unknown or expected})")
                continue
            wanted = {int(index.group_ids[by_path[p]]) for p in paths}
        elif expected is not None and expected is not _MISSING:
            label_errors += 1
            rows.append(f"{name}: LABEL ERROR (expected a list of paths or null)")
            continue

        normalized = normalize_photo(photo)
        if normalized is None:
            if wanted is not None:
                labeled += 1  # проекция не найдена: это промах, а не выпадение из статистики
            rows.append(f"{name}: projection not found" + ("  MISS" if wanted is not None else ""))
            continue

        matches = searcher.search(normalized, top_n=5)
        top = matches[0]
        found = [int(index.group_ids[m.index]) for m in matches]
        note = "  (not in library)" if expected is None else ""
        if wanted is not None:
            labeled += 1
            in_top1 = found[0] in wanted
            in_top5 = any(group in wanted for group in found)
            hits1 += in_top1
            hits5 += in_top5
            note = "  OK top-1" if in_top1 else ("  OK top-5" if in_top5 else "  MISS")
            if in_top1:
                hit_scores.append(min(top.score, 1.0))
        elif expected is None:
            null_scores.append(min(top.score, 1.0))
        rows.append(f"{name}: {index.files[top.index].rel_path}  {min(top.score, 1.0) * 100:.1f}%{note}")
    for name in sorted(set(labels) - {p.name for p in photo_paths}):
        label_errors += 1
        rows.append(f"LABEL ERROR: label for unknown photo {name}")
    return {
        "rows": rows,
        "labeled": labeled,
        "top1": hits1 / labeled if labeled else None,
        "top5": hits5 / labeled if labeled else None,
        "unreadable": unreadable,
        "label_errors": label_errors,
        "hit_scores": hit_scores,
        "null_scores": null_scores,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", required=True, type=Path)
    parser.add_argument("--model", type=Path, default=None)
    parser.add_argument("--index", type=Path, default=None)
    parser.add_argument("--samples", type=int, default=300)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--w-embed", type=float, default=DEFAULT_W_EMBED)
    parser.add_argument("--photos", type=Path, default=ROOT / "photo")
    parser.add_argument("--labels", type=Path, default=None)
    args = parser.parse_args(argv)

    labels_path = args.labels or args.photos / "labels.json"
    if args.labels is not None and not args.labels.is_file():
        print(f"labels file not found: {args.labels}", file=sys.stderr)
        return 3

    embedder = build_embedder(args.model)
    if embedder is None:
        return 3
    index_path = args.index or ROOT / ".gmagc-cache" / f"index-{embedder.model_id}.npz"
    try:
        index = load_or_build(args.library, embedder, index_path)
    except (LibraryNotFound, LibraryScanError) as error:
        print(error, file=sys.stderr)
        return 3
    searcher = Searcher(index.search_data(), embedder, w_embed=args.w_embed)

    families = len(set(index.group_ids.tolist()))
    print(f"model: {embedder.model_id}  w_embed={args.w_embed}  files={len(index)}  families={families}")

    stats = synthetic_eval(index, args.library, searcher, args.samples, args.seed)
    print(
        f"synthetic (n={stats['samples']}): top-1 {stats['top1'] * 100:.1f}%  "
        f"top-5 {stats['top5'] * 100:.1f}%  "
        f"segmentation failed {stats['segmentation_failed'] * 100:.1f}%  "
        f"median {stats['median_ms']:.0f} ms"
    )

    try:
        real = real_eval(index, searcher, args.photos, labels_path)
    except LabelsError as error:
        print(error, file=sys.stderr)
        return 3

    if real is None:
        print("no real photos folder, skipped")
        return 0
    if real["labeled"]:
        print(
            f"real photos: labeled={real['labeled']}  top-1 {real['top1'] * 100:.1f}%  "
            f"top-5 {real['top5'] * 100:.1f}%  (unreadable={real['unreadable']}, label errors={real['label_errors']})"
        )
    else:
        print(
            f"real photos: no labels yet (fill labels.json)  "
            f"(unreadable={real['unreadable']}, label errors={real['label_errors']})"
        )
    if real["hit_scores"] and real["null_scores"]:
        print(
            f"top-1 score: correct min {min(real['hit_scores']) * 100:.1f}% "
            f"median {statistics.median(real['hit_scores']) * 100:.1f}% | "
            f"not in library max {max(real['null_scores']) * 100:.1f}%"
        )
    print("\n".join(real["rows"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Тест `test_benchmark_synthetic_smoke` ждёт строку `no real photos` при отсутствии папки, а реализация печатает `no real photos folder, skipped`: подстрока совпадает.

- [ ] **Step 4: Run test to verify it passes, commit**

Run: `.venv\Scripts\python.exe -m pytest tests/test_scripts.py -v`
Expected: 12 passed.

```bash
git add scripts tests
git commit -m "feat: add quality benchmark script" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 14: Отчёт по реальным фото и просмотр семейств дублей

**Files:**
- Create: `scripts/_thumbs.py`, `scripts/report_photos.py`, `scripts/inspect_groups.py`, `tests/test_thumbs.py`
- Modify: `tests/test_scripts.py` (дописать в конец; при выполнении импорты `inspect_groups` и `report_photos` перенесены наверх файла, `import json` там уже есть), `pyproject.toml` (добавить `"tests/test_thumbs.py"` в per-file-ignores)

**Interfaces:**
- Consumes: `load_or_build`, `PHOTO_SUFFIXES` (Task 13), `make_embedder` (Task 11), `normalize_photo`, `Searcher`, `load_index`.
- Produces:
  - `scripts/report_photos.py --library DIR [--model ONNX] [--index FILE] [--photos DIR] [--out FILE] [--top 5]`: HTML с миниатюрой вырезки проекции и top-N (превью, оценка, путь, число копий) для каждого фото; рядом `labels.template.json` со всеми фото и значениями `null`. По умолчанию `--out` это `.gmagc-cache/photo_report.html`. `main(argv) -> int`.
  - `scripts/inspect_groups.py --library DIR --index FILE [--count 12] [--seed 0] [--out FILE]`: печатает статистику семейств и пути участников случайных семейств с дублями; сохраняет контактный лист (по умолчанию `.gmagc-cache/groups_sheet.png`). `main(argv) -> int`.
  - `scripts/_thumbs.py::square_pad(gray: np.ndarray) -> np.ndarray`: дополняет изображение чёрным до квадрата, оригинал по центру (общий помощник обоих скриптов вместо дублирования кода).
  - Ошибки `report_photos` (решения ревью): нет папки `--photos` или библиотеки -> сообщение в stderr и код выхода 3; нечитаемое фото не прерывает прогон (карточка `cannot read photo: ...`, фото остаётся в шаблоне разметки); недоступный файл библиотеки при рисовании превью заменяется чёрным изображением 1×1. В `inspect_groups` недоступный файл даёт чёрную ячейку.

- [ ] **Step 1: Write the failing tests** (`tests/test_thumbs.py` создаётся целиком, остальное дописывается в конец `tests/test_scripts.py`)

```python
# path: tests/test_thumbs.py
import sys
from pathlib import Path

import numpy as np

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import _thumbs  # noqa: E402


def test_square_pad_rectangular_image():
    """A 10x20 image becomes 20x20 with the original centered."""
    gray = np.ones((10, 20), np.uint8) * 100
    result = _thumbs.square_pad(gray)

    assert result.shape == (20, 20), f"expected shape (20, 20), got {result.shape}"
    # Original should be centered: rows 5..15 hold the data
    assert np.all(result[0:5, :] == 0), "top padding should be zero"
    assert np.all(result[15:20, :] == 0), "bottom padding should be zero"
    assert np.all(result[5:15, :] == 100), "center rows should contain original data"


def test_square_pad_square_image():
    """A square image is returned equal to the input."""
    gray = np.ones((20, 20), np.uint8) * 50
    result = _thumbs.square_pad(gray)

    assert result.shape == (20, 20)
    assert np.array_equal(result, gray)
```

```python
import inspect_groups  # noqa: E402
import report_photos  # noqa: E402


def test_report_photos_writes_html_and_label_template(tmp_path):
    library = make_library(tmp_path)
    photos = tmp_path / "photos"
    save_photo(photos, "a.png", shape_images()["ell"], 5)
    out = tmp_path / "report" / "photo_report.html"

    code = report_photos.main(
        [
            "--library", str(library),
            "--index", str(tmp_path / "idx.npz"),
            "--photos", str(photos),
            "--out", str(out),
            "--top", "3",
        ]
    )

    html_text = out.read_text(encoding="utf-8")
    template = json.loads((out.parent / "labels.template.json").read_text(encoding="utf-8"))
    assert code == 0
    assert "a.png" in html_text and "vendor_" in html_text and "data:image/png;base64," in html_text
    assert template == {"a.png": None}


def test_inspect_groups_lists_duplicate_families(tmp_path, capsys):
    library = make_library(tmp_path)
    index_path = tmp_path / "idx.npz"
    cli.main(["index", str(library), "--index", str(index_path)])
    capsys.readouterr()
    sheet = tmp_path / "sheet.png"

    code = inspect_groups.main(
        ["--library", str(library), "--index", str(index_path), "--out", str(sheet)]
    )

    out = capsys.readouterr().out
    assert code == 0 and "5 families, 1 with duplicates, 2 files in them" in out
    assert "vendor_b/ell.png" in out and "vendor_c/ell_small.png" in out
    assert sheet.exists()


def test_report_photos_survives_an_unreadable_photo(tmp_path):
    library = make_library(tmp_path)
    photos = tmp_path / "photos"
    save_photo(photos, "good.png", shape_images()["ell"], 5)
    # Create an unreadable file
    (photos / "bad.png").write_bytes(b"junk")
    out = tmp_path / "report" / "photo_report.html"

    code = report_photos.main(
        [
            "--library", str(library),
            "--index", str(tmp_path / "idx.npz"),
            "--photos", str(photos),
            "--out", str(out),
        ]
    )

    html_text = out.read_text(encoding="utf-8")
    template = json.loads((out.parent / "labels.template.json").read_text(encoding="utf-8"))
    assert code == 0
    assert "cannot read photo" in html_text
    assert "good.png" in html_text
    assert "bad.png" in html_text
    assert template == {"bad.png": None, "good.png": None}


def test_report_photos_missing_photos_folder_returns_3(tmp_path, capsys):
    library = make_library(tmp_path)
    out = tmp_path / "report" / "photo_report.html"

    code = report_photos.main(
        [
            "--library", str(library),
            "--index", str(tmp_path / "idx.npz"),
            "--photos", str(tmp_path / "nonexistent"),
            "--out", str(out),
        ]
    )

    err = capsys.readouterr().err
    assert code == 3
    assert "photos folder not found" in err


def test_report_photos_missing_library_returns_3(tmp_path, capsys):
    photos = tmp_path / "photos"
    save_photo(photos, "a.png", shape_images()["ell"], 5)
    out = tmp_path / "report" / "photo_report.html"

    code = report_photos.main(
        [
            "--library", str(tmp_path / "nonexistent_lib"),
            "--index", str(tmp_path / "idx.npz"),
            "--photos", str(photos),
            "--out", str(out),
        ]
    )

    err = capsys.readouterr().err
    assert code == 3
    assert "cannot read library" in err or "cannot read" in err or "FileNotFoundError" in err


def test_benchmark_missing_library_returns_3(tmp_path, capsys):
    index_path = tmp_path / "idx.npz"

    code = benchmark.main(["--library", str(tmp_path / "unplugged"), "--index", str(index_path)])

    assert code == 3
    assert "library folder not found" in capsys.readouterr().err
    assert not index_path.exists()


def test_benchmark_empty_library_returns_3_without_writing_an_index(tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    index_path = tmp_path / "idx.npz"

    code = benchmark.main(["--library", str(empty), "--index", str(index_path)])

    assert code == 3
    assert "no PNG/BMP files found" in capsys.readouterr().err
    assert not index_path.exists()


@pytest.mark.parametrize("problem", ["missing", "garbage"])
def test_benchmark_bad_model_returns_3(tmp_path, capsys, problem):
    library = make_library(tmp_path)
    model = tmp_path / "model.onnx"
    if problem == "garbage":
        model.write_bytes(b"not an onnx model")
    index_path = tmp_path / "idx.npz"

    code = benchmark.main(["--library", str(library), "--model", str(model), "--index", str(index_path)])

    err = capsys.readouterr().err
    assert code == 3 and "cannot load model" in err and "Traceback" not in err
    assert not index_path.exists()


def test_benchmark_missing_labels_file_returns_3_before_any_index_is_built(tmp_path, capsys):
    library = make_library(tmp_path)
    photos = tmp_path / "photos"
    save_photo(photos, "a.png", shape_images()["ell"], 5)
    index_path = tmp_path / "idx.npz"

    code = benchmark.main(
        [
            "--library", str(library),
            "--index", str(index_path),
            "--photos", str(photos),
            "--labels", str(tmp_path / "missing_labels.json"),
        ]
    )

    captured = capsys.readouterr()
    assert code == 3 and "labels file not found" in captured.err
    assert not index_path.exists()
    assert "synthetic" not in captured.out


def test_report_photos_bad_model_returns_3(tmp_path, capsys):
    library = make_library(tmp_path)
    photos = tmp_path / "photos"
    save_photo(photos, "a.png", shape_images()["ell"], 5)
    index_path = tmp_path / "idx.npz"

    code = report_photos.main(
        [
            "--library", str(library),
            "--model", str(tmp_path / "nope.onnx"),
            "--index", str(index_path),
            "--photos", str(photos),
            "--out", str(tmp_path / "report" / "r.html"),
        ]
    )

    err = capsys.readouterr().err
    assert code == 3 and "cannot load model" in err and "Traceback" not in err
    assert not index_path.exists()


def test_report_photos_empty_library_returns_3(tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    photos = tmp_path / "photos"
    save_photo(photos, "a.png", shape_images()["ell"], 5)

    code = report_photos.main(
        [
            "--library", str(empty),
            "--index", str(tmp_path / "idx.npz"),
            "--photos", str(photos),
            "--out", str(tmp_path / "report" / "r.html"),
        ]
    )

    assert code == 3 and "no PNG/BMP files found" in capsys.readouterr().err


def test_inspect_groups_missing_library_returns_3(tmp_path, capsys):
    library = make_library(tmp_path)
    index_path = tmp_path / "idx.npz"
    cli.main(["index", str(library), "--index", str(index_path)])
    capsys.readouterr()

    code = inspect_groups.main(
        ["--library", str(tmp_path / "unplugged"), "--index", str(index_path), "--out", str(tmp_path / "s.png")]
    )

    err = capsys.readouterr().err
    assert code == 3 and f"library folder not found: {tmp_path / 'unplugged'}" in err
    assert not (tmp_path / "s.png").exists()


def test_load_labels_accepts_a_utf8_bom_from_windows_powershell(tmp_path):
    path = tmp_path / "labels.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"a.png": None, "b.png": ["x/y.png"]}).encode("utf-8"))

    assert benchmark.load_labels(path) == {"a.png": None, "b.png": ["x/y.png"]}


def test_real_eval_works_with_a_bom_labels_file(tmp_path):
    index, searcher = build_searcher(tmp_path)
    photos = tmp_path / "photos"
    save_photo(photos, "a.png", shape_images()["ell"], 5)
    (photos / "labels.json").write_bytes(b"\xef\xbb\xbf" + b'{"a.png": ["vendor_c/ell_small.png"]}')

    result = benchmark.real_eval(index, searcher, photos, photos / "labels.json")

    assert result["labeled"] == 1 and result["top1"] == 1.0 and result["label_errors"] == 0


def test_real_eval_reports_a_label_for_a_photo_that_does_not_exist(tmp_path):
    index, searcher = build_searcher(tmp_path)
    photos = tmp_path / "photos"
    save_photo(photos, "a.png", shape_images()["ell"], 5)
    write_labels(photos, {"a.png": ["vendor_c/ell_small.png"], "ghost.png": None, "typo.png": ["vendor_a/ring.png"]})

    result = benchmark.real_eval(index, searcher, photos, photos / "labels.json")

    assert result["label_errors"] == 2
    assert "LABEL ERROR: label for unknown photo ghost.png" in result["rows"]
    assert "LABEL ERROR: label for unknown photo typo.png" in result["rows"]
    assert result["labeled"] == 1 and result["top1"] == 1.0


def test_real_eval_a_label_value_of_unlabeled_is_an_error_not_a_missing_label(tmp_path):
    index, searcher = build_searcher(tmp_path)
    photos = tmp_path / "photos"
    save_photo(photos, "a.png", shape_images()["ell"], 5)
    write_labels(photos, {"a.png": "unlabeled"})

    result = benchmark.real_eval(index, searcher, photos, photos / "labels.json")

    assert result["label_errors"] == 1 and result["labeled"] == 0
    assert any("a.png: LABEL ERROR" in row for row in result["rows"])


def test_real_eval_collects_top1_scores_for_hits_and_for_not_in_library_photos(tmp_path):
    index, searcher = build_searcher(tmp_path)
    photos = tmp_path / "photos"
    save_photo(photos, "hit.png", shape_images()["ell"], 5)
    save_photo(photos, "top5only.png", shape_images()["ell"], 7)
    save_photo(photos, "null.png", shape_images()["ring"], 6)
    save_photo(photos, "unlabeled.png", shape_images()["star"], 8)
    write_labels(
        photos,
        {"hit.png": ["vendor_c/ell_small.png"], "top5only.png": ["vendor_b/star.bmp"], "null.png": None},
    )

    result = benchmark.real_eval(index, searcher, photos, photos / "labels.json")

    assert result["labeled"] == 2 and result["top1"] == 0.5
    assert len(result["hit_scores"]) == 1  # только фото с верным top-1
    assert len(result["null_scores"]) == 1  # только фото с меткой null
    assert all(0.0 <= score <= 1.0 for score in result["hit_scores"] + result["null_scores"])
    hit_row = next(row for row in result["rows"] if row.startswith("hit.png"))
    null_row = next(row for row in result["rows"] if row.startswith("null.png"))
    assert f"{result['hit_scores'][0] * 100:.1f}%" in hit_row
    assert f"{result['null_scores'][0] * 100:.1f}%" in null_row


def test_real_eval_clamps_collected_scores_to_one(tmp_path):
    from gmagc_desktop.matcher.search import Match

    index, _ = build_searcher(tmp_path)
    position = [f.rel_path for f in index.files].index("vendor_c/ell_small.png")

    class Overconfident:
        def search(self, normalized, top_n=10):
            return [Match(position, 1.3, 0.9, 1.0, 0.0, False, (position,))]

    photos = tmp_path / "photos"
    save_photo(photos, "a.png", shape_images()["ell"], 5)
    save_photo(photos, "b.png", shape_images()["ring"], 6)
    write_labels(photos, {"a.png": ["vendor_c/ell_small.png"], "b.png": None})

    result = benchmark.real_eval(index, Overconfident(), photos, photos / "labels.json")

    assert result["hit_scores"] == [1.0] and result["null_scores"] == [1.0]


def _run_benchmark_on_photos(tmp_path, capsys, labels):
    library = make_library(tmp_path)
    photos = tmp_path / "photos"
    save_photo(photos, "a.png", shape_images()["ell"], 5)
    save_photo(photos, "b.png", shape_images()["ring"], 6)
    write_labels(photos, labels)
    code = benchmark.main(
        ["--library", str(library), "--samples", "2", "--index", str(tmp_path / "idx.npz"), "--photos", str(photos)]
    )
    assert code == 0
    return capsys.readouterr().out


def test_benchmark_prints_the_no_match_calibration_line(tmp_path, capsys):
    out = _run_benchmark_on_photos(tmp_path, capsys, {"a.png": ["vendor_c/ell_small.png"], "b.png": None})

    line = next(line for line in out.splitlines() if line.startswith("top-1 score:"))
    match = re.fullmatch(r"top-1 score: correct min ([\d.]+)% median ([\d.]+)% \| not in library max ([\d.]+)%", line)
    assert match, line
    hit_row = next(row for row in out.splitlines() if row.startswith("a.png:"))
    null_row = next(row for row in out.splitlines() if row.startswith("b.png:"))
    hit_percent, null_percent = match.group(1), match.group(3)
    assert f"  {hit_percent}%" in hit_row and f"  {null_percent}%" in null_row
    assert match.group(1) == match.group(2)  # одно попадание: минимум == медиана


def test_benchmark_omits_the_calibration_line_when_there_are_no_null_photos(tmp_path, capsys):
    out = _run_benchmark_on_photos(
        tmp_path, capsys, {"a.png": ["vendor_c/ell_small.png"], "b.png": ["vendor_a/ring.png"]}
    )
    assert "top-1 score:" not in out


def test_benchmark_omits_the_calibration_line_when_there_are_no_correct_hits(tmp_path, capsys):
    out = _run_benchmark_on_photos(tmp_path, capsys, {"a.png": None, "b.png": None})
    assert "top-1 score:" not in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_scripts.py -v`
Expected: FAIL (`ModuleNotFoundError: report_photos`).

- [ ] **Step 3: Write minimal implementation**

```python
# path: scripts/_thumbs.py
"""Shared thumbnail utilities."""

import numpy as np


def square_pad(gray: np.ndarray) -> np.ndarray:
    """Дополняет изображение чёрным до квадрата, оригинал по центру."""
    side = max(gray.shape)
    square = np.zeros((side, side), np.uint8)
    y, x = (side - gray.shape[0]) // 2, (side - gray.shape[1]) // 2
    square[y : y + gray.shape[0], x : x + gray.shape[1]] = gray
    return square
```

В `pyproject.toml` добавить в `[tool.ruff.lint.per-file-ignores]` строку `"tests/test_thumbs.py" = ["E402", "I001"]`.

```python
# path: scripts/report_photos.py
"""HTML-отчёт по фото: вырезка проекции и top-N результатов для ручной разметки."""

from __future__ import annotations

import argparse
import base64
import html
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "desktop"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from benchmark import PHOTO_SUFFIXES, load_or_build  # noqa: E402
from _thumbs import square_pad  # noqa: E402

from gmagc_desktop.cli import build_embedder  # noqa: E402
from gmagc_desktop.library.index import LibraryNotFound, LibraryScanError  # noqa: E402
from gmagc_desktop.matcher.imageio import load_library_gray, load_photo_bgr  # noqa: E402
from gmagc_desktop.matcher.pipeline import normalize_photo  # noqa: E402
from gmagc_desktop.matcher.search import DEFAULT_W_EMBED, Searcher  # noqa: E402

THUMB = 128


def data_uri(gray: np.ndarray) -> str:
    small = cv2.resize(square_pad(gray), (THUMB, THUMB), interpolation=cv2.INTER_AREA)
    ok, buffer = cv2.imencode(".png", small)
    return "data:image/png;base64," + base64.b64encode(buffer.tobytes()).decode("ascii")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", required=True, type=Path)
    parser.add_argument("--model", default=None)
    parser.add_argument("--index", type=Path, default=None)
    parser.add_argument("--photos", type=Path, default=ROOT / "photo")
    parser.add_argument("--out", type=Path, default=ROOT / ".gmagc-cache" / "photo_report.html")
    parser.add_argument("--top", type=int, default=5)
    args = parser.parse_args(argv)

    # Check if photos directory exists
    if not args.photos.is_dir():
        print(f"photos folder not found: {args.photos}", file=sys.stderr)
        return 3

    embedder = build_embedder(args.model)
    if embedder is None:
        return 3
    index_path = args.index or ROOT / ".gmagc-cache" / f"index-{embedder.model_id}.npz"
    try:
        index = load_or_build(args.library, embedder, index_path)
    except (LibraryNotFound, LibraryScanError) as error:
        print(f"cannot read library: {error}", file=sys.stderr)
        return 3
    searcher = Searcher(index.search_data(), embedder, w_embed=DEFAULT_W_EMBED)

    sections = []
    template: dict[str, None] = {}
    for photo_path in sorted(p for p in args.photos.iterdir() if p.is_file() and p.suffix.lower() in PHOTO_SUFFIXES):
        template[photo_path.name] = None
        cards = []

        # Try to read the photo
        try:
            photo = load_photo_bgr(photo_path)
        except (OSError, ValueError) as error:
            cards.append(f"<p>cannot read photo: {html.escape(str(error))}</p>")
            sections.append(f"<h2>{html.escape(photo_path.name)}</h2><div class=\"row\">{''.join(cards)}</div>")
            continue

        normalized = normalize_photo(photo)
        if normalized is None:
            cards.append("<p>projection not found</p>")
        else:
            cards.append(f'<div class="card"><img src="{data_uri(normalized)}"><b>photo</b></div>')
            for rank, match in enumerate(searcher.search(normalized, top_n=args.top), start=1):
                file = index.files[match.index]
                copies = "; ".join(index.files[i].rel_path for i in match.members)

                # Try to load the thumbnail, use blank image if it fails
                try:
                    thumb_gray = load_library_gray(args.library / file.rel_path)
                    thumb = data_uri(thumb_gray)
                except (OSError, ValueError):
                    # Use blank 1x1 black image
                    blank = np.zeros((1, 1), np.uint8)
                    thumb = data_uri(blank)

                cards.append(
                    f'<div class="card"><img src="{thumb}">'
                    f"<b>#{rank} {match.score * 100:.1f}%</b>"
                    f'<span title="{html.escape(copies)}">{html.escape(file.rel_path)}'
                    f"{f' (+{len(match.members) - 1})' if len(match.members) > 1 else ''}</span></div>"
                )
        sections.append(f"<h2>{html.escape(photo_path.name)}</h2><div class=\"row\">{''.join(cards)}</div>")

    style = (
        ".row{display:flex;gap:12px;flex-wrap:wrap}.card{width:150px;font:12px sans-serif}"
        ".card img{width:128px;height:128px;background:#000;display:block}"
        ".card span{display:block;word-break:break-all}"
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        f"<!doctype html><meta charset=utf-8><style>{style}</style>{''.join(sections)}",
        encoding="utf-8",
    )
    (args.out.parent / "labels.template.json").write_text(
        json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"report: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

```python
# path: scripts/inspect_groups.py
"""Показать случайные семейства дублей (для подбора порогов группировки)."""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _thumbs import square_pad  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "desktop"))

from gmagc_desktop.library.index import load_index  # noqa: E402
from gmagc_desktop.matcher.imageio import load_library_gray  # noqa: E402

CELL = 96
COLUMNS = 8


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", required=True, type=Path)
    parser.add_argument("--index", required=True, type=Path)
    parser.add_argument("--count", type=int, default=12)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=Path, default=ROOT / ".gmagc-cache" / "groups_sheet.png")
    args = parser.parse_args(argv)

    if not args.library.is_dir():
        print(f"library folder not found: {args.library}", file=sys.stderr)
        return 3
    index = load_index(args.index)
    if index is None:
        print("index not found", file=sys.stderr)
        return 1
    families: dict[int, list[int]] = defaultdict(list)
    for position, group in enumerate(index.group_ids.tolist()):
        families[group].append(position)
    duplicated = [members for members in families.values() if len(members) > 1]
    print(
        f"{len(families)} families, {len(duplicated)} with duplicates, "
        f"{sum(len(m) for m in duplicated)} files in them"
    )
    if not duplicated:
        return 0

    rng = np.random.default_rng(args.seed)
    chosen = rng.choice(len(duplicated), size=min(args.count, len(duplicated)), replace=False)
    sheet = np.zeros((len(chosen) * CELL, COLUMNS * CELL), np.uint8)
    for row, choice in enumerate(chosen):
        members = duplicated[int(choice)]
        print(f"family of {len(members)}:")
        for column, position in enumerate(members):
            rel = index.files[position].rel_path
            print(f"  {rel}")
            if column < COLUMNS:
                try:
                    gray = load_library_gray(args.library / rel)
                except (OSError, ValueError):
                    # Use blank 1x1 black image if file cannot be read
                    gray = np.zeros((1, 1), np.uint8)
                square = square_pad(gray)
                sheet[row * CELL : (row + 1) * CELL, column * CELL : (column + 1) * CELL] = cv2.resize(
                    square, (CELL, CELL), interpolation=cv2.INTER_AREA
                )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imencode(".png", sheet)[1].tofile(str(args.out))
    print(f"sheet: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass, commit**

Run: `.venv\Scripts\python.exe -m pytest tests/test_scripts.py -v`
Expected: 24 passed.

```bash
git add scripts tests
git commit -m "feat: add photo report and duplicate-group inspection scripts" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 15: Замеры на реальных данных и выбор конфигурации

Это исполняемая задача без нового кода: результат это документ с цифрами и решение о модели и весах. Требует папок `gobos/` и `photo/` в корне репозитория и интернета один раз (загрузка модели).

**Files:**
- Create: `docs/benchmarks/2026-09-19-core-matcher.md`
- Modify (если веса меняются): `apps/desktop/gmagc_desktop/matcher/search.py` (значение по умолчанию `w_embed`), `apps/desktop/gmagc_desktop/cli.py` (`--w-embed`), `apps/desktop/gmagc_desktop/library/grouping.py` (пороги, если подобраны иначе)

- [ ] **Step 1: Полный прогон тестов**

Run: `.venv\Scripts\python.exe -m pytest -q` и `.venv\Scripts\python.exe -m ruff check .`
Expected: все тесты зелёные, ruff без замечаний (при замечаниях исправить `ruff check --fix .` и закоммитить `style: ruff fixes`).

- [ ] **Step 2: Baseline без нейросети**

Run: `.venv\Scripts\python.exe scripts\benchmark.py --library gobos --samples 300`
Expected: индекс библиотеки строится (порядка минуты, ~11 тыс. файлов), печатается строка `model: pixels-16 ...`, метрики `synthetic (n=300): top-1 ..% top-5 ..%`, затем строки по 17 фото (пока без разметки). Записать числа.

- [ ] **Step 3: Модель DINOv2-small и замеры**

Run: `.venv\Scripts\python.exe scripts\fetch_model.py --variant fp32`
Затем для каждого веса (индекс модели строится один раз, дальше берётся из кэша):

```
.venv\Scripts\python.exe scripts\benchmark.py --library gobos --model models\dinov2-small-fp32.onnx --w-embed 0.0
.venv\Scripts\python.exe scripts\benchmark.py --library gobos --model models\dinov2-small-fp32.onnx --w-embed 0.5
.venv\Scripts\python.exe scripts\benchmark.py --library gobos --model models\dinov2-small-fp32.onnx --w-embed 1.0
```
Expected: три набора метрик. Дополнительно (по желанию) `--variant int8`: сравнить точность и скорость с fp32. Записать также время построения индекса и размер файла индекса из `.gmagc-cache/`.

- [ ] **Step 4: Проверка групп дублей**

Run: `.venv\Scripts\python.exe scripts\inspect_groups.py --library gobos --index .gmagc-cache\index-<model_id>.npz` (имя файла индекса брать из `.gmagc-cache/`)
Открыть `.gmagc-cache\groups_sheet.png`. Если в одном ряду разные гобо, поднять `iou_threshold`/`cosine_threshold` в `grouping.py`; если явные копии не сгруппированы, снизить. После правки повторить шаг, затем `pytest`.

- [ ] **Step 5: Разметка реальных фото (вместе с пользователем)**

Run: `.venv\Scripts\python.exe scripts\report_photos.py --library gobos --model models\dinov2-small-fp32.onnx`
Открыть `.gmagc-cache\photo_report.html`, вместе с пользователем определить для каждого фото верный файл (`rel_path`) или отметить «в библиотеке нет». Заполнить `photo\labels.json` по образцу `.gmagc-cache\labels.template.json`:

```json
{
  "photo_13_2026-09-19_15-35-01.jpg": ["carallon/gobos/elumen8/67190008.png"],
  "photo_15_2026-09-19_15-35-01.jpg": null
}
```
Пути пишутся с `/` относительно `gobos/`; `null` значит «в библиотеке нет».

- [ ] **Step 6: Итоговый замер и документ**

Run: команда из шага 3 для лучшего веса, плюс baseline из шага 2 (теперь с метриками по реальным фото).
Создать `docs/benchmarks/2026-09-19-core-matcher.md`: таблица (строки: `pixels-16`, `dinov2-small fp32 w=0.0/0.5/1.0`, при наличии `int8`; столбцы: synthetic top-1, top-5, сбои сегментации, медиана мс; реальные top-1, top-5; время построения и размер индекса), пути и подтверждённые пороги группировки, вывод о лицензии модели (проверить карточку `facebook/dinov2-small` и `onnx-community/dinov2-small`; включать в сборку только при разрешающей лицензии), выбранные модель и вес.

- [ ] **Step 7: Решение и коммит**

Показать таблицу пользователю. Если цифры устраивают, зафиксировать выбранный `w_embed` как значение по умолчанию (в `search.py` и `cli.py`), прогнать `pytest`, затем:

```bash
git add docs apps
git commit -m "docs: record core matcher benchmark and choose defaults" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

Если цифры не устраивают (порог качества назначает пользователь по таблице), не переходить дальше: завести отдельный план на дообучение лёгкой модели на синтетических «плохих фото» (интерфейс `Embedder` уже позволяет заменить ONNX-файл).

---

## Самопроверка плана

**Покрытие спецификации (разделы 6, 9, 12 этап 1–2):**
- 6.1 данные и прозрачность, служебные файлы → Task 1, 7.
- 6.2 нормализация и сегментация → Task 2, 3.
- 6.3 модель ONNX, индекс один вектор на файл, float16, инкрементальность, группировка → Task 5, 8, 10, 12.
- 6.4 поиск: 24 поворота × зеркало, shortlist, уточнение формы, вес → Task 4, 6, 9.
- 9 тесты и бенчмарк на синтетике и 17 реальных фото с разметкой → Task 13, 14, 15.
- Пороги качества назначаются после замера → Task 15 (решение пользователя).
- Вне этого плана (отдельные планы): сервер и API, ПК-интерфейс, мобильный клиент, CI/сборки, QR, cleartext на Android.

**Согласованность имён:** `LibraryFile`, `SearchData`, `Match`, `ShapeMatch`, `soft_mask`, `normalize_gray`, `normalize_photo`, `query_variants`, `rotate_image`, `variant_pose`, `make_embedder`, `load_or_build` определены до использования; `Embedder.model_id` есть у обоих эмбеддеров; маска в индексе `(N, 64, 64)` совпадает с `MASK_SIZE`.

**Известные допущения, которые проверяются выполнением:** параметры сегментации взяты из прототипа на 17 реальных фото и должны пройти на симуляторе (Task 3); пороги группировки по умолчанию (`0.97`, `0.85`) предварительные и подбираются в Task 15; выбор `n_rotations=24`, `shortlist=20` и вида `w_embed` подтверждается замерами.

## Что дальше

После Task 15 и решения по качеству пишутся отдельные планы: (2) сервер и ПК-интерфейс, (3) мобильный клиент, (4) CI и сборки под Windows/macOS/Android. Тогда же закрываются риски 3–6 из спецификации (QR, cleartext на Android, брандмауэр, общий пакет в `flet build`).


---

## Итоги выполнения (дописано после реализации)

План выполнен на ветке `feat/core-matcher`: 15 задач, 149 тестов, `ruff check .` чист. Код в блоках выше синхронизирован с тем, что реально лежит в репозитории после ревью (расхождение только в месте импортов `tests/test_scripts.py`: в репозитории они наверху файла).

**Что изменило ревью относительно первоначального текста плана** (все изменения уже внесены в блоки кода и «Interfaces»):
- Задача 3: тест слияния пятен заменён парой «близкие / далёкие пятна» (прежний проходил и без слияния).
- Задача 5: ошибки onnxruntime переводятся в `ValueError`; тест с реальными разными строками в батчах.
- Задача 8: проверка пар порциями по бюджету в байтах (100 000 пар занимали бы ~1,6 ГБ).
- Задача 10: `LibraryNotFound` / `LibraryScanError`, отказ строить частичный или пустой индекс, «временные» сбои чтения не сохраняются как пропуск, `zlib.error` / `TokenError` при чтении кэша.
- Задача 11: контракт кодов выхода 0 / 1 / 2 / 3, публичные `read_photo` и `build_embedder`, проверка размерности индекса и эмбеддера, единый `DEFAULT_W_EMBED`.
- Задача 12: атомарная загрузка (`.part`, `Content-Length`, `--force`).
- Задача 13: честные метрики бенчмарка (промах сегментации остаётся в знаменателе, ошибки разметки и нечитаемые фото отдельно, `utf-8-sig`, калибровочная строка порога «нет совпадения»).
- Задача 14: общий помощник `scripts/_thumbs.py`, понятные ошибки вместо traceback.

**Результат замеров** (Задача 15): `docs/benchmarks/2026-09-19-core-matcher.md`. Готовая нейросеть DINOv2-small проиграла пиксельному вектору 16×16; на реальных фото пиксельный движок даёт top-5 ≈ 91%.

**Отложено в следующие планы** (зафиксировано при ревью, не блокирует объединение ветки):
- Обрезанные PNG/BMP сейчас считаются «временно нечитаемыми» и перечитываются при каждой сборке: в ветке `OSError` с `errno is None` и текстом `truncated` / `broken data stream` / `decoder error` нужно считать окончательным пропуском (около 5 строк и тест на настоящий обрезанный PNG).
- Проверка `rel_path` из индекса на абсолютные пути и `..` до того, как индекс будет приходить не только с локального диска (сервер).
- Уникальное имя временного файла при сохранении индекса и сериализация пересборок (сервер).
- Проход `stat()` при сканировании библиотеки, отличный от `FileNotFoundError`, пока даёт traceback; кэши, построенные до финальной волны, сохраняют ошибочно пропущенные файлы (версия формата не менялась).
- Перенос логики «загрузить или построить индекс» из `scripts/benchmark.py` в пакет, чтобы её могли использовать сервер и интерфейс.
- Проброс порогов группировки (`cosine_threshold`, `iou_threshold`) через `build_index`, CLI и бенчмарк: нужен, только если вернёмся к нейросетевому вектору.
- Пересчёт индекса после обновления кода: кэш из-за смены правил пропуска стоит пересобрать.
