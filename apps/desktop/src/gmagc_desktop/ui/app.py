"""Экран ПК-приложения: боковая навигация (Поиск/Телефон/Библиотека/Настройки), поиск по фото, сервер телефона."""

from __future__ import annotations

import logging
import os
import platform
import urllib.parse
import webbrowser
from collections.abc import Callable
from pathlib import Path

import cv2
import flet as ft
import numpy as np

from gmagc_common import i18n
from gmagc_common.i18n import CHOICES, FILES_EN, FILES_RU, RESULTS_EN, RESULTS_RU, language_name, plural, t
from gmagc_common.protocol import build_link, format_code
from gmagc_common.theme import (
    DESKTOP_ACCENT,
    DESKTOP_BG,
    DESKTOP_DIM,
    DESKTOP_LINE,
    DESKTOP_MUTED,
    DESKTOP_OK,
    DESKTOP_PANEL,
    DESKTOP_PANEL2,
    DESKTOP_STRONG,
    score_band,
)
from gmagc_desktop import lang_en  # noqa: F401 - при импорте регистрирует английские переводы
from gmagc_desktop.about import AUTHOR, NAME, VERSION
from gmagc_desktop.library.index import IndexCancelled, LibraryNotFound, LibraryScanError
from gmagc_desktop.matcher.adjust import apply_adjustments
from gmagc_desktop.matcher.pipeline import normalize_photo
from gmagc_desktop.matcher.thumbnail import thumbnail_png
from gmagc_desktop.selfcheck import run_core_check
from gmagc_desktop.server.api import RequestRecord
from gmagc_desktop.server.network import lan_addresses
from gmagc_desktop.server.qr import qr_png
from gmagc_desktop.server.runner import PhoneServer, ServerStartError
from gmagc_desktop.service import autostart
from gmagc_desktop.service.fixture_export import default_ma2_dir, default_ma3_dir
from gmagc_desktop.service.logging_setup import setup_logging
from gmagc_desktop.service.results import Outcome, Result, SearchOutcome
from gmagc_desktop.service.reveal import reveal_in_file_manager
from gmagc_desktop.service.search_service import (
    PROJECTION_SIZE,
    CorrectionError,
    NoIndexError,
    PhotoError,
    SearchService,
)
from gmagc_desktop.service.settings import RESULTS_COUNT_CHOICES, data_dir
from gmagc_desktop.ui.support import SupportPrompt
from gmagc_desktop.ui.texts import history_text, outcome_message, score_text, source_text, status_text
from gmagc_desktop.ui.update_bar import UpdateBar
from gmagc_desktop.update.installer import current_executable
from gmagc_desktop.update.manager import UpdateManager

logger = logging.getLogger("gmagc.desktop")
SUPPORT_EMAIL = "yodayodaspace@gmail.com"

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
HISTORY_LIMIT = 10

BRIGHTNESS_RANGE = (-80.0, 80.0)
CONTRAST_RANGE = (0.5, 2.0)
EXPOSURE_RANGE = (-2.0, 2.0)

_VIEW_NAMES = ("search", "phone", "library", "settings")


def no_library_hint() -> str:
    return t("Сначала выберите папку библиотеки и постройте индекс")


def phone_hint() -> str:
    return t("Телефон и ПК должны быть в одной сети Wi-Fi. При первом запуске разрешите доступ в брандмауэре Windows.")


def onboarding_hint() -> str:
    return t(
        "Добро пожаловать! Откройте экран «Библиотека» слева, чтобы выбрать папку гобо и построить индекс — "
        "после этого можно искать по фото (файл или буфер обмена) или подключить телефон на экране «Телефон»."
    )


def _screen_label(name: str) -> str:
    """Название экрана на текущем языке (для заголовка и хлебных крошек)."""
    labels = {"search": t("Поиск гобо"), "phone": t("Телефон"), "library": t("Библиотека"), "settings": t("Настройки")}
    return labels[name]


_BADGE_COLORS = {
    "good": (ft.Colors.GREEN_100, ft.Colors.GREEN_900),
    "low": (ft.Colors.AMBER_100, ft.Colors.AMBER_900),
    "bad": (ft.Colors.RED_100, ft.Colors.RED_900),
}


def _signed(value: float, decimals: int) -> str:
    return f"{value:+.{decimals}f}" if value else f"{value:.{decimals}f}"


def _score_badge(score: float) -> ft.Container:
    """Цветной бейдж оценки на карточке результата: зелёный/жёлтый/красный по порогу совпадения."""
    bgcolor, color = _BADGE_COLORS[score_band(score)]
    return ft.Container(
        ft.Text(score_text(score), size=11, weight=ft.FontWeight.BOLD, color=color),
        bgcolor=bgcolor,
        border_radius=10,
        padding=ft.Padding.symmetric(horizontal=7, vertical=2),
    )


def _panel(controls: list[ft.Control], *, width: int | None = None, expand: bool | int = False) -> ft.Container:
    """Плоская панель-секция без тени (в отличие от Material-карточки) — «Библиотека», «Телефон» и т.п."""
    return ft.Container(
        ft.Column(controls, spacing=10),
        padding=16,
        bgcolor=DESKTOP_PANEL,
        border=ft.Border.all(1, DESKTOP_LINE),
        border_radius=2,
        width=width,
        expand=expand,
    )


def _nav_item(icon: str, label: str, on_click) -> ft.Container:
    """Пункт боковой навигации; активный/неактивный вид переключает DesktopApp._show()."""
    return ft.Container(
        ft.Row([ft.Icon(icon, size=18), ft.Text(label, size=13, expand=True)], spacing=10),
        padding=ft.Padding.symmetric(horizontal=10, vertical=11),
        border_radius=2,
        on_click=on_click,
    )


def _theme(large_text: bool) -> ft.Theme:
    """Тёмная палитра ПК-приложения по макету пользователя (боковая панель, бирюзовый акцент) — светлой темы нет.

    large_text увеличивает шрифт без явно заданного размера — для тёмных залов; часть подписей
    задаёт свой размер напрямую и крупным текстом не увеличивается."""
    base = {
        "use_material3": True,
        "color_scheme_seed": DESKTOP_ACCENT,
        "scaffold_bgcolor": DESKTOP_BG,
        "card_bgcolor": DESKTOP_PANEL,
    }
    if not large_text:
        return ft.Theme(**base)
    return ft.Theme(
        **base,
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
        log_path: Path | None = None,
    ):
        self.page = page
        self.service = service
        self.picker = picker or ft.FilePicker()
        self.clipboard = clipboard or ft.Clipboard()
        self.rebuilt_as: DesktopApp | None = None  # новый экземпляр после смены языка (этот уже не используется)
        self.reveal = reveal
        self._open_url = open_url
        self._log_path = log_path or (service.data_dir / "gmagc.log")
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
        # всё, что нужно, чтобы собрать приложение заново на тех же службах (смена языка без перезапуска);
        # окно поддержки и счётчик запусков при пересборке не повторяются
        self._kwargs = {
            "picker": self.picker,
            "clipboard": self.clipboard,
            "reveal": reveal,
            "check": check,
            "server": self.server,
            "addresses": addresses,
            "qr": qr,
            "updates": updates,
            "open_url": open_url,
            "quit_app": quit_app,
            "update_delay": update_delay,
            "support": False,
            "support_delay": support_delay,
            "log_path": self._log_path,
        }
        self.history: list[RequestRecord] = []
        self._busy = False
        self._cancel = False
        self._last_query_photo: bytes | None = None  # для повтора поиска сразу после «Это не то»
        self._last_search_ms: float | None = None
        self._last_score: float | None = None
        self._adjust_brightness = 0.0
        self._adjust_contrast = 1.0
        self._adjust_exposure = 0.0
        self._proj_adjust_brightness = 0.0
        self._proj_adjust_contrast = 1.0
        self._proj_adjust_exposure = 0.0

        self.splash = ft.Container(
            ft.Image(src="logo.svg", width=140, height=140, fit=ft.BoxFit.CONTAIN),
            alignment=ft.Alignment.CENTER,
            expand=True,
            bgcolor=ft.Colors.with_opacity(0.92, ft.Colors.BLACK),
        )

        # ---- навигация -----------------------------------------------------------
        self.current_view = "search"
        self.breadcrumb = ft.Text(f"GMAGC / {_screen_label('search')}", size=12, color=DESKTOP_MUTED)
        self._nav_containers: dict[str, ft.Container] = {}

        # ---- метрики и статус-строка ------------------------------------------------
        self.metric_files = ft.Text("0", size=13)
        self.metric_time = ft.Text("—", size=13)
        self.metric_score = ft.Text("—", size=13)
        self.statusbar_index = ft.Text("INDEX: NOT BUILT", size=9, color=DESKTOP_DIM)

        # ---- подсказка при первом запуске -------------------------------------------
        self.onboarding_text = ft.Text(onboarding_hint(), size=13)
        self.onboarding_dismiss_button = ft.TextButton(
            content=ft.Text(t("Понятно"), size=12), on_click=self.on_dismiss_onboarding
        )
        self.onboarding_goto_library_button = ft.TextButton(
            content=ft.Text(t("Перейти в «Библиотека»"), size=12), on_click=lambda _e: self._show("library")
        )
        self.onboarding_hint = ft.Container(
            ft.Column(
                [self.onboarding_text, ft.Row([self.onboarding_goto_library_button, self.onboarding_dismiss_button])],
                spacing=2,
            ),
            padding=12,
            border_radius=2,
            bgcolor=DESKTOP_PANEL2,
            border=ft.Border.all(1, DESKTOP_LINE),
            visible=False,
        )

        # ---- библиотека ------------------------------------------------------------
        self.library_text = ft.Text(t("не выбрана"), selectable=True)
        self.status_label = ft.Text(t("Индекс не построен"))
        self.progress = ft.ProgressBar(value=0, visible=False)
        self.progress_label = ft.Text(visible=False)
        self.choose_folder_button = ft.Button(t("Выбрать папку…"), on_click=self.on_choose_folder)
        self.rebuild_button = ft.Button(t("Обновить индекс"), on_click=self.on_rebuild)
        self.cancel_button = ft.Button(t("Отмена"), on_click=self.on_cancel, visible=False)

        # ---- поиск -------------------------------------------------------------
        self.pick_photo_button = ft.Button(t("Выбрать фото…"), on_click=self.on_pick_photo)
        self.paste_button = ft.Button(t("Вставить из буфера"), on_click=self.on_paste)
        self.banner_text = ft.Text(color=ft.Colors.BLACK)
        self.banner = ft.Container(self.banner_text, padding=10, border_radius=2, visible=False)
        self.source_label = ft.Text("", visible=False, size=11, color=DESKTOP_MUTED)
        self.photo_holder = ft.Column(visible=False, spacing=4)
        self.projection_holder = ft.Column(visible=False, spacing=4)
        self.adjust_brightness_label = ft.Text(t("Яркость: 0"), size=11, color=DESKTOP_MUTED)
        self.adjust_brightness_slider = ft.Slider(
            min=BRIGHTNESS_RANGE[0],
            max=BRIGHTNESS_RANGE[1],
            value=0.0,
            divisions=32,
            on_change=self.on_adjust_change,
            on_change_end=self.on_adjust_commit,
        )
        self.adjust_contrast_label = ft.Text(t("Контраст: 1.0×"), size=11, color=DESKTOP_MUTED)
        self.adjust_contrast_slider = ft.Slider(
            min=CONTRAST_RANGE[0],
            max=CONTRAST_RANGE[1],
            value=1.0,
            divisions=15,
            on_change=self.on_adjust_change,
            on_change_end=self.on_adjust_commit,
        )
        self.adjust_exposure_label = ft.Text(t("Экспозиция: 0 EV"), size=11, color=DESKTOP_MUTED)
        self.adjust_exposure_slider = ft.Slider(
            min=EXPOSURE_RANGE[0],
            max=EXPOSURE_RANGE[1],
            value=0.0,
            divisions=40,
            on_change=self.on_adjust_change,
            on_change_end=self.on_adjust_commit,
        )
        self.adjust_reset_button = ft.TextButton(content=ft.Text(t("Сбросить")), on_click=self.on_reset_adjustments)
        self.adjust_panel = ft.Column(
            [
                ft.Text(t("Поправка фото"), size=12, weight=ft.FontWeight.W_600),
                self.adjust_brightness_label,
                self.adjust_brightness_slider,
                self.adjust_contrast_label,
                self.adjust_contrast_slider,
                self.adjust_exposure_label,
                self.adjust_exposure_slider,
                self.adjust_reset_button,
            ],
            spacing=2,
            visible=False,
        )
        self.proj_adjust_brightness_label = ft.Text(t("Яркость: 0"), size=11, color=DESKTOP_MUTED)
        self.proj_adjust_brightness_slider = ft.Slider(
            min=BRIGHTNESS_RANGE[0],
            max=BRIGHTNESS_RANGE[1],
            value=0.0,
            divisions=32,
            on_change=self.on_proj_adjust_change,
            on_change_end=self.on_proj_adjust_commit,
        )
        self.proj_adjust_contrast_label = ft.Text(t("Контраст: 1.0×"), size=11, color=DESKTOP_MUTED)
        self.proj_adjust_contrast_slider = ft.Slider(
            min=CONTRAST_RANGE[0],
            max=CONTRAST_RANGE[1],
            value=1.0,
            divisions=15,
            on_change=self.on_proj_adjust_change,
            on_change_end=self.on_proj_adjust_commit,
        )
        self.proj_adjust_exposure_label = ft.Text(t("Экспозиция: 0 EV"), size=11, color=DESKTOP_MUTED)
        self.proj_adjust_exposure_slider = ft.Slider(
            min=EXPOSURE_RANGE[0],
            max=EXPOSURE_RANGE[1],
            value=0.0,
            divisions=40,
            on_change=self.on_proj_adjust_change,
            on_change_end=self.on_proj_adjust_commit,
        )
        self.proj_adjust_reset_button = ft.TextButton(
            content=ft.Text(t("Сбросить")), on_click=self.on_reset_proj_adjustments
        )
        self.proj_adjust_panel = ft.Column(
            [
                ft.Text(t("Поправка найденной проекции"), size=12, weight=ft.FontWeight.W_600),
                self.proj_adjust_brightness_label,
                self.proj_adjust_brightness_slider,
                self.proj_adjust_contrast_label,
                self.proj_adjust_contrast_slider,
                self.proj_adjust_exposure_label,
                self.proj_adjust_exposure_slider,
                self.proj_adjust_reset_button,
            ],
            spacing=2,
            visible=False,
        )
        # GridView (не Row с wrap=True) — переносит карточки по строкам в реально доступной ширине панели,
        # а не только визуально «внутри себя» без учёта родителя (проверено скриншотом: с Row карточки
        # обрезались по правому краю панели вместо переноса)
        self.results_column = ft.GridView(max_extent=200, spacing=10, run_spacing=10, child_aspect_ratio=0.8, expand=True)
        self.results_summary = ft.Text("", size=11, color=DESKTOP_DIM)
        self.copy_label = ft.Text("", size=12, visible=False, selectable=True)

        # ---- настройки ---------------------------------------------------------
        self.check_label = ft.Text("", size=12)
        self.large_text_switch = ft.Switch(label=t("Крупный текст"), value=False, on_change=self.on_toggle_large_text)
        self.autostart_switch = ft.Switch(
            label=t("Автозапуск при включении компьютера"), value=False, on_change=self.on_toggle_autostart
        )
        # папки для типов приборов, присланных с телефона: пусто — приложение ищет папки grandMA само
        self.ma3_dir_field = ft.TextField(
            label=t("Папка типов приборов grandMA3"),
            on_blur=self.on_fixture_dirs_change,
            on_submit=self.on_fixture_dirs_change,
            width=520,
        )
        self.ma2_dir_field = ft.TextField(
            label=t("Папка типов приборов grandMA2 (importexport)"),
            on_blur=self.on_fixture_dirs_change,
            on_submit=self.on_fixture_dirs_change,
            width=520,
        )
        # ключ облачного распознавания инструкций: нужен только для кнопки «Распознать в облаке» на телефоне
        self.cloud_key_field = ft.TextField(
            label=t("Ключ Anthropic для облачного распознавания инструкций"),
            helper=t("Необязательно. Файл уходит в облако только по кнопке на телефоне и после подтверждения."),
            password=True,
            can_reveal_password=True,
            on_blur=self.on_cloud_key_change,
            on_submit=self.on_cloud_key_change,
            width=520,
        )
        self.language_dropdown = ft.Dropdown(
            label="Язык / Language",
            value=self.service.settings.language,
            options=[ft.DropdownOption(key=choice, text=language_name(choice)) for choice in CHOICES],
            on_select=self.on_language_change,
            width=240,
        )
        self.results_count_dropdown = ft.Dropdown(
            label=t("Число результатов поиска"),
            value="50",
            options=[ft.DropdownOption(key=str(n), text=str(n)) for n in RESULTS_COUNT_CHOICES],
            on_select=self.on_results_count_change,
            width=240,
        )

        # ---- сервер для телефона -----------------------------------------------
        self.server_switch = ft.Switch(label=t("Сервер для телефона"), value=False, on_change=self.on_toggle_server)
        self.server_status = ft.Text(t("Выключен"))
        self.qr_holder = ft.Column(visible=False)
        self.code_text = ft.Text("", size=16, weight=ft.FontWeight.BOLD, selectable=True, visible=False)
        self.code_row = ft.Row(
            [
                ft.TextButton(content=ft.Text(t("Копировать код")), on_click=self.on_copy_code),
                ft.TextButton(content=ft.Text(t("Новый код")), on_click=self.on_new_code),
            ],
            spacing=4,
            visible=False,
        )
        self.phone_note = ft.Text("", size=12, visible=False)
        self.addresses_text = ft.Text("", size=12, visible=False, selectable=True)
        self.history_title = ft.Text(t("Запросы с телефона"), size=14, weight=ft.FontWeight.BOLD, visible=False)
        self.history_column = ft.Column(spacing=0)

    # ---- построение экрана -------------------------------------------------
    def build(self) -> None:
        # сплэш сразу, до тяжёлой части построения экрана — окно не остаётся пустым, пока грузятся настройки/индекс
        self.page.add(self.splash)
        self.page.update()
        self._finish_build()

    def _metric(self, label: str, value: ft.Text) -> ft.Column:
        return ft.Column(
            [value, ft.Text(label.upper(), size=9, color=DESKTOP_DIM)],
            spacing=2,
        )

    def _build_sidebar(self) -> ft.Container:
        nav_specs = [
            (ft.Icons.SEARCH, _screen_label("search"), "search"),
            (ft.Icons.SMARTPHONE, _screen_label("phone"), "phone"),
            (ft.Icons.FOLDER_OUTLINED, _screen_label("library"), "library"),
        ]
        nav_items = []
        for icon, label, name in nav_specs:
            item = _nav_item(icon, label, lambda _e, n=name: self._show(n))
            self._nav_containers[name] = item
            nav_items.append(item)
        settings_item = _nav_item(ft.Icons.SETTINGS_OUTLINED, _screen_label("settings"), lambda _e: self._show("settings"))
        self._nav_containers["settings"] = settings_item

        return ft.Container(
            ft.Column(
                [
                    ft.Container(
                        ft.Row(
                            [
                                ft.Image(src="logo.svg", width=28, height=28, fit=ft.BoxFit.CONTAIN),
                                ft.Text(NAME, size=16, weight=ft.FontWeight.W_800),
                            ],
                            spacing=10,
                        ),
                        padding=ft.Padding.symmetric(horizontal=18, vertical=0),
                        height=64,
                        alignment=ft.Alignment.CENTER_LEFT,
                    ),
                    ft.Container(height=1, bgcolor=DESKTOP_LINE),
                    ft.Container(
                        ft.Column(
                            [ft.Text(t("РАБОЧАЯ ОБЛАСТЬ"), size=9, color=DESKTOP_DIM), *nav_items],
                            spacing=6,
                        ),
                        padding=ft.Padding.symmetric(horizontal=10, vertical=14),
                    ),
                    ft.Container(height=40),
                    ft.Container(
                        ft.Column([ft.Text(t("СИСТЕМА"), size=9, color=DESKTOP_DIM), settings_item], spacing=6),
                        padding=ft.Padding.symmetric(horizontal=10, vertical=6),
                    ),
                    ft.Container(height=1, bgcolor=DESKTOP_LINE),
                    ft.Container(
                        ft.Column(
                            [
                                ft.Row(
                                    [
                                        ft.Icon(ft.Icons.CIRCLE, size=7, color=DESKTOP_OK),
                                        ft.Text(t("Система готова"), size=11, color=DESKTOP_MUTED),
                                    ],
                                    spacing=7,
                                ),
                                ft.Row(
                                    [
                                        ft.Text(AUTHOR, size=10, color=DESKTOP_DIM),
                                        ft.Text(f"v{VERSION}", size=10, color=DESKTOP_DIM),
                                    ],
                                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                ),
                            ],
                            spacing=10,
                        ),
                        padding=16,
                    ),
                ],
                spacing=0,
            ),
            width=224,
            bgcolor=DESKTOP_BG,
        )

    def _build_topbar(self) -> ft.Container:
        return ft.Container(
            self.breadcrumb,
            padding=ft.Padding.symmetric(horizontal=22, vertical=0),
            height=48,
            alignment=ft.Alignment.CENTER_LEFT,
        )

    def _build_statusbar(self) -> ft.Container:
        return ft.Container(
            ft.Row(
                [
                    ft.Text("OFFLINE MODE", size=9, color=DESKTOP_DIM),
                    self.statusbar_index,
                    ft.Text(f"DEVICE: {platform.system().upper() or 'DESKTOP'}", size=9, color=DESKTOP_DIM),
                    ft.Text(f"PYTHON {platform.python_version()}", size=9, color=DESKTOP_DIM),
                    ft.Text("FLET", size=9, color=DESKTOP_DIM),
                ],
                spacing=16,
            ),
            padding=ft.Padding.symmetric(horizontal=12, vertical=0),
            height=30,
        )

    def _build_search_view(self) -> ft.Column:
        heading = ft.Row(
            [
                ft.Column(
                    [
                        ft.Text(t("Поиск по изображению"), size=22, weight=ft.FontWeight.BOLD),
                        ft.Text(
                            t("Загрузите фотографию проекции, чтобы найти совпадение в библиотеке."),
                            size=11,
                            color=DESKTOP_MUTED,
                        ),
                    ],
                    spacing=4,
                ),
                ft.Row(
                    [
                        self._metric(t("гобо в базе"), self.metric_files),
                        self._metric(t("время поиска"), self.metric_time),
                        self._metric(t("совпадение"), self.metric_score),
                    ],
                    spacing=22,
                ),
            ],
            spacing=40,
        )
        source_panel = ft.Container(
            ft.Column(
                [
                    ft.Text(t("Исходное изображение"), size=12, weight=ft.FontWeight.W_600),
                    self.source_label,
                    ft.Container(
                        ft.Column(
                            [self.photo_holder, self.projection_holder],
                            spacing=12,
                            alignment=ft.MainAxisAlignment.CENTER,
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        border=ft.Border.all(1, DESKTOP_STRONG),
                        bgcolor=DESKTOP_BG,
                        padding=14,
                        alignment=ft.Alignment.CENTER,
                        clip_behavior=ft.ClipBehavior.HARD_EDGE,
                    ),
                    ft.Row([self.pick_photo_button, self.paste_button], spacing=8),
                    self.adjust_panel,
                    self.proj_adjust_panel,
                ],
                spacing=10,
                expand=True,
                scroll=ft.ScrollMode.AUTO,
            ),
            padding=14,
            bgcolor=DESKTOP_PANEL,
            border=ft.Border.all(1, DESKTOP_LINE),
            width=360,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )
        results_panel = ft.Container(
            ft.Column(
                [
                    ft.Row(
                        [ft.Text(t("Результаты"), size=12, weight=ft.FontWeight.W_600), self.results_summary],
                        spacing=10,
                    ),
                    self.banner,
                    self.copy_label,
                    ft.Container(self.results_column, expand=True),
                ],
                spacing=10,
                expand=True,
            ),
            padding=14,
            bgcolor=DESKTOP_PANEL2,
            border=ft.Border.all(1, DESKTOP_LINE),
            expand=True,
        )
        return ft.Column(
            [
                self.onboarding_hint,
                heading,
                ft.Row(
                    [source_panel, results_panel],
                    spacing=14,
                    expand=True,
                    vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                ),
            ],
            spacing=16,
            expand=True,
            visible=False,
        )

    def _build_phone_view(self) -> ft.Column:
        connection_card = _panel(
            [
                ft.Text(t("Параметры подключения"), size=14, weight=ft.FontWeight.BOLD),
                self.server_switch,
                self.server_status,
                self.code_text,
                self.code_row,
                self.phone_note,
                self.addresses_text,
                ft.Text(phone_hint(), size=12, color=DESKTOP_MUTED),
            ],
            expand=True,
        )
        qr_card = _panel([ft.Text(t("QR-код подключения"), size=14, weight=ft.FontWeight.BOLD), self.qr_holder], width=280)
        history_card = _panel([self.history_title, self.history_column])
        return ft.Column(
            [
                ft.Text(t("Подключение телефона"), size=22, weight=ft.FontWeight.BOLD),
                ft.Row([connection_card, qr_card], spacing=14, vertical_alignment=ft.CrossAxisAlignment.START),
                history_card,
            ],
            spacing=16,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            visible=False,
        )

    def _build_library_view(self) -> ft.Column:
        card = _panel(
            [
                ft.Text(t("Текущая библиотека"), size=14, weight=ft.FontWeight.BOLD),
                self.library_text,
                ft.Row([self.choose_folder_button, self.rebuild_button], spacing=8),
                self.status_label,
                self.progress,
                self.progress_label,
                self.cancel_button,
            ]
        )
        return ft.Column(
            [ft.Text(t("Библиотека гобо"), size=22, weight=ft.FontWeight.BOLD), card],
            spacing=16,
            expand=True,
            visible=False,
        )

    def _settings_row(self, label: str, button_text: str, on_click) -> ft.Row:
        return ft.Row(
            [
                ft.Text(label, size=13, expand=True),
                ft.TextButton(content=ft.Text(button_text), on_click=on_click),
            ]
        )

    def _build_settings_view(self) -> ft.Column:
        items: list[ft.Control] = [self.large_text_switch]
        if autostart.is_supported():
            items.append(self.autostart_switch)
        items.append(self.results_count_dropdown)
        items.append(self.language_dropdown)
        items += [ft.Divider(color=DESKTOP_LINE), self.ma3_dir_field, self.ma2_dir_field, self.cloud_key_field]
        items += [
            ft.Divider(color=DESKTOP_LINE),
            self._settings_row(t("Экспорт настроек"), t("Экспорт…"), self.on_export_settings),
            self._settings_row(t("Импорт настроек"), t("Импорт…"), self.on_import_settings),
            ft.Divider(color=DESKTOP_LINE),
            self._settings_row(t("Проверить ядро"), t("Проверить"), self.on_check),
            self.check_label,
        ]
        if self.update_bar is not None:
            items += [
                ft.Divider(color=DESKTOP_LINE),
                self.update_bar.switch,
                ft.Row([ft.Text(t("Проверить сейчас"), size=13, expand=True), self.update_bar.check_button]),
                self.update_bar.status,
            ]
        items += [
            ft.Divider(color=DESKTOP_LINE),
            self._settings_row(t("Диагностика"), t("Отправить лог по почте"), self.on_send_log),
        ]
        if self.support is not None:
            items += [
                ft.Divider(color=DESKTOP_LINE),
                self.support.link,
                self.support.telegram_link,
                self.support.channel_link,
            ]
        card = _panel(items)
        return ft.Column(
            [ft.Text(t("Настройки"), size=22, weight=ft.FontWeight.BOLD), card],
            spacing=16,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            visible=False,
        )

    def _show(self, name: str) -> None:
        self.current_view = name
        for view_name in _VIEW_NAMES:
            getattr(self, f"{view_name}_view").visible = view_name == name
        for nav_name, container in self._nav_containers.items():
            container.bgcolor = DESKTOP_PANEL2 if nav_name == name else None
        self.breadcrumb.value = f"GMAGC / {_screen_label(name)}"
        self.page.update()

    def _update_metrics(self) -> None:
        status = self.service.status()
        self.metric_files.value = f"{status.files:,}".replace(",", " ") if status else "0"
        self.metric_time.value = f"{self._last_search_ms:.0f} ms" if self._last_search_ms is not None else "—"
        self.metric_score.value = score_text(self._last_score) if self._last_score is not None else "—"

    def _update_statusbar(self) -> None:
        self.statusbar_index.value = f"INDEX: {'READY' if self.service.status() else 'NOT BUILT'}"

    def _update_results_summary(self) -> None:
        count = len(self.results_column.controls)
        results = plural(count, RESULTS_RU, RESULTS_EN)
        self.results_summary.value = t("{count} {results}", count=count, results=results) if count else ""

    def _finish_build(self) -> None:
        status = self.service.load()
        self.library_text.value = self.service.settings.library_dir or t("не выбрана")
        self.onboarding_hint.visible = not self.service.settings.library_dir
        self.status_label.value = status_text(status)
        if self.update_bar is not None:
            self.update_bar.switch.value = self.service.settings.check_updates
        self.large_text_switch.value = self.service.settings.large_text
        self.results_count_dropdown.value = str(self.service.settings.results_count)
        self.language_dropdown.value = self.service.settings.language
        self.ma3_dir_field.value = self.service.settings.ma3_fixture_dir
        self.ma2_dir_field.value = self.service.settings.ma2_fixture_dir
        self.cloud_key_field.value = self.service.settings.anthropic_api_key
        self.ma3_dir_field.hint_text = self._fixture_hint(default_ma3_dir())
        self.ma2_dir_field.hint_text = self._fixture_hint(default_ma2_dir())
        self._apply_theme()
        if autostart.is_supported():
            self.autostart_switch.value = autostart.is_autostart_enabled()
        for service in (self.picker, self.clipboard):
            if service not in self.page.services:  # при пересборке те же службы уже добавлены
                self.page.services.append(service)
        self.page.on_keyboard_event = self.on_key
        if self.service.settings.server_enabled:
            self.server_switch.value = True
            self._start_server()
        self._update_metrics()
        self._update_statusbar()

        self.search_view = self._build_search_view()
        self.phone_view = self._build_phone_view()
        self.library_view = self._build_library_view()
        self.settings_view = self._build_settings_view()

        self.page.clean()
        self.page.add(
            ft.SafeArea(
                ft.Row(
                    [
                        self._build_sidebar(),
                        ft.Container(width=1, bgcolor=DESKTOP_LINE),
                        ft.Column(
                            [
                                *([self.update_bar.container] if self.update_bar else []),
                                self._build_topbar(),
                                ft.Container(height=1, bgcolor=DESKTOP_LINE),
                                ft.Container(
                                    ft.Column(
                                        [self.search_view, self.phone_view, self.library_view, self.settings_view],
                                        expand=True,
                                    ),
                                    padding=24,
                                    expand=True,
                                ),
                                ft.Container(height=1, bgcolor=DESKTOP_LINE),
                                self._build_statusbar(),
                            ],
                            expand=True,
                            spacing=0,
                        ),
                    ],
                    expand=True,
                    spacing=0,
                ),
                expand=True,
            )
        )
        self._show("search")
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
        if error:
            logger.error(text)  # попадает в лог-файл — можно приложить письмом («Отправить лог по почте»)
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
            self.server_status.value = t("Не удалось запустить: {error}", error=error)
        elif not running:
            self.server_status.value = t("Выключен")
        elif not addresses:
            self.server_status.value = t(
                "Работает на порту {port}, но адрес ПК в сети не найден: подключите ПК к Wi-Fi", port=self.server.port
            )
        else:
            host, port = addresses[0], self.server.port
            code = self.service.ensure_access_code()
            self.server_status.value = t("Работает: {host}:{port}", host=host, port=port)
            self.qr_holder.controls = [
                ft.Image(src=self.qr(build_link(host, port, code)), width=220, height=220, fit=ft.BoxFit.CONTAIN)
            ]
            self.code_text.value = t("Код: {format_code}", format_code=format_code(code))
            self.addresses_text.value = t("Другие адреса ПК: ") + ", ".join(addresses[1:])
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
        self.phone_note.value = t("Код скопирован")
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
        self._last_query_photo = record.photo
        self._reset_all_adjustments()
        self._show_photo(record.photo)
        self._show_outcome(record.outcome)
        self._show("search")  # результат с телефона должен быть сразу виден, на каком бы экране ни были

    def on_dismiss_onboarding(self, _event) -> None:
        self.onboarding_hint.visible = False
        self.page.update()

    # ---- индексация --------------------------------------------------------
    async def on_choose_folder(self, _event) -> None:
        folder = await self.picker.get_directory_path(dialog_title=t("Папка библиотеки гобо"))
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
            self._show_banner(no_library_hint(), error=True)
            return
        self._cancel = False
        self._hide_banner()
        self._set_busy(True, indexing=True)
        self.page.run_thread(self._index_worker)

    def _index_worker(self) -> None:
        try:
            self.service.build_index(progress=self._on_progress, cancel=lambda: self._cancel)
        except IndexCancelled:
            self._show_banner(t("Индексация отменена"), error=False)
        except (LibraryNotFound, LibraryScanError) as error:
            self._show_banner(str(error), error=True)
        except Exception as error:  # noqa: BLE001 - рабочий поток обязан показать причину, а не пропасть
            self._show_banner(t("Ошибка индексации: {error}", error=error), error=True)
        finally:
            self.status_label.value = status_text(self.service.status())
            self._update_metrics()
            self._update_statusbar()
            self._set_busy(False)

    def _on_progress(self, done: int, total: int) -> None:
        self.progress.value = done / total if total else 0
        self.progress_label.value = t("Индексация: {done} из {total}", done=done, total=total)
        self.page.update()

    # ---- поиск -------------------------------------------------------------
    async def on_pick_photo(self, _event) -> None:
        files = await self.picker.pick_files(dialog_title=t("Фото проекции"), file_type=ft.FilePickerFileType.IMAGE)
        if files and files[0].path:
            self._search_bytes_from(Path(files[0].path))

    def _apply_theme(self) -> None:
        theme = _theme(self.service.settings.large_text)
        self.page.theme = theme
        self.page.dark_theme = theme
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.update()

    def on_toggle_large_text(self, _event) -> None:
        self.service.set_large_text(bool(self.large_text_switch.value))
        self._apply_theme()

    @staticmethod
    def _fixture_hint(found) -> str:
        return t("по умолчанию: {found}", found=found) if found else t("папка не найдена, укажите её")

    def on_fixture_dirs_change(self, _event) -> None:
        self.service.set_fixture_dirs(self.ma3_dir_field.value or "", self.ma2_dir_field.value or "")

    def on_cloud_key_change(self, _event) -> None:
        self.service.set_cloud_key(self.cloud_key_field.value or "")

    def on_language_change(self, _event) -> None:
        """Выбор языка: сохраняется и применяется сразу, интерфейс собирается заново на новом языке."""
        choice = self.language_dropdown.value or "auto"
        self.service.set_language(choice)
        i18n.set_language(choice)
        self.rebuild("settings")

    def rebuild(self, view: str = "settings") -> DesktopApp:
        """Собирает приложение заново на тех же службах (индекс, сервер, настройки сохраняются) и открывает экран `view`.

        Временное состояние экрана (текущее фото и результаты) теряется."""
        fresh = DesktopApp(self.page, self.service, **self._kwargs)
        fresh.build()
        fresh._show(view)
        self.rebuilt_as = fresh
        return fresh

    def on_results_count_change(self, _event) -> None:
        self.service.set_results_count(int(self.results_count_dropdown.value))

    def on_toggle_autostart(self, _event) -> None:
        target = bool(self.autostart_switch.value)
        exe = current_executable()
        if exe is None:
            self.autostart_switch.value = False
            self._show_banner(t("Не удалось определить путь к приложению"), error=True)
            self.page.update()
            return
        autostart.set_autostart(target, exe)
        self.page.update()

    async def on_key(self, event) -> None:
        """Ctrl+V — вставить фото из буфера, F5 — обновить индекс: горячие клавиши для частой работы."""
        if event.ctrl and event.key == "V":
            await self.on_paste(None)
        elif event.key == "F5":
            await self.on_rebuild(None)

    async def on_export_settings(self, _event) -> None:
        data = self.service.export_settings_json().encode("utf-8")
        path = await self.picker.save_file(
            dialog_title=t("Экспорт настроек"), file_name="gmagc-settings.json", allowed_extensions=["json"], src_bytes=data
        )
        if path:
            self._show_banner(t("Настройки сохранены: {path}", path=path), error=False)

    async def on_import_settings(self, _event) -> None:
        files = await self.picker.pick_files(dialog_title=t("Импорт настроек"), allowed_extensions=["json"])
        if not files:
            return
        try:
            raw = files[0].bytes if files[0].bytes else Path(files[0].path).read_bytes()
            text = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError) as error:
            self._show_banner(t("Не удалось прочитать файл: {error}", error=error), error=True)
            return
        self.service.import_settings_json(text)
        status = self.service.load()
        self.library_text.value = self.service.settings.library_dir or t("не выбрана")
        self.onboarding_hint.visible = not self.service.settings.library_dir
        self.status_label.value = status_text(status)
        if self.update_bar is not None:
            self.update_bar.switch.value = self.service.settings.check_updates
        self._update_metrics()
        self._update_statusbar()
        self._show_banner(
            t("Настройки импортированы. Сервер для телефона и код доступа применятся после перезапуска приложения."),
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
        self._show_banner(t("В буфере обмена нет картинки или файла-изображения"), error=True)

    def _search_bytes_from(self, path: Path) -> None:
        try:
            data = path.read_bytes()
        except OSError as error:
            self._show_banner(t("Не удалось прочитать файл: {error}", error=error), error=True)
            return
        self._start_search(data)

    def _start_search(self, data: bytes) -> None:
        if self._busy:
            return
        if self.service.status() is None:
            self._show_banner(no_library_hint(), error=True)
            return
        self._hide_banner()
        self.source_label.visible = False
        self._last_query_photo = data
        self._reset_all_adjustments()
        self._show_photo(data)
        self._set_busy(True)
        self.page.run_thread(lambda: self._search_worker(data))

    def _run_search_and_show(self, run: Callable[[], SearchOutcome]) -> None:
        try:
            outcome = run()
        except NoIndexError:
            self._show_banner(no_library_hint(), error=True)
        except PhotoError as error:
            self._show_banner(t("Не удалось прочитать фото: {error}", error=error), error=True)
        except Exception as error:  # noqa: BLE001 - рабочий поток обязан показать причину, а не пропасть
            self._show_banner(t("Ошибка поиска: {error}", error=error), error=True)
        else:
            self._show_outcome(outcome)
        finally:
            self._set_busy(False)

    def _search_worker(self, data: bytes) -> None:
        self._run_search_and_show(
            lambda: self.service.search_image_bytes(
                data,
                top_n=self.service.settings.results_count,
                projection_brightness=self._proj_adjust_brightness,
                projection_contrast=self._proj_adjust_contrast,
                projection_exposure=self._proj_adjust_exposure,
            )
        )

    def _search_worker_array(self, photo_bgr: np.ndarray) -> None:
        self._run_search_and_show(
            lambda: self.service.search_photo(
                photo_bgr,
                top_n=self.service.settings.results_count,
                projection_brightness=self._proj_adjust_brightness,
                projection_contrast=self._proj_adjust_contrast,
                projection_exposure=self._proj_adjust_exposure,
            )
        )

    def _update_photo_preview(self, data: bytes) -> None:
        self.photo_holder.controls = [
            ft.Text(t("Фото"), size=11, color=DESKTOP_MUTED),
            ft.Image(src=data, width=150, height=110, fit=ft.BoxFit.CONTAIN),
        ]
        self.photo_holder.visible = True

    def _show_photo(self, data: bytes) -> None:
        self._update_photo_preview(data)
        self.adjust_panel.visible = True
        self.projection_holder.visible = False
        self.results_column.controls = []
        self._update_results_summary()
        self.copy_label.visible = False
        self.page.update()

    def _update_live_previews(self) -> None:
        """Пока ползунок ещё двигают: пересчитывает превью фото и проекции без запуска поиска по библиотеке."""
        photo = self._current_photo_array()
        if photo is None:
            return
        ok, encoded = cv2.imencode(".png", photo)
        if ok:
            self._update_photo_preview(bytes(encoded))
        normalized = normalize_photo(photo)
        if normalized is None:
            return
        if self._proj_adjust_brightness or self._proj_adjust_contrast != 1.0 or self._proj_adjust_exposure:
            normalized = apply_adjustments(
                normalized,
                brightness=self._proj_adjust_brightness,
                contrast=self._proj_adjust_contrast,
                exposure=self._proj_adjust_exposure,
            )
        self.projection_holder.controls = [
            ft.Text(t("Найденная проекция"), size=11, color=DESKTOP_MUTED),
            ft.Image(src=thumbnail_png(normalized, PROJECTION_SIZE), width=75, height=75, fit=ft.BoxFit.CONTAIN),
        ]
        self.projection_holder.visible = True

    def _reset_adjustments(self) -> None:
        self._adjust_brightness = 0.0
        self._adjust_contrast = 1.0
        self._adjust_exposure = 0.0
        self.adjust_brightness_slider.value = 0.0
        self.adjust_contrast_slider.value = 1.0
        self.adjust_exposure_slider.value = 0.0
        self._update_adjustment_labels()

    def _reset_projection_adjustments(self) -> None:
        self._proj_adjust_brightness = 0.0
        self._proj_adjust_contrast = 1.0
        self._proj_adjust_exposure = 0.0
        self.proj_adjust_brightness_slider.value = 0.0
        self.proj_adjust_contrast_slider.value = 1.0
        self.proj_adjust_exposure_slider.value = 0.0
        self._update_projection_adjustment_labels()

    def _reset_all_adjustments(self) -> None:
        self._reset_adjustments()
        self._reset_projection_adjustments()

    def _update_adjustment_labels(self) -> None:
        self.adjust_brightness_label.value = t("Яркость: {signed}", signed=_signed(self._adjust_brightness, 0))
        self.adjust_contrast_label.value = t("Контраст: {adjust_contrast:.1f}×", adjust_contrast=self._adjust_contrast)
        self.adjust_exposure_label.value = t("Экспозиция: {signed} EV", signed=_signed(self._adjust_exposure, 1))

    def _update_projection_adjustment_labels(self) -> None:
        self.proj_adjust_brightness_label.value = t("Яркость: {signed}", signed=_signed(self._proj_adjust_brightness, 0))
        self.proj_adjust_contrast_label.value = t(
            "Контраст: {proj_adjust_contrast:.1f}×", proj_adjust_contrast=self._proj_adjust_contrast
        )
        self.proj_adjust_exposure_label.value = t("Экспозиция: {signed} EV", signed=_signed(self._proj_adjust_exposure, 1))

    def _decode_last_query_photo(self) -> np.ndarray | None:
        if self._last_query_photo is None:
            return None
        return cv2.imdecode(np.frombuffer(self._last_query_photo, np.uint8), cv2.IMREAD_COLOR)

    def _current_photo_array(self) -> np.ndarray | None:
        """Оригинальное фото с уже применённой поправкой яркости/контраста/экспозиции фото (не проекции)."""
        photo = self._decode_last_query_photo()
        if photo is None:
            return None
        if self._adjust_brightness or self._adjust_contrast != 1.0 or self._adjust_exposure:
            return apply_adjustments(
                photo,
                brightness=self._adjust_brightness,
                contrast=self._adjust_contrast,
                exposure=self._adjust_exposure,
            )
        return photo

    def _rerun_search_with_adjustments(self) -> None:
        if self._busy:
            return
        photo = self._current_photo_array()
        if photo is None:
            return
        ok, encoded = cv2.imencode(".png", photo)
        self._show_photo(bytes(encoded) if ok else self._last_query_photo)
        self._set_busy(True)
        self.page.run_thread(lambda: self._search_worker_array(photo))

    def on_adjust_change(self, _event) -> None:
        self._adjust_brightness = self.adjust_brightness_slider.value
        self._adjust_contrast = self.adjust_contrast_slider.value
        self._adjust_exposure = self.adjust_exposure_slider.value
        self._update_adjustment_labels()
        self._update_live_previews()
        self.page.update()

    def on_adjust_commit(self, _event) -> None:
        """Ползунок фото отпущен: пересчитываем поправку и запускаем поиск снова по тому же фото."""
        self.on_adjust_change(_event)
        self._rerun_search_with_adjustments()

    def on_reset_adjustments(self, _event) -> None:
        self._reset_adjustments()
        self.page.update()
        self._rerun_search_with_adjustments()

    def on_proj_adjust_change(self, _event) -> None:
        self._proj_adjust_brightness = self.proj_adjust_brightness_slider.value
        self._proj_adjust_contrast = self.proj_adjust_contrast_slider.value
        self._proj_adjust_exposure = self.proj_adjust_exposure_slider.value
        self._update_projection_adjustment_labels()
        self._update_live_previews()
        self.page.update()

    def on_proj_adjust_commit(self, _event) -> None:
        """Ползунок проекции отпущен: та же поправка фото, но с новыми параметрами проекции."""
        self.on_proj_adjust_change(_event)
        self._rerun_search_with_adjustments()

    def on_reset_proj_adjustments(self, _event) -> None:
        self._reset_projection_adjustments()
        self.page.update()
        self._rerun_search_with_adjustments()

    def _show_outcome(self, outcome: SearchOutcome) -> None:
        self._last_search_ms = outcome.took_ms
        self._last_score = outcome.results[0].score if outcome.results else None
        self._update_metrics()
        message = outcome_message(outcome.kind)
        if message:
            self._show_banner(message, error=outcome.kind is Outcome.NO_PROJECTION)
        if outcome.projection_png:
            self.projection_holder.controls = [
                ft.Text(t("Найденная проекция"), size=11, color=DESKTOP_MUTED),
                ft.Image(src=outcome.projection_png, width=75, height=75, fit=ft.BoxFit.CONTAIN),
            ]
        self.projection_holder.visible = bool(outcome.projection_png)
        self.proj_adjust_panel.visible = bool(outcome.projection_png)
        self.results_column.controls = [self._result_card(result) for result in outcome.results]
        self._update_results_summary()
        self.page.update()

    def _result_card(self, result: Result) -> ft.Container:
        thumb = ft.Stack(
            [
                ft.Container(
                    ft.Image(src=result.thumbnail_png, fit=ft.BoxFit.CONTAIN),
                    alignment=ft.Alignment.CENTER,
                    bgcolor=DESKTOP_BG,
                    expand=True,
                ),
                ft.Container(ft.Text(f"{result.rank:02d}", size=9, color=DESKTOP_DIM), top=6, left=6),
                ft.Container(_score_badge(result.score), top=6, right=6),
            ],
            height=110,
        )
        details: list[ft.Control] = [
            ft.Text(result.name, weight=ft.FontWeight.BOLD, size=12, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
            ft.Text(result.full_path, size=10, color=DESKTOP_MUTED, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
        ]
        if result.copies:
            details.append(
                ft.Text(
                    t("ещё {count} {files}", count=len(result.copies), files=plural(len(result.copies), FILES_RU, FILES_EN)),
                    size=9,
                    color=DESKTOP_DIM,
                    tooltip="\n".join(result.copies),
                )
            )
        actions = ft.Row(
            [
                ft.IconButton(
                    icon=ft.Icons.FOLDER_OPEN,
                    icon_size=16,
                    tooltip=t("Показать в папке"),
                    on_click=lambda _event, path=result.full_path: self.reveal(path),
                ),
                ft.IconButton(
                    icon=ft.Icons.THUMB_DOWN_OUTLINED,
                    icon_size=16,
                    tooltip=t("Это не то — указать верный файл"),
                    data=result,
                    on_click=self.on_report_wrong,
                ),
            ],
            spacing=0,
        )
        return ft.Container(
            ft.Column(
                [
                    thumb,
                    ft.Container(ft.Column(details, spacing=3), padding=ft.Padding.only(left=10, right=10, top=8)),
                    actions,
                ],
                spacing=4,
            ),
            bgcolor=DESKTOP_PANEL,
            border=ft.Border.all(1, DESKTOP_LINE),
            border_radius=2,
            ink=True,
            data=result.full_path,
            tooltip=t("Нажмите, чтобы скопировать путь к файлу"),
            on_click=self.on_card_click,
        )

    async def on_card_click(self, event) -> None:
        await self.copy_path(event.control.data)

    async def copy_path(self, path: str) -> None:
        """Копирует абсолютный путь файла (вместе с именем) в буфер обмена."""
        absolute = os.path.abspath(path)
        await self.clipboard.set(absolute)
        self.copy_label.value = t("Путь скопирован: {absolute}", absolute=absolute)
        self.copy_label.visible = True
        self.page.update()

    async def on_report_wrong(self, event) -> None:
        """«Это не то»: пользователь указывает верный файл — учитывается при похожих запросах впредь."""
        result: Result = event.control.data
        files = await self.picker.pick_files(dialog_title=t("Выберите верный файл"), file_type=ft.FilePickerFileType.IMAGE)
        if not files or not files[0].path:
            return
        try:
            self.service.add_correction(result.rel_path, files[0].path)
        except CorrectionError as error:
            self._show_banner(str(error), error=True)
            return
        self._show_banner(t("Запомнено: при похожих запросах теперь будет показан верный файл"), error=False)
        if self._last_query_photo is not None:
            self._start_search(self._last_query_photo)

    # ---- прочее ------------------------------------------------------------
    def on_check(self, _event) -> None:
        info = self.check()
        head = t("ОК: ядро работает") if info["ok"] else t("ОШИБКА: ядро не сработало")
        self.check_label.value = head + ", " + ", ".join(f"{name}: {value}" for name, value in info["versions"].items())
        self.page.update()

    def on_send_log(self, _event) -> None:
        """Открывает почтовый клиент с готовым письмом и показывает файл лога в проводнике, чтобы приложить
        его вручную: само приложение не может безопасно отправить почту (учётные данные никуда не вшиты)."""
        body = (
            f"Версия: {NAME} {VERSION}\n"
            f"ОС: {platform.platform()}\n"
            f"Индекс: {status_text(self.service.status())}\n\n"
            "Опишите проблему и приложите файл лога — он открыт в проводнике/Finder.\n"
        )
        query = urllib.parse.urlencode({"subject": "GMAGC: лог и описание проблемы", "body": body})
        self._open_url(f"mailto:{SUPPORT_EMAIL}?{query}")
        if self._log_path.exists() and self._log_path.stat().st_size > 0:
            self.reveal(str(self._log_path))
        else:
            self._show_banner(t("Файл лога пока пуст: ошибок в этой сессии не было"), error=False)

    def _run_demo(self, library: str, photo: str) -> None:
        """Отладка: GMAGC_DEMO_LIBRARY / GMAGC_DEMO_PHOTO запускают индексацию и поиск при старте."""
        self._set_busy(True, indexing=True)
        if library:
            self.service.set_library(library)
            self.library_text.value = library
        self._index_worker()
        self._set_busy(True)
        data = Path(photo).read_bytes()
        self._last_query_photo = data
        self._reset_all_adjustments()
        self._show_photo(data)
        self._search_worker(data)


def build_page(page: ft.Page, service: SearchService | None = None, **services) -> DesktopApp:
    page.title = f"{NAME} {VERSION} — {AUTHOR}"
    window = getattr(page, "window", None)
    if window is not None:
        window.width, window.height = 1100, 760
    service = service or SearchService(data_dir())
    i18n.set_language(service.saved_language())  # до сборки: тексты берутся при создании элементов
    if "updates" not in services:  # updates=None в тестах отключает обновления
        services["updates"] = UpdateManager(service, data_dir())
    services.setdefault("log_path", setup_logging(service.data_dir))
    app = DesktopApp(page, service, **services)
    app.build()
    return app
