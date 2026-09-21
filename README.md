# GMAGC: поиск гобо по фото

Автор: @ANDY_BUM

Находит в библиотеке гобо (папка в структуре grandMA) файл, который лучше всего совпадает с **фотографией проекции** на стене или экране. Выдаёт несколько лучших вариантов: название, путь, оценку совпадения; одинаковые гобо из разных папок производителей собираются в одну карточку.

**Статус: ядро распознавания (v0.1.0) и каркасы приложений со сборками под Windows, macOS и Android.** Индексация библиотеки, поиск по фото, командная строка, бенчмарк и вспомогательные скрипты готовы и покрыты тестами. Сервер на ПК, интерфейс Flet, Android-клиент (телефон как камера) и сборки под Windows / macOS / Android запланированы отдельными этапами (см. `docs/superpowers/specs`).

## Как это работает

Фото → поиск проекции (яркая малонасыщенная область, пятна узора сливаются в одну) → нормализация до 224×224 → 48 вариантов запроса (24 поворота × зеркало) → вектор признаков → косинусный поиск по кэшу индекса → мягкое сравнение формы для 20 лучших семейств дублей → результаты по семействам. Всё работает **офлайн**.

Вектор признаков сменный (`Embedder`): по умолчанию простой пиксельный вектор 16×16, без модели. Готовая нейросеть DINOv2-small на этих данных оказалась хуже и медленнее, подробности в `docs/benchmarks/2026-09-19-core-matcher.md`.

## Быстрый старт

Нужен Python 3.12+ (проверено на 3.14).

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
$env:PYTHONPATH = "apps\desktop\src"    # bash: export PYTHONPATH=apps/desktop/src

# один раз (и после изменений в библиотеке; при повторном запуске дозаписываются только новые файлы)
.venv\Scripts\python.exe -m gmagc_desktop.cli index D:\путь\к\gobos --index .gmagc-cache\index.npz

# поиск по фото
.venv\Scripts\python.exe -m gmagc_desktop.cli search photo.jpg --index .gmagc-cache\index.npz --library D:\путь\к\gobos --top 10
```

Пример вывода поиска: ` 1.  87.3%  vendor/ell.png  (+1 copies)`. Коды выхода: `0` успех; `1` индекса нет, он пуст или не подходит к модели; `2` проекция на фото не найдена; `3` не удалось прочитать входной файл (фото, модель, папка библиотеки).

## Результаты замеров

На 17 реальных фото (11 размечены, у 6 нужного гобо в библиотеке нет): верный ответ в первой пятёрке у **91%** (10 из 11), на первом месте у 64%. Поиск ~80 мс, индексация 11 тыс. файлов около минуты. Выборка небольшая (одна стена, одна камера), цифры показывают порядок величин.

## Сборки (Windows, macOS, Android)

Сборки делает GitHub Actions: по тегу `v*` (например `v0.2.0`) в релиз попадают `GMAGC-desktop-windows-<версия>.zip`, `GMAGC-desktop-macos-<версия>.zip`, `GMAGC-android-<версия>.apk` и файлы `.sha256`. Те же сборки запускаются на Pull Request и вручную (Actions → нужный workflow → Run workflow), артефакты лежат в запуске.

Пока это **каркасы**: ПК-приложение показывает версию и кнопку «Проверить ядро», Android-приложение показывает превью камеры. Поиск в интерфейсе, сервер и подключение телефона придут следующими этапами. Приложения без подписей:
- macOS: правый клик по приложению → «Открыть»;
- Windows: SmartScreen → «Подробнее» → «Выполнить в любом случае»;
- Android: разрешить установку из неизвестных источников.

Версия Flet записана в четырёх местах и меняется вместе: `FLET_VERSION` в трёх `build-*.yml`, `dependencies` в `apps/*/pyproject.toml` и `requirements-dev.txt`. Версия приложения (`VERSION` в `about.py` обоих приложений, `version` в их `pyproject.toml`) меняется вместе с тегом.

## Локальная разработка (Windows)

Один раз: Python 3.12 (`winget install Python.Python.3.12`), Visual Studio 2022 с «Desktop development with C++», режим разработчика Windows. Окружение для сборки: `py -3.12 -m venv $env:USERPROFILE\.venv312`, затем `$env:USERPROFILE\.venv312\Scripts\python.exe -m pip install flet==1.0.0 -r requirements-dev.txt` (Flutter Flet скачает сам).

| Что | Команда | Время |
|---|---|---|
| Тесты и линтер | `.venv\Scripts\python.exe -m pytest -q`, `... -m ruff check .` | секунды |
| Экран без упаковки (горячая перезагрузка) | `$env:USERPROFILE\.venv312\Scripts\flet.exe run apps/desktop/src/main.py -d` | секунды |
| Сборка Windows + проверка запуска | `.\scripts\build_windows.ps1` | несколько минут |
| Финальные сборки Windows, macOS, Android | тег `v*` → GitHub Actions | ~10 минут |

Логи собранного приложения: `%LOCALAPPDATA%\@ANDY_BUM\GMAGC\console.log`. macOS локально на Windows не собрать, только через GitHub.

## Разработка

```powershell
.venv\Scripts\python.exe -m pytest -q          # 149 тестов, только синтетические данные
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe scripts\benchmark.py --library D:\путь\к\gobos --samples 150
.venv\Scripts\python.exe scripts\report_photos.py --library D:\путь\к\gobos --top 10   # HTML-отчёт для разметки фото
```

Папки `gobos/` (библиотека), `photo/` (реальные фото) и `models/` (скачанные модели, `scripts/fetch_model.py`) в репозиторий **не входят**.

```
apps/desktop/src/gmagc_desktop/   ядро: matcher/ (изображение, эмбеддинги, поиск), library/ (обход, индекс, дубли), cli.py
apps/desktop/src/main.py          ПК-приложение Flet (каркас)
apps/mobile/src/                  Android-приложение Flet (каркас: камера)
.github/workflows/                тесты и сборки Windows / macOS / Android
scripts/                      бенчмарк, отчёт по фото, просмотр групп дублей, загрузка модели
tests/                        тесты (синтетическая библиотека в tests/fixtures.py)
docs/                         спецификация, план реализации, замеры
```

## Дальше

Сервер на ПК и связь с телефоном по Wi-Fi (QR + код), интерфейс Flet, Android-клиент, сборки в GitHub Actions. Известные отложенные доработки перечислены в конце плана `docs/superpowers/plans/2026-09-19-gmagc-core-matcher.md`.

## Лицензия

Лицензия пока не выбрана: по умолчанию все права сохраняются за автором. Библиотека гобо принадлежит своим производителям и в репозиторий не входит.
