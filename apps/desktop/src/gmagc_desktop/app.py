"""Экран ПК-приложения (каркас): версия, автор и проверка ядра."""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from gmagc_desktop.about import AUTHOR, NAME, VERSION
from gmagc_desktop.selfcheck import run_core_check


def build_page(page: ft.Page, check: Callable[[], dict] = run_core_check) -> ft.Text:
    """Строит экран и возвращает поле результата (нужно тестам)."""
    page.title = f"{NAME} {VERSION}"
    result = ft.Text("Нажмите «Проверить ядро»", selectable=True)

    def on_check(_event) -> None:
        info = check()
        head = "ОК: ядро работает" if info["ok"] else "ОШИБКА: ядро не сработало"
        result.value = "\n".join([head] + [f"{name}: {value}" for name, value in info["versions"].items()])
        page.update()

    page.add(
        ft.SafeArea(
            ft.Column(
                [
                    ft.Text(NAME, size=28, weight=ft.FontWeight.BOLD),
                    ft.Text(f"Версия {VERSION}"),
                    ft.Text(f"Автор: {AUTHOR}"),
                    ft.Text("Поиск гобо по фото. Это каркас: функции появятся в следующих этапах."),
                    ft.Button("Проверить ядро", on_click=on_check),
                    result,
                ],
                spacing=12,
            )
        )
    )
    return result
