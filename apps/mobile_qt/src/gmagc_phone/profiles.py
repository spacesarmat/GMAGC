"""Редактор профилей приборов без виджетов: список → профиль → режим → канал (автосохранение в настройки).

Экран только показывает состояние и вызывает методы; сеть (отправка, распознавание, поиск гобо) идёт в фоне через
исполнитель телефона, а продолжение возвращается в поток интерфейса сигналом."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import replace

from PySide6.QtCore import QObject, Signal

from gmagc_common.fixtures import (
    Channel,
    FixtureProfile,
    Gobo,
    Mode,
    ProfileError,
    Range,
    channel_from_template,
    new_profile,
    next_free_dmx,
    profile_file_name,
    profile_from_dict,
    profile_to_dict,
    template_by_id,
    template_ranges,
    validate_profile,
)
from gmagc_common.gdtf_export import export_gdtf, gdtf_file_name
from gmagc_common.i18n import t
from gmagc_common.ma2_export import export_ma2_files
from gmagc_common.ma3_export import ExportError, export_ma3
from gmagc_common.phone_client import UNREACHABLE, ClientError
from gmagc_common.phone_texts import error_text
from gmagc_common.protocol import (
    SKIP_NO_FOLDER,
    SKIP_NO_GOBO,
    FixtureUploadResult,
    GoboItem,
    parse_skip,
)
from gmagc_common.scan_apply import add_draft_channels
from gmagc_common.scan_draft import WARN_NO_TABLE, DraftChannel, ScanDraft
from gmagc_phone.controller import PhoneController

SCREEN_LIST = "list"
SCREEN_PROFILE = "profile"
SCREEN_MODE = "mode"
SCREEN_CHANNEL = "channel"
SCREEN_SCAN = "scan"
SCREEN_GOBO = "gobo"

ShareFn = Callable[[list[tuple[str, "str | bytes", str]], str], None]


def parse_int(text: str, fallback: int) -> int:
    """Число из поля ввода; пустая или нечисловая строка оставляет прежнее значение."""
    try:
        return int(str(text).strip())
    except ValueError:
        return fallback


def not_connected() -> str:
    return t("Нет подключения к ПК: подключитесь на главном экране и повторите.")


def skip_text(item: str) -> str:
    """Пропуск на ПК словами на языке телефона (код приходит от ПК; неизвестная запись показывается как есть)."""
    parsed = parse_skip(item)
    if parsed is None:
        return item
    code, target, detail = parsed
    console = "grandMA3" if target == "ma3" else "grandMA2"
    if code == SKIP_NO_FOLDER:
        return t("{console}: папка не найдена, укажите её в настройках ПК-приложения", console=console)
    if code == SKIP_NO_GOBO:
        return t("{console}: файл гобо «{detail}» не найден в библиотеке", console=console, detail=detail)
    return t("{console}: не удалось использовать папку ({detail})", console=console, detail=detail)


def warning_text(code: str) -> str:
    """Предупреждение распознавания словами на языке телефона (код приходит от ПК; неизвестный показывается как есть)."""
    if code == WARN_NO_TABLE:
        return t("В инструкции не найдена таблица каналов DMX. Снимите таблицу ближе и ровнее или выберите другой файл.")
    return code


def draft_channel_label(channel: DraftChannel) -> str:
    """Строка канала на экране проверки: адрес, название и число диапазонов; «?» — распознано неуверенно."""
    span = f"{channel.dmx}–{channel.dmx + 1}" if channel.bits == 16 and channel.dmx else str(channel.dmx or "?")
    text = f"{span}  {channel.name}"
    if channel.ranges:
        text += " · " + t("диапазонов: {count}", count=len(channel.ranges))
    if channel.confidence < 1.0:
        text += " ?"
    return text


def upload_text(result: FixtureUploadResult) -> str:
    """Что записал ПК: пульт и имя каждого файла, затем то, что пришлось пропустить."""
    labels = {"ma3": "grandMA3", "ma2": "grandMA2"}
    lines = [t("Записано на ПК:")]
    for target, path in result.written:
        lines.append(f"• {labels.get(target, target)}: {re.split(r'[\\\\/]', path)[-1]}")
    lines.extend(t("Пропущено: {item}", item=skip_text(item)) for item in result.skipped)
    return "\n".join(lines)


class ProfilesController(QObject):
    changed = Signal()  # состояние изменилось: экран перерисовывается
    _main = Signal(object)  # продолжение фоновой работы в потоке интерфейса

    def __init__(
        self,
        phone: PhoneController,
        share: ShareFn | None = None,
        pick_scan_file: Callable[[], bytes | None] | None = None,
        pick_photo: Callable[[], bytes | None] | None = None,
        pick_json: Callable[[], bytes | None] | None = None,
    ):
        super().__init__()
        self.phone = phone
        self.settings = phone.settings
        self.share = share
        self.pick_scan_file = pick_scan_file  # выбор фото или PDF инструкции; None в ответе — отмена
        self.pick_photo = pick_photo  # выбор фото гобо
        self.pick_json = pick_json  # выбор файла профиля JSON
        self._main.connect(lambda fn: fn())
        self.profiles: list[FixtureProfile] = []
        self.profile: FixtureProfile | None = None
        self.mode_index: int | None = None
        self.channel_index: int | None = None
        self.screen = SCREEN_LIST
        self.pending_delete: str | None = None
        self.message = ""
        self.notice = ""
        self.scanning = False
        self.confirm_cloud: bool | None = None  # ждём подтверждения облака; значение — «взять прежний файл»
        self.last_scan_file: bytes | None = None
        self.draft: ScanDraft | None = None
        self.draft_checked: set[tuple[int, int]] = set()
        self.draft_done: set[int] = set()
        self.undo_profile: FixtureProfile | None = None
        self.undo_done: set[int] = set()
        self.gobo_range: int | None = None
        self.gobo_items: list[GoboItem] = []
        self.gobo_total = 0
        self.gobo_query = ""
        self.gobo_busy = False

    # ---- служебное -------------------------------------------------------------------
    def _render(self) -> None:
        self.changed.emit()

    def _background(self, work: Callable[[], object], done: Callable[[object, ClientError | None], None]) -> None:
        """work — сетевой вызов в фоне; done(результат, ошибка) — уже в потоке интерфейса."""

        def run() -> None:
            result, failure = None, None
            try:
                result = work()
            except ClientError as error:
                failure = error
            except Exception as error:  # noqa: BLE001
                failure = ClientError(UNREACHABLE, t("Ошибка: {error}", error=error))
            self._main.emit(lambda: done(result, failure))

        self.phone.executor.submit(run)

    def _client(self):
        return self.phone.client

    # ---- навигация ---------------------------------------------------------------------
    def open(self) -> None:
        self.profiles = self.settings.load_profiles()
        self.profile = None
        self.mode_index = self.channel_index = None
        self.pending_delete = None
        self._forget_draft()
        self.message = self.notice = ""
        self.screen = SCREEN_LIST
        self._render()

    def _forget_draft(self) -> None:
        self.draft = None
        self.draft_checked = set()
        self.draft_done = set()
        self.undo_profile = None

    def go_back(self) -> bool:
        """Шаг назад внутри редактора. False — уже на списке, выходить должно приложение."""
        self.message = self.notice = ""
        self.confirm_cloud = None
        if self.screen != SCREEN_SCAN:
            self.undo_profile = None
        if self.screen == SCREEN_GOBO:
            self.gobo_range = None
            self.screen = SCREEN_CHANNEL
        elif self.screen == SCREEN_SCAN:
            self.screen = SCREEN_MODE
        elif self.screen == SCREEN_CHANNEL:
            self.channel_index = None
            self.screen = SCREEN_MODE
        elif self.screen == SCREEN_MODE:
            self.mode_index = None
            self.screen = SCREEN_PROFILE
        elif self.screen == SCREEN_PROFILE:
            self.profile = None
            self._forget_draft()
            self.screen = SCREEN_LIST
        else:
            return False
        self._render()
        return True

    # ---- список --------------------------------------------------------------------------
    def new_profile(self) -> None:
        profile = new_profile()
        self._store(profile)
        self.profile = profile
        self.screen = SCREEN_PROFILE
        self._render()

    def open_profile(self, profile_id: str) -> None:
        self.profile = next((p for p in self.profiles if p.id == profile_id), None)
        if self.profile is not None:
            self.screen = SCREEN_PROFILE
            self._render()

    def ask_delete(self, profile_id: str) -> None:
        self.pending_delete = profile_id
        self._render()

    def cancel_delete(self) -> None:
        self.pending_delete = None
        self._render()

    def confirm_delete(self, profile_id: str) -> None:
        self.profiles = [p for p in self.profiles if p.id != profile_id]
        self.settings.save_profiles(self.profiles)
        self.pending_delete = None
        self._render()

    def import_json(self) -> None:
        """Профиль из файла JSON (например, присланного из другого телефона или старой версии приложения)."""
        self.message = self.notice = ""
        raw = self.pick_json() if self.pick_json else None
        if raw is None:
            return
        try:
            profile = profile_from_dict(json.loads(raw.decode("utf-8")))
        except (ValueError, ProfileError, UnicodeDecodeError) as error:
            self.message = t("Не удалось прочитать профиль: {error}", error=error)
            self._render()
            return
        profile = replace(profile, id=new_profile().id)  # копия: чужой идентификатор не затирает свои профили
        self._store(profile)
        self.notice = t("Профиль добавлен: {name}", name=profile.name or profile.manufacturer)
        self._render()

    # ---- сохранение --------------------------------------------------------------------------
    def _store(self, profile: FixtureProfile) -> None:
        others = [p for p in self.profiles if p.id != profile.id]
        known = {p.id for p in self.profiles}
        if profile.id in known:
            self.profiles = [profile if p.id == profile.id else p for p in self.profiles]
        else:
            self.profiles = [*others, profile]
        self.settings.save_profiles(self.profiles)

    def _commit(self, profile: FixtureProfile, *, render: bool = True) -> None:
        """Автосохранение: новая версия профиля сразу пишется в настройки."""
        self.undo_profile = None  # любая правка, кроме самого добавления, закрывает возможность отмены
        self.profile = profile
        self._store(profile)
        if render:
            self._render()

    # ---- профиль и режимы -------------------------------------------------------------------------
    def set_profile_text(self, field: str, value: str, *, render: bool = False) -> None:
        self._commit(replace(self.profile, **{field: value}), render=render)

    def _unique_mode_name(self, base: str, taken_extra: tuple[str, ...] = ()) -> str:
        taken = {mode.name for mode in self.profile.modes} | set(taken_extra)
        if base not in taken:
            return base
        number = 2
        while f"{base} {number}" in taken:
            number += 1
        return f"{base} {number}"

    def add_mode(self) -> None:
        name = self._unique_mode_name(t("Режим {number}", number=len(self.profile.modes) + 1))
        self._commit(replace(self.profile, modes=(*self.profile.modes, Mode(name))))

    def duplicate_mode(self, index: int) -> None:
        source = self.profile.modes[index]
        copy = replace(source, name=self._unique_mode_name(t("{name} (копия)", name=source.name)))
        modes = (*self.profile.modes[: index + 1], copy, *self.profile.modes[index + 1 :])
        self._commit(replace(self.profile, modes=modes))

    def delete_mode(self, index: int) -> None:
        if len(self.profile.modes) <= 1:  # у прибора всегда есть хотя бы один режим
            return
        modes = tuple(m for i, m in enumerate(self.profile.modes) if i != index)
        self._commit(replace(self.profile, modes=modes))

    def rename_mode(self, index: int, name: str, *, render: bool = False) -> None:
        modes = tuple(replace(m, name=name) if i == index else m for i, m in enumerate(self.profile.modes))
        self._commit(replace(self.profile, modes=modes), render=render)

    def open_mode(self, index: int) -> None:
        self.mode_index = index
        self.message = self.notice = ""
        self.screen = SCREEN_MODE
        self._render()

    @property
    def mode(self) -> Mode:
        return self.profile.modes[self.mode_index]

    def _commit_mode(self, mode: Mode, *, render: bool = True) -> None:
        modes = tuple(mode if i == self.mode_index else m for i, m in enumerate(self.profile.modes))
        self._commit(replace(self.profile, modes=modes), render=render)

    def rename_current_mode(self, name: str) -> None:
        self.rename_mode(self.mode_index, name)

    # ---- отправка на ПК и файлы ---------------------------------------------------------------------
    def send_to_pc(self) -> None:
        """Отправляет профиль на ПК по Wi-Fi: ПК сам кладёт типы grandMA3 и grandMA2 в папки пультов."""
        if self.profile is None:
            return
        self.message = self.notice = ""
        problems = [i for i in validate_profile(self.profile) if i.error]
        if problems:
            details = "; ".join(f"{i.path}: {i.message}" if i.path else i.message for i in problems)
            self.message = t("Профиль не готов к отправке: {problems}", problems=details)
            self._render()
            return
        client = self._client()
        if client is None:
            self.message = not_connected()
            self._render()
            return
        payload = profile_to_dict(self.profile)

        def done(result, failure) -> None:
            if failure is not None:
                self.message = error_text(failure)
            else:
                self.notice = upload_text(result)
            self._render()

        self._background(lambda: client.send_fixture(payload), done)

    def _subject(self) -> str:
        return f"{self.profile.manufacturer} {self.profile.name}".strip() or t("Профиль прибора")

    def _share(self, files: list[tuple[str, str | bytes, str]], subject: str) -> None:
        if self.share is None:
            self.message = t("Не удалось поделиться: {error}", error=t("недоступно на этом устройстве"))
            self._render()
            return
        try:
            self.share(files, subject)
        except Exception as error:  # noqa: BLE001 - недоступное «Поделиться» не должно ломать редактор
            self.message = t("Не удалось поделиться: {error}", error=error)
            self._render()

    def share_json(self) -> None:
        text = json.dumps(profile_to_dict(self.profile), ensure_ascii=False, indent=2)
        self._share([(profile_file_name(self.profile, "json"), text, "application/json")], self._subject())

    def share_gdtf(self) -> None:
        try:
            data = export_gdtf(self.profile)
        except ExportError as error:
            self.message = str(error)
            self._render()
            return
        self._share([(gdtf_file_name(self.profile), data, "application/octet-stream")], f"{self._subject()} (GDTF)")

    def share_ma3(self) -> None:
        try:
            text = export_ma3(self.profile)
        except ExportError as error:
            self.message = str(error)
            self._render()
            return
        self._share([(profile_file_name(self.profile, "xml"), text, "application/xml")], f"{self._subject()} (grandMA3)")

    def share_ma2(self) -> None:
        try:
            files = export_ma2_files(self.profile)
        except ExportError as error:
            self.message = str(error)
            self._render()
            return
        self._share([(name, text, "application/xml") for name, text in files], f"{self._subject()} (grandMA2)")

    # ---- автозаполнение по инструкции -------------------------------------------------------------------
    def scan(self, engine: str = "local", reuse: bool = False) -> None:
        """Фото или PDF инструкции → распознавание (на ПК или в облаке) → экран проверки с галочками."""
        self.message = self.notice = ""
        self.confirm_cloud = None
        client = self._client()
        if client is None:
            self.message = not_connected()
            self._render()
            return
        if reuse and self.last_scan_file is not None:
            raw = self.last_scan_file
        else:
            raw = self.pick_scan_file() if self.pick_scan_file else None
            if raw is None:  # пользователь закрыл выбор файла
                self._render()
                return
            self.last_scan_file = raw
        content_type = "application/pdf" if raw[:1024].lstrip().startswith(b"%PDF") else "image/jpeg"
        self.scanning = True
        self._render()

        def done(draft, failure) -> None:
            self.scanning = False
            if failure is not None:
                self.message = error_text(failure)
            elif not draft.modes:
                self.message = " ".join(warning_text(code) for code in draft.warnings) or warning_text(WARN_NO_TABLE)
            else:
                self.draft = draft
                self.draft_checked = {(m, c) for m, mode in enumerate(draft.modes) for c in range(len(mode.channels))}
                self.draft_done = set()
                self.undo_profile = None
                self.screen = SCREEN_SCAN
            self._render()

        self._background(lambda: client.scan_fixture(raw, content_type, engine), done)

    def resume_draft(self) -> None:
        """Возвращается к прошлому результату распознавания: файл выбирать и распознавать заново не нужно."""
        if self.draft is None:
            return
        self.message = self.notice = ""
        self.screen = SCREEN_SCAN
        self._render()

    def ask_cloud(self, reuse: bool) -> None:
        """Просит подтверждения: облачное распознавание отправляет файл инструкции за пределы вашей сети."""
        self.confirm_cloud = reuse
        self._render()

    def cancel_cloud(self) -> None:
        self.confirm_cloud = None
        self._render()

    def confirm_cloud_scan(self) -> None:
        self.scan(engine="cloud", reuse=bool(self.confirm_cloud))

    def toggle_draft_channel(self, mode_index: int, channel_index: int, checked: bool) -> None:
        key = (mode_index, channel_index)
        if checked:
            self.draft_checked.add(key)
        else:
            self.draft_checked.discard(key)

    def _chosen(self, draft_mode: int) -> list[DraftChannel]:
        channels = self.draft.modes[draft_mode].channels
        return [channel for index, channel in enumerate(channels) if (draft_mode, index) in self.draft_checked]

    def _new_mode_name(self, draft_mode: int, taken_extra: tuple[str, ...] = ()) -> str:
        base = self.draft.modes[draft_mode].name or t("Режим {number}", number=len(self.profile.modes) + 1)
        return self._unique_mode_name(base, taken_extra)

    def apply_draft(self, draft_mode: int, new_mode: bool) -> None:
        """Добавляет отмеченные каналы в текущий режим или создаёт из них новый режим."""
        chosen = self._chosen(draft_mode)
        if not chosen:
            self.message = t("Отметьте хотя бы один канал.")
            self._render()
            return
        before, done = self.profile, set(self.draft_done)
        if new_mode:
            name = self._new_mode_name(draft_mode)
            modes = (*self.profile.modes, add_draft_channels(Mode(name), chosen))
            self._commit(replace(self.profile, modes=modes), render=False)
            self.notice = t("Создан режим «{name}»: каналов {count}", name=name, count=len(chosen))
        else:
            self._commit_mode(add_draft_channels(self.mode, chosen), render=False)
            self.notice = t("Добавлено каналов: {count}", count=len(chosen))
        self.draft_done.add(draft_mode)
        self.undo_profile, self.undo_done = before, done  # после _commit, который отмену сбрасывает
        self.message = ""
        self._render()

    def apply_all_new(self) -> None:
        """Каждый ещё не добавленный режим черновика — новым режимом профиля (по отмеченным каналам)."""
        before, done = self.profile, set(self.draft_done)
        new_modes: list[Mode] = []
        added: list[int] = []
        for index in range(len(self.draft.modes)):
            chosen = self._chosen(index)
            if index in self.draft_done or not chosen:
                continue
            name = self._new_mode_name(index, tuple(m.name for m in new_modes))
            new_modes.append(add_draft_channels(Mode(name), chosen))
            added.append(index)
        if not new_modes:
            self.message = t("Нечего добавлять: все режимы уже добавлены или ничего не отмечено.")
            self._render()
            return
        self._commit(replace(self.profile, modes=(*self.profile.modes, *new_modes)), render=False)
        self.draft_done.update(added)
        self.undo_profile, self.undo_done = before, done
        self.message = ""
        self.notice = t("Создано режимов: {count}", count=len(new_modes))
        self._render()

    def undo_apply(self) -> None:
        """Отменяет последнее добавление из инструкции (в режим, новым режимом или все режимы сразу)."""
        before = self.undo_profile
        if before is None:
            return
        done = self.undo_done
        self._commit(before, render=False)
        self.draft_done = done
        self.message = ""
        self.notice = t("Добавление отменено.")
        self._render()

    # ---- каналы ------------------------------------------------------------------------------------------
    def add_channel(self, template_id: str) -> None:
        channel = channel_from_template(template_id, next_free_dmx(self.mode))
        self._commit_mode(replace(self.mode, channels=(*self.mode.channels, channel)))

    def delete_channel(self, index: int) -> None:
        channels = tuple(c for i, c in enumerate(self.mode.channels) if i != index)
        self._commit_mode(replace(self.mode, channels=channels))

    def open_channel(self, index: int) -> None:
        self.channel_index = index
        self.message = self.notice = ""
        self.screen = SCREEN_CHANNEL
        self._render()

    @property
    def channel(self) -> Channel:
        return self.mode.channels[self.channel_index]

    def _commit_channel(self, channel: Channel, *, render: bool = True) -> None:
        channels = tuple(channel if i == self.channel_index else c for i, c in enumerate(self.mode.channels))
        self._commit_mode(replace(self.mode, channels=channels), render=render)

    def set_channel(self, *, render: bool = False, **changes) -> None:
        current = self.channel
        if "template" in changes:  # смена шаблона: разрядность и диапазоны новые, имя и адрес свои
            template = template_by_id(changes.pop("template"))
            current = replace(current, template=template.id, bits=template.bits, ranges=template_ranges(template))
            render = True
        self._commit_channel(replace(current, **changes), render=render)

    def add_range(self) -> None:
        ranges = self.channel.ranges
        start = min(ranges[-1].end + 1, 255) if ranges else 0
        self._commit_channel(replace(self.channel, ranges=(*ranges, Range(start, 255, t("Новый диапазон")))))

    def set_range(self, index: int, start=None, end=None, name=None, *, render: bool = False) -> None:
        def changed(item: Range) -> Range:
            return replace(
                item,
                start=item.start if start is None else start,
                end=item.end if end is None else end,
                name=item.name if name is None else name,
            )

        ranges = tuple(changed(r) if i == index else r for i, r in enumerate(self.channel.ranges))
        self._commit_channel(replace(self.channel, ranges=ranges), render=render)

    def delete_range(self, index: int) -> None:
        ranges = tuple(r for i, r in enumerate(self.channel.ranges) if i != index)
        self._commit_channel(replace(self.channel, ranges=ranges))

    # ---- гобо из библиотеки ----------------------------------------------------------------------------------
    def open_gobo_picker(self, range_index: int) -> None:
        self.gobo_range = range_index
        self.gobo_items = []
        self.gobo_total = 0
        self.gobo_query = ""
        self.message = self.notice = ""
        self.screen = SCREEN_GOBO
        self._render()

    def find_gobos(self, query: str) -> None:
        """Поиск гобо по имени на ПК; результат показывается списком с картинками."""
        self.gobo_query = query
        self.message = ""
        client = self._client()
        if client is None:
            self.message = not_connected()
            self._render()
            return
        if not query.strip():
            self.gobo_items, self.gobo_total = [], 0
            self._render()
            return
        self.gobo_busy = True
        self._render()

        def done(found, failure) -> None:
            self.gobo_busy = False
            if failure is not None:
                self.message = error_text(failure)
                self.gobo_items, self.gobo_total = [], 0
            else:
                self.gobo_items, self.gobo_total = list(found.items), found.total
                if not found.items:
                    self.message = t("Ничего не найдено.")
            self._render()

        self._background(lambda: client.find_gobos(query), done)

    def find_gobos_by_photo(self) -> None:
        """Фото гобо → ближайшие гобо библиотеки (тот же поиск, что и на главном экране)."""
        self.message = ""
        client = self._client()
        if client is None:
            self.message = not_connected()
            self._render()
            return
        data = self.pick_photo() if self.pick_photo else None
        if data is None:
            return
        self.gobo_busy = True
        self._render()

        def lookup() -> list:
            response = client.match(data)
            return [client.gobo(item.path) for item in response.results]

        def done(found, failure) -> None:
            self.gobo_busy = False
            if failure is not None:
                self.message = error_text(failure)
            else:
                self.gobo_items, self.gobo_total = list(found), len(found)
                self.gobo_query = ""
                if not found:
                    self.message = t("Ничего не найдено.")
            self._render()

        self._background(lookup, done)

    def pick_gobo(self, item_index: int) -> None:
        """Ставит выбранное гобо в диапазон; пустое название диапазона берётся из имени гобо."""
        item = self.gobo_items[item_index]
        index = self.gobo_range
        chosen = Gobo(item.name, item.path, item.thumb, item.source)

        def changed(current: Range) -> Range:
            return replace(current, gobo=chosen, name=current.name.strip() or item.name)

        ranges = tuple(changed(r) if i == index else r for i, r in enumerate(self.channel.ranges))
        self.gobo_range = None
        self.screen = SCREEN_CHANNEL
        self._commit_channel(replace(self.channel, ranges=ranges))

    def clear_gobo(self, range_index: int) -> None:
        ranges = tuple(replace(r, gobo=None) if i == range_index else r for i, r in enumerate(self.channel.ranges))
        self._commit_channel(replace(self.channel, ranges=ranges))
