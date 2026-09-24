"""Окно «Профили приборов» мобильного приложения: список → профиль → режим → канал (автосохранение)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from functools import partial

import flet as ft

from gmagc_common.fixtures import FixtureProfile, Issue, Mode, new_profile, validate_profile
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

    # ---- профиль и режимы ---------------------------------------------------
    async def _commit(self, profile: FixtureProfile, *, render: bool = True) -> None:
        """Автосохранение: новая версия профиля сразу пишется в хранилище."""
        self.profile = profile
        await self.store.save(profile)
        self.profiles = await self.store.list()
        if render:
            self.render()

    async def set_profile_text(self, field: str, value: str, *, render: bool = True) -> None:
        await self._commit(replace(self.profile, **{field: value}), render=render)

    def _unique_mode_name(self, base: str) -> str:
        taken = {mode.name for mode in self.profile.modes}
        if base not in taken:
            return base
        number = 2
        while f"{base} {number}" in taken:
            number += 1
        return f"{base} {number}"

    async def add_mode(self) -> None:
        name = self._unique_mode_name(f"Режим {len(self.profile.modes) + 1}")
        await self._commit(replace(self.profile, modes=(*self.profile.modes, Mode(name))))

    async def duplicate_mode(self, index: int) -> None:
        source = self.profile.modes[index]
        copy = replace(source, name=self._unique_mode_name(f"{source.name} (копия)"))
        modes = (*self.profile.modes[: index + 1], copy, *self.profile.modes[index + 1 :])
        await self._commit(replace(self.profile, modes=modes))

    async def delete_mode(self, index: int) -> None:
        if len(self.profile.modes) <= 1:  # у прибора всегда есть хотя бы один режим
            return
        modes = tuple(m for i, m in enumerate(self.profile.modes) if i != index)
        await self._commit(replace(self.profile, modes=modes))

    async def rename_mode(self, index: int, name: str, *, render: bool = True) -> None:
        modes = tuple(replace(m, name=name) if i == index else m for i, m in enumerate(self.profile.modes))
        await self._commit(replace(self.profile, modes=modes), render=render)

    async def open_mode(self, index: int) -> None:
        self.mode_index = index
        self.screen = SCREEN_MODE
        self.render()

    def _field(self, label: str, value: str, handler, **kwargs) -> ft.TextField:
        """Текстовое поле с автосохранением. Перерисовка только при потере фокуса: иначе на каждой букве
        поле пересоздаётся и клавиатура закрывается."""

        async def changed(event) -> None:
            await handler(event.control.value, render=False)

        def blurred(_event) -> None:
            self.render()

        return ft.TextField(label=label, value=value, on_change=changed, on_blur=blurred, **kwargs)

    def _issue_controls(self, issues: list[Issue]) -> list[ft.Control]:
        controls: list[ft.Control] = []
        for issue in issues:
            color = ft.Colors.RED_400 if issue.error else ft.Colors.AMBER_400
            text = f"{issue.path}: {issue.message}" if issue.path else issue.message
            controls.append(ft.Text(text, size=12, color=color))
        return controls

    async def _set_text(self, field: str, value: str, *, render: bool = True) -> None:
        await self.set_profile_text(field, value, render=render)

    def _render_profile(self) -> list[ft.Control]:
        profile = self.profile
        controls: list[ft.Control] = [
            self._header("Профиль прибора"),
            *(
                self._field(label, getattr(profile, field), partial(self._set_text, field))
                for label, field in (("Производитель", "manufacturer"), ("Название", "name"), ("Короткое имя", "short_name"))
            ),
            ft.Text("Режимы", size=14, weight=ft.FontWeight.BOLD),
        ]
        for index, mode in enumerate(profile.modes):
            controls.append(
                ft.Row(
                    [
                        ft.Container(
                            ft.Text(f"{mode.name} ({len(mode.channels)} кан.)"),
                            on_click=self._async_click(self.open_mode, index),
                            padding=8,
                            expand=True,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.COPY, tooltip="Дублировать", on_click=self._async_click(self.duplicate_mode, index)
                        ),
                        ft.IconButton(
                            icon=ft.Icons.DELETE_OUTLINE,
                            tooltip="Удалить",
                            on_click=self._async_click(self.delete_mode, index),
                        ),
                    ]
                )
            )
        controls.append(ft.Button("Добавить режим", icon=ft.Icons.ADD, on_click=self._async_click(self.add_mode)))
        controls.extend(self._issue_controls(validate_profile(profile)))
        return controls

    def _render_mode(self) -> list[ft.Control]:
        return [self._header("Режим")]  # наполняется в задаче 6

    def _render_channel(self) -> list[ft.Control]:
        return [self._header("Канал")]  # наполняется в задаче 7
