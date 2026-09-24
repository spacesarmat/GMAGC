# GMAGC: экспорт профиля прибора в grandMA2 (этап 3). Дизайн

Дата: 2026-09-24. Статус: дизайн; реализация начата по просьбе пользователя («приступай к экспорту в MA2»).
Продолжение `2026-09-24-gmagc-ma3-export-design.md`. Готово: редактор профилей и экспорт в grandMA3 (v0.8.0, проверен импортом в MA3).

## 1. Цель

Превратить режим профиля в файл типа прибора grandMA2 (`.xml`, `importexport` или библиотека MA2). Только экспорт в файл; отправка на ПК и слоты колёс остаются следующими этапами.

## 2. Что показал разбор реальных файлов MA2 (версия 3.9.63)

Эталоны: `library\ape_labs@mobilight_4@12_channel.xml` (3,5 КБ, «библиотечный» формат) и `library\shehds@380w_beam@19_channel.xml` (экспорт из MA2).

- **Один файл — один режим.** `FixtureType name="380W Beam" mode="19 channel"`; имя файла по правилу MA `производитель@модель@режим.xml` в нижнем регистре, пробелы → `_` (`shehds@380w_beam@19_channel.xml`).
- Корень `<MA xmlns=".../grandma2/xml/MA" major_vers="2" minor_vers="8" stream_vers="123">`; внутри `FixtureType` → `InfoItems`, `short_name`, `manufacturer`, `short_manufacturer`, `Modules`, `Instances`, `Wheels`.
- `Module name class beamtype beam_angle beam_intensity` → `Body/Size` и каналы `ChannelType`: `attribute`, `feature`, `preset`, `coarse` (адрес), `fine` (16 бит), `default` (в единицах канала, для 16 бит 32768 = центр), `highlight_value`, `snap`.
- `ChannelType` → `ChannelFunction` (`from`/`to` в процентах канала, `min_dmx_24`/`max_dmx_24` = 0…16777215, `physfrom`/`physto`, `subattribute`, `attribute`, `feature`, `preset`) → `ChannelSet name from_dmx to_dmx` (значения DMX в единицах канала: 16 бит до 65535).
- Имена атрибутов — верхним регистром: `DIM`, `PAN`, `TILT`, `SHUTTER`, `COLORRGB1/2/3/5`, `COLOR1`, `GOBO1`, `GOBO2_POS`, `PRISMA1`, `ZOOM`, `FOCUS`, `POSITIONMSPEED`; «пустой» канал — `attribute="DUMMY"`, `subattribute="NOFEATURE"`, `feature="CONTROL"`, `preset="CONTROL"`.

## 3. Решения

| Вопрос | Решение |
|---|---|
| Модуль | `packages/common/gmagc_common/ma2_export.py`; `ExportError` общий с MA3 |
| API | `export_ma2(profile, mode_index, now=None) -> str`, `export_ma2_files(profile, now=None) -> list[(имя файла, xml)]`, `ma2_file_name(profile, mode) -> str` |
| Атрибуты | Только подтверждённые файлами MA2: DIM, SHUTTER, PAN, TILT, POSITIONMSPEED, COLORRGB1/2/3/5, COLOR{n}, GOBO{n}, GOBO{n}_POS (вращение гобо, одним диапазоном), PRISMA{n}, ZOOM, FOCUS. Каналы, атрибут которых по образцам не подтверждён (CTO, ирис, фрост, «Управление», «Свой канал»), выгружаются пустым каналом `DUMMY` (имя и диапазоны сохраняются, но пульт функцию не увидит) |
| Значения | Диапазон `Range(start, end)` → `ChannelSet from_dmx/to_dmx`; для 16 бит `start·256` и `end·256+255`; `default` для 16 бит `default·256` |
| Без диапазонов | Как в образцах: наборы `min`/`max` (для Pan/Tilt ещё `center`) |
| Физика | Pan −270…270, Tilt −135…135, остальное 0…1 |
| Модуль | Один `Module "Main Module"`: с Pan/Tilt — `Headmover/Spot`, иначе `LED/Wash`; `Body/Size` 0,2 м; один `Instance module_index=0 patch=1` |
| Колёса | `Wheels` пустой (слоты — этап гобо-колёс) |
| Повторы | Как в MA3: нумерованные шаблоны получают номера, повтор остальных в одном режиме — `ExportError` |
| Проверка | Профиль с ошибками `validate_profile` не экспортируется |
| Как получить | Скрипт `scripts/export_ma2.py profile.json [-d папка]` пишет по файлу на каждый режим; кнопка «Поделиться режим для grandMA2 (XML)» на экране режима |

## 4. Риск и проверка

Как и в MA3, принятие файла пультом проверяется только импортом (`Setup` → `Patch and Fixture Schedule` → `Fixture Types` → `Import`). Каналы с неподтверждённым атрибутом выгружаются как `DUMMY`, чтобы не получить отказ из-за неизвестного имени; после образцов с ирисом, фростом и CTO таблица расширяется.

## 5. Тесты
`tests/common/test_ma2_export.py` (структура, имена, адреса, hex не нужны — десятичные значения, 16 бит, диапазоны, DUMMY, нумерация, ошибки, имя файла), `tests/test_export_ma2_script.py`, тесты кнопки на экране режима.
