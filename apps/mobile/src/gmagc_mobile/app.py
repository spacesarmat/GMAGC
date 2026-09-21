"""Экран Android-приложения: подключение к ПК, камера с приближением и фокусом, результаты поиска."""

from __future__ import annotations

import asyncio
import os
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
from gmagc_mobile.qr import QrUnavailable, connection_from_qr
from gmagc_mobile.store import ConnectionStore
from gmagc_mobile.texts import NO_INDEX_NOTE, error_text, outcome_message, score_text, status_line, zoom_text

MODE_SHOOT = "shoot"
MODE_SCAN = "scan"
ZOOM_STEP = 0.5
MARKER_SIZE = 64
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
        marker_seconds: float = 1.5,
    ):
        self.page = page
        self.store = store
        self.camera = camera
        self.preview = preview if preview is not None else camera.camera
        self.picker = picker or ft.FilePicker()
        self.clipboard = clipboard or ft.Clipboard()
        self.client_factory = client_factory
        self.qr_reader = qr_reader
        self.marker_seconds = marker_seconds
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
                ft.Text(f"Версия {VERSION}. Автор: {AUTHOR}", size=12),
            ],
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
            visible=True,
            expand=True,
        )

        # камера
        self.camera_title = ft.Text("", size=14)
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
        self.capture_button = ft.Button("Снять", on_click=self.on_capture)
        self.gallery_button = ft.Button("Из галереи", on_click=self.on_gallery)
        self.scan_now_button = ft.Button("Считать QR", on_click=self.on_scan_now, visible=False)
        self.cancel_scan_button = ft.Button("Отмена", on_click=self.on_cancel_scan, visible=False)
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
        self.camera_view = ft.Column(
            [
                ft.Row([self.camera_title, self.change_pc_button], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                self.gesture,
                ft.Row([self.zoom_out_button, self.zoom_slider, self.zoom_in_button, self.zoom_label]),
                self.focus_button,
                self.camera_message,
                ft.Row(
                    [
                        self.capture_button,
                        self.gallery_button,
                        self.scan_now_button,
                        self.cancel_scan_button,
                        self.busy_ring,
                    ],
                    spacing=8,
                    wrap=True,
                ),
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

    # ---- построение и запуск -----------------------------------------------
    def build(self) -> None:
        self.page.add(
            ft.SafeArea(
                ft.Column([self.connect_view, self.camera_view, self.results_view, self.diag_text], expand=True),
                expand=True,
            )
        )

    async def start(self) -> None:
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
        self.connect_view.visible = name == "connect"
        self.camera_view.visible = name == "camera"
        self.results_view.visible = name == "results"
        self.page.update()

    def _remember(self, text: str) -> None:
        self.last_error = text
        self.diag_text.value = f"Последняя ошибка: {text}"
        self.diag_text.visible = True

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

    async def _connect(self, connection: Connection) -> bool:
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
        self.status_text = status_line(connection, status)
        self._set_busy(False)
        self._show_camera(MODE_SHOOT, note=None if status.indexed else NO_INDEX_NOTE)
        await self._ensure_camera()
        return True

    async def _ensure_camera(self) -> None:
        if self.camera.ready:
            await self.camera.resume()
        else:
            await self.camera.start()
            if not self.camera.ready:
                self._camera_note(self.camera.error or "Камера недоступна")
        self._sync_zoom()
        self._set_busy(self._busy)

    async def on_change_pc(self, _event) -> None:
        await self.store.clear()
        self.connection = self.client = None
        self._show_connect()

    # ---- QR ------------------------------------------------------------------
    async def on_scan_qr(self, _event) -> None:
        self._show_camera(MODE_SCAN)
        await self._ensure_camera()

    async def on_cancel_scan(self, _event) -> None:
        self._show_connect()

    async def on_scan_now(self, _event) -> None:
        if self._busy or not self.camera.ready:
            return
        self._set_busy(True)
        connection = None
        failure = ""
        try:
            data = await self.camera.take_picture()
            connection = await asyncio.to_thread(self.qr_reader, data)
        except QrUnavailable:
            failure = "Чтение QR недоступно на этом телефоне: введите адрес и код вручную."
        except Exception as error:  # noqa: BLE001
            failure = f"Ошибка камеры: {error}"
        self._set_busy(False)
        if connection is not None:
            await self._connect(connection)
            return
        self._camera_note(
            failure
            or "QR-код не найден. Поднесите камеру ближе (приближение и касание для фокуса помогают): "
            "код должен быть целиком в кадре и чётким."
        )

    # ---- съёмка и поиск --------------------------------------------------------
    async def on_capture(self, _event) -> None:
        if self._busy or not self.camera.ready:
            return
        self._set_busy(True)
        try:
            data = await self.camera.take_picture()
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
        await self.camera.pause()
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
        await self.camera.resume()

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


async def build_page(page: ft.Page, **services) -> MobileApp:
    """Собирает экран из служб Flet (в тестах их подменяют) и запускает подключение."""
    page.title = f"{NAME} {VERSION}"
    prefs = services.pop("prefs", None) or ft.SharedPreferences()
    permission = services.pop("permission", None) or ph.PermissionHandler()
    camera_control = services.pop("camera_control", None) or fc.Camera(expand=True, preview_enabled=True)
    controller = services.pop("controller", None) or CameraController(camera_control, permission)
    app = MobileApp(page, ConnectionStore(prefs), controller, preview=camera_control, **services)
    page.services.extend([prefs, permission, app.picker, app.clipboard])
    app.build()
    await app.start()
    return app
