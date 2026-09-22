"""Экран ПК-приложения: библиотека, индекс, поиск по фото, сервер для телефона."""

from __future__ import annotations

import os
import webbrowser
from collections.abc import Callable
from pathlib import Path

import flet as ft

from gmagc_common.protocol import build_link, format_code
from gmagc_desktop.about import AUTHOR, NAME, VERSION
from gmagc_desktop.library.index import IndexCancelled, LibraryNotFound, LibraryScanError
from gmagc_desktop.selfcheck import run_core_check
from gmagc_desktop.server.api import RequestRecord
from gmagc_desktop.server.network import lan_addresses
from gmagc_desktop.server.qr import qr_png
from gmagc_desktop.server.runner import PhoneServer, ServerStartError
from gmagc_desktop.service import autostart
from gmagc_desktop.service.results import Outcome, Result, SearchOutcome
from gmagc_desktop.service.reveal import reveal_in_file_manager
from gmagc_desktop.service.search_service import NoIndexError, PhotoError, SearchService
from gmagc_desktop.service.settings import data_dir
from gmagc_desktop.ui.support import SupportPrompt
from gmagc_desktop.ui.texts import history_text, outcome_message, score_text, source_text, status_text
from gmagc_desktop.ui.update_bar import UpdateBar
from gmagc_desktop.update.installer import current_executable
from gmagc_desktop.update.manager import UpdateManager

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
NO_LIBRARY_HINT = "Сначала выберите папку библиотеки и постройте индекс"
PHONE_HINT = "Телефон и ПК должны быть в одной сети Wi-Fi. При первом запуске разрешите доступ в брандмауэре Windows."
ONBOARDING_HINT = (
    "Добро пожаловать! Сначала выберите папку библиотеки гобо и постройте индекс — после этого можно искать "
    "по фото (файл или буфер обмена) или подключить телефон по Wi-Fi (код и QR — в блоке «Телефон»)."
)
HISTORY_LIMIT = 10


def _theme(large_text: bool) -> ft.Theme:
    """Обычная тема или увеличенная (крупнее шрифт по умолчанию и просторнее элементы) — для тёмных залов.

    Затрагивает текст без явно заданного размера (многие подписи в этом приложении задают свой размер
    напрямую и увеличенным текстом не становятся крупнее)."""
    if not large_text:
        return ft.Theme(use_material3=True)
    return ft.Theme(
        use_material3=True,
        visual_density=ft.VisualDensity.COMFORTABLE,
        text_theme=ft.TextTheme(
            body_small=ft.TextStyle(size=14),
            body_medium=ft.TextStyle(size=16),
            body_large=ft.TextStyle(size=18),
            label_small=ft.TextStyle(size=14),
            label_medium=ft.TextStyle(size=16),
            label_large=ft.TextStyle(size=18),
            title_small=ft.TextStyle(size=16),
            title_medium=ft.TextStyle(size=20),
            title_large=ft.TextStyle(size=26),
        ),
    )


class DesktopApp:
    def __init__(
        self,
        page: ft.Page,
        service: SearchService,
        picker=None,
        clipboard=None,
        reveal: Callable[[str], bool] = reveal_in_file_manager,
        check: Callable[[], dict] = run_core_check,
        server=None,
        addresses: Callable[[], list[str]] = lan_addresses,
        qr: Callable[[str], bytes] = qr_png,
        updates=None,
        open_url: Callable[[str], object] = webbrowser.open,
        quit_app: Callable[[], None] | None = None,
        update_delay: float = 5.0,
        support: bool = True,
        support_delay: float = 8.0,
    ):
        self.page = page
        self.service = service
        self.picker = picker or ft.FilePicker()
        self.clipboard = clipboard or ft.Clipboard()
        self.reveal = reveal
        self.check = check
        self.server = server or PhoneServer(service)
        self.server.on_request = self.on_phone_request
        self.addresses = addresses
        self.qr = qr
        self.support = (
            SupportPrompt(page, service, open_url=open_url, delay=support_delay, busy=lambda: self._busy)
            if support
            else None
        )
        self.update_bar = (
            UpdateBar(page, service, updates, open_url=open_url, quit_app=quit_app, delay=update_delay)
            if updates is not None
            else None
        )
        self.history: list[RequestRecord] = []
        self._busy = False
        self._cancel = False

        self.onboarding_text = ft.Text(ONBOARDING_HINT, size=13)
        self.onboarding_dismiss_button = ft.TextButton(
            content=ft.Text("Понятно", size=12), on_click=self.on_dismiss_onboarding
        )
        self.onboarding_hint = ft.Container(
            ft.Column([self.onboarding_text, self.onboarding_dismiss_button], spacing=2),
            padding=10,
            border_radius=6,
            bgcolor=ft.Colors.BLUE_50,
            visible=False,
        )
        self.library_text = ft.Text("не выбрана", selectable=True)
        self.status_label = ft.Text("Индекс не построен")
        self.progress = ft.ProgressBar(value=0, visible=False)
        self.progress_label = ft.Text(visible=False)
        self.choose_folder_button = ft.Button("Выбрать папку…", on_click=self.on_choose_folder)
        self.rebuild_button = ft.Button("Обновить индекс", on_click=self.on_rebuild)
        self.cancel_button = ft.Button("Отмена", on_click=self.on_cancel, visible=False)
        self.pick_photo_button = ft.Button("Выбрать фото…", on_click=self.on_pick_photo)
        self.paste_button = ft.Button("Вставить из буфера", on_click=self.on_paste)
        self.banner_text = ft.Text(color=ft.Colors.BLACK)
        self.banner = ft.Container(self.banner_text, padding=10, border_radius=6, visible=False)
        self.source_label = ft.Text("", visible=False)
        self.photo_holder = ft.Column(visible=False, spacing=4)
        self.projection_holder = ft.Column(visible=False, spacing=4)
        self.results_column = ft.Column(spacing=8)
        self.copy_label = ft.Text("", size=12, visible=False, selectable=True)
        self.check_label = ft.Text("")
        self.export_settings_button = ft.TextButton(
            content=ft.Text("Экспорт настроек", size=12), on_click=self.on_export_settings
        )
        self.import_settings_button = ft.TextButton(
            content=ft.Text("Импорт настроек", size=12), on_click=self.on_import_settings
        )
        self.dark_theme_switch = ft.Switch(label="Тёмная тема", value=False, on_change=self.on_toggle_dark_theme)
        self.large_text_switch = ft.Switch(label="Крупный текст", value=False, on_change=self.on_toggle_large_text)

        self.server_switch = ft.Switch(label="Сервер для телефона", value=False, on_change=self.on_toggle_server)
        self.autostart_switch = ft.Switch(
            label="Автозапуск при включении компьютера", value=False, on_change=self.on_toggle_autostart
        )
        self.server_status = ft.Text("Выключен")
        self.qr_holder = ft.Column(visible=False)
        self.code_text = ft.Text("", size=16, weight=ft.FontWeight.BOLD, selectable=True, visible=False)
        self.code_row = ft.Row(
            [
                ft.TextButton(content=ft.Text("Копировать код"), on_click=self.on_copy_code),
                ft.TextButton(content=ft.Text("Новый код"), on_click=self.on_new_code),
            ],
            spacing=4,
            visible=False,
        )
        self.phone_note = ft.Text("", size=12, visible=False)
        self.addresses_text = ft.Text("", size=12, visible=False, selectable=True)
        self.history_title = ft.Text("Запросы с телефона", size=14, weight=ft.FontWeight.BOLD, visible=False)
        self.history_column = ft.Column(spacing=0)

    # ---- построение экрана -------------------------------------------------
    def build(self) -> None:
        status = self.service.load()
        self.library_text.value = self.service.settings.library_dir or "не выбрана"
        self.onboarding_hint.visible = not self.service.settings.library_dir
        self.status_label.value = status_text(status)
        if self.update_bar is not None:
            self.update_bar.switch.value = self.service.settings.check_updates
        self.dark_theme_switch.value = self.service.settings.dark_theme
        self.large_text_switch.value = self.service.settings.large_text
        self._apply_theme()
        if autostart.is_supported():
            self.autostart_switch.value = autostart.is_autostart_enabled()
        self.page.services.extend([self.picker, self.clipboard])
        self.page.on_keyboard_event = self.on_key
        if self.service.settings.server_enabled:
            self.server_switch.value = True
            self._start_server()

        left = ft.Column(
            [
                self.onboarding_hint,
                ft.Text("Библиотека", size=18, weight=ft.FontWeight.BOLD),
                self.library_text,
                self.choose_folder_button,
                self.rebuild_button,
                self.status_label,
                self.progress,
                self.progress_label,
                self.cancel_button,
                ft.Divider(),
                ft.Text("Телефон", size=18, weight=ft.FontWeight.BOLD),
                self.server_switch,
                self.server_status,
                self.qr_holder,
                self.code_text,
                self.code_row,
                self.phone_note,
                self.addresses_text,
                ft.Text(PHONE_HINT, size=12),
                *([self.autostart_switch] if autostart.is_supported() else []),
                self.history_title,
                self.history_column,
                *([self.update_bar.switch] if self.update_bar else []),
                ft.Divider(),
                ft.Text("Вид", size=18, weight=ft.FontWeight.BOLD),
                self.dark_theme_switch,
                self.large_text_switch,
            ],
            spacing=8,
            width=320,
            scroll=ft.ScrollMode.AUTO,
        )
        right = ft.Column(
            [
                ft.Row([self.pick_photo_button, self.paste_button], spacing=8),
                self.source_label,
                self.banner,
                ft.Row(
                    [self.photo_holder, self.projection_holder],
                    spacing=16,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                ft.Text("Результаты", size=18, weight=ft.FontWeight.BOLD),
                self.copy_label,
                self.results_column,
            ],
            spacing=10,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        )
        footer = ft.Row(
            [
                ft.Text(f"{NAME} {VERSION} · Автор: {AUTHOR}", size=12),
                ft.TextButton(content=ft.Text("Проверить ядро", size=12), on_click=self.on_check),
                self.check_label,
                self.export_settings_button,
                self.import_settings_button,
                *([self.update_bar.check_button, self.update_bar.status] if self.update_bar else []),
                *([self.support.link, self.support.telegram_link, self.support.channel_link] if self.support else []),
            ],
            spacing=12,
            wrap=True,  # длинный текст (проверка ядра, статус обновления) переносится, а не прячет остальное за краем
        )
        self.page.add(
            ft.SafeArea(
                ft.Column(
                    [
                        *([self.update_bar.container] if self.update_bar else []),
                        ft.Row(
                            [left, ft.VerticalDivider(), right],
                            expand=True,
                            vertical_alignment=ft.CrossAxisAlignment.START,
                        ),
                        footer,
                    ],
                    expand=True,
                ),
                expand=True,
            )
        )
        if self.update_bar is not None:
            self.update_bar.start()
        if self.support is not None:
            self.support.start()
        demo_photo = os.environ.get("GMAGC_DEMO_PHOTO")
        if demo_photo:
            self.page.run_thread(lambda: self._run_demo(os.environ.get("GMAGC_DEMO_LIBRARY", ""), demo_photo))

    # ---- состояние ---------------------------------------------------------
    def _set_busy(self, busy: bool, *, indexing: bool = False) -> None:
        self._busy = busy
        for button in (self.choose_folder_button, self.rebuild_button, self.pick_photo_button, self.paste_button):
            button.disabled = busy
        self.progress.visible = busy and indexing
        self.progress_label.visible = busy and indexing
        self.cancel_button.visible = busy and indexing
        if not busy or not indexing:
            self.progress.value = 0
        self.page.update()

    def _show_banner(self, text: str, *, error: bool) -> None:
        self.banner_text.value = text
        self.banner.bgcolor = ft.Colors.RED_100 if error else ft.Colors.AMBER_100
        self.banner.visible = True
        self.page.update()

    def _hide_banner(self) -> None:
        self.banner.visible = False

    # ---- сервер для телефона -----------------------------------------------
    def _start_server(self) -> None:
        try:
            self.server.start(self.service.settings.port)
        except ServerStartError as error:
            self._show_server(error=str(error))
        else:
            self._show_server()

    def _show_server(self, error: str | None = None) -> None:
        """Отражает состояние сервера в блоке «Телефон» (экран обновляет вызывающий)."""
        running = self.server.running and error is None
        addresses = self.addresses() if running else []
        for control in (self.qr_holder, self.code_text, self.code_row, self.addresses_text, self.phone_note):
            control.visible = False
        if error:
            self.server_status.value = f"Не удалось запустить: {error}"
        elif not running:
            self.server_status.value = "Выключен"
        elif not addresses:
            self.server_status.value = (
                f"Работает на порту {self.server.port}, но адрес ПК в сети не найден: подключите ПК к Wi-Fi"
            )
        else:
            host, port = addresses[0], self.server.port
            code = self.service.ensure_access_code()
            self.server_status.value = f"Работает: {host}:{port}"
            self.qr_holder.controls = [
                ft.Image(src=self.qr(build_link(host, port, code)), width=240, height=240, fit=ft.BoxFit.CONTAIN)
            ]
            self.code_text.value = f"Код: {format_code(code)}"
            self.addresses_text.value = "Другие адреса ПК: " + ", ".join(addresses[1:])
            self.qr_holder.visible = self.code_text.visible = self.code_row.visible = True
            self.addresses_text.visible = len(addresses) > 1

    def on_toggle_server(self, _event) -> None:
        enabled = bool(self.server_switch.value)
        self.service.set_server_enabled(enabled)
        if enabled:
            self._start_server()
        else:
            self.server.stop()
            self._show_server()
        self.page.update()

    async def on_copy_code(self, _event) -> None:
        await self.clipboard.set(format_code(self.service.ensure_access_code()))
        self.phone_note.value = "Код скопирован"
        self.phone_note.visible = True
        self.page.update()

    def on_new_code(self, _event) -> None:
        self.service.reset_access_code()
        self._show_server()
        self.page.update()

    def on_phone_request(self, record: RequestRecord) -> None:
        """Вызывается из потока сервера: запись в историю и показ результата в основном окне."""
        self.history.insert(0, record)
        del self.history[HISTORY_LIMIT:]
        self.history_column.controls = [self._history_row(item) for item in self.history]
        self.history_title.visible = True
        self._show_record(record)

    def _history_row(self, record: RequestRecord) -> ft.TextButton:
        return ft.TextButton(
            content=ft.Text(history_text(record.time, record.client, record.outcome), size=12),
            data=record,
            on_click=self.on_history_click,
        )

    def on_history_click(self, event) -> None:
        self._show_record(event.control.data)

    def _show_record(self, record: RequestRecord) -> None:
        self._hide_banner()
        self.source_label.value = source_text(record.time, record.client)
        self.source_label.visible = True
        self._show_photo(record.photo)
        self._show_outcome(record.outcome)

    def on_dismiss_onboarding(self, _event) -> None:
        self.onboarding_hint.visible = False
        self.page.update()

    # ---- индексация --------------------------------------------------------
    async def on_choose_folder(self, _event) -> None:
        folder = await self.picker.get_directory_path(dialog_title="Папка библиотеки гобо")
        if not folder:
            return
        self.service.set_library(folder)
        self.library_text.value = folder
        self.onboarding_hint.visible = False
        self.status_label.value = status_text(self.service.status())
        self._start_index()

    async def on_rebuild(self, _event) -> None:
        self._start_index()

    def on_cancel(self, _event) -> None:
        self._cancel = True

    def _start_index(self) -> None:
        if self._busy:
            return
        if not self.service.settings.library_dir:
            self._show_banner(NO_LIBRARY_HINT, error=True)
            return
        self._cancel = False
        self._hide_banner()
        self._set_busy(True, indexing=True)
        self.page.run_thread(self._index_worker)

    def _index_worker(self) -> None:
        try:
            self.service.build_index(progress=self._on_progress, cancel=lambda: self._cancel)
        except IndexCancelled:
            self._show_banner("Индексация отменена", error=False)
        except (LibraryNotFound, LibraryScanError) as error:
            self._show_banner(str(error), error=True)
        except Exception as error:  # noqa: BLE001 - рабочий поток обязан показать причину, а не пропасть
            self._show_banner(f"Ошибка индексации: {error}", error=True)
        finally:
            self.status_label.value = status_text(self.service.status())
            self._set_busy(False)

    def _on_progress(self, done: int, total: int) -> None:
        self.progress.value = done / total if total else 0
        self.progress_label.value = f"Индексация: {done} из {total}"
        self.page.update()

    # ---- поиск -------------------------------------------------------------
    async def on_pick_photo(self, _event) -> None:
        files = await self.picker.pick_files(dialog_title="Фото проекции", file_type=ft.FilePickerFileType.IMAGE)
        if files and files[0].path:
            self._search_bytes_from(Path(files[0].path))

    def _apply_theme(self) -> None:
        theme = _theme(self.service.settings.large_text)
        self.page.theme = theme
        self.page.dark_theme = theme
        self.page.theme_mode = ft.ThemeMode.DARK if self.service.settings.dark_theme else ft.ThemeMode.LIGHT
        self.page.update()

    def on_toggle_dark_theme(self, _event) -> None:
        self.service.set_dark_theme(bool(self.dark_theme_switch.value))
        self._apply_theme()

    def on_toggle_large_text(self, _event) -> None:
        self.service.set_large_text(bool(self.large_text_switch.value))
        self._apply_theme()

    def on_toggle_autostart(self, _event) -> None:
        exe = current_executable()
        if exe is None:
            self.autostart_switch.value = False
            self._show_banner("Не удалось определить путь к приложению", error=True)
            return
        autostart.set_autostart(bool(self.autostart_switch.value), exe)

    async def on_key(self, event) -> None:
        """Ctrl+V — вставить фото из буфера, F5 — обновить индекс: горячие клавиши для частой работы."""
        if event.ctrl and event.key == "V":
            await self.on_paste(None)
        elif event.key == "F5":
            await self.on_rebuild(None)

    async def on_export_settings(self, _event) -> None:
        data = self.service.export_settings_json().encode("utf-8")
        path = await self.picker.save_file(
            dialog_title="Экспорт настроек", file_name="gmagc-settings.json", allowed_extensions=["json"], src_bytes=data
        )
        if path:
            self._show_banner(f"Настройки сохранены: {path}", error=False)

    async def on_import_settings(self, _event) -> None:
        files = await self.picker.pick_files(dialog_title="Импорт настроек", allowed_extensions=["json"])
        if not files:
            return
        try:
            raw = files[0].bytes if files[0].bytes else Path(files[0].path).read_bytes()
            text = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError) as error:
            self._show_banner(f"Не удалось прочитать файл: {error}", error=True)
            return
        self.service.import_settings_json(text)
        status = self.service.load()
        self.library_text.value = self.service.settings.library_dir or "не выбрана"
        self.onboarding_hint.visible = not self.service.settings.library_dir
        self.status_label.value = status_text(status)
        if self.update_bar is not None:
            self.update_bar.switch.value = self.service.settings.check_updates
        self._show_banner(
            "Настройки импортированы. Сервер для телефона и код доступа применятся после перезапуска приложения.",
            error=False,
        )

    async def on_paste(self, _event) -> None:
        data = await self.clipboard.get_image()
        if data:
            self._start_search(data)
            return
        for name in await self.clipboard.get_files():
            if Path(name).suffix.lower() in IMAGE_SUFFIXES:
                self._search_bytes_from(Path(name))
                return
        self._show_banner("В буфере обмена нет картинки или файла-изображения", error=True)

    def _search_bytes_from(self, path: Path) -> None:
        try:
            data = path.read_bytes()
        except OSError as error:
            self._show_banner(f"Не удалось прочитать файл: {error}", error=True)
            return
        self._start_search(data)

    def _start_search(self, data: bytes) -> None:
        if self._busy:
            return
        if self.service.status() is None:
            self._show_banner(NO_LIBRARY_HINT, error=True)
            return
        self._hide_banner()
        self.source_label.visible = False
        self._show_photo(data)
        self._set_busy(True)
        self.page.run_thread(lambda: self._search_worker(data))

    def _search_worker(self, data: bytes) -> None:
        try:
            outcome = self.service.search_image_bytes(data)
        except NoIndexError:
            self._show_banner(NO_LIBRARY_HINT, error=True)
        except PhotoError as error:
            self._show_banner(f"Не удалось прочитать фото: {error}", error=True)
        except Exception as error:  # noqa: BLE001 - рабочий поток обязан показать причину, а не пропасть
            self._show_banner(f"Ошибка поиска: {error}", error=True)
        else:
            self._show_outcome(outcome)
        finally:
            self._set_busy(False)

    def _show_photo(self, data: bytes) -> None:
        self.photo_holder.controls = [
            ft.Text("Фото"),
            ft.Image(src=data, width=260, height=200, fit=ft.BoxFit.CONTAIN),
        ]
        self.photo_holder.visible = True
        self.projection_holder.visible = False
        self.results_column.controls = []
        self.copy_label.visible = False
        self.page.update()

    def _show_outcome(self, outcome: SearchOutcome) -> None:
        message = outcome_message(outcome.kind)
        if message:
            self._show_banner(message, error=outcome.kind is Outcome.NO_PROJECTION)
        if outcome.projection_png:
            self.projection_holder.controls = [
                ft.Text("Найденная проекция"),
                ft.Image(src=outcome.projection_png, width=160, height=160, fit=ft.BoxFit.CONTAIN),
            ]
        self.projection_holder.visible = bool(outcome.projection_png)
        self.results_column.controls = [self._result_card(result) for result in outcome.results]
        self.page.update()

    def _result_card(self, result: Result) -> ft.Card:
        details: list[ft.Control] = [
            ft.Text(result.name, weight=ft.FontWeight.BOLD),
            ft.Text(result.full_path, size=12),
            ft.Text(score_text(result.score)),
        ]
        if result.copies:
            details.append(ft.Text(f"ещё {len(result.copies)} файлов", tooltip="\n".join(result.copies)))
        return ft.Card(
            ft.Container(
                ft.Row(
                    [
                        ft.Image(src=result.thumbnail_png, width=96, height=96, fit=ft.BoxFit.CONTAIN),
                        ft.Column(details, spacing=2, expand=True),
                        ft.IconButton(
                            icon=ft.Icons.FOLDER_OPEN,
                            tooltip="Показать в папке",
                            on_click=lambda _event, path=result.full_path: self.reveal(path),
                        ),
                    ],
                    spacing=12,
                ),
                padding=10,
                ink=True,
                data=result.full_path,
                tooltip="Нажмите, чтобы скопировать путь к файлу",
                on_click=self.on_card_click,
            )
        )

    async def on_card_click(self, event) -> None:
        await self.copy_path(event.control.data)

    async def copy_path(self, path: str) -> None:
        """Копирует абсолютный путь файла (вместе с именем) в буфер обмена."""
        absolute = os.path.abspath(path)
        await self.clipboard.set(absolute)
        self.copy_label.value = f"Путь скопирован: {absolute}"
        self.copy_label.visible = True
        self.page.update()

    # ---- прочее ------------------------------------------------------------
    def on_check(self, _event) -> None:
        info = self.check()
        head = "ОК: ядро работает" if info["ok"] else "ОШИБКА: ядро не сработало"
        self.check_label.value = head + ", " + ", ".join(f"{name}: {value}" for name, value in info["versions"].items())
        self.page.update()

    def _run_demo(self, library: str, photo: str) -> None:
        """Отладка: GMAGC_DEMO_LIBRARY / GMAGC_DEMO_PHOTO запускают индексацию и поиск при старте."""
        self._set_busy(True, indexing=True)
        if library:
            self.service.set_library(library)
            self.library_text.value = library
        self._index_worker()
        self._set_busy(True)
        data = Path(photo).read_bytes()
        self._show_photo(data)
        self._search_worker(data)


def build_page(page: ft.Page, service: SearchService | None = None, **services) -> DesktopApp:
    page.title = f"{NAME} {VERSION}"
    window = getattr(page, "window", None)
    if window is not None:
        window.width, window.height = 1100, 760
    service = service or SearchService(data_dir())
    if "updates" not in services:  # updates=None в тестах отключает обновления
        services["updates"] = UpdateManager(service, data_dir())
    app = DesktopApp(page, service, **services)
    app.build()
    return app
