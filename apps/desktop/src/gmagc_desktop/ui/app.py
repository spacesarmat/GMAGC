"""Экран ПК-приложения: библиотека, индекс, поиск по фото."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import flet as ft

from gmagc_desktop.about import AUTHOR, NAME, VERSION
from gmagc_desktop.library.index import IndexCancelled, LibraryNotFound, LibraryScanError
from gmagc_desktop.selfcheck import run_core_check
from gmagc_desktop.service.results import Outcome, Result, SearchOutcome
from gmagc_desktop.service.reveal import reveal_in_file_manager
from gmagc_desktop.service.search_service import NoIndexError, PhotoError, SearchService
from gmagc_desktop.service.settings import data_dir
from gmagc_desktop.ui.texts import outcome_message, score_text, status_text

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
NO_LIBRARY_HINT = "Сначала выберите папку библиотеки и постройте индекс"


class DesktopApp:
    def __init__(
        self,
        page: ft.Page,
        service: SearchService,
        picker=None,
        clipboard=None,
        reveal: Callable[[str], bool] = reveal_in_file_manager,
        check: Callable[[], dict] = run_core_check,
    ):
        self.page = page
        self.service = service
        self.picker = picker or ft.FilePicker()
        self.clipboard = clipboard or ft.Clipboard()
        self.reveal = reveal
        self.check = check
        self._busy = False
        self._cancel = False

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
        self.photo_holder = ft.Column(visible=False, spacing=4)
        self.projection_holder = ft.Column(visible=False, spacing=4)
        self.results_column = ft.Column(spacing=8)
        self.check_label = ft.Text("")

    # ---- построение экрана -------------------------------------------------
    def build(self) -> None:
        status = self.service.load()
        self.library_text.value = self.service.settings.library_dir or "не выбрана"
        self.status_label.value = status_text(status)
        self.page.services.extend([self.picker, self.clipboard])

        left = ft.Column(
            [
                ft.Text("Библиотека", size=18, weight=ft.FontWeight.BOLD),
                self.library_text,
                self.choose_folder_button,
                self.rebuild_button,
                self.status_label,
                self.progress,
                self.progress_label,
                self.cancel_button,
            ],
            spacing=8,
            width=320,
        )
        right = ft.Column(
            [
                ft.Row([self.pick_photo_button, self.paste_button], spacing=8),
                self.banner,
                ft.Row(
                    [self.photo_holder, self.projection_holder],
                    spacing=16,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                ft.Text("Результаты", size=18, weight=ft.FontWeight.BOLD),
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
            ],
            spacing=12,
        )
        self.page.add(
            ft.SafeArea(
                ft.Column(
                    [
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

    # ---- индексация --------------------------------------------------------
    async def on_choose_folder(self, _event) -> None:
        folder = await self.picker.get_directory_path(dialog_title="Папка библиотеки гобо")
        if not folder:
            return
        self.service.set_library(folder)
        self.library_text.value = folder
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
            ft.TextButton(
                content=ft.Text(result.full_path, size=12),
                tooltip="Показать в папке",
                on_click=lambda _event, path=result.full_path: self.reveal(path),
            ),
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
                    ],
                    spacing=12,
                ),
                padding=10,
            )
        )

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
    app = DesktopApp(page, service or SearchService(data_dir()), **services)
    app.build()
    return app
