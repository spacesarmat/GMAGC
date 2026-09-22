"""Экран Android-приложения: подключение к ПК, камера с приближением и фокусом, результаты поиска."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable
from pathlib import Path

import flet as ft
import flet_camera as fc
import flet_permission_handler as ph

from gmagc_common.protocol import (
    OUTCOME_NO_PROJECTION,
    Connection,
    MatchResponse,
    ResultItem,
    is_valid_code,
    normalize_code,
    parse_address,
    parse_link,
)
from gmagc_mobile.about import AUTHOR, NAME, VERSION
from gmagc_mobile.camera import CameraController
from gmagc_mobile.client import UNAUTHORIZED, ClientError, GmagcClient
from gmagc_mobile.imaging import prepare_upload
from gmagc_mobile.qr import QrImageError, QrUnavailable, connection_from_qr, diagnose
from gmagc_mobile.store import ConnectionStore
from gmagc_mobile.support import SupportPrompt
from gmagc_mobile.texts import NO_INDEX_NOTE, error_text, outcome_message, score_text, status_line, zoom_text
from gmagc_mobile.update_bar import UpdateBar
from gmagc_mobile.updates import UpdateTracker

MODE_SHOOT = "shoot"
MODE_SCAN = "scan"
ZOOM_STEP = 0.5
MARKER_SIZE = 64
PAGE_PADDING = 12  # общий отступ страницы; кадр камеры вычитает его отрицательным полем, чтобы быть во всю ширину
SCAN_HINT = (
    "Наведите камеру на QR-код в приложении на ПК (приближение и касание для фокуса помогают) "
    "и нажмите «Считать QR»"
)


class MobileApp:
    def __init__(
        self,
        page: ft.Page,
        store: ConnectionStore,
        camera: CameraController,
        preview: ft.Control | None = None,
        picker=None,
        clipboard=None,
        client_factory: Callable[[Connection], GmagcClient] = GmagcClient,
        qr_reader: Callable[[bytes], Connection | None] = connection_from_qr,
        qr_diagnose: Callable[[bytes], str] = diagnose,
        marker_seconds: float = 1.5,
        mount_seconds: float = 0.3,
        clock: Callable[[], float] = time.monotonic,
        back_seconds: float = 2.5,
        hint_seconds: float | None = None,
        tracker=None,
        launcher=None,
        check_on_start: bool = True,
        update_delay: float = 3.0,
        support: bool = False,
        support_delay: float = 8.0,
        prefs=None,
    ):
        self.page = page
        self.store = store
        self.camera = camera
        self.preview = preview if preview is not None else camera.camera
        self.picker = picker or ft.FilePicker()
        self.clipboard = clipboard or ft.Clipboard()
        self.client_factory = client_factory
        self.qr_reader = qr_reader
        self.qr_diagnose = qr_diagnose
        self.marker_seconds = marker_seconds
        self.mount_seconds = mount_seconds  # пауза, чтобы виджет камеры успел появиться на экране до запуска камеры
        self._clock = clock
        self.back_seconds = back_seconds  # окно второго нажатия «Назад» для выхода из приложения
        self.hint_seconds = back_seconds if hint_seconds is None else hint_seconds  # сколько висит подсказка о выходе
        self._last_back = -1e9
        self._hint_token = 0
        self.launcher = launcher
        self.check_on_start = check_on_start
        self.update_task: asyncio.Task | None = None
        self.update_bar = UpdateBar(tracker, launcher, page, delay=update_delay) if tracker is not None else None
        self.support_task: asyncio.Task | None = None
        self.support = (
            SupportPrompt(prefs, launcher, page, delay=support_delay, busy=lambda: self._busy)
            if support and prefs is not None and launcher is not None
            else None
        )
        self.connection: Connection | None = None
        self.client: GmagcClient | None = None
        self.mode = MODE_SHOOT
        self.status_text = ""
        self.last_error = ""
        self._busy = False
        self._preview_size = (0.0, 0.0)
        self._pinch_start = 1.0
        self._zooming = False
        self._marker_token = 0

        # подключение
        self.address_field = ft.TextField(label="Адрес ПК", hint_text="192.168.1.5 или 192.168.1.5:8765")
        self.code_field = ft.TextField(
            label="Код доступа",
            hint_text="ABCD-2345",
            capitalization=ft.TextCapitalization.CHARACTERS,
            max_length=9,
            on_submit=self.on_connect,
        )
        self.scan_button = ft.Button("Считать QR-код с ПК", on_click=self.on_scan_qr)
        self.connect_button = ft.Button("Подключиться", on_click=self.on_connect)
        self.connect_busy = ft.ProgressRing(visible=False, width=24, height=24)
        self.connect_error = ft.Text("", color=ft.Colors.RED_700, visible=False, selectable=True)
        self.connect_view = ft.Column(
            [
                ft.Text(NAME, size=28, weight=ft.FontWeight.BOLD),
                ft.Text("Поиск гобо по фото проекции. Подключитесь к ПК с GMAGC в той же сети Wi-Fi."),
                self.scan_button,
                ft.Text("или введите вручную (адрес и код показаны в приложении на ПК):", size=12),
                self.address_field,
                self.code_field,
                ft.Row([self.connect_button, self.connect_busy], spacing=12),
                self.connect_error,
                *self._update_controls(),
                *([ft.Row([self.support.link, self.support.telegram_link], wrap=True)] if self.support else []),
                ft.Text(f"Версия {VERSION}. Автор: {AUTHOR}", size=12),
            ],
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
            visible=True,
            expand=True,
        )

        # камера
        self.camera_title = ft.Text("", size=14, expand=True)  # переносится на несколько строк, кнопка справа остаётся видна
        self.marker = ft.Container(
            width=MARKER_SIZE,
            height=MARKER_SIZE,
            border=ft.Border.all(2, ft.Colors.YELLOW_400),
            border_radius=MARKER_SIZE // 2,
            left=0,
            top=0,
            visible=False,
        )
        self.zoom_slider = ft.Slider(min=1, max=2, value=1, disabled=True, on_change=self.on_zoom_slider, expand=True)
        self.zoom_label = ft.Text("×1.0")
        self.zoom_out_button = ft.IconButton(icon=ft.Icons.ZOOM_OUT, disabled=True, on_click=self.on_zoom_out)
        self.zoom_in_button = ft.IconButton(icon=ft.Icons.ZOOM_IN, disabled=True, on_click=self.on_zoom_in)
        self.focus_text = ft.Text("Фокус: авто")
        self.focus_button = ft.TextButton(content=self.focus_text, on_click=self.on_focus_lock)
        self.capture_button = ft.FloatingActionButton(icon=ft.Icons.CAMERA_ALT, tooltip="Снять", on_click=self.on_capture)
        self.gallery_button = ft.IconButton(
            icon=ft.Icons.PHOTO_LIBRARY,
            tooltip="Из галереи",
            icon_color=ft.Colors.WHITE,
            bgcolor=ft.Colors.with_opacity(0.45, ft.Colors.BLACK),
            on_click=self.on_gallery,
        )
        self.scan_now_button = ft.Button("Считать QR", on_click=self.on_scan_now, visible=False)
        self.cancel_scan_button = ft.Button("Ввести вручную", on_click=self.on_cancel_scan, visible=False)
        self.change_pc_button = ft.TextButton(content=ft.Text("Сменить ПК", size=12), on_click=self.on_change_pc)
        self.camera_message = ft.Text("", visible=False, selectable=True)
        self.busy_ring = ft.ProgressRing(visible=False, width=24, height=24)
        self.gesture = ft.GestureDetector(
            content=ft.Stack([self.preview, self.marker], expand=True),
            on_tap_down=self.on_preview_tap,
            on_scale_start=self.on_scale_start,
            on_scale_update=self.on_scale_update,
            expand=True,
        )
        if hasattr(self.preview, "on_size_change"):
            self.preview.on_size_change = self.on_preview_size
        # «Снять» и «Из галереи» — отдельный слой над self.gesture (не внутри него), чтобы нажатие на кнопку
        # не попадало и в обработчик касания кадра (фокус по точке)
        gallery_overlay = ft.Container(
            self.gallery_button,
            alignment=ft.Alignment.BOTTOM_RIGHT,
            padding=ft.Padding.only(right=16, bottom=16),
            expand=True,
        )
        capture_overlay = ft.Container(
            self.capture_button, alignment=ft.Alignment.BOTTOM_CENTER, padding=ft.Padding.only(bottom=16), expand=True
        )
        self.camera_stage = ft.Stack([self.gesture, gallery_overlay, capture_overlay], expand=True)
        # отрицательное поле компенсирует отступ страницы, чтобы кадр камеры доходил до краёв экрана
        self.camera_preview_area = ft.Container(
            self.camera_stage, margin=ft.Margin.symmetric(horizontal=-PAGE_PADDING), expand=True
        )
        self.camera_view = ft.Column(
            [
                ft.Row([self.camera_title, self.change_pc_button], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                self.camera_preview_area,
                ft.Row([self.zoom_out_button, self.zoom_slider, self.zoom_in_button, self.zoom_label]),
                self.focus_button,
                self.camera_message,
                ft.Row([self.scan_now_button, self.cancel_scan_button, self.busy_ring], spacing=8, wrap=True),
            ],
            spacing=6,
            visible=False,
            expand=True,
        )

        # результаты
        self.results_banner_text = ft.Text(color=ft.Colors.BLACK)
        self.results_banner = ft.Container(self.results_banner_text, padding=10, border_radius=6, visible=False)
        self.results_photo = ft.Column(visible=False, spacing=4)
        self.results_projection = ft.Column(visible=False, spacing=4)
        self.copy_note = ft.Text("", size=12, visible=False, selectable=True)
        self.results_column = ft.Column(spacing=8)
        self.again_button = ft.Button("Снять ещё", on_click=self.on_again)
        self.results_view = ft.Column(
            [
                self.again_button,
                self.results_banner,
                ft.Row(
                    [self.results_photo, self.results_projection],
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                ft.Text("Результаты (нажмите на карточку, чтобы скопировать путь)", size=14, weight=ft.FontWeight.BOLD),
                self.copy_note,
                self.results_column,
            ],
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
            visible=False,
            expand=True,
        )

        self.diag_text = ft.Text("", size=10, color=ft.Colors.GREY_600, selectable=True, visible=False)
        self.back_hint = ft.Text("Нажмите «Назад» ещё раз, чтобы выйти", size=12, visible=False)

    # ---- построение и запуск -----------------------------------------------
    def build(self) -> None:
        self.page.padding = PAGE_PADDING
        views = getattr(self.page, "views", None)
        if views:  # системная кнопка «Назад» идёт в on_confirm_pop, а не закрывает приложение
            views[0].can_pop = False
            views[0].on_confirm_pop = self.on_confirm_pop
        self.page.add(
            ft.SafeArea(
                ft.Column(
                    [
                        *([self.update_bar.container] if self.update_bar else []),
                        self.connect_view,
                        self.camera_view,
                        self.results_view,
                        self.back_hint,
                        self.diag_text,
                    ],
                    expand=True,
                ),
                expand=True,
            )
        )

    def _update_controls(self) -> list[ft.Control]:
        if self.update_bar is None:
            return []
        return [self.update_bar.switch, ft.Row([self.update_bar.check_button, self.update_bar.status], wrap=True)]

    async def start(self) -> None:
        await self._start_flow()
        await self._begin_update_check()
        if self.support is not None:
            self.support_task = asyncio.create_task(self.support.startup())

    async def _begin_update_check(self) -> None:
        if self.update_bar is None:
            return
        await self.update_bar.load()
        if self.check_on_start and self.update_bar.switch.value:
            self.update_task = asyncio.create_task(self.update_bar.startup())

    async def _start_flow(self) -> None:
        demo_link = os.environ.get("GMAGC_MOBILE_DEMO_LINK")
        if demo_link:
            await self._demo(demo_link, os.environ.get("GMAGC_MOBILE_DEMO_PHOTO"))
            return
        stored = await self.store.load()
        if stored is None:
            self._show_connect()
            return
        self._fill(stored)
        await self._connect(stored)

    async def _demo(self, link: str, photo: str | None) -> None:
        """Отладка на ПК: GMAGC_MOBILE_DEMO_LINK подключает, GMAGC_MOBILE_DEMO_PHOTO сразу ищет."""
        connection = parse_link(link)
        if connection is None or not await self._connect(connection):
            return
        if photo:
            self._set_busy(True)
            await self._search(Path(photo).read_bytes())

    # ---- вид -----------------------------------------------------------------
    def _show(self, name: str) -> None:
        if self.camera_view.visible and name != "camera":
            self.camera.invalidate()  # Flet убирает скрытый виджет камеры вместе с контроллером: при возврате запуск заново
        self.connect_view.visible = name == "connect"
        self.camera_view.visible = name == "camera"
        self.results_view.visible = name == "results"
        self.page.update()

    def _remember(self, text: str) -> None:
        self.last_error = text
        self.diag_text.value = f"Последняя ошибка: {text}"
        self.diag_text.visible = True

    def _clear_diag(self) -> None:
        self.last_error = ""
        self.diag_text.visible = False

    def _show_connect(self, error: str | None = None) -> None:
        self.connect_error.value = error or ""
        self.connect_error.visible = bool(error)
        if error:
            self._remember(error)
        self._show("connect")

    def _show_camera(self, mode: str, note: str | None = None) -> None:
        self.mode = mode
        scanning = mode == MODE_SCAN
        self.camera_title.value = SCAN_HINT if scanning else self.status_text
        self.capture_button.visible = self.gallery_button.visible = not scanning
        self.scan_now_button.visible = self.cancel_scan_button.visible = scanning
        self.change_pc_button.visible = not scanning
        self.camera_message.value = note or ""
        self.camera_message.visible = bool(note)
        self._show("camera")

    def _camera_note(self, text: str) -> None:
        self.camera_message.value = text
        self.camera_message.visible = True
        self._remember(text)
        self.page.update()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        buttons = (self.capture_button, self.gallery_button, self.scan_now_button, self.connect_button, self.scan_button)
        for button in buttons:
            button.disabled = busy
        if not busy and not self.camera.ready:
            self.capture_button.disabled = self.scan_now_button.disabled = True
        self.busy_ring.visible = self.connect_busy.visible = busy
        self.page.update()

    def _fill(self, connection: Connection) -> None:
        self.address_field.value = f"{connection.host}:{connection.port}"
        self.code_field.value = connection.code

    def _sync_zoom(self) -> None:
        usable = self.camera.ready and self.camera.max_zoom > self.camera.min_zoom
        self.zoom_slider.min = self.camera.min_zoom
        self.zoom_slider.max = self.camera.max_zoom if usable else self.camera.min_zoom + 1
        self.zoom_slider.value = self.camera.zoom
        self.zoom_label.value = zoom_text(self.camera.zoom)
        self.zoom_slider.disabled = self.zoom_in_button.disabled = self.zoom_out_button.disabled = not usable

    # ---- подключение ---------------------------------------------------------
    async def on_connect(self, _event) -> None:
        if self._busy:
            return
        address = parse_address(self.address_field.value or "")
        if address is None:
            self._show_connect("Введите адрес ПК, например 192.168.1.5 или 192.168.1.5:8765")
            return
        code = self.code_field.value or ""
        if not is_valid_code(code):
            self._show_connect("Код доступа состоит из 8 символов (буквы и цифры), он показан в приложении на ПК")
            return
        await self._connect(Connection(address[0], address[1], normalize_code(code)))

    async def _connect(self, connection: Connection, announce: bool = False) -> bool:
        self._set_busy(True)
        client = self.client_factory(connection)
        try:
            _, status = await asyncio.to_thread(client.verify)
        except ClientError as error:
            self._set_busy(False)
            self._show_connect(error_text(error))
            return False
        except Exception as error:  # noqa: BLE001 - подключение обязано показать причину
            self._set_busy(False)
            self._show_connect(f"Ошибка подключения: {error}")
            return False
        self.connection, self.client = connection, client
        await self.store.save(connection)
        self._fill(connection)
        self._clear_diag()
        self.status_text = status_line(connection, status)
        self._set_busy(False)
        self._show_camera(MODE_SHOOT, note=None if status.indexed else NO_INDEX_NOTE)
        if announce:  # по QR подключение происходит без ручного ввода: коротко подтвердить, что оно удалось
            self.page.show_dialog(ft.SnackBar(ft.Text(f"Подключено к ПК: {connection.host}:{connection.port}")))
        await self._ensure_camera()
        return True

    async def _ensure_camera(self) -> None:
        """Запускает камеру, если она не готова (первый заход или возврат на экран после результатов)."""
        if not self.camera.ready:
            await asyncio.sleep(self.mount_seconds)
            await self.camera.start()
            if not self.camera.ready:
                self._camera_note(self.camera.error or "Камера недоступна")
        self._sync_zoom()
        self._set_busy(self._busy)

    async def _take_picture(self) -> bytes:
        """Снимок; если камера потеряла контроллер, один раз запускает её заново и снимает ещё раз."""
        try:
            return await self.camera.take_picture()
        except Exception:  # noqa: BLE001 - любая ошибка снимка: пробуем восстановить камеру
            if not await self.camera.restart():
                raise RuntimeError(self.camera.error or "камера недоступна") from None
            self._sync_zoom()
            return await self.camera.take_picture()

    async def on_change_pc(self, _event) -> None:
        await self.store.clear()
        self.connection = self.client = None
        self._clear_diag()
        self._show_connect()

    # ---- QR ------------------------------------------------------------------
    async def on_scan_qr(self, _event) -> None:
        self._show_camera(MODE_SCAN)
        await self._ensure_camera()

    # ---- кнопка «Назад» ------------------------------------------------------
    async def on_confirm_pop(self, event) -> None:
        """Системная «Назад»: возвращает на предыдущий экран; из первого экрана выходит при втором нажатии."""
        exit_now = await self._handle_back()
        await event.control.confirm_pop(exit_now)
        token = self._hint_token
        if self.back_hint.visible:
            await asyncio.sleep(self.hint_seconds)
            if token == self._hint_token:
                self.back_hint.visible = False
                self.page.update()

    async def _handle_back(self) -> bool:
        """True, если приложение нужно закрыть; иначе делает шаг назад (или показывает подсказку о выходе)."""
        if self._busy:
            return False  # идёт отправка или подключение: не выходим случайно
        self.back_hint.visible = False
        if self.results_view.visible:
            await self.on_again(None)
            return False
        if self.camera_view.visible and self.mode == MODE_SCAN:
            self._show_connect()
            return False
        now = self._clock()
        if now - self._last_back <= self.back_seconds:
            return True
        self._last_back = now
        self._hint_token += 1
        self.back_hint.visible = True
        self.page.update()
        return False

    async def on_cancel_scan(self, _event) -> None:
        self._show_connect()

    async def on_scan_now(self, _event) -> None:
        if self._busy or not self.camera.ready:
            return
        self._set_busy(True)
        connection = None
        failure = ""
        data = b""
        try:
            data = await self._take_picture()
            connection = await asyncio.to_thread(self.qr_reader, data)
        except QrUnavailable:
            failure = "Чтение QR недоступно на этом телефоне: введите адрес и код вручную."
        except QrImageError as error:
            failure = f"Снимок камеры не удалось прочитать ({error}). Введите адрес и код вручную."
        except Exception as error:  # noqa: BLE001
            failure = f"Ошибка камеры: {error}"
        self._set_busy(False)
        if connection is not None:
            await self._connect(connection, announce=True)
            return
        if not failure:
            failure = (
                "QR-код не найден. Поднесите камеру ближе (приближение и касание для фокуса помогают): "
                "код должен быть целиком в кадре и чётким. Если не выходит, введите адрес и код вручную."
            )
        if data:  # диагностика: что за снимок получила программа и работает ли чтение QR на этом телефоне
            failure += f" [{await asyncio.to_thread(self.qr_diagnose, data)}]"
        self._camera_note(failure)

    # ---- съёмка и поиск --------------------------------------------------------
    async def on_capture(self, _event) -> None:
        if self._busy or not self.camera.ready:
            return
        self._set_busy(True)
        try:
            data = await self._take_picture()
        except Exception as error:  # noqa: BLE001
            self._set_busy(False)
            self._camera_note(f"Не удалось снять: {error}")
            return
        await self._search(data)

    async def on_gallery(self, _event) -> None:
        if self._busy:
            return
        files = await self.picker.pick_files(dialog_title="Фото проекции", file_type=ft.FilePickerFileType.IMAGE)
        if not files:
            return
        picked = files[0]
        try:
            raw = picked.bytes if picked.bytes else Path(picked.path).read_bytes()
            data = await asyncio.to_thread(prepare_upload, raw)
        except (OSError, ValueError, TypeError) as error:
            self._camera_note(f"Не удалось подготовить фото: {error}")
            return
        self._set_busy(True)
        await self._search(data)

    async def _search(self, data: bytes) -> None:
        """Отправляет фото на ПК (вызывающий уже включил busy) и показывает результат или ошибку."""
        response: MatchResponse | None = None
        failure: ClientError | None = None
        message = ""
        try:
            response = await asyncio.to_thread(self.client.match, data)
        except ClientError as error:
            failure = error
        except Exception as error:  # noqa: BLE001
            message = f"Ошибка: {error}"
        self._set_busy(False)
        if failure is not None:
            if failure.kind == UNAUTHORIZED:
                self._show_connect(error_text(failure))
            else:
                self._camera_note(error_text(failure))
            return
        if response is None:
            self._camera_note(message or "Ошибка поиска")
            return
        await self._show_results(data, response)

    async def _show_results(self, photo: bytes, response: MatchResponse) -> None:
        banner = outcome_message(response.outcome)
        self.results_banner_text.value = banner or ""
        self.results_banner.bgcolor = ft.Colors.RED_100 if response.outcome == OUTCOME_NO_PROJECTION else ft.Colors.AMBER_100
        self.results_banner.visible = bool(banner)
        self.results_photo.controls = [ft.Text("Фото"), ft.Image(src=photo, width=160, height=120, fit=ft.BoxFit.CONTAIN)]
        self.results_photo.visible = True
        if response.projection_png:
            self.results_projection.controls = [
                ft.Text("Найденная проекция"),
                ft.Image(src=response.projection_png, width=120, height=120, fit=ft.BoxFit.CONTAIN),
            ]
        self.results_projection.visible = bool(response.projection_png)
        self.results_column.controls = [self._result_card(item) for item in response.results]
        self.copy_note.visible = False
        self._show("results")

    def _result_card(self, item: ResultItem) -> ft.Card:
        details: list[ft.Control] = [
            ft.Text(item.name, weight=ft.FontWeight.BOLD),
            ft.Text(item.path, size=12, selectable=False),
            ft.Text(score_text(item.score)),
        ]
        if item.copies:
            details.append(ft.Text(f"ещё {len(item.copies)} файлов", tooltip="\n".join(item.copies)))
        details.append(ft.Button("Копировать путь", data=item.path, on_click=self.on_copy_click))
        return ft.Card(
            ft.Container(
                ft.Row(
                    [
                        ft.Image(src=item.thumbnail_png, width=80, height=80, fit=ft.BoxFit.CONTAIN),
                        ft.Column(details, spacing=2, expand=True),
                    ],
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                padding=10,
                ink=True,
                data=item.path,
                on_click=self.on_card_click,
            )
        )

    async def on_again(self, _event) -> None:
        self._show_camera(MODE_SHOOT)
        await self._ensure_camera()

    async def on_card_click(self, event) -> None:
        await self.copy_path(event.control.data)

    async def on_copy_click(self, event) -> None:
        await self.copy_path(event.control.data)

    async def copy_path(self, path: str) -> None:
        """Копирует путь файла на ПК (как пришёл в ответе, вместе с именем файла) в буфер обмена."""
        await self.clipboard.set(path)
        self.copy_note.value = f"Путь скопирован: {path}"
        self.copy_note.visible = True
        self.page.update()

    # ---- приближение и фокус -----------------------------------------------------
    async def _zoom_to(self, value: float) -> None:
        zoom = await self.camera.set_zoom(value)
        self.zoom_slider.value = zoom
        self.zoom_label.value = zoom_text(zoom)
        self.page.update()

    async def on_zoom_slider(self, event) -> None:
        await self._zoom_to(float(event.control.value))

    async def on_zoom_in(self, _event) -> None:
        await self._zoom_to(self.camera.zoom + ZOOM_STEP)

    async def on_zoom_out(self, _event) -> None:
        await self._zoom_to(self.camera.zoom - ZOOM_STEP)

    def on_scale_start(self, _event) -> None:
        self._pinch_start = self.camera.zoom

    async def on_scale_update(self, event) -> None:
        if event.pointer_count < 2 or self._zooming:
            return
        self._zooming = True
        try:
            await self._zoom_to(self._pinch_start * event.scale)
        finally:
            self._zooming = False

    def on_preview_size(self, event) -> None:
        self._preview_size = (float(event.width), float(event.height))

    async def on_preview_tap(self, event) -> None:
        """Касание кадра наводит фокус и замер экспозиции в эту точку, на кадре мигает метка."""
        width, height = self._preview_size
        if not self.camera.ready or width <= 0 or height <= 0:
            return
        x, y = float(event.local_position.x), float(event.local_position.y)
        self._marker_token += 1
        token = self._marker_token
        self.marker.left, self.marker.top = x - MARKER_SIZE / 2, y - MARKER_SIZE / 2
        self.marker.visible = True
        self.page.update()
        if not await self.camera.focus_at(x, y, width, height):
            self._camera_note(self.camera.error or "Фокус по точке недоступен")
        await asyncio.sleep(self.marker_seconds)
        if token == self._marker_token:
            self.marker.visible = False
            self.page.update()

    async def on_focus_lock(self, _event) -> None:
        locked = await self.camera.toggle_focus_lock()
        self.focus_text.value = "Фокус: зафиксирован" if locked else "Фокус: авто"
        self.page.update()


def camera_supported(page: ft.Page) -> bool:
    """Контрол Camera в Flet 1.0.0 работает только на Android, iOS и в вебе (на других платформах бросает исключение)."""
    if getattr(page, "web", False):
        return True
    return getattr(page, "platform", None) in (ft.PagePlatform.ANDROID, ft.PagePlatform.IOS)


def _camera_placeholder() -> ft.Control:
    return ft.Container(ft.Text("Камера доступна только на телефоне (Android)"), alignment=ft.Alignment.CENTER, expand=True)


async def build_page(page: ft.Page, **services) -> MobileApp:
    """Собирает экран из служб Flet (в тестах их подменяют) и запускает подключение."""
    page.title = f"{NAME} {VERSION}"
    if getattr(page, "platform", None) in (ft.PagePlatform.ANDROID, ft.PagePlatform.IOS):
        try:  # приложение рассчитано только на вертикальное положение (камера, экраны)
            await page.set_allowed_device_orientations([ft.DeviceOrientation.PORTRAIT_UP])
        except Exception:  # noqa: BLE001 - блокировка поворота не должна мешать запуску экрана
            pass
    prefs = services.pop("prefs", None) or ft.SharedPreferences()
    permission = services.pop("permission", None) or ph.PermissionHandler()
    supported = camera_supported(page)
    camera_control = services.pop("camera_control", None) or (
        fc.Camera(expand=True, preview_enabled=True) if supported else _camera_placeholder()
    )
    controller = services.pop("controller", None) or CameraController(camera_control, permission, supported=supported)
    launcher = services.pop("launcher", None) or ft.UrlLauncher()
    tracker = services.pop("tracker", "default")  # tracker=None в тестах отключает обновления
    support = services.pop("support", True)  # support=False в тестах отключает окно поддержки
    if tracker == "default":
        tracker = UpdateTracker(prefs)
    app = MobileApp(
        page,
        ConnectionStore(prefs),
        controller,
        preview=camera_control,
        tracker=tracker,
        launcher=launcher,
        support=support,
        prefs=prefs,
        **services,
    )
    page.services.extend([prefs, permission, app.picker, app.clipboard, launcher])
    app.build()
    await app.start()
    return app
