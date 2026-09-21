# GMAGC: сборки под Windows, macOS и Android. Дизайн

Дата: 2026-09-21. Статус: дизайн утверждён в диалоге (подход B: три отдельных workflow), ждёт проверки пользователем.
Продолжение `2026-09-19-gmagc-gobo-recognizer-design.md` (раздел 10). Ядро распознавания уже выпущено (v0.1.0).

## 1. Цель

GitHub Actions собирает установочные артефакты и прикрепляет их к релизу по тегу:
- **Windows**: zip с приложением (`GMAGC-desktop-windows-<версия>.zip`);
- **macOS**: zip с `.app` (`GMAGC-desktop-macos-<версия>.zip`);
- **Android**: `GMAGC-android-<версия>.apk`;
- рядом контрольные суммы (`*.sha256`).

Содержимое первых сборок это **каркасы**: приложений на Flet пока нет, функции (сервер, поиск в интерфейсе, подключение телефона) приходят следующими этапами. Цель каркасов: доказать, что упаковка тяжёлых зависимостей и сам конвейер сборки работают, чтобы дальше дописывать только функции.

## 2. Решения

| Вопрос | Решение |
|---|---|
| Что собираем | Каркасы: ПК-приложение с проверкой ядра, Android-приложение с камерой |
| Структура CI | Три отдельных workflow сборки (по платформе) + отдельный `ci.yml` с тестами |
| Flet | Закрепляем `flet==1.0.0` (последний стабильный на 2026-09-21), расширения `flet-camera==1.0.0`, `flet-permission-handler==1.0.0` |
| Python в приложениях | `requires-python = ">=3.12,<3.13"` (у Flet по умолчанию 3.14, колёса numpy / OpenCV / onnxruntime надёжнее на 3.12) |
| macOS | Универсальный пакет (Apple Silicon + Intel), для чего нужны колёса обеих архитектур; если для одной колёс нет, собираем `--arch arm64` |
| Подписи | Нет: macOS-приложение без подписи Apple, APK без release-ключа, Windows без подписи (SmartScreen предупредит) |
| Данные | Модель и библиотека гобо в сборки не входят |
| Общий пакет протокола | `gmagc_common` откладывается до этапа сервера |
| Запуск сборок | Тег `v*`, ручной запуск, Pull Request, затрагивающий `apps/**` или workflow сборки |
| Публикация | Только по тегу: артефакты прикрепляются к GitHub Release |

## 3. Раскладка репозитория

```
apps/desktop/pyproject.toml        Flet-приложение: зависимости, [tool.flet]
apps/desktop/src/main.py           окно ПК-приложения
apps/desktop/src/gmagc_desktop/    ядро (переезжает из apps/desktop/gmagc_desktop, git mv)
apps/mobile/pyproject.toml         Flet + flet-camera + flet-permission-handler, без numpy/OpenCV
apps/mobile/src/main.py            экран Android-приложения
.github/workflows/ci.yml           тесты и ruff
.github/workflows/build-windows.yml
.github/workflows/build-macos.yml
.github/workflows/build-android.yml
```

Flet упаковывает содержимое `src/` приложения, поэтому ядро должно лежать внутри `apps/desktop/src/`. Переезд затрагивает пути в корневом `pyproject.toml` (pytest `pythonpath`), в `scripts/*.py` (вставка в `sys.path`), в README и документах. Тесты остаются прежними.

## 4. Приложения

**ПК (`apps/desktop/src/main.py`).** Окно с названием, версией и кнопкой «Проверить ядро». Проверка вынесена в чистую функцию `gmagc_desktop/selfcheck.py::run_core_check() -> dict` (её тестирует pytest): строит синтетическое фото (`simulate_photo`), прогоняет через `normalize_photo` и возвращает `{ok, shape, versions: {numpy, opencv, onnxruntime, python}}`. Окно показывает результат. Так собранное приложение доказывает, что ядро и зависимости упаковались.

**Android (`apps/mobile/src/main.py`).** Экран с заголовком, превью камеры (`flet_camera.Camera`, запрос разрешения через `PermissionHandler`) и текстом «Подключение к серверу появится в следующем этапе». В `pyproject.toml`: разрешение `android.permission.CAMERA`, `usesCleartextTraffic = "true"` (HTTP по локальной сети, риск 4 исходной спецификации).

Приложения не зависят друг от друга. Версия приложения берётся из тега без буквы `v` (`--build-version`), вне тега это `0.0.0`; номер сборки из `github.run_number`.

## 5. Workflows

**`ci.yml`** (push и Pull Request): матрица Ubuntu / Windows / macOS на Python 3.12: `pip install -r requirements-dev.txt`, `pytest -q`, `ruff check .`.

**`build-windows.yml`, `build-macos.yml`, `build-android.yml`.** Триггеры: `push: tags: ['v*']`, `workflow_dispatch`, `pull_request` с фильтром путей. Шаги: checkout → `actions/setup-python` 3.12 → `pip install flet==1.0.0` → `flet build <windows|macos|apk> apps/<desktop|mobile> --yes --no-rich-output --build-version <версия> --build-number <run_number>` → упаковка (Windows: zip папки сборки; macOS: `ditto -c -k --keepParent` для `.app`; Android: копия `.apk`) → SHA-256 → `actions/upload-artifact`. На теге: `gh release create <тег> ... || true` (три workflow гоняются за создание релиза, повторное создание безопасно игнорируется), затем `gh release upload <тег> <файлы> --clobber`. Права `contents: write` только у шага публикации.

Версия Flet (`FLET_VERSION`) задаётся в переменной окружения каждого workflow и дублируется в `dependencies` приложений: при обновлении менять все места (правило записано в README).

## 6. Тестирование и критерии готовности

- pytest: тест `run_core_check()` (структура ответа, `ok is True`, версии заполнены); существующие 149 тестов проходят после переезда пакета.
- Три workflow сборки зелёные на Pull Request; после тега `v0.2.0` на странице релиза три файла и контрольные суммы.
- Ручная проверка пользователем: приложение для Windows и macOS открывается, кнопка «Проверить ядро» показывает OK; APK устанавливается на телефон и показывает превью камеры.

## 7. Риски и запасные варианты

1. **macOS universal**: нет колёс для одной из архитектур → сборка падает; запасной вариант `--arch arm64`.
2. **Колёса тяжёлых пакетов на выбранном Python** (onnxruntime, OpenCV) для упаковщика Flet; запасной вариант: другая версия Python в `requires-python` или отказ от `onnxruntime` в каркасе (он нужен только модели, а пиксельному движку не нужен).
3. **Android**: плагин камеры увеличивает сборку; если он ломает сборку, каркас Android временно теряет превью камеры и остаётся с экраном-заглушкой.
4. **Время и размер**: Flet при каждом запуске скачивает Flutter; при долгих сборках добавляется кэш `~/flutter`. Публичный репозиторий не расходует платные минуты.
5. **Расхождение версий Flet** между workflow и приложениями (см. раздел 5).
6. **Непроверенный запуск GUI в CI**: проверка приложений ручная (раздел 6).

## 8. Вне объёма

Подписи и нотаризация, iOS, автообновление, модель в сборке, сервер и подключение телефона, общий пакет `gmagc_common`, установщики (MSI/DMG).
