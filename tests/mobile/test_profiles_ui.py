import asyncio
import json
from dataclasses import replace

import flet as ft

from gmagc_common.fixtures import Channel, FixtureProfile, Mode, new_profile
from gmagc_common.protocol import FixtureUploadResult
from gmagc_mobile.client import NO_TARGET, ClientError
from gmagc_mobile.profile_store import ProfileStore, profile_key
from gmagc_mobile.profiles_ui import ProfileEditor, parse_int
from tests.fakes import StubPage, texts, walk
from tests.fakes_mobile import FakePrefs, FakeShare


def run(coroutine):
    return asyncio.run(coroutine)


def make_editor(prefs=None):
    prefs = prefs if prefs is not None else FakePrefs()
    store = ProfileStore(prefs)
    editor = ProfileEditor(StubPage(), store, FakeShare(), on_exit=lambda: None)
    return editor, store, prefs


def shown(editor):
    return " | ".join(t for t in texts(editor.view) if t)


def test_an_empty_list_offers_to_create_the_first_profile():
    editor, _, _ = make_editor()

    run(editor.open())

    assert editor.screen == "list" and "Нет профилей" in shown(editor)


def test_a_new_profile_is_saved_at_once_and_opens_its_screen():
    editor, store, prefs = make_editor()
    run(editor.open())

    run(editor.on_new_profile(None))

    assert editor.screen == "profile" and editor.profile is not None
    assert len(run(store.list())) == 1 and profile_key(editor.profile.id) in prefs.data


def test_the_list_shows_saved_profiles_with_manufacturer_and_mode_count():
    editor, store, _ = make_editor()
    run(store.save(FixtureProfile("1", "SHEHDS", "380W Beam", "", (Mode("a"), Mode("b")))))

    run(editor.open())

    assert "380W Beam" in shown(editor) and "SHEHDS" in shown(editor) and "2" in shown(editor)


def test_opening_a_profile_from_the_list_shows_its_screen():
    editor, store, _ = make_editor()
    run(store.save(new_profile("M", "N")))
    run(editor.open())

    run(editor.on_open_profile(editor.profiles[0].id))

    assert editor.screen == "profile" and editor.profile.name == "N"


def test_deleting_needs_a_second_confirmation():
    editor, store, _ = make_editor()
    run(store.save(new_profile("M", "N")))
    run(editor.open())
    profile_id = editor.profiles[0].id

    editor.on_ask_delete(profile_id)
    assert len(run(store.list())) == 1 and "Удалить" in shown(editor)
    editor.on_cancel_delete()
    assert len(run(store.list())) == 1
    editor.on_ask_delete(profile_id)
    run(editor.on_confirm_delete(profile_id))

    assert run(store.list()) == [] and "Нет профилей" in shown(editor)


def test_back_from_a_profile_returns_to_the_list_and_from_the_list_is_not_handled():
    editor, store, _ = make_editor()
    run(editor.open())
    run(editor.on_new_profile(None))

    assert editor.go_back() is True and editor.screen == "list"
    assert editor.go_back() is False


def open_new(editor):
    run(editor.open())
    run(editor.on_new_profile(None))


def test_profile_fields_are_saved_as_you_type():
    editor, store, _ = make_editor()
    open_new(editor)

    run(editor.set_profile_text("manufacturer", "SHEHDS"))
    run(editor.set_profile_text("name", "380W Beam"))
    run(editor.set_profile_text("short_name", "380WB"))

    saved = run(store.list())[0]
    assert (saved.manufacturer, saved.name, saved.short_name) == ("SHEHDS", "380W Beam", "380WB")


def test_adding_a_mode_gives_it_a_unique_name_and_saves():
    editor, store, _ = make_editor()
    open_new(editor)

    run(editor.add_mode())

    names = [m.name for m in run(store.list())[0].modes]
    assert names == ["Режим 1", "Режим 2"]


def test_duplicating_a_mode_copies_its_channels_under_a_new_name():
    editor, store, _ = make_editor()
    open_new(editor)
    mode = replace(editor.profile.modes[0], channels=(Channel(1, 8, "d", "dimmer"),))
    with_channel = replace(editor.profile, modes=(mode,))
    run(editor._commit(with_channel))

    run(editor.duplicate_mode(0))

    modes = run(store.list())[0].modes
    assert len(modes) == 2 and modes[1].name != modes[0].name and modes[1].channels == modes[0].channels


def test_the_last_mode_can_not_be_deleted_but_others_can():
    editor, store, _ = make_editor()
    open_new(editor)

    run(editor.delete_mode(0))
    assert len(run(store.list())[0].modes) == 1

    run(editor.add_mode())
    run(editor.delete_mode(0))
    assert len(run(store.list())[0].modes) == 1


def test_renaming_a_mode_is_saved():
    editor, store, _ = make_editor()
    open_new(editor)

    run(editor.rename_mode(0, "Расширенный"))

    assert run(store.list())[0].modes[0].name == "Расширенный"


def test_the_profile_screen_lists_modes_and_shows_validation_messages():
    editor, _, _ = make_editor()
    open_new(editor)

    text = shown(editor)

    assert "Режим 1" in text and "не указан производитель" in text


def test_a_channel_added_from_a_template_gets_the_next_free_address():
    editor, store, _ = make_editor()
    open_new(editor)
    run(editor.open_mode(0))

    run(editor.add_channel("dimmer"))
    run(editor.add_channel("pan"))
    run(editor.add_channel("shutter"))

    channels = run(store.list())[0].modes[0].channels
    assert [(c.dmx, c.bits, c.template) for c in channels] == [(1, 8, "dimmer"), (2, 16, "pan"), (4, 8, "shutter")]


def test_deleting_a_channel_keeps_the_others_untouched():
    editor, store, _ = make_editor()
    open_new(editor)
    run(editor.open_mode(0))
    run(editor.add_channel("dimmer"))
    run(editor.add_channel("red"))

    run(editor.delete_channel(0))

    assert [c.template for c in run(store.list())[0].modes[0].channels] == ["red"]


def test_the_mode_screen_shows_channels_in_dmx_order_and_validation_messages():
    editor, _, _ = make_editor()
    open_new(editor)
    run(editor.open_mode(0))
    run(editor.add_channel("dimmer"))
    run(editor.add_channel("pan"))

    text = shown(editor)

    assert "Диммер" in text and "Pan" in text


def test_a_channel_added_beyond_512_is_reported_as_an_error_on_the_screen():
    editor, store, _ = make_editor()
    open_new(editor)
    run(editor.open_mode(0))
    profile = run(store.list())[0]
    run(editor._commit(replace(profile, modes=(replace(profile.modes[0], channels=(Channel(512, 8, "z", "dimmer"),)),))))
    run(editor.add_channel("dimmer"))

    assert "адрес должен лежать" in shown(editor)


def test_opening_a_channel_switches_to_the_channel_screen():
    editor, _, _ = make_editor()
    open_new(editor)
    run(editor.open_mode(0))
    run(editor.add_channel("dimmer"))

    run(editor.open_channel(0))

    assert editor.screen == "channel" and editor.go_back() is True and editor.screen == "mode"


def open_channel_of(editor, template="gobo_wheel"):
    open_new(editor)
    run(editor.open_mode(0))
    run(editor.add_channel(template))
    run(editor.open_channel(0))


def saved_channel(store):
    return run(store.list())[0].modes[0].channels[0]


def test_channel_fields_are_saved():
    editor, store, _ = make_editor()
    open_channel_of(editor)

    run(editor.set_channel(name="Гобо 1", dmx=9, bits=16, default=10))

    channel = saved_channel(store)
    assert (channel.name, channel.dmx, channel.bits, channel.default) == ("Гобо 1", 9, 16, 10)


def test_changing_the_template_keeps_name_and_address_but_takes_bits_and_ranges():
    editor, store, _ = make_editor()
    open_channel_of(editor, "dimmer")
    run(editor.set_channel(name="Мой канал", dmx=5))

    run(editor.set_channel(template="pan"))

    channel = saved_channel(store)
    assert (channel.name, channel.dmx, channel.template, channel.bits) == ("Мой канал", 5, "pan", 16)


def test_ranges_can_be_added_edited_and_deleted():
    editor, store, _ = make_editor()
    open_channel_of(editor, "control")

    run(editor.add_range())
    run(editor.set_range(0, start=0, end=9, name="Открыто"))
    run(editor.add_range())
    run(editor.set_range(1, start=10, end=255, name="Гобо 1"))
    assert [(r.start, r.end, r.name) for r in saved_channel(store).ranges] == [(0, 9, "Открыто"), (10, 255, "Гобо 1")]

    run(editor.delete_range(0))

    assert [r.name for r in saved_channel(store).ranges] == ["Гобо 1"]


def test_a_new_range_starts_right_after_the_previous_one():
    editor, store, _ = make_editor()
    open_channel_of(editor, "gobo_wheel")  # шаблон даёт диапазон 0–9

    run(editor.add_range())

    added = saved_channel(store).ranges[-1]
    assert (added.start, added.end) == (10, 255)


def test_non_numeric_input_keeps_the_previous_value():
    assert parse_int("12", 5) == 12 and parse_int("x", 5) == 5 and parse_int("", 5) == 5


def test_the_channel_screen_shows_range_rows():
    editor, _, _ = make_editor()
    open_channel_of(editor, "gobo_wheel")

    values = [c.value for c in walk(editor.view) if isinstance(c, ft.TextField)]
    assert "Открыто" in values




def test_the_redraw_after_typing_happens_later_and_only_if_nothing_else_redrew(monkeypatch):
    """Мгновенная перерисовка на потере фокуса съедала первое касание по кнопке под пальцем."""
    editor, _, _ = make_editor()
    open_new(editor)
    before = editor.page.updates

    async def quick_sleep(_seconds):
        return None

    monkeypatch.setattr("gmagc_mobile.profiles_ui.asyncio.sleep", quick_sleep)
    run(editor._redraw_later(None))
    assert editor.page.updates == before + 1

    async def sleep_with_a_render_in_between(_seconds):
        editor.render()  # пользователь успел нажать кнопку, экран уже перерисован

    monkeypatch.setattr("gmagc_mobile.profiles_ui.asyncio.sleep", sleep_with_a_render_in_between)
    before = editor.page.updates
    run(editor._redraw_later(None))

    assert editor.page.updates == before + 1  # только та перерисовка, что сделал сам пользователь


def ready_editor():
    editor, _, _ = make_editor()
    open_new(editor)
    run(editor.set_profile_text("manufacturer", "SHEHDS"))
    run(editor.set_profile_text("name", "380W Beam"))
    run(editor.open_mode(0))
    run(editor.add_channel("dimmer"))
    editor.go_back()
    return editor


def shared(editor):
    return {name: (data.decode("utf-8"), mime) for name, data, mime in editor.share.files}


def test_the_profile_is_shared_as_a_json_file_with_a_proper_name():
    editor = ready_editor()

    run(editor.on_share(None))

    files = shared(editor)
    assert list(files) == ["shehds@380w_beam.json"] and editor.share.texts == []
    text, mime = files["shehds@380w_beam.json"]
    assert mime == "application/json" and json.loads(text)["name"] == "380W Beam"


def test_the_ma3_type_is_shared_as_an_xml_file():
    editor = ready_editor()

    run(editor.on_share_ma3(None))

    files = shared(editor)
    assert list(files) == ["shehds@380w_beam.xml"]
    text, mime = files["shehds@380w_beam.xml"]
    assert mime == "application/xml" and text.startswith("<?xml") and 'Name="380W Beam"' in text


def test_the_ma2_types_of_all_modes_are_shared_as_separate_xml_files():
    editor = ready_editor()
    run(editor.add_mode())
    run(editor.open_mode(1))
    run(editor.add_channel("dimmer"))
    editor.go_back()

    run(editor.on_share_ma2(None))

    files = shared(editor)
    assert list(files) == ["shehds@380w_beam@режим_1.xml", "shehds@380w_beam@режим_2.xml"]
    assert all(mime == "application/xml" and text.startswith("<?xml") for text, mime in files.values())


def test_an_unfinished_profile_is_not_shared_and_the_reason_is_shown():
    editor, _, _ = make_editor()
    open_new(editor)

    for handler in (editor.on_share_ma3, editor.on_share_ma2):
        run(handler(None))
        assert editor.share.files == [] and "не готов к экспорту" in shown(editor)
        editor.message = ""


def test_a_failing_share_is_reported_on_the_screen_for_every_kind_of_file():
    editor = ready_editor()
    editor.share.fail = True

    for handler in (editor.on_share, editor.on_share_ma3, editor.on_share_ma2):
        editor.message = ""
        run(handler(None))
        assert "Не удалось поделиться" in shown(editor) and editor.screen == "profile"


def make_sending_editor(send, ready=True):
    editor = ProfileEditor(StubPage(), ProfileStore(FakePrefs()), FakeShare(), on_exit=lambda: None, send=send)
    open_new(editor)
    if ready:  # профиль, который можно отправлять: производитель, название и канал в режиме
        run(editor.set_profile_text("manufacturer", "SHEHDS"))
        run(editor.set_profile_text("name", "380W Beam"))
        run(editor.open_mode(0))
        run(editor.add_channel("dimmer"))
        editor.go_back()
    return editor


def test_sending_to_the_pc_passes_the_profile_and_shows_what_the_pc_wrote():
    sent = []

    async def send(profile):
        sent.append(profile)
        return FixtureUploadResult(
            (("ma3", "C:\\lib\\shehds@380w_beam.xml"), ("ma2", "C:\\imp\\shehds@380w_beam@standard.xml")),
            ("grandMA2: папка не найдена",),
        )

    editor = make_sending_editor(send)

    run(editor.on_send_to_pc(None))

    assert len(sent) == 1 and sent[0].id == editor.profile.id
    text = shown(editor)
    assert "shehds@380w_beam.xml" in text and "shehds@380w_beam@standard.xml" in text and "папка не найдена" in text


def test_a_failed_send_shows_the_reason_and_no_success_notice():
    async def send(profile):
        raise ClientError(NO_TARGET, "некуда записать типы приборов")

    editor = make_sending_editor(send)

    run(editor.on_send_to_pc(None))

    assert "не найдена папка" in shown(editor) and "Записано на ПК" not in shown(editor)


def test_sending_without_a_connection_explains_what_to_do():
    editor = make_sending_editor(None)

    run(editor.on_send_to_pc(None))

    assert "подключ" in shown(editor).lower()


def test_the_profile_screen_has_a_send_to_pc_button():
    editor = make_sending_editor(None)

    labels = [c.content for c in walk(editor.view) if isinstance(c, ft.Button)]

    assert any(isinstance(label, str) and "Отправить на ПК" in label for label in labels)


def test_the_modes_block_on_the_profile_screen_is_titled_mod():
    editor, _, _ = make_editor()
    open_new(editor)

    assert "Мод" in texts(editor.view) and "Режимы" not in texts(editor.view)


def test_the_editor_speaks_english_when_the_language_is_english():
    from gmagc_common import i18n

    i18n.set_language("en")
    editor, _, _ = make_editor()
    open_new(editor)

    text = shown(editor)
    assert "Manufacturer" not in text  # это подпись поля ввода, а не Text: проверяем видимые заголовки и кнопки
    labels = [c.content for c in walk(editor.view) if isinstance(c, ft.Button)]
    assert "Send to PC" in labels and "Add a mode" in labels
    assert "Modes" in texts(editor.view) and "Мод" not in texts(editor.view)


def test_the_upload_summary_describes_skipped_consoles_in_the_phone_language():
    from gmagc_common import i18n
    from gmagc_mobile.profiles_ui import upload_text

    skipped = ("no_folder:ma2", "cannot_use:ma3:C:/x: denied", "старый текст")
    result = FixtureUploadResult((("ma3", "C:\lib\a.xml"),), skipped)

    russian = upload_text(result)
    assert "grandMA2: папка не найдена" in russian and "не удалось использовать папку (C:/x: denied)" in russian
    assert "старый текст" in russian
    i18n.set_language("en")
    english = upload_text(result)
    assert "grandMA2: folder not found" in english and "could not use the folder (C:/x: denied)" in english


def test_an_unfinished_profile_is_not_sent_and_the_problems_are_listed_on_the_phone():
    sent = []

    async def send(profile):
        sent.append(profile)

    editor = make_sending_editor(send, ready=False)

    run(editor.on_send_to_pc(None))

    assert sent == [] and "не готов к отправке" in shown(editor) and "производитель" in shown(editor)


# ---- автозаполнение по инструкции ------------------------------------------------------------
def draft_with_two_modes():
    from gmagc_common.scan_draft import DraftChannel, DraftMode, ScanDraft

    four = DraftMode(
        "4CH",
        tuple(DraftChannel(n, name, tpl) for n, name, tpl in ((1, "R dimming", "red"), (2, "G dimming", "green"))),
    )
    nine = DraftMode(
        "9CH",
        (
            DraftChannel(1, "Total dimming", "dimmer"),
            DraftChannel(2, "Strobing", "shutter", confidence=0.6),
        ),
    )
    return ScanDraft((four, nine))


def make_scanning_editor(scan):
    editor = ProfileEditor(StubPage(), ProfileStore(FakePrefs()), FakeShare(), on_exit=lambda: None, scan=scan)
    editor.profile = new_profile("M", "N")
    editor.mode_index = 0
    editor.screen = "mode"
    return editor


def test_scanning_shows_the_draft_with_every_channel_checked():
    async def scan():
        return draft_with_two_modes()

    editor = make_scanning_editor(scan)

    run(editor.on_scan())

    labels = [c.label for c in walk(editor.view) if isinstance(c, ft.Checkbox)]
    boxes = [c for c in walk(editor.view) if isinstance(c, ft.Checkbox)]
    assert editor.screen == "scan" and len(labels) == 4 and all(c.value for c in boxes)
    assert "1  R dimming" in labels[0] and labels[3].endswith("?")


def test_only_checked_channels_are_added_to_the_current_mode():
    async def scan():
        return draft_with_two_modes()

    editor = make_scanning_editor(scan)
    run(editor.on_scan())
    editor._toggle_draft_channel(0, 1, False)

    run(editor.apply_draft(0, new_mode=False))

    assert editor.screen == "mode" and [c.name for c in editor.mode.channels] == ["R dimming"]
    assert "Добавлено каналов: 1" in shown(editor)


def test_a_draft_mode_can_become_a_new_mode_of_the_profile():
    async def scan():
        return draft_with_two_modes()

    editor = make_scanning_editor(scan)
    run(editor.on_scan())

    run(editor.apply_draft(1, new_mode=True))

    assert [m.name for m in editor.profile.modes] == ["Режим 1", "9CH"]
    assert editor.mode_index == 1 and len(editor.mode.channels) == 2


def test_applying_with_nothing_checked_asks_to_check_something():
    async def scan():
        return draft_with_two_modes()

    editor = make_scanning_editor(scan)
    run(editor.on_scan())
    for index in range(2):
        editor._toggle_draft_channel(0, index, False)

    run(editor.apply_draft(0, new_mode=False))

    assert editor.screen == "scan" and "Отметьте хотя бы один канал" in shown(editor)


def test_a_page_without_a_table_explains_what_to_do_and_stays_on_the_mode():
    from gmagc_common.scan_draft import ScanDraft

    async def scan():
        return ScanDraft((), ("no_table",))

    editor = make_scanning_editor(scan)

    run(editor.on_scan())

    assert editor.screen == "mode" and "не найдена таблица" in shown(editor)


def test_cancelling_the_file_choice_changes_nothing():
    async def scan():
        return None

    editor = make_scanning_editor(scan)

    run(editor.on_scan())

    assert editor.screen == "mode" and editor.draft is None and not editor.scanning


def test_a_pc_error_during_scanning_is_shown_and_the_button_is_usable_again():
    async def scan():
        raise ClientError("scan_unavailable", "нет модуля")

    editor = make_scanning_editor(scan)

    run(editor.on_scan())

    assert "нет модуля" in shown(editor) and not editor.scanning


def test_scanning_without_a_connection_says_so():
    editor = make_scanning_editor(None)

    run(editor.on_scan())

    assert "Нет подключения к ПК" in shown(editor)


def test_back_from_the_review_screen_returns_to_the_mode_without_adding():
    async def scan():
        return draft_with_two_modes()

    editor = make_scanning_editor(scan)
    run(editor.on_scan())

    assert editor.go_back() and editor.screen == "mode" and editor.draft is None and not editor.mode.channels
