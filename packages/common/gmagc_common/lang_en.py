"""Английские переводы общих сообщений (проверка профиля, шаблоны каналов, обновления, поддержка автора, протокол)."""

from gmagc_common.i18n import register

EN = {
    # шаблоны каналов: названия и названия диапазонов (тексты хранятся в fixtures.TEMPLATES)
    "Диммер": "Dimmer",
    "Шаттер / строб": "Shutter / strobe",
    "Закрыт": "Closed",
    "Открыт": "Open",
    "Строб": "Strobe",
    "Скорость Pan/Tilt": "Pan/Tilt speed",
    "Быстро…медленно": "Fast…slow",
    "Красный": "Red",
    "Зелёный": "Green",
    "Синий": "Blue",
    "Белый": "White",
    "Тёплый…холодный": "Warm…cool",
    "Колесо цвета": "Color wheel",
    "Колесо гобо": "Gobo wheel",
    "Открыто": "Open",
    "Вращение гобо": "Gobo rotation",
    "Вращение": "Rotation",
    "Призма": "Prism",
    "Нет": "None",
    "Фокус": "Focus",
    "Ближе…дальше": "Nearer…farther",
    "Зум": "Zoom",
    "Уже…шире": "Narrower…wider",
    "Ирис": "Iris",
    "Закрыт…открыт": "Closed…open",
    "Фрост": "Frost",
    "Управление": "Control",
    "Свой канал": "Custom channel",
    # проверка профиля и разбор данных
    "неизвестный шаблон канала: {template_id}": "unknown channel template: {template_id}",
    "Режим {number}": "Mode {number}",
    "поле «{field}» должно быть строкой": "field “{field}” must be a string",
    "поле «{field}» должно быть целым числом": "field “{field}” must be an integer",
    "поле «{field}» должно быть списком": "field “{field}” must be a list",
    "поле «{field}» должно быть объектом": "field “{field}” must be an object",
    "диапазон": "range",
    "канал": "channel",
    "профиль": "profile",
    "режим": "mode",
    "разрядность канала должна быть 8 или 16": "the channel resolution must be 8 or 16 bits",
    "диапазон «{name}» должен лежать в 0–255 и идти от меньшего к большему": (
        "range “{name}” must lie within 0–255 and go from smaller to larger"
    ),
    "диапазоны «{name}» и «{name2}» пересекаются": "ranges “{name}” and “{name2}” overlap",
    "между диапазонами «{name}» и «{name2}» есть пропуск": "there is a gap between ranges “{name}” and “{name2}”",
    "не указан производитель": "the manufacturer is not specified",
    "не указано название прибора": "the fixture name is not specified",
    "нет ни одного режима": "there are no modes",
    "название режима «{name}» повторяется": "the mode name “{name}” is repeated",
    "в режиме нет каналов": "the mode has no channels",
    "у канала нет названия": "the channel has no name",
    "адрес должен лежать в 1–{MAX_DMX} (с учётом 16 бит)": "the address must be within 1–{MAX_DMX} (counting 16 bit)",
    "адрес {address} пересекается с каналом «{used}»": "address {address} overlaps with channel “{used}”",
    "пропуск адресов {start}–{end}": "gap in addresses {start}–{end}",
    "значение по умолчанию должно быть 0–255": "the default value must be 0–255",
    # экспорт в пульты
    "Диапазон {number}": "Range {number}",
    "профиль не готов к экспорту: {details}": "the profile is not ready for export: {details}",
    "нет режима с номером {mode_index}": "there is no mode number {mode_index}",
    "Создано в GMAGC": "Created with GMAGC",
    "в режиме «{name}» шаблон «{template}» повторяется: MA2 не различит эти каналы": (
        "in mode “{name}” the template “{template}” is repeated: MA2 cannot tell these channels apart"
    ),
    "в режиме «{name}» шаблон «{template}» повторяется: MA3 не различит эти каналы": (
        "in mode “{name}” the template “{template}” is repeated: MA3 cannot tell these channels apart"
    ),
    "нет определения атрибута {name}": "no definition of the attribute {name}",
    # протокол
    "повреждённое изображение в ответе": "damaged image in the reply",
    "неверный ответ сервера: {error}": "invalid server reply: {error}",
    "ожидались списки": "lists were expected",
    # поддержка автора
    "Поддержать автора": "Support the author",
    "GMAGC бесплатна, её делает один человек. Если программа помогает вам в работе, вы можете поддержать автора добровольным взносом. Спасибо!": (
        "GMAGC is free and is made by one person. If the program helps you in your work, "
        "you can support the author with a voluntary donation. Thank you!"
    ),
    "неизвестный ответ: {answer}": "unknown answer: {answer}",
    # обновления
    "Переход на недопустимый адрес: обновление отменено": "Redirect to a disallowed address: the update was cancelled",
    "Недопустимый адрес обновления": "Disallowed update address",
    "GitHub временно ограничил число запросов: попробуйте позже": "GitHub has temporarily limited the number of requests: try again later",
    "Релизы не найдены": "No releases found",
    "GitHub ответил ошибкой {code}": "GitHub replied with error {code}",
    "Нет связи с GitHub": "No connection to GitHub",
    "Слишком большой ответ GitHub": "The GitHub reply is too large",
    "Ответ GitHub не удалось разобрать": "The GitHub reply could not be parsed",
    "Ответ GitHub не похож на релиз": "The GitHub reply does not look like a release",
    "миниатюра гобо «{name}» повреждена": "the thumbnail of gobo “{name}” is damaged",
    "миниатюра гобо «{name}» имеет неверный размер": "the thumbnail of gobo “{name}” has the wrong size",
    "ожидался список": "a list was expected",
}

register("en", EN)
