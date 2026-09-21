# GMAGC: сборки под Windows, macOS и Android. План реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Каркасы ПК- и Android-приложений на Flet и GitHub Actions, которые собирают Windows / macOS / Android и по тегу прикрепляют артефакты к релизу.

**Architecture:** Ядро переезжает в `apps/desktop/src/` (Flet упаковывает `src/`). Экран каждого приложения вынесен в функцию `build_page`, которую тестирует pytest на заглушке страницы (GUI локально не запустить, поэтому ошибки API ловим тестами). Три отдельных workflow собирают платформы; `ci.yml` гоняет тесты на трёх ОС.

**Tech Stack:** Flet 1.0.0 (`flet-camera`, `flet-permission-handler` 1.0.0), Python 3.12, GitHub Actions, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-09-21-gmagc-builds-design.md`

## Global Constraints

- `flet==1.0.0`, `flet-camera==1.0.0`, `flet-permission-handler==1.0.0`; в приложениях `requires-python = ">=3.12,<3.13"`.
- Зависимости ПК-приложения: flet, numpy, opencv-python-headless, Pillow (без onnxruntime). Android-приложение: flet, flet-camera, flet-permission-handler, без numpy и OpenCV.
- Автор `@ANDY_BUM` в README, `authors` и `[tool.flet] company / copyright` обоих приложений, на экранах приложений.
- Модель и библиотека гобо в сборки не входят; `gmagc_common` не создаётся.
- Артефакты: `GMAGC-desktop-windows-<версия>.zip`, `GMAGC-desktop-macos-<версия>.zip`, `GMAGC-android-<версия>.apk` и `*.sha256`. Версия из тега без `v`, вне тега `0.0.0`.
- Триггеры сборок: тег `v*`, `workflow_dispatch`, `pull_request` с фильтром путей; публикация в релиз только по тегу.
- Коммиты: `git commit -m "<тип>: <описание>" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"`. Комментарии и строки интерфейса на русском.
- Работа ведётся на ветке `feat/builds`; в `main` только через Pull Request с зелёными проверками.

---

### Task 1: Переезд ядра в `apps/desktop/src/`

**Files:**
- Move: `apps/desktop/gmagc_desktop` → `apps/desktop/src/gmagc_desktop`
- Modify: `pyproject.toml`, `scripts/benchmark.py:15`, `scripts/report_photos.py:16`, `scripts/inspect_groups.py:18`, `README.md`

**Interfaces:**
- Produces: пакет `gmagc_desktop` импортируется через `apps/desktop/src` (pytest `pythonpath`, `sys.path` в скриптах); все 149 существующих тестов остаются зелёными без правок.

- [ ] **Step 1: Переезд и правка путей**

```bash
mkdir -p apps/desktop/src
git mv apps/desktop/gmagc_desktop apps/desktop/src/gmagc_desktop
sed -i 's|str(ROOT / "apps" / "desktop")|str(ROOT / "apps" / "desktop" / "src")|' scripts/benchmark.py scripts/report_photos.py scripts/inspect_groups.py
```

Корневой `pyproject.toml` (заменить целиком):

```toml
# path: pyproject.toml
[tool.pytest.ini_options]
pythonpath = ["apps/desktop/src", "apps/mobile/src", "."]
testpaths = ["tests"]

[tool.ruff]
line-length = 125
target-version = "py312"
src = ["apps/desktop/src", "apps/mobile/src", "."]

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP"]

[tool.ruff.lint.per-file-ignores]
"scripts/*.py" = ["E402", "I001"]  # sys.path подменяется до импортов намеренно
"tests/test_scripts.py" = ["E402", "I001"]
"tests/test_thumbs.py" = ["E402", "I001"]
```

- [ ] **Step 2: Проверка**

Run: `.venv\Scripts\python.exe -m pytest -q` и `.venv\Scripts\python.exe -m ruff check .`
Expected: `149 passed`, `All checks passed!`. Дополнительно `.venv\Scripts\python.exe scripts\benchmark.py --help` печатает справку (путь в скрипте верный).

- [ ] **Step 3: Commit**

```bash
git add -A apps scripts pyproject.toml
git commit -m "refactor: move the core into apps/desktop/src for Flet packaging" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: ПК-приложение (каркас)

**Files:**
- Create: `apps/desktop/pyproject.toml`, `apps/desktop/src/main.py`, `apps/desktop/src/gmagc_desktop/about.py`, `apps/desktop/src/gmagc_desktop/selfcheck.py`, `apps/desktop/src/gmagc_desktop/app.py`
- Modify: `requirements-dev.txt`
- Test: `tests/desktop/test_selfcheck.py`, `tests/desktop/test_desktop_app.py`

**Interfaces:**
- Produces: `gmagc_desktop.about.NAME / VERSION / AUTHOR`; `gmagc_desktop.selfcheck.run_core_check() -> dict` с ключами `ok: bool`, `shape: tuple | None`, `versions: {python, numpy, opencv}`; `gmagc_desktop.app.build_page(page, check=run_core_check) -> ft.Text` (возвращает поле результата).

- [ ] **Step 1: Зависимости для тестов и тесты (сначала падающие)**

```
# path: requirements-dev.txt
numpy
opencv-python-headless
onnxruntime
onnx
Pillow
pytest
ruff
flet==1.0.0
flet-camera==1.0.0
flet-permission-handler==1.0.0
```

Run: `.venv\Scripts\python.exe -m pip install -r requirements-dev.txt`

```python
# path: tests/desktop/test_selfcheck.py
from gmagc_desktop.selfcheck import run_core_check


def test_core_check_runs_the_pipeline_and_reports_versions():
    info = run_core_check()

    assert info["ok"] is True
    assert info["shape"] == (224, 224)
    assert set(info["versions"]) == {"python", "numpy", "opencv"}
    assert all(info["versions"].values())
```

```python
# path: tests/desktop/test_desktop_app.py
import flet as ft

from gmagc_desktop.about import AUTHOR, NAME, VERSION
from gmagc_desktop.app import build_page


class StubPage:
    """Минимальная замена ft.Page: запоминает, что на неё добавили."""

    def __init__(self):
        self.title = ""
        self.added = []
        self.updates = 0

    def add(self, *controls):
        self.added.extend(controls)

    def update(self):
        self.updates += 1


def texts(control):
    """Все строки Text внутри дерева контролов."""
    found = []
    for attribute in ("content", "controls"):
        value = getattr(control, attribute, None)
        for child in value if isinstance(value, list) else [value] if value is not None else []:
            found.extend(texts(child))
    if isinstance(control, ft.Text):
        found.append(control.value)
    return found


def find_button(control):
    if isinstance(control, ft.Button):
        return control
    for attribute in ("content", "controls"):
        value = getattr(control, attribute, None)
        for child in value if isinstance(value, list) else [value] if value is not None else []:
            button = find_button(child)
            if button is not None:
                return button
    return None


def test_page_shows_name_version_and_author():
    page = StubPage()

    build_page(page)

    assert page.title == f"{NAME} {VERSION}"
    shown = " ".join(texts(page.added[0]))
    assert NAME in shown and VERSION in shown and AUTHOR in shown


def test_button_runs_the_core_check_and_shows_the_result():
    page = StubPage()
    result = build_page(page, check=lambda: {"ok": True, "shape": (224, 224), "versions": {"numpy": "9.9"}})

    find_button(page.added[0]).on_click(None)

    assert "ОК" in result.value and "numpy: 9.9" in result.value
    assert page.updates == 1


def test_failed_check_is_reported_as_an_error():
    page = StubPage()
    result = build_page(page, check=lambda: {"ok": False, "shape": None, "versions": {}})

    find_button(page.added[0]).on_click(None)

    assert "ОШИБКА" in result.value
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/desktop -q`
Expected: FAIL (`ModuleNotFoundError: gmagc_desktop.selfcheck`).

- [ ] **Step 3: Implementation**

```python
# path: apps/desktop/src/gmagc_desktop/about.py
"""Название, версия и автор приложения."""

NAME = "GMAGC"
VERSION = "0.2.0"
AUTHOR = "@ANDY_BUM"
```

```python
# path: apps/desktop/src/gmagc_desktop/selfcheck.py
"""Самопроверка ядра: пайплайн работает, а упакованные зависимости загружаются."""

from __future__ import annotations

import platform

import cv2
import numpy as np

from gmagc_desktop.matcher.pipeline import normalize_photo
from gmagc_desktop.matcher.synthetic import simulate_photo


def _sample_gobo(size: int = 256) -> np.ndarray:
    """Небольшое асимметричное «гобо»: кольцо и две точки на чёрном фоне."""
    image = np.zeros((size, size), np.uint8)
    centre = size // 2
    cv2.circle(image, (centre, centre), int(size * 0.4), 255, size // 16)
    cv2.circle(image, (centre + size // 5, centre - size // 8), size // 12, 255, -1)
    cv2.circle(image, (centre - size // 4, centre + size // 6), size // 20, 255, -1)
    return image


def run_core_check() -> dict:
    """Строит синтетическое фото, прогоняет его через ядро и возвращает итог и версии библиотек."""
    photo = simulate_photo(_sample_gobo(), np.random.default_rng(1))
    normalized = normalize_photo(photo)
    shape = None if normalized is None else tuple(int(n) for n in normalized.shape)
    return {
        "ok": shape == (224, 224),
        "shape": shape,
        "versions": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "opencv": cv2.__version__,
        },
    }
```

```python
# path: apps/desktop/src/gmagc_desktop/app.py
"""Экран ПК-приложения (каркас): версия, автор и проверка ядра."""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from gmagc_desktop.about import AUTHOR, NAME, VERSION
from gmagc_desktop.selfcheck import run_core_check


def build_page(page: ft.Page, check: Callable[[], dict] = run_core_check) -> ft.Text:
    """Строит экран и возвращает поле результата (нужно тестам)."""
    page.title = f"{NAME} {VERSION}"
    result = ft.Text("Нажмите «Проверить ядро»", selectable=True)

    def on_check(_event) -> None:
        info = check()
        head = "ОК: ядро работает" if info["ok"] else "ОШИБКА: ядро не сработало"
        result.value = "\n".join([head] + [f"{name}: {value}" for name, value in info["versions"].items()])
        page.update()

    page.add(
        ft.SafeArea(
            ft.Column(
                [
                    ft.Text(NAME, size=28, weight=ft.FontWeight.BOLD),
                    ft.Text(f"Версия {VERSION}"),
                    ft.Text(f"Автор: {AUTHOR}"),
                    ft.Text("Поиск гобо по фото. Это каркас: функции появятся в следующих этапах."),
                    ft.Button("Проверить ядро", on_click=on_check),
                    result,
                ],
                spacing=12,
            )
        )
    )
    return result
```

```python
# path: apps/desktop/src/main.py
"""Точка входа ПК-приложения для `flet build`."""

import flet as ft

from gmagc_desktop.app import build_page

ft.run(build_page)
```

```toml
# path: apps/desktop/pyproject.toml
[project]
name = "gmagc-desktop"
version = "0.2.0"
description = "GMAGC: поиск гобо по фото (ПК-приложение)"
requires-python = ">=3.12,<3.13"
authors = [{ name = "@ANDY_BUM" }]
dependencies = [
  "flet==1.0.0",
  "numpy",
  "opencv-python-headless",
  "Pillow",
]

[tool.flet]
product = "GMAGC"
company = "@ANDY_BUM"
copyright = "Copyright (C) 2026 @ANDY_BUM"
org = "com.spacesarmat"

[tool.flet.app]
path = "src"  # main.py лежит в src/
```

- [ ] **Step 4: Run tests and ruff**

Run: `.venv\Scripts\python.exe -m pytest tests/desktop -q` затем весь набор `.venv\Scripts\python.exe -m pytest -q` и `.venv\Scripts\python.exe -m ruff check .`
Expected: 4 passed в `tests/desktop`, всего 153 passed, ruff чист.

- [ ] **Step 5: Commit**

```bash
git add apps/desktop requirements-dev.txt tests/desktop
git commit -m "feat: add the desktop app skeleton with a core self-check" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: Android-приложение (каркас)

**Files:**
- Create: `apps/mobile/pyproject.toml`, `apps/mobile/src/main.py`, `apps/mobile/src/gmagc_mobile/__init__.py` (пустой), `apps/mobile/src/gmagc_mobile/about.py`, `apps/mobile/src/gmagc_mobile/app.py`
- Test: `tests/mobile/test_mobile_app.py`

**Interfaces:**
- Produces: `gmagc_mobile.about.NAME / VERSION / AUTHOR`; `gmagc_mobile.app.start_camera(page, permission, camera, status) -> None` (async); `gmagc_mobile.app.build_page(page, starter=start_camera) -> ft.Text` (async, возвращает строку статуса).

- [ ] **Step 1: Тесты (сначала падающие)**

```python
# path: tests/mobile/test_mobile_app.py
import asyncio

import flet_permission_handler as ph

from gmagc_mobile.about import AUTHOR, NAME, VERSION
from gmagc_mobile.app import STUB_TEXT, build_page, start_camera


class StubPage:
    def __init__(self):
        self.title = ""
        self.added = []
        self.services = []
        self.updates = 0

    def add(self, *controls):
        self.added.extend(controls)

    def update(self):
        self.updates += 1


class FakeStatus:
    def __init__(self):
        self.value = ""


class FakePermission:
    def __init__(self, status):
        self.status = status

    async def request(self, permission):
        assert permission == ph.Permission.CAMERA
        return self.status


class FakeCamera:
    def __init__(self, cameras=("back",), fail=False):
        self.cameras = list(cameras)
        self.fail = fail
        self.initialized_with = None

    async def get_available_cameras(self):
        if self.fail:
            raise RuntimeError("нет плагина")
        return self.cameras

    async def initialize(self, description, preset, enable_audio=True):
        self.initialized_with = (description, enable_audio)


def run(page, permission, camera):
    status = FakeStatus()
    asyncio.run(start_camera(page, permission, camera, status))
    return status


def test_granted_permission_initializes_the_first_camera():
    camera = FakeCamera(cameras=("back", "front"))

    status = run(StubPage(), FakePermission(ph.PermissionStatus.GRANTED), camera)

    assert status.value == "Камера готова"
    assert camera.initialized_with == ("back", False)


def test_denied_permission_explains_what_to_do():
    camera = FakeCamera()

    status = run(StubPage(), FakePermission(ph.PermissionStatus.DENIED), camera)

    assert "разрешите" in status.value
    assert camera.initialized_with is None


def test_no_camera_and_plugin_errors_are_shown_not_raised():
    assert run(StubPage(), FakePermission(ph.PermissionStatus.GRANTED), FakeCamera(cameras=())).value == "Камера не найдена"
    assert "Ошибка камеры" in run(StubPage(), FakePermission(ph.PermissionStatus.GRANTED), FakeCamera(fail=True)).value


def test_page_shows_name_version_author_and_the_server_stub():
    page = StubPage()

    async def no_start(page, permission, camera, status):
        status.value = "запуск пропущен"

    status = asyncio.run(build_page(page, starter=no_start))

    assert page.title == f"{NAME} {VERSION}"
    assert len(page.services) == 1
    assert status.value == "запуск пропущен"
    assert page.updates >= 0
    assert STUB_TEXT and AUTHOR
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/mobile -q`
Expected: FAIL (`ModuleNotFoundError: gmagc_mobile`).

- [ ] **Step 3: Implementation**

```python
# path: apps/mobile/src/gmagc_mobile/about.py
"""Название, версия и автор приложения."""

NAME = "GMAGC"
VERSION = "0.2.0"
AUTHOR = "@ANDY_BUM"
```

```python
# path: apps/mobile/src/gmagc_mobile/app.py
"""Экран Android-приложения (каркас): превью камеры и заглушка подключения."""

from __future__ import annotations

import flet as ft
import flet_camera as fc
import flet_permission_handler as ph

from gmagc_mobile.about import AUTHOR, NAME, VERSION

STUB_TEXT = "Подключение к серверу появится в следующем этапе"


async def start_camera(page: ft.Page, permission, camera, status) -> None:
    """Запрашивает разрешение и запускает превью; любую ошибку показывает на экране."""
    try:
        if await permission.request(ph.Permission.CAMERA) != ph.PermissionStatus.GRANTED:
            status.value = "Нет доступа к камере: разрешите его в настройках"
        else:
            cameras = await camera.get_available_cameras()
            if not cameras:
                status.value = "Камера не найдена"
            else:
                await camera.initialize(cameras[0], fc.ResolutionPreset.MEDIUM, enable_audio=False)
                status.value = "Камера готова"
    except Exception as error:  # noqa: BLE001 - экран должен показать причину, а не закрыться
        status.value = f"Ошибка камеры: {error}"
    page.update()


async def build_page(page: ft.Page, starter=start_camera) -> ft.Text:
    """Строит экран, запускает камеру и возвращает строку статуса (нужна тестам)."""
    page.title = f"{NAME} {VERSION}"
    status = ft.Text("Запрашиваю доступ к камере…")
    camera = fc.Camera(expand=True, preview_enabled=True)
    permission = ph.PermissionHandler()
    page.services.append(permission)
    page.add(
        ft.SafeArea(
            ft.Column(
                [
                    ft.Text(NAME, size=24, weight=ft.FontWeight.BOLD),
                    ft.Text(f"Версия {VERSION}. Автор: {AUTHOR}"),
                    ft.Text(STUB_TEXT),
                    status,
                    ft.Container(camera, expand=True),
                ],
                expand=True,
            ),
            expand=True,
        )
    )
    await starter(page, permission, camera, status)
    return status
```

```python
# path: apps/mobile/src/main.py
"""Точка входа Android-приложения для `flet build apk`."""

import flet as ft

from gmagc_mobile.app import build_page

ft.run(build_page)
```

```toml
# path: apps/mobile/pyproject.toml
[project]
name = "gmagc-mobile"
version = "0.2.0"
description = "GMAGC: поиск гобо по фото (Android-клиент, камера)"
requires-python = ">=3.12,<3.13"
authors = [{ name = "@ANDY_BUM" }]
dependencies = [
  "flet==1.0.0",
  "flet-camera==1.0.0",
  "flet-permission-handler==1.0.0",
]

[tool.flet]
product = "GMAGC"
company = "@ANDY_BUM"
copyright = "Copyright (C) 2026 @ANDY_BUM"
org = "com.spacesarmat"

[tool.flet.app]
path = "src"  # main.py лежит в src/
```

Пустой `apps/mobile/src/gmagc_mobile/__init__.py` создаётся отдельно (`touch`).

- [ ] **Step 4: Run tests and ruff**

Run: `.venv\Scripts\python.exe -m pytest -q` и `.venv\Scripts\python.exe -m ruff check .`
Expected: 157 passed, ruff чист.

- [ ] **Step 5: Commit**

```bash
git add apps/mobile tests/mobile
git commit -m "feat: add the Android app skeleton with a camera preview" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: `ci.yml`

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Workflow**

```yaml
# path: .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    name: tests (${{ matrix.os }})
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest, macos-latest]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
          cache-dependency-path: requirements-dev.txt
      - run: python -m pip install -r requirements-dev.txt
      - run: python -m pytest -q
      - run: python -m ruff check .
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: run tests and ruff on Linux, Windows and macOS" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: Три workflow сборки

**Files:**
- Create: `.github/workflows/build-windows.yml`, `.github/workflows/build-macos.yml`, `.github/workflows/build-android.yml`

**Interfaces:**
- Каждый workflow кладёт в артефакт запуска файлы `dist/*` (архив или APK + `.sha256`); по тегу `v*` загружает их в GitHub Release (создаёт релиз, если его ещё нет).

- [ ] **Step 1: Windows**

```yaml
# path: .github/workflows/build-windows.yml
name: Build Windows

on:
  push:
    tags: ["v*"]
  workflow_dispatch:
  pull_request:
    paths: ["apps/**", ".github/workflows/build-windows.yml"]

env:
  # держать в синхронизации с apps/*/pyproject.toml и requirements-dev.txt
  FLET_VERSION: "1.0.0"

jobs:
  build:
    runs-on: windows-latest
    permissions:
      contents: write
    defaults:
      run:
        shell: bash
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Версия из тега
        run: |
          if [[ "$GITHUB_REF" == refs/tags/v* ]]; then VERSION="${GITHUB_REF_NAME#v}"; else VERSION="0.0.0"; fi
          echo "VERSION=$VERSION" >> "$GITHUB_ENV"
      - run: python -m pip install "flet==$FLET_VERSION"
      - name: Сборка
        run: flet build windows apps/desktop --yes --no-rich-output -v --build-version "$VERSION" --build-number "$GITHUB_RUN_NUMBER"
      - name: Упаковка
        run: |
          mkdir -p dist
          NAME="GMAGC-desktop-windows-${VERSION}.zip"
          (cd apps/desktop/build/windows && 7z a -tzip "$GITHUB_WORKSPACE/dist/$NAME" .)
          (cd dist && sha256sum "$NAME" > "$NAME.sha256")
      - uses: actions/upload-artifact@v4
        with:
          name: GMAGC-desktop-windows
          path: dist/*
      - name: Публикация в релиз
        if: startsWith(github.ref, 'refs/tags/v')
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          gh release create "$GITHUB_REF_NAME" --title "GMAGC $GITHUB_REF_NAME" --generate-notes || true
          gh release upload "$GITHUB_REF_NAME" dist/* --clobber
```

- [ ] **Step 2: macOS**

```yaml
# path: .github/workflows/build-macos.yml
name: Build macOS

on:
  push:
    tags: ["v*"]
  workflow_dispatch:
  pull_request:
    paths: ["apps/**", ".github/workflows/build-macos.yml"]

env:
  # держать в синхронизации с apps/*/pyproject.toml и requirements-dev.txt
  FLET_VERSION: "1.0.0"

jobs:
  build:
    runs-on: macos-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Версия из тега
        run: |
          if [[ "$GITHUB_REF" == refs/tags/v* ]]; then VERSION="${GITHUB_REF_NAME#v}"; else VERSION="0.0.0"; fi
          echo "VERSION=$VERSION" >> "$GITHUB_ENV"
      - run: python -m pip install "flet==$FLET_VERSION"
      - name: Сборка (универсальный пакет)
        run: flet build macos apps/desktop --yes --no-rich-output -v --build-version "$VERSION" --build-number "$GITHUB_RUN_NUMBER"
      - name: Упаковка
        run: |
          mkdir -p dist
          NAME="GMAGC-desktop-macos-${VERSION}.zip"
          APP=$(find apps/desktop/build/macos -maxdepth 1 -name "*.app" | head -1)
          ditto -c -k --keepParent "$APP" "dist/$NAME"
          (cd dist && shasum -a 256 "$NAME" > "$NAME.sha256")
      - uses: actions/upload-artifact@v4
        with:
          name: GMAGC-desktop-macos
          path: dist/*
      - name: Публикация в релиз
        if: startsWith(github.ref, 'refs/tags/v')
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          gh release create "$GITHUB_REF_NAME" --title "GMAGC $GITHUB_REF_NAME" --generate-notes || true
          gh release upload "$GITHUB_REF_NAME" dist/* --clobber
```

- [ ] **Step 3: Android**

```yaml
# path: .github/workflows/build-android.yml
name: Build Android

on:
  push:
    tags: ["v*"]
  workflow_dispatch:
  pull_request:
    paths: ["apps/**", ".github/workflows/build-android.yml"]

env:
  # держать в синхронизации с apps/*/pyproject.toml и requirements-dev.txt
  FLET_VERSION: "1.0.0"

jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - uses: actions/setup-java@v4
        with:
          distribution: temurin
          java-version: "17"
      - name: Версия из тега
        run: |
          if [[ "$GITHUB_REF" == refs/tags/v* ]]; then VERSION="${GITHUB_REF_NAME#v}"; else VERSION="0.0.0"; fi
          echo "VERSION=$VERSION" >> "$GITHUB_ENV"
      - run: python -m pip install "flet==$FLET_VERSION"
      - name: Сборка APK
        run: flet build apk apps/mobile --yes --no-rich-output -v --build-version "$VERSION" --build-number "$GITHUB_RUN_NUMBER"
      - name: Упаковка
        run: |
          mkdir -p dist
          NAME="GMAGC-android-${VERSION}.apk"
          APK=$(find apps/mobile/build/apk -name "*.apk" | head -1)
          cp "$APK" "dist/$NAME"
          (cd dist && sha256sum "$NAME" > "$NAME.sha256")
      - uses: actions/upload-artifact@v4
        with:
          name: GMAGC-android
          path: dist/*
      - name: Публикация в релиз
        if: startsWith(github.ref, 'refs/tags/v')
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          gh release create "$GITHUB_REF_NAME" --title "GMAGC $GITHUB_REF_NAME" --generate-notes || true
          gh release upload "$GITHUB_REF_NAME" dist/* --clobber
```

- [ ] **Step 4: Commit**

```bash
git add .github/workflows
git commit -m "ci: add Windows, macOS and Android build workflows" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6: README, публикация ветки, Pull Request и доводка CI до зелёного

**Files:**
- Modify: `README.md`

- [ ] **Step 1: README**

В `README.md`: обновить раздел «Быстрый старт» (`$env:PYTHONPATH = "apps\desktop\src"`, `export PYTHONPATH=apps/desktop/src`), строку структуры репозитория (`apps/desktop/src/gmagc_desktop/`, `apps/desktop/src/main.py`, `apps/mobile/src/`, `.github/workflows/`), добавить в начало под заголовком строку `Автор: @ANDY_BUM` и раздел «Сборки»: три файла релиза, как запускать (тег `v*`), что без подписей (macOS: правый клик → «Открыть»; Windows: SmartScreen «Подробнее → Выполнить в любом случае»; Android: разрешить установку из неизвестных источников), правило «версия Flet живёт в четырёх местах: `FLET_VERSION` в трёх workflow, `dependencies` в `apps/*/pyproject.toml`, `requirements-dev.txt`».

- [ ] **Step 2: Публикация ветки и Pull Request**

```bash
git add README.md docs
git commit -m "docs: describe the builds and add the author" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
git push -u origin feat/builds
gh pr create --base main --head feat/builds --title "Сборки под Windows, macOS и Android (каркасы приложений)" --body "Каркасы Flet-приложений, ci.yml и три workflow сборки. См. docs/superpowers/specs/2026-09-21-gmagc-builds-design.md"
```

- [ ] **Step 3: Цикл до зелёного**

`gh run list --branch feat/builds` показывает запуски; `gh run watch <id>` ждёт завершения, `gh run view <id> --log-failed` даёт причину. Для каждой красной проверки: диагностика по логу → минимальная правка → коммит → пуш → снова. Ожидаемые места отказов и запасные варианты (из спецификации): универсальная сборка macOS без колёс одной архитектуры → добавить `--arch arm64` в `build-macos.yml`; платформенные расхождения тестов на Linux/macOS → правка тестов (не ослабляя проверки); плагин камеры ломает APK → убрать `flet-camera` из каркаса и оставить заглушку, записав это в спецификацию.
Expected: `ci.yml` (3 ОС) и три workflow сборки зелёные, в артефактах запуска три архива и суммы.

---

### Task 7: Слияние, тег `v0.2.0` и релиз

- [ ] **Step 1: Слияние и тег**

```bash
gh pr merge --squash --delete-branch
git switch main && git pull
git tag -a v0.2.0 -m "GMAGC v0.2.0: app skeletons and builds" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
git push origin v0.2.0
```

- [ ] **Step 2: Проверка релиза**

`gh run list --limit 5` (три workflow по тегу зелёные), `gh release view v0.2.0` показывает `GMAGC-desktop-windows-0.2.0.zip`, `GMAGC-desktop-macos-0.2.0.zip`, `GMAGC-android-0.2.0.apk` и три `.sha256`. Скачать, сверить суммы (`sha256sum -c`).

- [ ] **Step 3: Ручная проверка пользователем**

Windows/macOS: приложение открывается, кнопка «Проверить ядро» показывает `ОК`. Android: APK устанавливается, показывает превью камеры (или понятное сообщение).

---

## Самопроверка плана

**Покрытие спецификации:** цель и артефакты → Tasks 5, 7; каркасы и автор → Tasks 2, 3, 6; переезд ядра → Task 1; `ci.yml` → Task 4; три workflow, триггеры, версия из тега, публикация → Task 5; критерии готовности и ручная проверка → Tasks 6, 7; риски (macOS universal, колёса, камера, тесты на других ОС) → Step 3 Task 6. Не входят (по спецификации): подписи, iOS, автообновление, модель, `gmagc_common`, HTTP на Android (записано как риск 7 спецификации).
**Согласованность имён:** `build_page` (desktop: `(page, check)`, mobile: async `(page, starter)`), `start_camera(page, permission, camera, status)`, `STUB_TEXT`, `about.NAME/VERSION/AUTHOR` совпадают между тестами и кодом. Версия `0.2.0` задана в `about.py` обоих приложений и `pyproject.toml`; при выпуске менять все четыре места вместе с тегом.
