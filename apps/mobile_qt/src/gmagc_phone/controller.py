"""Логика телефона без виджетов: подключение к ПК, поиск по снимку, история сессии, переходы между экранами.

Экраны только показывают состояние и вызывают методы контроллера; сеть идёт в фоне через подменяемый исполнитель
(в тестах — синхронный), результат возвращается сигналами Qt."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

from gmagc_common import i18n
from gmagc_common.i18n import t
from gmagc_common.phone_client import UNAUTHORIZED, UNREACHABLE, ClientError, GmagcClient
from gmagc_common.phone_texts import error_text, no_index_note, share_text
from gmagc_common.protocol import Connection, MatchResponse, is_valid_code, normalize_code, parse_address
from gmagc_phone.settings import PhoneSettings
from gmagc_phone.tasks import Executor, PoolExecutor

MODE_SHOOT = "shoot"
MODE_SCAN = "scan"
HISTORY_LIMIT = 10  # снимков за сессию, самый новый первым; дальше старые записи забываются

VIEWS = ("connect", "camera", "results", "gallery", "settings", "about", "help", "profiles")


class PhoneController(QObject):
    screen_requested = Signal(str)
    mode_changed = Signal(str)
    connect_error = Signal(str)  # текст ошибки на экране подключения; пусто — убрать
    connect_prefill = Signal(str, str)  # адрес и код: подставить в поля
    camera_note = Signal(str)  # сообщение поверх камеры; пусто — убрать
    retry_changed = Signal(bool)
    connectivity_changed = Signal(bool)
    busy_changed = Signal(bool)
    history_changed = Signal()
    results_shown = Signal(bytes, object)  # снимок и MatchResponse
    toast = Signal(str)  # короткое сообщение внизу («Подключено к ПК: …»)
    copied = Signal(str)
    diag_changed = Signal(str)  # «Последняя ошибка»: техническая строка для диагностики
    language_changed = Signal(str)

    def __init__(
        self,
        settings: PhoneSettings,
        client_factory: Callable[[Connection], GmagcClient] = GmagcClient,
        executor: Executor | None = None,
        copy_text: Callable[[str], None] | None = None,
    ):
        super().__init__()
        self.settings = settings
        self.client_factory = client_factory
        self.executor: Executor = executor or PoolExecutor()
        self._copy_text = copy_text or (lambda text: None)
        self.connection: Connection | None = None
        self.client: GmagcClient | None = None
        self.mode = MODE_SHOOT
        self.view = "connect"
        self.return_view = "connect"  # куда вернуться со вложенного экрана
        self.busy = False
        self.last_error = ""
        self.history: list[tuple[bytes, MatchResponse]] = []
        self.current_response: MatchResponse | None = None
        self._retry_data: bytes | None = None

    # ---- переходы -----------------------------------------------------------------
    def show(self, name: str) -> None:
        self.view = name
        self.screen_requested.emit(name)

    def open_overlay(self, name: str) -> None:
        """Галерея, настройки, «О программе», помощь, профили: «назад» вернёт туда, откуда открыли."""
        self.return_view = "camera" if self.view == "camera" else "connect"
        self.show(name)

    def close_overlay(self) -> None:
        self.show(self.return_view)

    def set_mode(self, mode: str, note: str | None = None) -> None:
        self.mode = mode
        self.mode_changed.emit(mode)
        self.camera_note.emit(note or "")

    def show_camera(self, mode: str = MODE_SHOOT, note: str | None = None) -> None:
        self.set_mode(mode, note)
        self.connectivity_changed.emit(self.connection is not None)
        self.show("camera")

    # ---- диагностика ----------------------------------------------------------------
    def remember(self, text: str) -> None:
        self.last_error = text
        self.diag_changed.emit(t("Последняя ошибка: {text}", text=text))

    def clear_diag(self) -> None:
        self.last_error = ""
        self.diag_changed.emit("")

    def note(self, text: str) -> None:
        """Сообщение поверх камеры и в строку диагностики."""
        self.camera_note.emit(text)
        self.remember(text)

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.busy_changed.emit(busy)

    # ---- подключение ------------------------------------------------------------------
    def start(self) -> None:
        """Запуск: сохранённое подключение проверяется и открывает камеру, иначе — экран подключения."""
        stored = self.settings.load_connection()
        if stored is None:
            self.show_connect()
            return
        self.connect_prefill.emit(f"{stored.host}:{stored.port}", stored.code)
        self.connect_to(stored)

    def show_connect(self, error: str | None = None) -> None:
        self.connect_error.emit(error or "")
        if error:
            self.remember(error)
        self.show("connect")

    def connect(self, address_text: str, code_text: str) -> None:
        """Подключение по введённым вручную адресу и коду."""
        if self.busy:
            return
        address = parse_address(address_text or "")
        if address is None:
            self.show_connect(t("Введите адрес ПК, например 192.168.1.5 или 192.168.1.5:8765"))
            return
        if not is_valid_code(code_text or ""):
            self.show_connect(t("Код доступа состоит из 8 символов (буквы и цифры), он показан в приложении на ПК"))
            return
        self.connect_to(Connection(address[0], address[1], normalize_code(code_text)))

    def connect_to(self, connection: Connection, announce: bool = False) -> None:
        self.set_busy(True)
        client = self.client_factory(connection)

        def work() -> None:
            try:
                _, status = client.verify()
            except ClientError as error:
                self._connect_failed(error_text(error))
                return
            except Exception as error:  # noqa: BLE001 - подключение обязано показать причину
                self._connect_failed(t("Ошибка подключения: {error}", error=error))
                return
            self.connection, self.client = connection, client
            self.settings.save_connection(connection)
            self.connect_prefill.emit(f"{connection.host}:{connection.port}", connection.code)
            self.clear_diag()
            self.set_busy(False)
            self.show_camera(MODE_SHOOT, note=None if status.indexed else no_index_note())
            if announce:  # по QR подключение идёт без ручного ввода: коротко подтвердить, что оно удалось
                self.toast.emit(t("Подключено к ПК: {host}:{port}", host=connection.host, port=connection.port))

        self.executor.submit(work)

    def _connect_failed(self, message: str) -> None:
        self.set_busy(False)
        self.show_connect(message)

    def change_pc(self) -> None:
        self.settings.clear_connection()
        self.connection = self.client = None
        self.show_connect()

    # ---- поиск -----------------------------------------------------------------------------
    def search(self, data: bytes) -> None:
        """Отправляет снимок на ПК и показывает результат или ошибку."""
        if self.client is None:
            self.show_connect(t("Сначала подключитесь к ПК"))
            return
        self.set_busy(True)
        self.retry_changed.emit(False)
        client = self.client

        def work() -> None:
            response: MatchResponse | None = None
            failure: ClientError | None = None
            message = ""
            try:
                response = client.match(data)
            except ClientError as error:
                failure = error
            except Exception as error:  # noqa: BLE001
                message = t("Ошибка: {error}", error=error)
            self._search_done(data, response, failure, message)

        self.executor.submit(work)

    def _search_done(
        self, data: bytes, response: MatchResponse | None, failure: ClientError | None, message: str
    ) -> None:
        self.set_busy(False)
        if failure is not None:
            self.connectivity_changed.emit(failure.kind != UNREACHABLE)
            if failure.kind == UNAUTHORIZED:
                self.show_connect(error_text(failure))
            else:
                self.offer_retry(data, error_text(failure))
            return
        if response is None:
            self.connectivity_changed.emit(False)  # локальная ошибка — тоже похоже на обрыв связи
            self.offer_retry(data, message or t("Ошибка поиска"))
            return
        self.connectivity_changed.emit(True)
        self._retry_data = None
        self.remember_history(data, response)
        # пока ждали ответ, могли уйти с камеры: снимок попадёт в историю, но экран самопроизвольно не переключаем
        if self.view == "camera" and self.mode == MODE_SHOOT:
            self.show_results(data, response)

    def offer_retry(self, data: bytes, message: str) -> None:
        """Запоминает неотправленное фото и предлагает отправить его ещё раз без повторной съёмки."""
        self._retry_data = data
        self.retry_changed.emit(True)
        self.note(message)

    def retry(self) -> None:
        if self.busy or self._retry_data is None:
            return
        self.search(self._retry_data)

    def remember_history(self, photo: bytes, response: MatchResponse) -> None:
        self.history.insert(0, (photo, response))
        del self.history[HISTORY_LIMIT:]
        self.history_changed.emit()

    def show_results(self, photo: bytes, response: MatchResponse) -> None:
        self.current_response = response
        self.results_shown.emit(photo, response)
        self.show("results")

    def open_history(self, index: int) -> None:
        """Открывает прошлый результат заново, не отправляя фото на ПК повторно."""
        if 0 <= index < len(self.history):
            photo, response = self.history[index]
            self.show_results(photo, response)

    # ---- результаты ---------------------------------------------------------------------------
    def copy_path(self, path: str) -> None:
        """Копирует путь файла на ПК (как пришёл в ответе, вместе с именем файла) в буфер обмена."""
        self._copy_text(path)
        self.copied.emit(path)

    def result_share_text(self) -> str | None:
        return share_text(self.current_response) if self.current_response is not None else None

    # ---- язык -------------------------------------------------------------------------------------
    def set_language(self, choice: str) -> None:
        """Выбор языка: сохраняется и применяется сразу, окно собирается заново на новом языке."""
        self.settings.save_language(choice)
        i18n.set_language(choice)
        self.language_changed.emit(choice)
