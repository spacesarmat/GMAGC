"""Экран «Профили приборов»: список → профиль → режим → канал; проверка результата распознавания; выбор гобо."""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from gmagc_common.fixtures import TEMPLATES, validate_profile
from gmagc_common.i18n import t
from gmagc_common.scan_draft import ENGINE_CLOUD
from gmagc_phone import profiles as p
from gmagc_phone.controller import PhoneController
from gmagc_phone.profiles import ProfilesController, draft_channel_label, parse_int, warning_text
from gmagc_phone.widgets import Page, button, card, label, picture


def _row(*widgets, stretch_first: bool = False) -> QWidget:
    box = QWidget()
    layout = QHBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    for index, widget in enumerate(widgets):
        layout.addWidget(widget, 1 if index == 0 and stretch_first else 0)
    return box


def _clear(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()


class ProfilesScreen(Page):
    def __init__(self, phone: PhoneController, editor: ProfilesController | None = None):
        super().__init__(t("Профили приборов"), lambda: None)
        self.back.clicked.connect(lambda _checked=False: self._back())
        self.phone = phone
        self.editor = editor or ProfilesController(phone)
        self.editor.changed.connect(self.render)
        self.render()

    # ---- общее -----------------------------------------------------------------------------
    def activate(self) -> None:
        self.editor.open()

    def _back(self) -> None:
        if not self.editor.go_back():
            self.phone.close_overlay()

    def _messages(self) -> None:
        if self.editor.notice:
            self.add(label(self.editor.notice, "online"))
        if self.editor.message:
            self.add(label(self.editor.message, "error"))

    def _issues(self, issues) -> None:
        for issue in issues:
            text = f"{issue.path}: {issue.message}" if issue.path else issue.message
            self.add(label(text, "error" if issue.error else "muted"))

    def _field(self, caption: str, value: str, setter, numeric: bool = False) -> None:
        self.add(label(caption, "muted"))
        edit = QLineEdit(value)
        if numeric:
            edit.setInputMethodHints(edit.inputMethodHints())
        edit.textEdited.connect(setter)
        self.add(edit)

    def render(self) -> None:
        _clear(self.layout_)
        editor = self.editor
        screen = editor.screen
        titles = {
            p.SCREEN_LIST: t("Профили приборов"),
            p.SCREEN_PROFILE: t("Профиль прибора"),
            p.SCREEN_MODE: t("Режим"),
            p.SCREEN_CHANNEL: t("Канал"),
            p.SCREEN_SCAN: t("Найдено в инструкции"),
            p.SCREEN_GOBO: t("Гобо из библиотеки"),
        }
        self.title.setText(titles[screen])
        getattr(self, f"_render_{screen}")()
        self.finish()

    # ---- список ----------------------------------------------------------------------------------
    def _render_list(self) -> None:
        editor = self.editor
        self._messages()
        if not editor.profiles:
            self.add(label(t("Нет профилей. Создайте первый."), "muted"))
        for profile in editor.profiles:
            title = f"{profile.manufacturer or t('(без производителя)')} — {profile.name or t('(без названия)')}"
            frame = card()
            box = QVBoxLayout(frame)
            if editor.pending_delete == profile.id:
                box.addWidget(label(t("Удалить «{title}»?", title=title)))
                box.addWidget(
                    _row(
                        button(t("Да"), "", lambda pid=profile.id: editor.confirm_delete(pid)),
                        button(t("Нет"), "", editor.cancel_delete),
                    )
                )
            else:
                box.addWidget(label(title, "heading"))
                box.addWidget(label(t("Режимов: {count}", count=len(profile.modes)), "muted"))
                box.addWidget(
                    _row(
                        button(t("Открыть"), "", lambda pid=profile.id: editor.open_profile(pid)),
                        button(t("Удалить"), "link", lambda pid=profile.id: editor.ask_delete(pid)),
                    )
                )
            self.add(frame)
        self.add(button(t("Новый профиль"), "primary", editor.new_profile))
        self.add(button(t("Импорт профиля из файла (JSON)"), "", editor.import_json))

    # ---- профиль -----------------------------------------------------------------------------------
    def _render_profile(self) -> None:
        editor, profile = self.editor, self.editor.profile
        self._messages()
        for caption, field in (
            (t("Производитель"), "manufacturer"),
            (t("Название"), "name"),
            (t("Короткое имя"), "short_name"),
        ):
            self._field(caption, getattr(profile, field), lambda value, f=field: editor.set_profile_text(f, value))
        self.add(label(t("Мод"), "heading"))
        for index, mode in enumerate(profile.modes):
            frame = card()
            box = QVBoxLayout(frame)
            box.addWidget(label(t("{name} ({count} кан.)", name=mode.name, count=len(mode.channels))))
            box.addWidget(
                _row(
                    button(t("Открыть"), "", lambda i=index: editor.open_mode(i)),
                    button(t("Дублировать"), "link", lambda i=index: editor.duplicate_mode(i)),
                    button(t("Удалить"), "link", lambda i=index: editor.delete_mode(i)),
                )
            )
            self.add(frame)
        self.add(button(t("Добавить режим"), "", editor.add_mode))
        self.add(button(t("Отправить на ПК"), "primary", editor.send_to_pc))
        self.add(button(t("Поделиться профилем (файл JSON)"), "link", editor.share_json))
        self.add(button(t("Поделиться для grandMA3 (файл XML)"), "link", editor.share_ma3))
        self.add(button(t("Поделиться для grandMA2 (файлы XML режимов)"), "link", editor.share_ma2))
        self._issues(validate_profile(profile))

    # ---- режим ---------------------------------------------------------------------------------------
    def _template_combo(self, current: str | None, on_pick) -> QComboBox:
        from gmagc_common.fixtures import template_title

        combo = QComboBox()
        if current is None:
            combo.addItem(t("Добавить канал (шаблон)"), "")
        for template in TEMPLATES:
            combo.addItem(template_title(template), template.id)
        if current is not None:
            combo.setCurrentIndex(next(i for i, tpl in enumerate(TEMPLATES) if tpl.id == current))
        combo.activated.connect(lambda index: on_pick(combo.itemData(index)))
        return combo

    def _render_mode(self) -> None:
        editor = self.editor
        mode = editor.mode
        self._messages()
        if editor.notice and editor.undo_profile is not None:
            self.add(button(t("Отменить"), "link", editor.undo_apply))
        self._field(t("Название режима"), mode.name, editor.rename_current_mode)
        self.add(label(t("Каналы"), "heading"))
        for index, channel in sorted(enumerate(mode.channels), key=lambda pair: pair[1].dmx):
            span = f"{channel.dmx}–{channel.last}" if channel.bits == 16 else str(channel.dmx)
            frame = card()
            box = QVBoxLayout(frame)
            box.addWidget(label(f"{span}  {channel.name}"))
            box.addWidget(
                _row(
                    button(t("Открыть"), "", lambda i=index: editor.open_channel(i)),
                    button(t("Удалить"), "link", lambda i=index: editor.delete_channel(i)),
                )
            )
            self.add(frame)
        scan = button(t("Заполнить по инструкции"), "", editor.scan)
        scan.setEnabled(not editor.scanning)
        self.add(scan)
        if editor.draft is not None:
            self.add(button(t("Продолжить с прошлым результатом"), "", editor.resume_draft))
        self._cloud_controls(reuse=False)
        if editor.scanning:
            self.add(label(t("Распознаю инструкцию на ПК, это может занять минуту…"), "muted"))
        combo = self._template_combo(None, lambda tid: tid and editor.add_channel(tid))
        self.add(combo)
        self._issues(
            [i for i in validate_profile(editor.profile) if i.path == mode.name or i.path.startswith(f"{mode.name} → ")]
        )

    def _cloud_controls(self, reuse: bool) -> None:
        """Кнопка облака; после нажатия — вопрос с объяснением, что уходит и куда."""
        editor = self.editor
        if editor.confirm_cloud is None:
            title = t("Улучшить в облаке") if reuse else t("Распознать в облаке")
            cloud = button(title, "", lambda: editor.ask_cloud(reuse))
            cloud.setEnabled(not editor.scanning)
            self.add(cloud)
            return
        self.add(
            label(
                t(
                    "Файл инструкции будет отправлен через ПК в облако Anthropic (Claude) для распознавания. "
                    "Нужен ключ Anthropic в настройках ПК-приложения. Отправить?"
                ),
                "muted",
            )
        )
        self.add(
            _row(
                button(t("Отправить в облако"), "primary", editor.confirm_cloud_scan),
                button(t("Отмена"), "", editor.cancel_cloud),
            )
        )

    # ---- проверка распознанного ----------------------------------------------------------------------------
    def _render_scan(self) -> None:
        editor, draft = self.editor, self.editor.draft
        self.add(label(t("Снимите галочки с лишнего. Названия и диапазоны можно поправить после добавления."), "muted"))
        self._messages()
        if editor.notice and editor.undo_profile is not None:
            self.add(button(t("Отменить"), "link", editor.undo_apply))
        if len(draft.modes) > 1:
            self.add(button(t("Добавить все режимы новыми"), "", editor.apply_all_new))
        for mode_index, draft_mode in enumerate(draft.modes):
            title = draft_mode.name or t("Продолжение таблицы")
            heading = t("{name} ({count} кан.)", name=title, count=len(draft_mode.channels))
            if mode_index in editor.draft_done:
                heading += " ✓"
            self.add(label(heading, "heading"))
            for channel_index, channel in enumerate(draft_mode.channels):
                box = QCheckBox(draft_channel_label(channel))
                box.setChecked((mode_index, channel_index) in editor.draft_checked)
                box.toggled.connect(lambda on, m=mode_index, c=channel_index: editor.toggle_draft_channel(m, c, on))
                self.add(box)
            self.add(
                _row(
                    button(t("В этот режим"), "", lambda m=mode_index: editor.apply_draft(m, False)),
                    button(t("Новым режимом"), "", lambda m=mode_index: editor.apply_draft(m, True)),
                )
            )
        for code in draft.warnings:
            self.add(label(warning_text(code), "muted"))
        if draft.engine != ENGINE_CLOUD:
            self._cloud_controls(reuse=True)
        if editor.scanning:
            self.add(label(t("Распознаю инструкцию на ПК, это может занять минуту…"), "muted"))

    # ---- канал и диапазоны ------------------------------------------------------------------------------------
    def _number(self, caption: str, value: int, setter) -> QWidget:
        box = QWidget()
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 0, 0, 0)
        col.addWidget(label(caption, "muted"))
        edit = QLineEdit(str(value))
        edit.textEdited.connect(lambda text: setter(parse_int(text, value)))
        col.addWidget(edit)
        return box

    def _render_channel(self) -> None:
        editor, channel = self.editor, self.editor.channel
        self._messages()
        self.add(label(t("Шаблон"), "muted"))
        self.add(self._template_combo(channel.template, lambda tid: editor.set_channel(template=tid)))
        self._field(t("Название"), channel.name, lambda value: editor.set_channel(name=value))
        self.add(
            _row(
                self._number("DMX", channel.dmx, lambda v: editor.set_channel(dmx=v)),
                self._number(t("По умолчанию"), channel.default, lambda v: editor.set_channel(default=v)),
            )
        )
        bits_buttons = []
        for bits in (8, 16):
            b = button(t("{bits} бит", bits=bits), "", lambda n=bits: editor.set_channel(bits=n, render=True))
            b.setEnabled(channel.bits != bits)
            bits_buttons.append(b)
        self.add(_row(*bits_buttons))
        self.add(label(t("Диапазоны значений (0–255)"), "heading"))
        for index, item in enumerate(channel.ranges):
            self._range_card(index, item)
        self.add(button(t("Добавить диапазон"), "", editor.add_range))
        path = f"{editor.mode.name} → {channel.name.strip() or '(без названия)'}"  # как в validate_profile
        self._issues([i for i in validate_profile(editor.profile) if i.path == path])

    def _range_card(self, index: int, item) -> None:
        editor = self.editor
        frame = card()
        box = QVBoxLayout(frame)
        box.addWidget(
            _row(
                self._number(t("От"), item.start, lambda v, i=index: editor.set_range(i, start=v)),
                self._number(t("До"), item.end, lambda v, i=index: editor.set_range(i, end=v)),
            )
        )
        box.addWidget(label(t("Название значения"), "muted"))
        name = QLineEdit(item.name)
        name.textEdited.connect(lambda value, i=index: editor.set_range(i, name=value))
        box.addWidget(name)
        if editor.channel.template == "gobo_wheel":
            if item.gobo is None:
                box.addWidget(button(t("Гобо из библиотеки"), "", lambda i=index: editor.open_gobo_picker(i)))
            else:
                box.addWidget(label(t("Гобо: {name}", name=item.gobo.name)))
                box.addWidget(button(t("Убрать гобо"), "link", lambda i=index: editor.clear_gobo(i)))
        box.addWidget(button(t("Удалить диапазон"), "link", lambda i=index: editor.delete_range(i)))
        self.add(frame)

    # ---- гобо ---------------------------------------------------------------------------------------------------
    def _render_gobo(self) -> None:
        editor = self.editor
        self.add(label(t("Имя гобо"), "muted"))
        query = QLineEdit(editor.gobo_query)
        query.returnPressed.connect(lambda: editor.find_gobos(query.text()))
        self.add(query)
        self.add(button(t("Найти по фото"), "", editor.find_gobos_by_photo))
        if editor.gobo_busy:
            self.add(label(t("Ищу на ПК…"), "muted"))
        if editor.message:
            self.add(label(editor.message, "error"))
        for index, item in enumerate(editor.gobo_items):
            frame = card()
            row = QHBoxLayout(frame)
            row.addWidget(picture(item.png, 56, 56))
            row.addWidget(label(item.name), 1)
            row.addWidget(button(t("Выбрать"), "", lambda i=index: editor.pick_gobo(i)))
            self.add(frame)
        if editor.gobo_total > len(editor.gobo_items):
            self.add(label(t("Ещё {count}: уточните запрос.", count=editor.gobo_total - len(editor.gobo_items)), "muted"))
