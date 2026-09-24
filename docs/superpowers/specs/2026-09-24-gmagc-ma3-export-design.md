# GMAGC: экспорт профиля прибора в grandMA3 (этап 2). Дизайн

Дата: 2026-09-24. Статус: дизайн; реализация начинается по просьбе пользователя («приступай к экспорту в MA3»).
Продолжение `2026-09-24-gmagc-fixture-editor-design.md` (раздел 8, этап 2). Готово: редактор и модель профиля (v0.7.0).

## 1. Цель

Превратить `FixtureProfile` из редактора в файл типа прибора grandMA3 (`.xml`, кладётся в `gma3_library\fixturetypes` и импортируется в MA3). Только экспорт в файл; MA2, отправка на ПК и колёса со слотами гобо остаются следующими этапами.

## 2. Что показал разбор реальных файлов MA3

- Корень `<GMA3 DataVersion="2.5.0.3">` → один `FixtureType` с атрибутами `Name`, `Guid` (16 байт hex через пробелы), `ShortName`, `Manufacturer`, `Source`, `Description`, `Color`.
- Собственные лёгкие типы MA (например, `set@alphabet_A.xml`, 725 байт) содержат только `Models`, `Geometries`, `DMXModes`, `Revisions`. `AttributeDefinitions` в готовых типах перечисляет только используемые атрибуты (вместе с `ActivationGroups` и `FeatureGroups`).
- Канал: `DMXChannel Coarse [Fine]` → `LogicalChannel Attribute` → `ChannelFunction Attribute Default` → `ChannelSet Name DMXFrom`. Значения DMX записываются как 24-битные hex: 8-битное значение `v` даёт `VVVVVV` (например, `010101`, `FFFFFF`), 16-битное грубым байтом даёт `VV0000` (центр `800000`). Первый `ChannelSet` со значением 0 идёт без `DMXFrom`.
- `DefaultChannelFunction` имеет вид `Атрибут.Атрибут 1`. Канал 16 бит задаётся атрибутами `Coarse` и `Fine`.
- Эталоны: `k10test.xml`, `shehds@380w beam.xml` (`gma3_library\fixturetypes`), `generic@moving_head.xml` (`gma3_2.5.0\shared\lib_fixture_types\grandma3`).

## 3. Решения

| Вопрос | Решение |
|---|---|
| Модуль | `packages/common/gmagc_common/ma3_export.py` (стандартная библиотека), копии делает `sync_common.py` |
| API | `export_ma3(profile, now=None) -> str`; `ExportError`; `fixture_guid(profile_id) -> str` |
| Один файл | Один `FixtureType` на профиль, режимы профиля становятся `DMXMode` |
| Guid | Из `profile.id` (32 hex → 16 байт), стабильный: повторный импорт заменяет тот же тип |
| Атрибуты | Таблица шаблон → атрибут MA3 (значения взяты из реальных файлов): Dimmer, Shutter1, Pan, Tilt, PositionMSpeed, ColorRGB_R/G/B/W, CTO, Color{n}, Gobo{n}, Gobo{n}PosRotate (+Gobo{n}Pos), Prism{n}, Focus1, Zoom, Iris, Frost1, Control1, NoFeature. Определения только для реально использованных атрибутов |
| Повторы | Шаблоны с номером (`color_wheel`, `gobo_wheel`, `gobo_rotation`, `prism`) нумеруются по порядку появления в режиме (Gobo1, Gobo2…); повтор остальных шаблонов в одном режиме — `ExportError` |
| Диапазоны | `range.name` → `ChannelSet Name`, `range.start` → `DMXFrom`; конец диапазона определяется началом следующего; если первый диапазон не с 0, добавляется безымянный набор с 0 |
| Физика | Pan −270…270, Tilt −135…135 (для энкодеров); остальным не задаётся |
| Геометрия | Минимальная: одна `Geometry Name="Body"` с моделью `Body`; полей `Models`, `Wheels`, `PhysicalDescriptions` минимум, как в лёгких типах MA (пустые контейнеры допустимы) |
| Колёса | Слоты `Wheels` не создаются (этап гобо-колёс); диапазоны колеса гобо/цвета экспортируются как обычные `ChannelSet` без ссылки на колесо |
| Проверка | Профиль с ошибками `validate_profile` не экспортируется: `ExportError` со списком |
| Как получить файл | Скрипт `scripts/export_ma3.py profile.json [-o файл.xml]` (JSON приходит с телефона через «Поделиться профилем») и кнопка «Поделиться MA3 XML» на экране профиля |

## 4. Риск и проверка

Принимает ли grandMA3 урезанный файл, проверить автоматически нельзя. Тесты сверяют структуру с эталонными файлами (порядок и набор тегов, формат Guid и hex, `Fine` для 16 бит). Окончательная проверка: пользователь копирует полученный `.xml` в `gma3_library\fixturetypes` и импортирует его в MA3 (`Patch` → `Fixture Types` → импорт). Если MA3 отвергнет файл, ошибка из консоли пульта указывает, какой раздел добавить (запасной вариант: взять целиком секции из `k10test.xml`).

## 5. Тесты
`tests/common/test_ma3_export.py`: корректный XML, корень и атрибуты типа, Guid (формат, стабильность, различие между профилями), режимы и каналы, `Coarse/Fine`, hex-значения `DMXFrom` и `Default`, таблица атрибутов и определения, нумерация колёс, ошибка на повторе и на невалидном профиле, порядок секций. `tests/mobile`: кнопка «Поделиться MA3 XML» и её сообщение об ошибке. `tests/test_scripts.py`: скрипт экспорта на примере профиля.
