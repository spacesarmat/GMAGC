"""Окно «Профили приборов» мобильного приложения: список → профиль → режим → канал (автосохранение)."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
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
    profile_file_name,
    profile_to_dict,
    template_by_id,
    validate_profile,
)
from gmagc_common.i18n import t
from gmagc_common.ma2_export import export_ma2_files
from gmagc_common.ma3_export import ExportError, export_ma3
from gmagc_common.protocol import FixtureUploadResult
from gmagc_mobile.client import ClientError
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


def upload_text(result: FixtureUploadResult) -> str:
    """Что записал ПК: пульт и имя каждого файла, затем то, что пришлось пропустить."""
    labels = {"ma3": "grandMA3", "ma2": "grandMA2"}
    lines = [t("Записано на ПК:")]
    for target, path in result.written:
        lines.append(f"• {labels.get(target, target)}: {re.split(r'[\\\\/]', path)[-1]}")
    lines.extend(t("Пропущено: {item}", item=item) for item in result.skipped)
    return "\n".join(lines)


class ProfileEditor:
    def __init__(
        self,
        page: ft.Page,
        store: ProfileStore,
        share,
        on_exit: Callable[[], None] | None = None,
        send: Callable[[FixtureProfile], Awaitable[FixtureUploadResult]] | None = None,
    ):
        self.page = page
        self.store = store
        self.share = share
        self.on_exit = on_exit
        self.send = send  # отправка профиля на ПК; None — нет подключения к ПК
        self.profiles: list[FixtureProfile] = []
        self.profile: FixtureProfile | None = None
        self.mode_index: int | None = None
        self.channel_index: int | None = None
        self.screen = SCREEN_LIST
        self.pending_delete: str | None = None
        self.message = ""
        self.notice = ""  # успешный итог (зелёным), например «записано на ПК»
        self._render_token = 0  # растёт с каждой отрисовкой: отложенная перерисовка после ввода видит, что уже не нужна
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
        self.message = self.notice = ""
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
        self._render_token += 1
        self.view.controls = getattr(self, f"_render_{self.screen}")()
        self.page.update()

    def _render_list(self) -> list[ft.Control]:
        controls: list[ft.Control] = [self._header(t("Профили приборов"))]
        if not self.profiles:
            controls.append(ft.Text(t("Нет профилей. Создайте первый."), size=13, color=ft.Colors.GREY_500))
        for profile in self.profiles:
            controls.append(self._profile_card(profile))
        controls.append(ft.Button(t("Новый профиль"), icon=ft.Icons.ADD, on_click=self.on_new_profile))
        return controls

    def _profile_card(self, profile: FixtureProfile) -> ft.Control:
        title = f"{profile.manufacturer or '(без производителя)'} — {profile.name or '(без названия)'}"
        subtitle = t("Режимов: {count}", count=len(profile.modes))
        if self.pending_delete == profile.id:
            return ft.Row(
                [
                    ft.Text(t("Удалить «{title}»?", title=title), expand=True),
                    ft.TextButton(t("Да"), on_click=self._async_click(self.on_confirm_delete, profile.id)),
                    ft.TextButton(t("Нет"), on_click=lambda _e: self.on_cancel_delete()),
                ]
            )
        return ft.Container(
            ft.Row(
                [
                    ft.Column(
                        [ft.Text(title, weight=ft.FontWeight.BOLD), ft.Text(subtitle, size=12)], expand=True, spacing=2
                    ),
                    ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, on_click=lambda _e, pid=profile.id: self.on_ask_delete(pid)),
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
        name = self._unique_mode_name(t("Режим {number}", number=len(self.profile.modes) + 1))
        await self._commit(replace(self.profile, modes=(*self.profile.modes, Mode(name))))

    async def duplicate_mode(self, index: int) -> None:
        source = self.profile.modes[index]
        copy = replace(source, name=self._unique_mode_name(t("{name} (копия)", name=source.name)))
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

    async def _redraw_later(self, _event) -> None:
        """Обновляет сообщения проверки после ввода. С задержкой: мгновенная перерисовка на потере фокуса
        заменяла бы кнопки под пальцем, и первое касание после ввода пропадало."""
        token = self._render_token
        await asyncio.sleep(0.4)
        if token == self._render_token:
            self.render()

    def _field(self, label: str, value: str, handler, **kwargs) -> ft.TextField:
        """Текстовое поле с автосохранением. Перерисовка только при потере фокуса: иначе на каждой букве
        поле пересоздаётся и клавиатура закрывается."""

        async def changed(event) -> None:
            await handler(event.control.value, render=False)

        return ft.TextField(label=label, value=value, on_change=changed, on_blur=self._redraw_later, **kwargs)

    def _issue_controls(self, issues: list[Issue]) -> list[ft.Control]:
        controls: list[ft.Control] = []
        for issue in issues:
            color = ft.Colors.RED_400 if issue.error else ft.Colors.AMBER_400
            text = f"{issue.path}: {issue.message}" if issue.path else issue.message
            controls.append(ft.Text(text, size=12, color=color))
        return controls

    async def on_send_to_pc(self, _event) -> None:
        """Отправляет профиль на ПК по Wi-Fi: ПК сам кладёт типы grandMA3 и grandMA2 в папки пультов."""
        if self.profile is None:
            return
        self.message = self.notice = ""
        if self.send is None:
            self.message = t("Нет подключения к ПК: подключитесь на главном экране и повторите.")
            self.render()
            return
        try:
            result = await self.send(self.profile)
        except ClientError as error:
            self.message = error.message
        else:
            self.notice = upload_text(result)
        self.render()

    async def _share_files(self, files: list[tuple[str, str, str]], subject: str) -> None:
        """Отправляет файлы (имя, текст, mime-тип) через системное «Поделиться»: приложение получает готовый файл."""
        try:
            await self.share.share_files(
                [ft.ShareFile.from_bytes(text.encode("utf-8"), mime_type=mime, name=name) for name, text, mime in files],
                subject=subject,
            )
        except Exception as error:  # noqa: BLE001 - недоступное «Поделиться» не должно ломать редактор
            self.message = t("Не удалось поделиться: {error}", error=error)
            self.render()

    def _subject(self) -> str:
        return f"{self.profile.manufacturer} {self.profile.name}".strip() or t("Профиль прибора")

    async def on_share(self, _event) -> None:
        """Профиль файлом .json: его можно открыть в GMAGC на другом телефоне или превратить в файл пульта скриптом."""
        if self.profile is None:
            return
        text = json.dumps(profile_to_dict(self.profile), ensure_ascii=False, indent=2)
        name = profile_file_name(self.profile, "json")
        await self._share_files([(name, text, "application/json")], self._subject())

    async def on_share_ma3(self, _event) -> None:
        """Готовый тип прибора grandMA3 файлом .xml: остаётся положить его в fixturetypes и импортировать."""
        if self.profile is None:
            return
        try:
            text = export_ma3(self.profile)
        except ExportError as error:
            self.message = str(error)
            self.render()
            return
        name = profile_file_name(self.profile, "xml")
        await self._share_files([(name, text, "application/xml")], f"{self._subject()} (grandMA3)")

    async def on_share_ma2(self, _event) -> None:
        """Типы прибора grandMA2 файлами .xml, по одному на режим (в MA2 один файл описывает один режим)."""
        if self.profile is None:
            return
        try:
            files = export_ma2_files(self.profile)
        except ExportError as error:
            self.message = str(error)
            self.render()
            return
        await self._share_files([(name, text, "application/xml") for name, text in files], f"{self._subject()} (grandMA2)")

    async def _set_text(self, field: str, value: str, *, render: bool = True) -> None:
        await self.set_profile_text(field, value, render=render)

    def _render_profile(self) -> list[ft.Control]:
        profile = self.profile
        controls: list[ft.Control] = [
            self._header(t("Профиль прибора")),
            *(
                self._field(label, getattr(profile, field), partial(self._set_text, field))
                for label, field in (
                    (t("Производитель"), "manufacturer"),
                    (t("Название"), "name"),
                    (t("Короткое имя"), "short_name"),
                )
            ),
            ft.Text(t("Мод"), size=14, weight=ft.FontWeight.BOLD),
        ]
        if self.notice:
            controls.insert(1, ft.Text(self.notice, size=12, color=ft.Colors.GREEN_400, selectable=True))
        if self.message:
            controls.insert(1, ft.Text(self.message, size=12, color=ft.Colors.RED_400, selectable=True))
        for index, mode in enumerate(profile.modes):
            controls.append(
                ft.Row(
                    [
                        ft.Container(
                            ft.Text(t("{name} ({count} кан.)", name=mode.name, count=len(mode.channels))),
                            on_click=self._async_click(self.open_mode, index),
                            padding=8,
                            expand=True,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.COPY,
                            tooltip=t("Дублировать"),
                            on_click=self._async_click(self.duplicate_mode, index),
                        ),
                        ft.IconButton(
                            icon=ft.Icons.DELETE_OUTLINE,
                            tooltip=t("Удалить"),
                            on_click=self._async_click(self.delete_mode, index),
                        ),
                    ]
                )
            )
        controls.append(ft.Button(t("Добавить режим"), icon=ft.Icons.ADD, on_click=self._async_click(self.add_mode)))
        controls.append(ft.Button(t("Отправить на ПК"), icon=ft.Icons.COMPUTER, on_click=self.on_send_to_pc))
        controls.append(ft.TextButton(t("Поделиться профилем (файл JSON)"), icon=ft.Icons.SHARE, on_click=self.on_share))
        controls.append(
            ft.TextButton(t("Поделиться для grandMA3 (файл XML)"), icon=ft.Icons.SHARE, on_click=self.on_share_ma3)
        )
        controls.append(
            ft.TextButton(t("Поделиться для grandMA2 (файлы XML режимов)"), icon=ft.Icons.SHARE, on_click=self.on_share_ma2)
        )
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
            self._header(t("Режим")),
            self._field(t("Название режима"), mode.name, self._rename_current_mode),
            ft.Text(t("Каналы"), size=14, weight=ft.FontWeight.BOLD),
        ]
        if self.message:
            controls.insert(1, ft.Text(self.message, size=12, color=ft.Colors.RED_400, selectable=True))
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
                            tooltip=t("Удалить"),
                            on_click=self._async_click(self.delete_channel, index),
                        ),
                    ]
                )
            )
        controls.append(
            ft.Dropdown(
                label=t("Добавить канал (шаблон)"),
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
        await self._commit_channel(replace(self.channel, ranges=(*ranges, Range(start, 255, t("Новый диапазон")))))

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
            on_blur=self._redraw_later,
            width=150,
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
                        self._number_field(t("От"), item.start, set_start),
                        self._number_field(t("До"), item.end, set_end),
                        ft.IconButton(
                            icon=ft.Icons.DELETE_OUTLINE,
                            tooltip=t("Удалить диапазон"),
                            on_click=self._async_click(self.delete_range, index),
                        ),
                    ]
                ),
                self._field(t("Название значения"), item.name, set_name),
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
            self._header(t("Канал")),
            ft.Dropdown(
                label=t("Шаблон"),
                value=channel.template,
                options=[ft.DropdownOption(key=t.id, text=t.title) for t in TEMPLATES],
                on_select=self._on_template_change,
            ),
            self._field(t("Название"), channel.name, set_name),
            ft.Row(
                [
                    self._number_field("DMX", channel.dmx, set_dmx),
                    self._number_field(t("По умолчанию"), channel.default, set_default),
                ]
            ),
            ft.Row(
                [
                    ft.Button(
                        t("{bits} бит", bits=bits),
                        disabled=channel.bits == bits,
                        on_click=self._async_click(self.set_channel_bits, bits),
                    )
                    for bits in (8, 16)
                ]
            ),
            ft.Text(t("Диапазоны значений (0–255)"), size=14, weight=ft.FontWeight.BOLD),
        ]
        for index, item in enumerate(channel.ranges):
            controls.append(self._range_row(index, item))
        controls.append(ft.Button(t("Добавить диапазон"), icon=ft.Icons.ADD, on_click=self._async_click(self.add_range)))
        path = f"{self.mode.name} → {channel.name.strip() or '(без названия)'}"
        controls.extend(self._issue_controls([i for i in validate_profile(self.profile) if i.path == path]))
        return controls
