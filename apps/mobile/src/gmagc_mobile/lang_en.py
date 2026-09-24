"""Английские переводы интерфейса телефона: словарь «русский текст → английский»."""

from gmagc_common import lang_en as _common  # noqa: F401 - общие переводы регистрируются при импорте
from gmagc_common.i18n import register

EN = {
    # подключение и главный экран
    "Адрес ПК": "PC address",
    "192.168.1.5 или 192.168.1.5:8765": "192.168.1.5 or 192.168.1.5:8765",
    "Код доступа": "Access code",
    "Считать QR-код с ПК": "Scan the QR code from the PC",
    "Подключиться": "Connect",
    "Версия {VERSION}": "Version {VERSION}",
    "Профили приборов": "Fixture profiles",
    "Настройки": "Settings",
    "Помощь": "Help",
    "О программе": "About",
    "Галерея": "Gallery",
    "Версия {VERSION}. Автор: {AUTHOR}": "Version {VERSION}. Author: {AUTHOR}",
    "Поддержать автора": "Support the author",
    "Telegram автора": "Author's Telegram",
    "Канал GMAGC": "GMAGC channel",
    "Подключитесь к ПК с запущенным GMAGC в той же сети Wi-Fi: наведите камеру на QR-код в его окне (подключение произойдёт само) или введите адрес и код вручную. Дальше наводите камеру на проекцию и снимайте — совпадения из библиотеки на ПК придут в ответ.": (
        "Connect to a PC running GMAGC on the same Wi-Fi network: point the camera at the QR code in its window "
        "(it connects by itself) or enter the address and code manually. Then aim the camera at the projection and "
        "take a photo: the matches from the PC library come back as the answer."
    ),
    "«Профили»: создание профиля прибора для grandMA2 и grandMA3 с нуля (режимы, каналы из шаблонов, диапазоны значений). Все правки сохраняются сразу. Кнопки «Поделиться» отправляют готовые файлы: JSON профиля, XML для grandMA3 и по одному XML на режим для grandMA2 (положите их в fixturetypes библиотеки MA3 или в importexport MA2 и импортируйте в пульте).": (
        "“Profiles”: create a fixture profile for grandMA2 and grandMA3 from scratch (modes, channels from "
        "templates, value ranges). All edits are saved at once. The “Share” buttons send ready files: the profile "
        "JSON, an XML for grandMA3 and one XML per mode for grandMA2 (put them into the fixturetypes folder of the "
        "MA3 library or into the MA2 importexport folder and import them on the console)."
    ),
    # камера и снимок
    "Наведите камеру на QR-код в приложении на ПК — считается автоматически (приближение и касание для фокуса помогают)": (
        "Point the camera at the QR code in the PC app: it is read automatically (zoom and tapping to focus help)"
    ),
    "Автосканирование недоступно на этом телефоне. Наведите камеру на QR-код в приложении на ПК (приближение и касание для фокуса помогают) и нажмите «Считать QR»": (
        "Automatic scanning is not available on this phone. Point the camera at the QR code in the PC app "
        "(zoom and tapping to focus help) and tap “Scan QR”"
    ),
    "Фокус: авто": "Focus: auto",
    "Фокус: зафиксирован": "Focus: locked",
    "Фокус по точке недоступен": "Tap to focus is not available",
    "СФОТОГРАФИРОВАТЬ": "TAKE A PHOTO",
    "Готово к съёмке": "Ready to shoot",
    "Снять": "Shoot",
    "Выбрать фото": "Choose a photo",
    "Считать QR": "Scan QR",
    "Ввести вручную": "Enter manually",
    "Сменить ПК": "Change PC",
    "Повторить": "Retry",
    "Пока нет снимков в этой сессии": "No photos in this session yet",
    "Камера доступна только на телефоне (Android)": "The camera is available only on a phone (Android)",
    "Камера доступна только на телефоне (Android): здесь можно выбрать фото из галереи": (
        "The camera is available only on a phone (Android): here you can choose a photo from the gallery"
    ),
    "Нет доступа к камере: разрешите его в настройках телефона": (
        "No access to the camera: allow it in the phone settings"
    ),
    "Камера не найдена": "Camera not found",
    "Камера недоступна": "Camera unavailable",
    "камера недоступна": "camera unavailable",
    "камера не готова": "camera is not ready",
    "Приближение недоступно: {error}": "Zoom is not available: {error}",
    "Фокус по точке недоступен: {error}": "Tap to focus is not available: {error}",
    "Фокус недоступен: {error}": "Focus is not available: {error}",
    "Поток камеры недоступен: {error}": "The camera stream is not available: {error}",
    "Не удалось снять: {error}": "Could not take the photo: {error}",
    "Не удалось подготовить фото: {error}": "Could not prepare the photo: {error}",
    "Ошибка: {error}": "Error: {error}",
    "Ошибка поиска": "Search error",
    "Не удалось поделиться": "Could not share",
    "Нажмите «Назад» ещё раз, чтобы выйти": "Press “Back” again to exit",
    "Последняя ошибка: {text}": "Last error: {text}",
    # результаты
    "Фото проекции": "Projection photo",
    "Фото": "Photo",
    "Найденная проекция": "Found projection",
    "ещё {count} {files}": "{count} more {files}",
    "Копировать путь": "Copy path",
    "Путь скопирован: {path}": "Path copied: {path}",
    "Снять ещё": "Shoot again",
    "Поделиться": "Share",
    "Результаты (нажмите на карточку, чтобы скопировать путь)": "Results (tap a card to copy the path)",
    # подключение: сообщения
    "Нет подключения к ПК: подключитесь на главном экране и повторите.": (
        "Not connected to a PC: connect on the main screen and try again."
    ),
    "Введите адрес ПК, например 192.168.1.5 или 192.168.1.5:8765": (
        "Enter the PC address, for example 192.168.1.5 or 192.168.1.5:8765"
    ),
    "Код доступа состоит из 8 символов (буквы и цифры), он показан в приложении на ПК": (
        "The access code has 8 characters (letters and digits); it is shown in the PC app"
    ),
    "Ошибка подключения: {error}": "Connection error: {error}",
    "Подключено к ПК: {host}:{port}": "Connected to the PC: {host}:{port}",
    "Автоматическое чтение QR недоступно на этом телефоне: введите адрес и код вручную.": (
        "Automatic QR reading is not available on this phone: enter the address and code manually."
    ),
    "Чтение QR недоступно на этом телефоне: введите адрес и код вручную.": (
        "QR reading is not available on this phone: enter the address and code manually."
    ),
    "Снимок камеры не удалось прочитать ({error}). Введите адрес и код вручную.": (
        "Could not read the camera shot ({error}). Enter the address and code manually."
    ),
    "Ошибка камеры: {error}": "Camera error: {error}",
    "QR-код не найден. Поднесите камеру ближе (приближение и касание для фокуса помогают): код должен быть целиком в кадре и чётким. Если не выходит, введите адрес и код вручную.": (
        "QR code not found. Bring the camera closer (zoom and tapping to focus help): the code must be fully in "
        "the frame and sharp. If it does not work, enter the address and code manually."
    ),
    # клиент и тексты ответов
    "Неожиданный ответ ПК на поиск.": "Unexpected reply from the PC to the search.",
    "Неожиданный ответ ПК на отправку профиля.": "Unexpected reply from the PC to sending the profile.",
    "Неожиданный ответ ПК на запрос состояния.": "Unexpected reply from the PC to the status request.",
    "Ответ ПК: HTTP {status}": "PC reply: HTTP {status}",
    "Это не сервер GMAGC: проверьте адрес и порт.": "This is not a GMAGC server: check the address and port.",
    "Версия приложения на ПК (API {api}) не подходит к этому телефону (API {phone_api}): обновите оба приложения.": (
        "The PC app version (API {api}) does not match this phone (API {phone_api}): update both apps."
    ),
    "Нет связи с ПК. Телефон и ПК должны быть в одной сети Wi-Fi, GMAGC должен быть запущен на ПК, а брандмауэр Windows должен разрешать доступ. ({message})": (
        "No connection to the PC. The phone and the PC must be on the same Wi-Fi network, GMAGC must be running "
        "on the PC and the Windows firewall must allow access. ({message})"
    ),
    "Неверный код доступа. Код показан в приложении на ПК; если его сменили, введите новый.": (
        "Wrong access code. The code is shown in the PC app; if it was changed, enter the new one."
    ),
    "Слишком много неверных кодов. Подождите {seconds} с.": "Too many wrong codes. Wait {seconds} s.",
    "На ПК не выбрана библиотека или индекс ещё не построен. Постройте индекс в приложении на ПК.": (
        "No library is selected on the PC or its index is not built yet. Build the index in the PC app."
    ),
    "ПК не смог прочитать изображение. Попробуйте снять ещё раз.": (
        "The PC could not read the image. Try shooting again."
    ),
    "Изображение слишком большое для отправки.": "The image is too large to send.",
    "Ошибка на ПК: {message}": "PC error: {message}",
    "На ПК не найдена папка для grandMA3 или grandMA2: укажите её на экране «Настройки» ПК-приложения.": (
        "No folder for grandMA3 or grandMA2 was found on the PC: specify it on the “Settings” screen of the PC app."
    ),
    "ПК не принял профиль: {message}": "The PC did not accept the profile: {message}",
    "Профиль не готов к отправке: {problems}": "The profile is not ready to send: {problems}",
    "{console}: папка не найдена, укажите её в настройках ПК-приложения": (
        "{console}: folder not found, specify it in the PC app settings"
    ),
    "{console}: не удалось использовать папку ({detail})": "{console}: could not use the folder ({detail})",
    "Совпадение ненадёжно: похоже, такого гобо в библиотеке нет. Ниже самые близкие.": (
        "The match is unreliable: this gobo is probably not in the library. The closest ones are below."
    ),
    "Проекция на фото не найдена: переснимите ближе, затемните фон.": (
        "No projection found in the photo: shoot closer and darken the background."
    ),
    "Подключено: {host}:{port}": "Connected: {host}:{port}",
    " · индекс на ПК не построен": " · the PC index is not built",
    " · {number} {files}": " · {number} {files}",
    " (идёт индексация)": " (indexing)",
    "проекция не найдена": "projection not found",
    "GMAGC: проекция на фото не найдена": "GMAGC: no projection found in the photo",
    "GMAGC нашёл: {name} ({score_text})\n{path}": "GMAGC found: {name} ({score_text})\n{path}",
    "На ПК ещё не построен индекс: выберите папку библиотеки в приложении на ПК.": (
        "The index is not built on the PC yet: choose the library folder in the PC app."
    ),
    # диагностика QR
    "неизвестный формат": "unknown format",
    "{kind}, {size} КБ": "{kind}, {size} KB",
    ", Pillow не открывает": ", Pillow cannot open it",
    "библиотека недоступна ({error})": "library unavailable ({error})",
    "Pillow не открывает PNG ({error})": "Pillow cannot open the PNG ({error})",
    "сбой ({kind}: {error})": "failure ({kind}: {error})",
    "ок": "ok",
    "не прочитан ({text})": "not read ({text})",
    "снимок: {describe_shot}; самопроверка чтения QR: {selftest}": "shot: {describe_shot}; QR reading self-test: {selftest}",
    "кадр камеры повреждён: {count} байт для {width}×{height}": "camera frame is damaged: {count} bytes for {width}×{height}",
    # поддержка автора и обновления
    "Поддержать": "Support",
    "Позже": "Later",
    "Больше не показывать": "Do not show again",
    "Скачать": "Download",
    "Пропустить": "Skip",
    "Проверить обновления": "Check for updates",
    "Ошибка проверки обновлений: {error}": "Update check error: {error}",
    "Установлена последняя версия ({VERSION})": "The latest version is installed ({VERSION})",
    "Доступна версия {version} (у вас {VERSION})": "Version {version} is available (you have {VERSION})",
    "Проверяю обновления…": "Checking for updates…",
    "Не удалось открыть ссылку на загрузку: {error}": "Could not open the download link: {error}",
    # редактор профилей
    "Нет профилей. Создайте первый.": "No profiles. Create the first one.",
    "Новый профиль": "New profile",
    "Режимов: {count}": "Modes: {count}",
    "Удалить «{title}»?": "Delete “{title}”?",
    "Да": "Yes",
    "Нет": "No",
    "Режим {number}": "Mode {number}",
    "{name} (копия)": "{name} (copy)",
    "Не удалось поделиться: {error}": "Could not share: {error}",
    "Профиль прибора": "Fixture profile",
    "Производитель": "Manufacturer",
    "Короткое имя": "Short name",
    "Мод": "Modes",
    "{name} ({count} кан.)": "{name} ({count} ch.)",
    "Дублировать": "Duplicate",
    "Удалить": "Delete",
    "Добавить режим": "Add a mode",
    "Отправить на ПК": "Send to PC",
    "Поделиться профилем (файл JSON)": "Share the profile (JSON file)",
    "Поделиться для grandMA3 (файл XML)": "Share for grandMA3 (XML file)",
    "Поделиться для grandMA2 (файлы XML режимов)": "Share for grandMA2 (XML files of the modes)",
    "Режим": "Mode",
    "Название режима": "Mode name",
    "Каналы": "Channels",
    "Добавить канал (шаблон)": "Add a channel (template)",
    "Новый диапазон": "New range",
    "Записано на ПК:": "Written on the PC:",
    "Пропущено: {item}": "Skipped: {item}",
    "От": "From",
    "До": "To",
    "Удалить диапазон": "Delete the range",
    "Название значения": "Value name",
    "Канал": "Channel",
    "Шаблон": "Template",
    "Название": "Name",
    "По умолчанию": "Default",
    "{bits} бит": "{bits} bit",
    "Диапазоны значений (0–255)": "Value ranges (0–255)",
    "Добавить диапазон": "Add a range",
    "В инструкции не найдена таблица каналов DMX. Снимите таблицу ближе и ровнее или выберите другой файл.": (
        "No DMX channel table was found in the manual. Shoot the table closer and straighter, or pick another file."
    ),
    "В этот режим": "Into this mode",
    "Новым режимом": "As a new mode",
    "Добавлено каналов: {count}": "Channels added: {count}",
    "Заполнить по инструкции": "Fill in from the manual",
    "Инструкция прибора (фото или PDF)": "Fixture manual (photo or PDF)",
    "На ПК не установлено распознавание текста: {message}": "Text recognition is not installed on the PC: {message}",
    "Найдено в инструкции": "Found in the manual",
    "Не удалось прочитать файл: {error}": "Could not read the file: {error}",
    "Неожиданный ответ ПК на распознавание.": "Unexpected reply from the PC to the recognition request.",
    "Отметьте хотя бы один канал.": "Check at least one channel.",
    "ПК не смог прочитать файл инструкции: {message}": "The PC could not read the manual file: {message}",
    "Продолжение таблицы": "Table continuation",
    "Распознаю инструкцию на ПК, это может занять минуту…": "Recognizing the manual on the PC, this may take a minute…",
    "Снимите галочки с лишнего. Названия и диапазоны можно поправить после добавления.": (
        "Uncheck what you do not need. Names and ranges can be edited after adding."
    ),
    "диапазонов: {count}": "ranges: {count}",
    "Улучшить в облаке": "Improve in the cloud",
    "Распознать в облаке": "Recognize in the cloud",
    "Файл инструкции будет отправлен через ПК в облако Anthropic (Claude) для распознавания. Нужен ключ Anthropic в настройках ПК-приложения. Отправить?": (
        "The manual file will be sent through the PC to the Anthropic (Claude) cloud for recognition. "
        "An Anthropic key must be set in the PC app settings. Send it?"
    ),
    "Отправить в облако": "Send to the cloud",
    "Отмена": "Cancel",
    "Добавление отменено.": "Adding cancelled.",
    "Отменить": "Undo",
    "Неожиданный ответ ПК на поиск гобо.": "Unexpected reply from the PC to the gobo search.",
    "Гобо из библиотеки": "Gobo from the library",
    "Имя гобо": "Gobo name",
    "Найти по фото": "Find by photo",
    "Ищу на ПК…": "Searching on the PC…",
    "Ничего не найдено.": "Nothing found.",
    "Ещё {count}: уточните запрос.": "{count} more: narrow the query.",
    "Гобо: {name}": "Gobo: {name}",
    "Убрать гобо": "Remove the gobo",
    "{console}: файл гобо «{detail}» не найден в библиотеке": "{console}: the gobo file “{detail}” was not found in the library",
    "Создан режим «{name}»: каналов {count}": "Mode “{name}” created: {count} channels",
    "Создано режимов: {count}": "Modes created: {count}",
    "Нечего добавлять: все режимы уже добавлены или ничего не отмечено.": (
        "Nothing to add: all modes are already added or nothing is checked."
    ),
    "Добавить все режимы новыми": "Add all modes as new",
    "Продолжить с прошлым результатом": "Continue with the previous result",
}

register("en", EN)
