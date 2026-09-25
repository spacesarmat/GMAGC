import json

import pytest
from PySide6.QtCore import QSettings

from gmagc_common import i18n
from gmagc_common.fixtures import Gobo, Range, profile_to_dict
from gmagc_common.phone_client import UNREACHABLE, ClientError
from gmagc_common.protocol import Connection, FixtureUploadResult, GoboItem, GoboList, MatchResponse, ResultItem
from gmagc_common.scan_draft import DraftChannel, DraftMode, ScanDraft
from gmagc_phone import profiles as p
from gmagc_phone.controller import PhoneController
from gmagc_phone.profiles import ProfilesController
from gmagc_phone.screens.profiles import ProfilesScreen
from gmagc_phone.settings import PhoneSettings
from gmagc_phone.tasks import InlineExecutor


class FakeClient:
    def __init__(self):
        self.sent = []
        self.draft = ScanDraft(
            modes=(
                DraftMode("9CH", (DraftChannel(1, "Dimmer", "dimmer"), DraftChannel(2, "Pan", "pan", 16))),
                DraftMode("12CH", (DraftChannel(1, "Dimmer", "dimmer"),)),
            )
        )
        self.scans = []
        self.error = None

    def send_fixture(self, profile):
        if self.error:
            raise self.error
        self.sent.append(profile)
        return FixtureUploadResult((("ma3", "C:/x/a.xml"),), ("no_folder:ma2",))

    def scan_fixture(self, data, content_type="image/jpeg", engine="local"):
        self.scans.append((data, content_type, engine))
        return self.draft

    def find_gobos(self, query, limit=30):
        item = GoboItem("star", "lib/star.png", "gobos/star.png", b"", "thumb")
        return GoboList((item,), 1)

    def gobo(self, path):
        return GoboItem("star", "lib/star.png", "gobos/star.png", b"", "thumb")

    def match(self, data, top=None):
        return MatchResponse("r", "found", 1.0, (ResultItem(1, "star", "C:/s.png", 0.9, (), b""),), None)


@pytest.fixture(autouse=True)
def russian():
    i18n.set_language("ru")


@pytest.fixture
def env(tmp_path):
    settings = PhoneSettings(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    phone = PhoneController(settings, executor=InlineExecutor())
    client = FakeClient()
    phone.client = client
    phone.connection = Connection("192.168.1.5", 8765, "ABCD2345")
    shared = []
    picks = {"scan": b"jpegbytes", "photo": b"photo", "json": None}
    editor = ProfilesController(
        phone,
        share=lambda files, subject: shared.append((files, subject)),
        pick_scan_file=lambda: picks["scan"],
        pick_photo=lambda: picks["photo"],
        pick_json=lambda: picks["json"],
    )
    editor.open()
    return editor, client, settings, shared, picks


def ready_profile(editor):
    editor.new_profile()
    editor.set_profile_text("manufacturer", "Acme")
    editor.set_profile_text("name", "Spot")
    editor.open_mode(0) if editor.profile.modes else (editor.add_mode(), editor.open_mode(0))
    editor.add_channel("dimmer")


def test_new_profile_is_saved_and_listed(env):
    editor, _, settings, _, _ = env
    editor.new_profile()
    editor.set_profile_text("name", "Spot")
    editor.go_back()
    assert editor.screen == p.SCREEN_LIST
    assert [x.name for x in settings.load_profiles()] == ["Spot"]


def test_delete_profile_needs_confirmation(env):
    editor, _, settings, _, _ = env
    editor.new_profile()
    pid = editor.profile.id
    editor.go_back()
    editor.ask_delete(pid)
    assert settings.load_profiles()
    editor.cancel_delete()
    editor.ask_delete(pid)
    editor.confirm_delete(pid)
    assert settings.load_profiles() == []


def test_modes_add_duplicate_delete(env):
    editor, *_ = env
    editor.new_profile()
    editor.add_mode()
    editor.duplicate_mode(0)
    names = [m.name for m in editor.profile.modes]
    assert len(names) == len(set(names)) == 3
    editor.delete_mode(0)
    editor.delete_mode(0)
    editor.delete_mode(0)  # последний режим не удаляется
    assert len(editor.profile.modes) == 1


def test_channels_and_ranges(env):
    editor, *_ = env
    ready_profile(editor)
    assert len(editor.mode.channels) == 1
    editor.open_channel(0)
    editor.set_channel(name="Яркость", dmx=5)
    editor.add_range()
    editor.set_range(len(editor.channel.ranges) - 1, start=3, end=9, name="Диапазон")
    assert editor.channel.name == "Яркость" and editor.channel.dmx == 5
    assert editor.channel.ranges[-1].name == "Диапазон"
    editor.delete_range(len(editor.channel.ranges) - 1)
    editor.set_channel(template="gobo_wheel")
    assert editor.channel.template == "gobo_wheel"
    editor.go_back()
    editor.delete_channel(0)
    assert editor.mode.channels == ()


def test_gobo_picker_by_name_and_photo(env):
    editor, *_ = env
    ready_profile(editor)
    editor.open_channel(0)
    editor.set_channel(template="gobo_wheel")
    editor.open_gobo_picker(0)
    editor.find_gobos("star")
    assert [g.name for g in editor.gobo_items] == ["star"]
    editor.find_gobos_by_photo()
    assert editor.gobo_items
    editor.pick_gobo(0)
    assert editor.screen == p.SCREEN_CHANNEL
    assert isinstance(editor.channel.ranges[0].gobo, Gobo)
    editor.clear_gobo(0)
    assert editor.channel.ranges[0].gobo is None


def test_send_to_pc_reports_result(env):
    editor, client, *_ = env
    ready_profile(editor)
    editor.go_back()
    editor.send_to_pc()
    assert client.sent and client.sent[0]["name"] == "Spot"
    assert "a.xml" in editor.notice


def test_send_invalid_profile_is_refused(env):
    editor, client, *_ = env
    editor.new_profile()
    editor.send_to_pc()
    assert client.sent == []
    assert editor.message


def test_send_error_is_shown(env):
    editor, client, *_ = env
    ready_profile(editor)
    editor.go_back()
    client.error = ClientError(UNREACHABLE, "нет связи")
    editor.send_to_pc()
    assert editor.message


def test_send_without_connection(env):
    editor, *_ = env
    ready_profile(editor)
    editor.go_back()
    editor.phone.client = None
    editor.send_to_pc()
    assert editor.message == p.not_connected()


def test_scan_apply_undo_and_all_modes(env):
    editor, client, *_ = env
    ready_profile(editor)
    editor.scan()
    assert client.scans == [(b"jpegbytes", "image/jpeg", "local")]
    assert editor.screen == p.SCREEN_SCAN
    editor.apply_draft(0, False)
    assert len(editor.mode.channels) == 3
    assert editor.undo_profile is not None
    editor.undo_apply()
    assert len(editor.mode.channels) == 1
    editor.apply_all_new()
    assert len(editor.profile.modes) == 3
    editor.apply_all_new()
    assert "Нечего" in editor.message


def test_scan_without_channels_selected(env):
    editor, *_ = env
    ready_profile(editor)
    editor.scan()
    for c in range(2):
        editor.toggle_draft_channel(0, c, False)
    editor.apply_draft(0, True)
    assert editor.message


def test_scan_cancelled_by_user(env):
    editor, client, _, _, picks = env
    ready_profile(editor)
    picks["scan"] = None
    editor.scan()
    assert client.scans == [] and editor.screen == p.SCREEN_MODE


def test_cloud_requires_confirmation_and_reuses_file(env):
    editor, client, *_ = env
    ready_profile(editor)
    editor.scan()
    editor.go_back()
    editor.resume_draft()
    editor.ask_cloud(True)
    assert client.scans[-1][2] == "local"
    editor.confirm_cloud_scan()
    assert client.scans[-1] == (b"jpegbytes", "image/jpeg", "cloud")


def test_pdf_content_type(env):
    editor, client, _, _, picks = env
    ready_profile(editor)
    picks["scan"] = b"%PDF-1.4 ..."
    editor.scan()
    assert client.scans[0][1] == "application/pdf"


def test_share_json_and_ma3(env):
    editor, _, _, shared, _ = env
    ready_profile(editor)
    editor.go_back()
    editor.share_json()
    editor.share_ma3()
    assert shared[0][0][0][0].endswith(".json")
    assert json.loads(shared[0][0][0][1])["name"] == "Spot"
    assert shared[1][0][0][0].endswith(".xml")


def test_share_without_backend_shows_message(env):
    editor, *_ = env
    ready_profile(editor)
    editor.share = None
    editor.share_json()
    assert editor.message


def test_import_json_creates_copy(env):
    editor, _, settings, _, picks = env
    ready_profile(editor)
    original = profile_to_dict(editor.profile)
    editor.go_back()
    picks["json"] = json.dumps(original).encode()
    editor.import_json()
    profiles = settings.load_profiles()
    assert len(profiles) == 2
    assert len({x.id for x in profiles}) == 2


def test_import_broken_json(env):
    editor, _, _, _, picks = env
    picks["json"] = b"{not json"
    editor.import_json()
    assert editor.message


def test_screens_render_every_stage(qtbot, env):
    editor, *_ = env
    screen = ProfilesScreen(editor.phone, editor)
    qtbot.addWidget(screen)
    screen.activate()
    ready_profile(editor)
    screen.render()
    editor.open_channel(0)
    editor.set_channel(template="gobo_wheel")
    editor.add_range()
    editor.open_gobo_picker(0)
    editor.find_gobos("star")
    editor.pick_gobo(0)
    editor.go_back()
    editor.scan()
    editor.ask_cloud(True)
    editor.go_back()
    editor.go_back()
    editor.go_back()
    editor.ask_delete(editor.profile.id if editor.profile else editor.profiles[0].id)
    assert screen.title.text()


def test_screen_back_leaves_to_previous_overlay(qtbot, env):
    editor, *_ = env
    screen = ProfilesScreen(editor.phone, editor)
    qtbot.addWidget(screen)
    seen = []
    editor.phone.screen_requested.connect(seen.append)
    editor.phone.return_view = "camera"
    screen._back()
    assert seen == ["camera"]


def test_range_helper_dataclass_roundtrip():
    assert Range(0, 1, "x").start == 0
