"""Английские переводы интерфейса ПК-приложения: словарь «русский текст → английский»."""

from gmagc_common.i18n import register

EN = {
    # навигация и боковая панель
    "Поиск гобо": "Gobo search",
    "Телефон": "Phone",
    "Библиотека": "Library",
    "Настройки": "Settings",
    "РАБОЧАЯ ОБЛАСТЬ": "WORKSPACE",
    "СИСТЕМА": "SYSTEM",
    "Система готова": "System ready",
    # поиск
    "Поиск по изображению": "Image search",
    "Загрузите фотографию проекции, чтобы найти совпадение в библиотеке.": (
        "Upload a photo of the projection to find a match in the library."
    ),
    "гобо в базе": "gobos in the database",
    "время поиска": "search time",
    "совпадение": "match",
    "Исходное изображение": "Source image",
    "Результаты": "Results",
    "Фото": "Photo",
    "Фото проекции": "Projection photo",
    "Найденная проекция": "Found projection",
    "Выбрать фото…": "Choose a photo…",
    "Вставить из буфера": "Paste from clipboard",
    "Сбросить": "Reset",
    "Поправка фото": "Photo adjustment",
    "Поправка найденной проекции": "Found projection adjustment",
    "Яркость: 0": "Brightness: 0",
    "Контраст: 1.0×": "Contrast: 1.0×",
    "Экспозиция: 0 EV": "Exposure: 0 EV",
    "Яркость: {signed}": "Brightness: {signed}",
    "Контраст: {adjust_contrast:.1f}×": "Contrast: {adjust_contrast:.1f}×",
    "Контраст: {proj_adjust_contrast:.1f}×": "Contrast: {proj_adjust_contrast:.1f}×",
    "Экспозиция: {signed} EV": "Exposure: {signed} EV",
    "{count} {results}": "{count} {results}",
    "ещё {count} {files}": "{count} more {files}",
    "Показать в папке": "Show in folder",
    "Это не то — указать верный файл": "This is wrong: choose the correct file",
    "Нажмите, чтобы скопировать путь к файлу": "Click to copy the file path",
    "Путь скопирован: {absolute}": "Path copied: {absolute}",
    "Выберите верный файл": "Choose the correct file",
    "Запомнено: при похожих запросах теперь будет показан верный файл": (
        "Remembered: the correct file will now be shown for similar queries"
    ),
    "Оценка ниже {percent}%: похоже, такого гобо в библиотеке нет. Ниже самые близкие.": (
        "The score is below {percent}%: this gobo is probably not in the library. The closest ones are below."
    ),
    "Проекция на фото не найдена: переснимите ближе, затемните фон.": (
        "No projection found in the photo: shoot closer and darken the background."
    ),
    "Запрос с телефона {client}, {stamp}": "Phone request from {client}, {stamp}",
    "{stamp} · {client} · проекция не найдена": "{stamp} · {client} · projection not found",
    "Не удалось прочитать фото: {error}": "Could not read the photo: {error}",
    "Ошибка поиска: {error}": "Search error: {error}",
    "В буфере обмена нет картинки или файла-изображения": "The clipboard has no picture or image file",
    "Сначала выберите папку библиотеки и постройте индекс": "First choose the library folder and build the index",
    # библиотека
    "Библиотека гобо": "Gobo library",
    "Текущая библиотека": "Current library",
    "не выбрана": "not chosen",
    "Индекс не построен": "Index not built",
    "Выбрать папку…": "Choose folder…",
    "Обновить индекс": "Update the index",
    "Отмена": "Cancel",
    "Папка библиотеки гобо": "Gobo library folder",
    "Индексация отменена": "Indexing cancelled",
    "Ошибка индексации: {error}": "Indexing error: {error}",
    "Индексация: {done} из {total}": "Indexing: {done} of {total}",
    "Понятно": "Got it",
    "Перейти в «Библиотека»": "Go to “Library”",
    "Добро пожаловать! Откройте экран «Библиотека» слева, чтобы выбрать папку гобо и построить индекс — после этого можно искать по фото (файл или буфер обмена) или подключить телефон на экране «Телефон».": (
        "Welcome! Open the “Library” screen on the left to choose the gobo folder and build the index. After that "
        "you can search by photo (file or clipboard) or connect a phone on the “Phone” screen."
    ),
    "{number} {files}, {number2} {families}": "{number} {files}, {number2} {families}",
    ", пропущено {number}": ", skipped {number}",
    ", нечитаемо сейчас {number} (повторю при обновлении)": ", unreadable for now {number} (will retry on update)",
    ". Библиотека изменилась — обновите индекс": ". The library has changed: update the index",
    # телефон и сервер
    "Сервер для телефона": "Phone server",
    "Выключен": "Off",
    "Копировать код": "Copy code",
    "Новый код": "New code",
    "Запросы с телефона": "Phone requests",
    "Параметры подключения": "Connection settings",
    "QR-код подключения": "Connection QR code",
    "Подключение телефона": "Phone connection",
    "Телефон и ПК должны быть в одной сети Wi-Fi. При первом запуске разрешите доступ в брандмауэре Windows.": (
        "The phone and the PC must be on the same Wi-Fi network. On the first launch allow access in the Windows firewall."
    ),
    "Не удалось запустить: {error}": "Could not start: {error}",
    "Работает на порту {port}, но адрес ПК в сети не найден: подключите ПК к Wi-Fi": (
        "Running on port {port}, but the PC address on the network was not found: connect the PC to Wi-Fi"
    ),
    "Работает: {host}:{port}": "Running: {host}:{port}",
    "Код: {format_code}": "Code: {format_code}",
    "Другие адреса ПК: ": "Other PC addresses: ",
    "Код скопирован": "Code copied",
    "порт {port} занят (проверено портов: {count}): {last_error}": "port {port} is busy (ports checked: {count}): {last_error}",
    # настройки
    "Крупный текст": "Large text",
    "Автозапуск при включении компьютера": "Start when the computer turns on",
    "Папка типов приборов grandMA3": "grandMA3 fixture types folder",
    "Папка типов приборов grandMA2 (importexport)": "grandMA2 fixture types folder (importexport)",
    "Число результатов поиска": "Number of search results",
    "по умолчанию: {found}": "default: {found}",
    "папка не найдена, укажите её": "folder not found, please specify it",
    "Экспорт настроек": "Export settings",
    "Экспорт…": "Export…",
    "Импорт настроек": "Import settings",
    "Импорт…": "Import…",
    "Проверить ядро": "Check the core",
    "Проверить": "Check",
    "Проверить сейчас": "Check now",
    "Диагностика": "Diagnostics",
    "Отправить лог по почте": "Send the log by email",
    "Настройки сохранены: {path}": "Settings saved: {path}",
    "Не удалось прочитать файл: {error}": "Could not read the file: {error}",
    "Настройки импортированы. Сервер для телефона и код доступа применятся после перезапуска приложения.": (
        "Settings imported. The phone server and access code will apply after the app is restarted."
    ),
    "Не удалось определить путь к приложению": "Could not determine the path to the app",
    "ОК: ядро работает": "OK: the core works",
    "ОШИБКА: ядро не сработало": "ERROR: the core failed",
    "Файл лога пока пуст: ошибок в этой сессии не было": "The log file is empty: there were no errors in this session",
    # поддержка автора
    "Поддержать автора": "Support the author",
    "Telegram автора": "Author's Telegram",
    "Канал GMAGC": "GMAGC channel",
    "Поддержать": "Support",
    "Позже": "Later",
    "Больше не показывать": "Do not show again",
    # обновления
    "Ошибка проверки обновлений: {error}": "Update check error: {error}",
    "Установлена последняя версия ({VERSION})": "The latest version is installed ({VERSION})",
    "Доступна версия {version} (у вас {VERSION})": "Version {version} is available (you have {VERSION})",
    "Что нового": "What's new",
    "Открыть страницу релиза": "Open the release page",
    "Скачивание…": "Downloading…",
    "Загрузка отменена.": "Download cancelled.",
    "Ошибка обновления: {error}.{fallback}": "Update error: {error}.{fallback}",
    " Можно скачать обновление вручную на странице релиза.": " You can download the update manually from the release page.",
    "Обновление скачано, приложение перезапускается…": "The update is downloaded, the app is restarting…",
    "Скачивание: {done} из {total} МБ": "Downloading: {done} of {total} MB",
    "Обновить": "Update",
    "Пропустить": "Skip",
    "Проверять обновления при запуске": "Check for updates on start",
    "Проверить обновления": "Check for updates",
    "Проверяю обновления…": "Checking for updates…",
    "Не удалось получить контрольную сумму: {error}": "Could not get the checksum: {error}",
    "Контрольная сумма в релизе повреждена: обновление не установлено": (
        "The checksum in the release is damaged: the update was not installed"
    ),
    "Файл обновления слишком большой": "The update file is too large",
    "Загрузка оборвалась: файл получен не полностью": "The download was interrupted: the file is incomplete",
    "Контрольная сумма не совпала: файл повреждён, обновление не установлено": (
        "The checksum does not match: the file is damaged, the update was not installed"
    ),
    "Не удалось скачать обновление: {error}": "Could not download the update: {error}",
    "Не удалось распаковать обновление: {error}": "Could not unpack the update: {error}",
    "Файл обновления повреждён: это не архив": "The update file is damaged: it is not an archive",
    "Архив обновления слишком велик после распаковки": "The update archive is too large after unpacking",
    "Архив обновления содержит небезопасный путь: установка отменена": (
        "The update archive contains an unsafe path: the installation was cancelled"
    ),
    "В архиве нет приложения GMAGC": "The archive does not contain the GMAGC app",
    "Обновление из приложения на этой платформе не поддерживается": (
        "Updating from inside the app is not supported on this platform"
    ),
    "Не удалось запустить установщик обновления: {error}": "Could not start the update installer: {error}",
    "В релизе нет контрольной суммы: обновление не установлено, скачайте его вручную": (
        "The release has no checksum: the update was not installed, download it manually"
    ),
    "Обновление из приложения недоступно": "Updating from inside the app is not available",
    "Для этой платформы в релизе нет готового файла: скачайте обновление на странице релиза.": (
        "The release has no ready file for this platform: download the update from the release page."
    ),
    "Приложение запущено не из собранной папки: обновите его вручную.": (
        "The app is not running from a built folder: update it manually."
    ),
    "В релизе нет контрольной суммы: обновление из приложения отключено, скачайте его вручную.": (
        "The release has no checksum: updating from inside the app is disabled, download it manually."
    ),
    "Нет прав на запись в папку приложения ({target}): скачайте обновление вручную.": (
        "No permission to write to the app folder ({target}): download the update manually."
    ),
    # ошибки службы
    "папка библиотеки не выбрана": "the library folder is not chosen",
    "выбранный файл не в папке библиотеки": "the chosen file is not in the library folder",
    "выбранный файл не входит в текущий индекс: обновите его и попробуйте снова": (
        "the chosen file is not in the current index: update it and try again"
    ),
    "индекс не построен": "the index is not built",
    "не удалось прочитать изображение": "could not read the image",
    "путь вне библиотеки: {rel_path}": "path outside the library: {rel_path}",
}

register("en", EN)
