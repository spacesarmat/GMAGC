"""Окно «Профили приборов» мобильного приложения: список → профиль → режим → канал (автосохранение)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from functools import partial

import flet as ft

from gmagc_common.fixtures import (
    TEMPLATES,
    Channel,
    FixtureProfile,
    Issue,
    Mode,
    Range,
    channel_from_template,
    new_profile,
    next_free_dmx,
    template_by_id,
    validate_profile,
)
from gmagc_mobile.profile_store import ProfileStore

SCREEN_LIST = "list"
SCREEN_PROFILE = "profile"
SCREEN_MODE = "mode"
SCREEN_CHANNEL = "channel"


def parse_int(text: str, fallback: int) -> int:
    """Число из поля ввода; пустая или нечисловая строка оставляет прежнее значение."""
    try:
        return int(str(text).strip())
    except ValueError:
        return fallback


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

    # ---- режим и каналы -----------------------------------------------------
    @property
    def mode(self) -> Mode:
        return self.profile.modes[self.mode_index]

    async def _commit_mode(self, mode: Mode, *, render: bool = True) -> None:
        modes = tuple(mode if i == self.mode_index else m for i, m in enumerate(self.profile.modes))
        await self._commit(replace(self.profile, modes=modes), render=render)

    async def add_channel(self, template_id: str) -> None:
        channel = channel_from_template(template_id, next_free_dmx(self.mode))
        await self._commit_mode(replace(self.mode, channels=(*self.mode.channels, channel)))

    async def delete_channel(self, index: int) -> None:
        channels = tuple(c for i, c in enumerate(self.mode.channels) if i != index)
        await self._commit_mode(replace(self.mode, channels=channels))

    async def open_channel(self, index: int) -> None:
        self.channel_index = index
        self.screen = SCREEN_CHANNEL
        self.render()

    async def _rename_current_mode(self, value: str, *, render: bool = True) -> None:
        await self.rename_mode(self.mode_index, value, render=render)

    async def _on_template_pick(self, event) -> None:
        if event.control.value:
            await self.add_channel(event.control.value)

    def _render_mode(self) -> list[ft.Control]:
        mode = self.mode
        controls: list[ft.Control] = [
            self._header("Режим"),
            self._field("Название режима", mode.name, self._rename_current_mode),
            ft.Text("Каналы", size=14, weight=ft.FontWeight.BOLD),
        ]
        for index, channel in sorted(enumerate(mode.channels), key=lambda pair: pair[1].dmx):
            span = f"{channel.dmx}–{channel.last}" if channel.bits == 16 else str(channel.dmx)
            controls.append(
                ft.Row(
                    [
                        ft.Container(
                            ft.Text(f"{span}  {channel.name}"),
                            on_click=self._async_click(self.open_channel, index),
                            padding=8,
                            expand=True,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.DELETE_OUTLINE,
                            tooltip="Удалить",
                            on_click=self._async_click(self.delete_channel, index),
                        ),
                    ]
                )
            )
        controls.append(
            ft.Dropdown(
                label="Добавить канал (шаблон)",
                options=[ft.DropdownOption(key=t.id, text=t.title) for t in TEMPLATES],
                on_select=self._on_template_pick,
            )
        )
        issues = [i for i in validate_profile(self.profile) if i.path == mode.name or i.path.startswith(f"{mode.name} → ")]
        controls.extend(self._issue_controls(issues))
        return controls

    # ---- канал и диапазоны --------------------------------------------------
    @property
    def channel(self) -> Channel:
        return self.mode.channels[self.channel_index]

    async def _commit_channel(self, channel: Channel, *, render: bool = True) -> None:
        channels = tuple(channel if i == self.channel_index else c for i, c in enumerate(self.mode.channels))
        await self._commit_mode(replace(self.mode, channels=channels), render=render)

    async def set_channel(self, *, render: bool = True, **changes) -> None:
        current = self.channel
        if "template" in changes:  # смена шаблона: разрядность и диапазоны новые, имя и адрес свои
            template = template_by_id(changes.pop("template"))
            current = replace(current, template=template.id, bits=template.bits, ranges=template.ranges)
        await self._commit_channel(replace(current, **changes), render=render)

    async def set_channel_bits(self, bits: int) -> None:
        await self.set_channel(bits=bits)

    async def add_range(self) -> None:
        ranges = self.channel.ranges
        start = min(ranges[-1].end + 1, 255) if ranges else 0
        await self._commit_channel(replace(self.channel, ranges=(*ranges, Range(start, 255, "Новый диапазон"))))

    async def set_range(self, index: int, start=None, end=None, name=None, *, render: bool = True) -> None:
        def changed(item: Range) -> Range:
            return Range(
                item.start if start is None else start,
                item.end if end is None else end,
                item.name if name is None else name,
            )

        ranges = tuple(changed(r) if i == index else r for i, r in enumerate(self.channel.ranges))
        await self._commit_channel(replace(self.channel, ranges=ranges), render=render)

    async def delete_range(self, index: int) -> None:
        ranges = tuple(r for i, r in enumerate(self.channel.ranges) if i != index)
        await self._commit_channel(replace(self.channel, ranges=ranges))

    async def _on_template_change(self, event) -> None:
        if event.control.value:
            await self.set_channel(template=event.control.value)

    def _number_field(self, label: str, value: int, handler) -> ft.TextField:
        """Числовое поле: пустой ввод не трогает значение; сохраняем на каждый символ, перерисовка при потере фокуса."""

        async def changed(event) -> None:
            await handler(parse_int(event.control.value, value), render=False)

        return ft.TextField(
            label=label,
            value=str(value),
            keyboard_type=ft.KeyboardType.NUMBER,
            on_change=changed,
            on_blur=lambda _e: self.render(),
            width=110,
        )

    def _range_row(self, index: int, item: Range) -> ft.Control:
        async def set_start(value, *, render=True):
            await self.set_range(index, start=value, render=render)

        async def set_end(value, *, render=True):
            await self.set_range(index, end=value, render=render)

        async def set_name(value, *, render=True):
            await self.set_range(index, name=value, render=render)

        return ft.Column(
            [
                ft.Row(
                    [
                        self._number_field("От", item.start, set_start),
                        self._number_field("До", item.end, set_end),
                        ft.IconButton(
                            icon=ft.Icons.DELETE_OUTLINE,
                            tooltip="Удалить диапазон",
                            on_click=self._async_click(self.delete_range, index),
                        ),
                    ]
                ),
                self._field("Название значения", item.name, set_name),
            ],
            spacing=4,
        )

    def _render_channel(self) -> list[ft.Control]:
        channel = self.channel

        async def set_name(value, *, render=True):
            await self.set_channel(name=value, render=render)

        async def set_dmx(value, *, render=True):
            await self.set_channel(dmx=value, render=render)

        async def set_default(value, *, render=True):
            await self.set_channel(default=value, render=render)

        controls: list[ft.Control] = [
            self._header("Канал"),
            ft.Dropdown(
                label="Шаблон",
                value=channel.template,
                options=[ft.DropdownOption(key=t.id, text=t.title) for t in TEMPLATES],
                on_select=self._on_template_change,
            ),
            self._field("Название", channel.name, set_name),
            ft.Row(
                [
                    self._number_field("DMX", channel.dmx, set_dmx),
                    self._number_field("По умолчанию", channel.default, set_default),
                ]
            ),
            ft.Row(
                [
                    ft.Button(
                        f"{bits} бит",
                        disabled=channel.bits == bits,
                        on_click=self._async_click(self.set_channel_bits, bits),
                    )
                    for bits in (8, 16)
                ]
            ),
            ft.Text("Диапазоны значений (0–255)", size=14, weight=ft.FontWeight.BOLD),
        ]
        for index, item in enumerate(channel.ranges):
            controls.append(self._range_row(index, item))
        controls.append(ft.Button("Добавить диапазон", icon=ft.Icons.ADD, on_click=self._async_click(self.add_range)))
        path = f"{self.mode.name} → {channel.name.strip() or '(без названия)'}"
        controls.extend(self._issue_controls([i for i in validate_profile(self.profile) if i.path == path]))
        return controls
