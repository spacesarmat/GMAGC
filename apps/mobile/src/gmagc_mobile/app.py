"""Экран Android-приложения: подключение к ПК, камера с приближением и фокусом, результаты поиска."""

from __future__ import annotations

import asyncio
import math
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
from gmagc_common.theme import MOBILE_ACCENT_COLOR, SEED_COLOR, score_band
from gmagc_mobile.about import AUTHOR, NAME, VERSION
from gmagc_mobile.camera import CameraController
from gmagc_mobile.client import UNAUTHORIZED, UNREACHABLE, ClientError, GmagcClient
from gmagc_mobile.imaging import prepare_upload
from gmagc_mobile.profile_store import MemoryPrefs, ProfileStore
from gmagc_mobile.profiles_ui import ProfileEditor
from gmagc_mobile.qr import QrImageError, QrUnavailable, connection_from_frame, connection_from_qr, diagnose
from gmagc_mobile.store import ConnectionStore
from gmagc_mobile.support import SupportPrompt
from gmagc_mobile.texts import (
    NO_INDEX_NOTE,
    error_text,
    history_text,
    outcome_message,
    score_text,
    share_text,
    zoom_text,
)
from gmagc_mobile.update_bar import UpdateBar
from gmagc_mobile.updates import UpdateTracker

MODE_SHOOT = "shoot"
MODE_SCAN = "scan"
ZOOM_STEP = 0.5
MARKER_SIZE = 64
HISTORY_LIMIT = 10  # снимков за сессию, самый новый первым; дальше старые записи забываются
PAGE_PADDING = 12  # общий отступ страницы; кадр камеры вычитает его отрицательным полем, чтобы быть во всю ширину
SCAN_INTERVAL = 0.4  # пауза между попытками распознать QR в потоке кадров камеры: бережёт батарею и процессор
SCAN_HINT = (
    "Наведите камеру на QR-код в приложении на ПК — считается автоматически (приближение и касание для фокуса помогают)"
)
SCAN_HINT_MANUAL = (
    "Автосканирование недоступно на этом телефоне. Наведите камеру на QR-код в приложении на ПК "
    "(приближение и касание для фокуса помогают) и нажмите «Считать QR»"
)

_BADGE_COLORS = {
    "good": (ft.Colors.GREEN_100, ft.Colors.GREEN_900),
    "low": (ft.Colors.AMBER_100, ft.Colors.AMBER_900),
    "bad": (ft.Colors.RED_100, ft.Colors.RED_900),
}


def _score_badge(score: float) -> ft.Container:
    """Цветной бейдж оценки на карточке результата: зелёный/жёлтый/красный по порогу совпадения."""
    bgcolor, color = _BADGE_COLORS[score_band(score)]
    return ft.Container(
        ft.Text(score_text(score), size=12, weight=ft.FontWeight.BOLD, color=color),
        bgcolor=bgcolor,
        border_radius=12,
        padding=ft.Padding.symmetric(horizontal=8, vertical=3),
    )


def _nav_item(icon: str, label: str, on_click) -> ft.Container:
    """Один пункт нижней навигации (иконка + подпись), как на референсе дизайна."""
    return ft.Container(
        ft.Column(
            [ft.Icon(icon, size=22), ft.Text(label, size=11)],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=2,
            tight=True,
        ),
        on_click=on_click,
        padding=8,
        expand=True,
    )


def _nav_row(items: list[ft.Control]) -> ft.Row:
    """Нижняя навигация экрана: пункты через тонкий разделитель, поровну делят ширину."""
    row: list[ft.Control] = []
    for index, item in enumerate(items):
        if index:
            row.append(ft.VerticalDivider(width=1))
        row.append(item)
    return ft.Row(row, alignment=ft.MainAxisAlignment.SPACE_EVENLY)


def _back_row(title: str, on_back) -> ft.Row:
    """Заголовок вложенного экрана (Настройки/О программе/Помощь/Галерея) со стрелкой назад."""
    back_button = ft.IconButton(icon=ft.Icons.ARROW_BACK, on_click=on_back)
    return ft.Row([back_button, ft.Text(title, size=20, weight=ft.FontWeight.BOLD)])


OVERLAY_BUTTON_BGCOLOR = ft.Colors.with_opacity(0.35, ft.Colors.BLACK)  # тёмная подложка для кнопок поверх кадра камеры


def _camera_icon_button(icon, tooltip: str, on_click, *, disabled: bool = False) -> ft.IconButton:
    """Кнопка поверх превью камеры: полупрозрачная тёмная подложка, чтобы значок был виден на любом фоне."""
    return ft.IconButton(
        icon=icon,
        icon_color=ft.Colors.WHITE,
        bgcolor=OVERLAY_BUTTON_BGCOLOR,
        tooltip=tooltip,
        on_click=on_click,
        disabled=disabled,
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
        share=None,
        client_factory: Callable[[Connection], GmagcClient] = GmagcClient,
        qr_reader: Callable[[bytes], Connection | None] = connection_from_qr,
        qr_diagnose: Callable[[bytes], str] = diagnose,
        frame_reader: Callable[[int, int, str, bytes], Connection | None] = connection_from_frame,
        scan_interval: float = SCAN_INTERVAL,
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
        profile_store: ProfileStore | None = None,
    ):
        self.page = page
        self.store = store
        self.camera = camera
        self.preview = preview if preview is not None else camera.camera
        self.picker = picker or ft.FilePicker()
        self.clipboard = clipboard or ft.Clipboard()
        self.share = share or ft.Share()
        self.editor = ProfileEditor(
            page,
            profile_store or ProfileStore(prefs or MemoryPrefs()),
            self.share,
            on_exit=lambda: self._show(self._return_view),
        )
        self.profiles_view = self.editor.view
        self.client_factory = client_factory
        self.qr_reader = qr_reader
        self.qr_diagnose = qr_diagnose
        self.frame_reader = frame_reader
        self.scan_interval = scan_interval  # пауза между попытками распознать QR в потоке кадров
        self._scan_busy = False
        self._scan_last = -1e9
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
        self._return_view = "connect"  # куда вернуться со вложенного экрана (Настройки/О программе/Помощь/Галерея)
        self.mode = MODE_SHOOT
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
                ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Image(src="logo.svg", width=56, height=56, fit=ft.BoxFit.CONTAIN),
                                ft.Text(NAME, size=28, weight=ft.FontWeight.BOLD),
                            ],
                            spacing=12,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        self.address_field,
                        self.code_field,
                        ft.Row([self.connect_button, self.connect_busy], spacing=12, alignment=ft.MainAxisAlignment.CENTER),
                        ft.Row([self.scan_button], alignment=ft.MainAxisAlignment.CENTER),
                        ft.Row(
                            [ft.TextButton("Профили приборов", icon=ft.Icons.TUNE, on_click=self.on_open_profiles)],
                            alignment=ft.MainAxisAlignment.CENTER,
                        ),
                        self.connect_error,
                    ],
                    spacing=12,
                    scroll=ft.ScrollMode.AUTO,
                    expand=True,
                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                ),
                ft.Divider(),
                _nav_row(
                    [
                        _nav_item(ft.Icons.SETTINGS, "Настройки", self.on_open_settings),
                        _nav_item(ft.Icons.HELP_OUTLINE, "Помощь", self.on_open_help),
                        _nav_item(ft.Icons.INFO_OUTLINE, "О программе", self.on_open_about),
                    ]
                ),
                ft.Text(f"Версия {VERSION}", size=11, color=ft.Colors.GREY_600),
            ],
            spacing=12,
            visible=True,
            expand=True,
        )

        # камера — полноэкранный оверлей по референсу дизайна: превью на весь экран, элементы управления
        # плавают поверх него (Stack), а не делят с ним место в колонке
        self.camera_title = ft.Text("", size=13, color=ft.Colors.WHITE, text_align=ft.TextAlign.CENTER, visible=False)
        self.wifi_icon = ft.Icon(ft.Icons.WIFI_OFF, color=ft.Colors.RED_400, size=20)
        self.marker = ft.Container(
            width=MARKER_SIZE,
            height=MARKER_SIZE,
            border=ft.Border.all(2, ft.Colors.YELLOW_400),
            border_radius=MARKER_SIZE // 2,
            left=0,
            top=0,
            visible=False,
        )
        # слайдер разворачивается на 90° (стандартный приём Flet/Flutter для вертикальных слайдеров);
        # свой width/height становятся визуальными height/width уже ПОСЛЕ поворота
        self.zoom_slider = ft.Slider(
            min=1, max=2, value=1, disabled=True, on_change=self.on_zoom_slider, width=150, rotate=-math.pi / 2
        )
        self.zoom_label = ft.Text("×1.0", size=12, color=ft.Colors.WHITE)
        self.zoom_out_button = ft.IconButton(
            icon=ft.Icons.ZOOM_OUT, disabled=True, on_click=self.on_zoom_out, icon_color=ft.Colors.WHITE
        )
        self.zoom_in_button = ft.IconButton(
            icon=ft.Icons.ZOOM_IN, disabled=True, on_click=self.on_zoom_in, icon_color=ft.Colors.WHITE
        )
        self.focus_text = ft.Text("Фокус: авто")  # хранит состояние; на экране виден только значок (его tooltip)
        self.focus_button = _camera_icon_button(ft.Icons.CENTER_FOCUS_WEAK, self.focus_text.value, self.on_focus_lock)
        self.capture_title = ft.Text("СФОТОГРАФИРОВАТЬ", size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE)
        self.capture_subtitle = ft.Text("Готово к съёмке", size=11, color=ft.Colors.GREY_300)
        self.capture_button = ft.FloatingActionButton(
            icon=ft.Icons.CAMERA_ALT,
            tooltip="Снять",
            bgcolor=ft.Colors.WHITE,
            foreground_color=ft.Colors.BLACK,
            on_click=self.on_capture,
        )
        # заголовок и подпись переключаются вместе с самой кнопкой — иначе при сканировании QR (кнопка
        # съёмки скрыта) подписи «СФОТОГРАФИРОВАТЬ»/«Готово к съёмке» зависали бы без кнопки под ними
        self.capture_group = ft.Column(
            [self.capture_title, self.capture_button, self.capture_subtitle],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=2,
        )
        self.gallery_button = _camera_icon_button(ft.Icons.PHOTO_LIBRARY, "Выбрать фото", self.on_gallery)
        self.scan_now_button = ft.Button("Считать QR", on_click=self.on_scan_now, visible=False)
        self.cancel_scan_button = ft.Button("Ввести вручную", on_click=self.on_cancel_scan, visible=False)
        self.change_pc_button = ft.TextButton(content=ft.Text("Сменить ПК", size=12), on_click=self.on_change_pc)
        self.camera_message = ft.Text(
            "", visible=False, selectable=True, color=ft.Colors.WHITE, text_align=ft.TextAlign.CENTER
        )
        self.retry_button = ft.Button("Повторить", on_click=self.on_retry, visible=False)
        self.busy_ring = ft.ProgressRing(visible=False, width=24, height=24)
        self._retry_data: bytes | None = None
        self.history: list[tuple[bytes, MatchResponse]] = []  # снимки этой сессии, самый новый первым
        self._current_response: MatchResponse | None = None  # для кнопки «Поделиться» на экране результатов
        self.history_empty = ft.Text("Пока нет снимков в этой сессии", size=13, color=ft.Colors.GREY_500)
        self.history_column = ft.Column(spacing=0)
        self.gesture = ft.GestureDetector(
            content=ft.Stack([self.preview, self.marker], expand=True),
            on_tap_down=self.on_preview_tap,
            on_scale_start=self.on_scale_start,
            on_scale_update=self.on_scale_update,
            expand=True,
        )
        self.gesture.on_size_change = self.on_preview_size  # реальный размер кадра, а не виджета камеры внутри него
        # угловые скобки рамки-видоискателя (только оформление, по референсу дизайна)
        corner_side = ft.BorderSide(3, MOBILE_ACCENT_COLOR)
        no_side = ft.BorderSide(0, ft.Colors.TRANSPARENT)
        corners = [
            ft.Container(
                width=28,
                height=28,
                border=ft.Border(
                    top=corner_side if top else no_side,
                    bottom=no_side if top else corner_side,
                    left=corner_side if left else no_side,
                    right=no_side if left else corner_side,
                ),
                top=12 if top else None,
                bottom=12 if not top else None,
                left=12 if left else None,
                right=12 if not left else None,
            )
            for top in (True, False)
            for left in (True, False)
        ]
        self.camera_stage = ft.Stack([self.gesture, *corners], expand=True)
        # отрицательное поле со всех сторон компенсирует отступ страницы, чтобы кадр камеры доходил
        # до краёв экрана целиком (а не только по бокам) — плавающие кнопки поверх позиционируются
        # относительно исходных границ Stack, так что сами не съезжают к краю вместе с картинкой
        self.camera_preview_area = ft.Container(self.camera_stage, margin=ft.Margin.all(-PAGE_PADDING), expand=True)
        top_row = ft.Row(
            [
                ft.Row(
                    [
                        _camera_icon_button(ft.Icons.PHOTO_LIBRARY, "Галерея", self.on_open_gallery),
                        _camera_icon_button(ft.Icons.TUNE, "Профили приборов", self.on_open_profiles),
                        _camera_icon_button(ft.Icons.SETTINGS, "Настройки", self.on_open_settings),
                        _camera_icon_button(ft.Icons.INFO_OUTLINE, "О программе", self.on_open_about),
                    ],
                    spacing=4,
                ),
                ft.Container(self.wifi_icon, bgcolor=OVERLAY_BUTTON_BGCOLOR, border_radius=20, padding=8),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )
        zoom_column = ft.Container(
            ft.Column(
                [self.zoom_in_button, self.zoom_slider, self.zoom_out_button, self.zoom_label],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=2,
            ),
            bgcolor=OVERLAY_BUTTON_BGCOLOR,
            border_radius=24,
            padding=ft.Padding.symmetric(vertical=8, horizontal=4),
            width=56,
            height=230,
            alignment=ft.Alignment.CENTER,
        )
        capture_slot = ft.Column(
            [self.capture_group], expand=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER
        )
        bottom_row = ft.Row(
            [self.focus_button, capture_slot, self.gallery_button],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        scan_row = ft.Row(
            [self.scan_now_button, self.cancel_scan_button, self.busy_ring],
            spacing=8,
            wrap=True,
            alignment=ft.MainAxisAlignment.CENTER,
        )
        note_column = ft.Column(
            [self.camera_message, self.retry_button, scan_row],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=8,
        )
        self.camera_view = ft.Column(
            [
                ft.Stack(
                    [
                        self.camera_preview_area,
                        ft.Container(top_row, top=36, left=12, right=12),
                        ft.Container(self.camera_title, top=88, left=16, right=16),
                        ft.Container(zoom_column, right=8, top=140),
                        ft.Container(note_column, left=16, right=16, bottom=110),
                        ft.Container(bottom_row, left=8, right=8, bottom=20),
                    ],
                    expand=True,
                )
            ],
            spacing=0,
            visible=False,
            expand=True,
        )

        # вложенные экраны (Галерея / Настройки / О программе / Помощь) — открываются с экранов
        # подключения и камеры через нижнюю навигацию, «назад» возвращает туда, откуда открыли
        self.gallery_view = ft.Column(
            [_back_row("Галерея", self.on_close_overlay), self.history_empty, self.history_column],
            spacing=8,
            visible=False,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        )
        self.settings_view = ft.Column(
            [
                _back_row("Настройки", self.on_close_overlay),
                self.change_pc_button,
                ft.Divider(),
                *self._update_controls(),
            ],
            spacing=8,
            visible=False,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        )
        self.about_view = ft.Column(
            [
                _back_row("О программе", self.on_close_overlay),
                ft.Text(NAME, size=22, weight=ft.FontWeight.BOLD),
                ft.Text(f"Версия {VERSION}. Автор: {AUTHOR}", size=13),
                *self._support_links(),
            ],
            spacing=8,
            visible=False,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        )
        self.help_view = ft.Column(
            [
                _back_row("Помощь", self.on_close_overlay),
                ft.Text(
                    "Подключитесь к ПК с запущенным GMAGC в той же сети Wi-Fi: наведите камеру на QR-код в его "
                    "окне (подключение произойдёт само) или введите адрес и код вручную. Дальше наводите камеру "
                    "на проекцию и снимайте — совпадения из библиотеки на ПК придут в ответ.",
                    size=13,
                ),
                ft.Text(
                    "«Профили»: создание профиля прибора для grandMA2 и grandMA3 с нуля (режимы, каналы из шаблонов, "
                    "диапазоны значений). Все правки сохраняются сразу; готовый профиль можно отправить кнопкой "
                    "«Поделиться профилем» в виде JSON или «Поделиться для grandMA3» готовым XML типа прибора "
                    "(сохраните текст как .xml и положите в gma3_library\fixturetypes). Экспорт для grandMA2 появится позже.",
                    size=13,
                ),
            ],
            spacing=8,
            visible=False,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        )

        # результаты
        self.results_banner_text = ft.Text(color=ft.Colors.BLACK)
        self.results_banner = ft.Container(self.results_banner_text, padding=10, border_radius=6, visible=False)
        self.results_photo = ft.Column(visible=False, spacing=4)
        self.results_projection = ft.Column(visible=False, spacing=4)
        self.copy_note = ft.Text("", size=12, visible=False, selectable=True)
        self.results_column = ft.Column(spacing=8)
        self.again_button = ft.Button("Снять ещё", on_click=self.on_again)
        self.share_button = ft.TextButton(content=ft.Text("Поделиться"), on_click=self.on_share)
        self.results_view = ft.Column(
            [
                ft.Row([self.again_button, self.share_button], spacing=8, wrap=True),
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
        self.back_hint_text = ft.Text("Нажмите «Назад» ещё раз, чтобы выйти", size=12)
        # Container сам visible=False (а не только текст внутри): иначе прозрачный expand=True слой оверлея
        # остаётся в дереве и перехватывает касания по всему экрану, хотя визуально ничего не видно.
        self.back_hint = ft.Container(
            self.back_hint_text,
            alignment=ft.Alignment.BOTTOM_CENTER,
            padding=ft.Padding.only(bottom=8),
            expand=True,
            visible=False,
        )

    # ---- построение и запуск -----------------------------------------------
    def build(self) -> None:
        self.page.padding = PAGE_PADDING
        scrollbar_theme = ft.ScrollbarTheme(
            thumb_color=ft.Colors.with_opacity(0.6, MOBILE_ACCENT_COLOR),
            track_color=ft.Colors.with_opacity(0.15, MOBILE_ACCENT_COLOR),
            thickness=6,
            radius=8,
        )
        theme = ft.Theme(use_material3=True, color_scheme_seed=SEED_COLOR, scrollbar_theme=scrollbar_theme)
        self.page.theme = theme
        self.page.dark_theme = theme
        self.page.theme_mode = ft.ThemeMode.DARK  # всегда тёмная — по одобренному референсу дизайна
        views = getattr(self.page, "views", None)
        if views:  # системная кнопка «Назад» идёт в on_confirm_pop, а не закрывает приложение
            views[0].can_pop = False
            views[0].on_confirm_pop = self.on_confirm_pop
        self.page.add(
            ft.SafeArea(
                ft.Stack(
                    [
                        ft.Column(
                            [
                                *([self.update_bar.container] if self.update_bar else []),
                                self.connect_view,
                                self.camera_view,
                                self.results_view,
                                self.gallery_view,
                                self.settings_view,
                                self.about_view,
                                self.help_view,
                                self.profiles_view,
                                self.diag_text,
                            ],
                            expand=True,
                        ),
                        # оверлей, а не элемент той же Column: иначе видимая подсказка отжимает высоту у камеры
                        # (оба делят место через expand=True в одной колонке)
                        self.back_hint,
                    ],
                    expand=True,
                ),
                expand=True,
            )
        )

    def _update_controls(self) -> list[ft.Control]:
        if self.update_bar is None:
            return []
        return [ft.Row([self.update_bar.check_button, self.update_bar.status], wrap=True)]

    def _support_links(self) -> list[ft.Control]:
        """Свежие кнопки на каждый вызов: один и тот же контрол Flet нельзя вставить сразу на несколько экранов."""
        if self.support is None:
            return []
        return [
            ft.Row(
                [
                    ft.TextButton(content=ft.Text("Поддержать автора", size=12), on_click=self.support.on_open_link),
                    ft.TextButton(content=ft.Text("Telegram автора", size=12), on_click=self.support.on_open_telegram),
                    ft.TextButton(content=ft.Text("Канал GMAGC", size=12), on_click=self.support.on_open_channel),
                ],
                wrap=True,
            )
        ]

    async def start(self) -> None:
        await self._start_flow()
        await self._begin_update_check()
        if self.support is not None:
            self.support_task = asyncio.create_task(self.support.startup())

    async def _begin_update_check(self) -> None:
        if self.update_bar is None:
            return
        if self.check_on_start:  # на Android проверка обязательна: выключателя нет, только ручная кнопка
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
    _VIEW_NAMES = ("connect", "camera", "results", "gallery", "settings", "about", "help", "profiles")

    def _show(self, name: str) -> None:
        if self.camera_view.visible and name != "camera":
            self.camera.invalidate()  # Flet убирает скрытый виджет камеры вместе с контроллером: при возврате запуск заново
        for view_name in self._VIEW_NAMES:
            getattr(self, f"{view_name}_view").visible = view_name == name
        # на экране камеры строка последней ошибки не нужна (камера должна быть во весь экран без
        # технической информации) — на остальных экранах, включая подключение, она остаётся
        self.diag_text.visible = name != "camera" and bool(self.last_error)
        self.page.update()

    def _open_overlay(self, name: str) -> None:
        """Открывает Галерею/Настройки/О программе/Помощь; «назад» вернёт туда, откуда открыли."""
        self._return_view = "camera" if self.camera_view.visible else "connect"
        self._show(name)

    def on_close_overlay(self, _event) -> None:
        self._show(self._return_view)

    def on_open_gallery(self, _event) -> None:
        self._open_overlay("gallery")

    def on_open_settings(self, _event) -> None:
        self._open_overlay("settings")

    def on_open_about(self, _event) -> None:
        self._open_overlay("about")

    def on_open_help(self, _event) -> None:
        self._open_overlay("help")

    async def on_open_profiles(self, _event) -> None:
        self._open_overlay("profiles")
        await self.editor.open()

    def _remember(self, text: str) -> None:
        self.last_error = text
        self.diag_text.value = f"Последняя ошибка: {text}"
        # на экране камеры строка не показывается (см. _show()); тут же — на случай, если ошибка
        # пришла уже после ухода с камеры (например, «Назад» во время долгого запроса) и нового _show() не будет
        self.diag_text.visible = not self.camera_view.visible

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
        self.camera_title.value = SCAN_HINT if scanning else ""
        self.camera_title.visible = scanning
        # заголовок и подпись съёмки прячутся вместе с кнопкой — иначе при сканировании они бы зависли
        # без кнопки под ними (кнопка скрыта, надписи «СФОТОГРАФИРОВАТЬ»/«Готово к съёмке» — нет)
        self.capture_button.visible = self.capture_title.visible = self.capture_subtitle.visible = not scanning
        self.gallery_button.visible = not scanning
        self.scan_now_button.visible = False  # включится в _start_auto_scan, если автопоток недоступен на телефоне
        self.cancel_scan_button.visible = scanning
        self.camera_message.value = note or ""
        self.camera_message.visible = bool(note)
        self._set_connectivity(self.connection is not None)
        self._show("camera")

    def _set_connectivity(self, ok: bool) -> None:
        """Значок Wi-Fi: обновляется по факту запроса, а не только при заходе на экран камеры —
        иначе он оставался зелёным сколько угодно после того, как сервер на ПК уже выключили."""
        self.wifi_icon.icon = ft.Icons.WIFI if ok else ft.Icons.WIFI_OFF
        self.wifi_icon.color = ft.Colors.GREEN_400 if ok else ft.Colors.RED_400

    def _camera_note(self, text: str) -> None:
        self.camera_message.value = text
        self.camera_message.visible = True
        self._remember(text)
        self.page.update()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        buttons = (
            self.capture_button,
            self.gallery_button,
            self.scan_now_button,
            self.connect_button,
            self.scan_button,
            self.retry_button,
        )
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
        await self._start_auto_scan()

    async def _start_auto_scan(self) -> None:
        """Пробует читать QR из потока кадров камеры без нажатия кнопки; если телефон это не умеет — ручная кнопка."""
        self._scan_busy = False
        self._scan_last = -1e9
        started = self.camera.ready and await self.camera.start_scanning(self._on_scan_frame)
        self.scan_now_button.visible = not started
        if not started:
            self.camera_title.value = SCAN_HINT_MANUAL
        self.page.update()

    async def _on_scan_frame(self, event) -> None:
        """Вызывается на каждый кадр потока камеры, пока идёт сканирование; не чаще scan_interval и не параллельно."""
        now = self._clock()
        if self._scan_busy or now - self._scan_last < self.scan_interval:
            return
        self._scan_busy = True
        self._scan_last = now
        connection = None
        try:
            connection = await asyncio.to_thread(
                self.frame_reader, event.width, event.height, event.encoded_format, event.bytes
            )
        except QrUnavailable:
            await self.camera.stop_scanning()
            self.scan_now_button.visible = True
            self.camera_title.value = SCAN_HINT_MANUAL
            self._camera_note("Автоматическое чтение QR недоступно на этом телефоне: введите адрес и код вручную.")
        except QrImageError:
            pass  # нечитаемый кадр — обычное дело на видео с камеры, просто ждём следующий
        except Exception:  # noqa: BLE001 - поток не должен падать экран, просто пробуем следующий кадр
            pass
        finally:
            self._scan_busy = False
        if connection is None:
            return
        await self.camera.stop_scanning()
        await self._connect(connection, announce=True)

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
        self.back_hint.visible = False
        if self.camera_view.visible:
            # с камеры «Назад» работает сразу, даже если ещё не пришёл ответ на запрос (например, сервер
            # недоступен и «Сфотографировать» повисло) — раньше это на самом деле блокировалось self._busy
            # и «Назад» не реагировал, пока не истечёт таймаут запроса (реальный отзыв пользователя)
            if self.mode == MODE_SCAN:
                await self.camera.stop_scanning()
            self._show_connect()
            return False
        if self._busy:
            return False  # идёт отправка или подключение: не выходим случайно
        if self.results_view.visible:
            await self.on_again(None)
            return False
        if self.profiles_view.visible and self.editor.go_back():
            return False
        if any(getattr(self, f"{name}_view").visible for name in ("gallery", "settings", "about", "help", "profiles")):
            self._show(self._return_view)
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
        await self.camera.stop_scanning()
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
        self.retry_button.visible = False
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
            self._set_connectivity(failure.kind != UNREACHABLE)
            if failure.kind == UNAUTHORIZED:
                self._show_connect(error_text(failure))
            else:
                self._offer_retry(data, error_text(failure))
            return
        if response is None:
            self._set_connectivity(False)  # локальная ошибка (не ClientError) — тоже похоже на обрыв связи
            self._offer_retry(data, message or "Ошибка поиска")
            return
        self._set_connectivity(True)
        self._retry_data = None
        self._remember_history(data, response)
        # пока ждали ответ, могли уйти с камеры (например, «Назад» во время долгого запроса) — тогда
        # снимок всё равно попадёт в историю, но экран самопроизвольно на «Результаты» не переключаем
        if self.camera_view.visible and self.mode == MODE_SHOOT:
            await self._show_results(data, response)

    def _remember_history(self, photo: bytes, response: MatchResponse) -> None:
        """Добавляет успешный поиск в историю этой сессии (самый новый первым, не больше HISTORY_LIMIT)."""
        self.history.insert(0, (photo, response))
        del self.history[HISTORY_LIMIT:]
        self.history_empty.visible = not self.history
        self.history_column.controls = [
            ft.TextButton(
                content=ft.Text(history_text(item), size=12), data=(entry_photo, item), on_click=self.on_history_click
            )
            for entry_photo, item in self.history
        ]

    async def on_history_click(self, event) -> None:
        """Открывает прошлый результат заново, не отправляя фото на ПК повторно."""
        photo, response = event.control.data
        await self._show_results(photo, response)

    async def on_share(self, _event) -> None:
        if self._current_response is None:
            return
        try:
            await self.share.share_text(share_text(self._current_response), subject="GMAGC")
        except Exception:  # noqa: BLE001 - на телефоне может не быть приложения, куда поделиться
            self.copy_note.value = "Не удалось поделиться"
            self.copy_note.visible = True
            self.page.update()

    def _offer_retry(self, data: bytes, message: str) -> None:
        """Запоминает неотправленное фото и предлагает отправить его ещё раз без повторной съёмки."""
        self._retry_data = data
        self.retry_button.visible = True
        self._camera_note(message)

    async def on_retry(self, _event) -> None:
        if self._busy or self._retry_data is None:
            return
        self._set_busy(True)
        await self._search(self._retry_data)

    async def _show_results(self, photo: bytes, response: MatchResponse) -> None:
        self._current_response = response
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
            ft.Row([ft.Text(item.name, weight=ft.FontWeight.BOLD, expand=True), _score_badge(item.score)]),
            ft.Text(item.path, size=12, selectable=False),
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
        """Подгоняет соотношение сторон камеры под реально доступное место, чтобы кадр не сжимался у края."""
        width, height = float(event.width), float(event.height)
        self._preview_size = (width, height)
        if hasattr(self.preview, "aspect_ratio") and width > 0 and height > 0:
            ratio = width / height
            if self.preview.aspect_ratio != ratio:
                self.preview.aspect_ratio = ratio
                self.page.update()

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
        self.focus_button.icon = ft.Icons.CENTER_FOCUS_STRONG if locked else ft.Icons.CENTER_FOCUS_WEAK
        self.focus_button.tooltip = self.focus_text.value
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
        profile_store=ProfileStore(prefs),
        **services,
    )
    page.services.extend([prefs, permission, app.picker, app.clipboard, app.share, launcher])
    app.build()
    await app.start()
    return app
