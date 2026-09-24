"""Окно «Профили приборов» мобильного приложения: список → профиль → режим → канал (автосохранение)."""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from gmagc_common.fixtures import FixtureProfile, new_profile
from gmagc_mobile.profile_store import ProfileStore

SCREEN_LIST = "list"
SCREEN_PROFILE = "profile"
SCREEN_MODE = "mode"
SCREEN_CHANNEL = "channel"


class ProfileEditor:
    def __init__(self, page: ft.Page, store: ProfileStore, share, on_exit: Callable[[], None] | None = None):
        self.page = page
        self.store = store
        self.share = share
        self.on_exit = on_exit
        self.profiles: list[FixtureProfile] = []
        self.profile: FixtureProfile | None = None
        self.mode_index: int | None = None
        self.channel_index: int | None = None
        self.screen = SCREEN_LIST
        self.pending_delete: str | None = None
        self.message = ""
        self.view = ft.Column(spacing=8, visible=False, expand=True, scroll=ft.ScrollMode.AUTO)

    # ---- навигация ----------------------------------------------------------
    async def open(self) -> None:
        self.profiles = await self.store.list()
        self.profile = None
        self.mode_index = self.channel_index = None
        self.pending_delete = None
        self.screen = SCREEN_LIST
        self.render()

    def go_back(self) -> bool:
        """Шаг назад внутри редактора. False — уже на списке, выходить должно приложение."""
        self.message = ""
        if self.screen == SCREEN_CHANNEL:
            self.channel_index = None
            self.screen = SCREEN_MODE
        elif self.screen == SCREEN_MODE:
            self.mode_index = None
            self.screen = SCREEN_PROFILE
        elif self.screen == SCREEN_PROFILE:
            self.profile = None
            self.screen = SCREEN_LIST
        else:
            return False
        self.render()
        return True

    def _on_back_click(self, _event) -> None:
        if not self.go_back() and self.on_exit:
            self.on_exit()

    # ---- список -------------------------------------------------------------
    async def on_new_profile(self, _event) -> None:
        profile = new_profile()
        await self.store.save(profile)
        self.profiles = await self.store.list()
        self.profile = profile
        self.screen = SCREEN_PROFILE
        self.render()

    async def on_open_profile(self, profile_id: str) -> None:
        self.profile = next((p for p in self.profiles if p.id == profile_id), None)
        if self.profile is not None:
            self.screen = SCREEN_PROFILE
            self.render()

    def on_ask_delete(self, profile_id: str) -> None:
        self.pending_delete = profile_id
        self.render()

    def on_cancel_delete(self) -> None:
        self.pending_delete = None
        self.render()

    async def on_confirm_delete(self, profile_id: str) -> None:
        await self.store.delete(profile_id)
        self.profiles = await self.store.list()
        self.pending_delete = None
        self.render()

    # ---- отрисовка ----------------------------------------------------------
    def _header(self, title: str) -> ft.Row:
        return ft.Row(
            [
                ft.IconButton(icon=ft.Icons.ARROW_BACK, on_click=self._on_back_click),
                ft.Text(title, size=20, weight=ft.FontWeight.BOLD),
            ]
        )

    @staticmethod
    def _async_click(handler, *args):
        """Flet принимает async-обработчики: возвращаем корутинную функцию с уже подставленными аргументами."""

        async def click(_event) -> None:
            await handler(*args)

        return click

    @staticmethod
    def _async_click(handler, *args):
        """Flet принимает async-обработчики: возвращаем корутинную функцию с уже подставленными аргументами."""

        async def click(_event) -> None:
            await handler(*args)

        return click

    def render(self) -> None:
        self.view.controls = getattr(self, f"_render_{self.screen}")()
        self.page.update()

    def _render_list(self) -> list[ft.Control]:
        controls: list[ft.Control] = [self._header("Профили приборов")]
        if not self.profiles:
            controls.append(ft.Text("Нет профилей. Создайте первый.", size=13, color=ft.Colors.GREY_500))
        for profile in self.profiles:
            controls.append(self._profile_card(profile))
        controls.append(ft.Button("Новый профиль", icon=ft.Icons.ADD, on_click=self.on_new_profile))
        return controls

    def _profile_card(self, profile: FixtureProfile) -> ft.Control:
        title = f"{profile.manufacturer or '(без производителя)'} — {profile.name or '(без названия)'}"
        subtitle = f"Режимов: {len(profile.modes)}"
        if self.pending_delete == profile.id:
            return ft.Row(
                [
                    ft.Text(f"Удалить «{title}»?", expand=True),
                    ft.TextButton("Да", on_click=self._async_click(self.on_confirm_delete, profile.id)),
                    ft.TextButton("Нет", on_click=lambda _e: self.on_cancel_delete()),
                ]
            )
        return ft.Container(
            ft.Row(
                [
                    ft.Column(
                        [ft.Text(title, weight=ft.FontWeight.BOLD), ft.Text(subtitle, size=12)], expand=True, spacing=2
                    ),
                    ft.IconButton(
                        icon=ft.Icons.DELETE_OUTLINE, on_click=lambda _e, pid=profile.id: self.on_ask_delete(pid)
                    ),
                ]
            ),
            on_click=self._async_click(self.on_open_profile, profile.id),
            padding=8,
        )

    def _render_profile(self) -> list[ft.Control]:
        return [self._header("Профиль")]  # наполняется в задаче 5

    def _render_mode(self) -> list[ft.Control]:
        return [self._header("Режим")]  # наполняется в задаче 6

    def _render_channel(self) -> list[ft.Control]:
        return [self._header("Канал")]  # наполняется в задаче 7
