"""Экран Android-приложения (каркас): превью камеры и заглушка подключения."""

from __future__ import annotations

import flet as ft
import flet_camera as fc
import flet_permission_handler as ph

from gmagc_mobile.about import AUTHOR, NAME, VERSION

STUB_TEXT = "Подключение к серверу появится в следующем этапе"


async def start_camera(page: ft.Page, permission, camera, status) -> None:
    """Запрашивает разрешение и запускает превью; любую ошибку показывает на экране."""
    try:
        if await permission.request(ph.Permission.CAMERA) != ph.PermissionStatus.GRANTED:
            status.value = "Нет доступа к камере: разрешите его в настройках"
        else:
            cameras = await camera.get_available_cameras()
            if not cameras:
                status.value = "Камера не найдена"
            else:
                await camera.initialize(cameras[0], fc.ResolutionPreset.MEDIUM, enable_audio=False)
                status.value = "Камера готова"
    except Exception as error:  # noqa: BLE001 - экран должен показать причину, а не закрыться
        status.value = f"Ошибка камеры: {error}"
    page.update()


async def build_page(page: ft.Page, starter=start_camera) -> ft.Text:
    """Строит экран, запускает камеру и возвращает строку статуса (нужна тестам)."""
    page.title = f"{NAME} {VERSION}"
    status = ft.Text("Запрашиваю доступ к камере…")
    camera = fc.Camera(expand=True, preview_enabled=True)
    permission = ph.PermissionHandler()
    page.services.append(permission)
    page.add(
        ft.SafeArea(
            ft.Column(
                [
                    ft.Text(NAME, size=24, weight=ft.FontWeight.BOLD),
                    ft.Text(f"Версия {VERSION}. Автор: {AUTHOR}"),
                    ft.Text(STUB_TEXT),
                    status,
                    ft.Container(camera, expand=True),
                ],
                expand=True,
            ),
            expand=True,
        )
    )
    await starter(page, permission, camera, status)
    return status
