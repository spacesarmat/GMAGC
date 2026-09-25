"""Экран «Настройки» на Qt: сохранение значений, язык на лету, перенос настроек, проверка ядра, лог."""

import json

import pytest
from PySide6.QtWidgets import QApplication, QLineEdit

from gmagc_common import i18n
from gmagc_desktop.qt import controller as controller_module
from gmagc_desktop.qt.app import apply_theme, build_window, rebuild_window
from gmagc_desktop.qt.controller import AppController, InlineExecutor
from gmagc_desktop.qt.screens.settings import SettingsScreen
from gmagc_desktop.qt.theme import stylesheet
from tests.fakes import FakeServer


def make(service, saves=None, opens=None, **services):
    opened, revealed = [], []
    controller = AppController(
        service,
        InlineExecutor(),
        reveal=lambda path: revealed.append(path) or True,
        open_url=opened.append,
        server=FakeServer(),
        **services,
    )
    save_queue, open_queue = list(saves or []), list(opens or [])
    screen = SettingsScreen(
        controller,
        save_json=lambda _parent, _name: save_queue.pop(0) if save_queue else "",
        open_json=lambda _parent: open_queue.pop(0) if open_queue else "",
    )
    screen.show()
    return screen, controller, opened, revealed


def test_the_screen_shows_the_saved_settings(qapp, service):
    service.set_large_text(True)
    service.set_results_count(20)
    service.set_fixture_dirs("C:/ma3", "C:/ma2")
    service.set_cloud_key("sk-ant-secret")

    screen, _, _, _ = make(service)

    assert screen.large_text_check.isChecked() and screen.results_combo.currentData() == 20
    assert (screen.ma3_field.text(), screen.ma2_field.text()) == ("C:/ma3", "C:/ma2")
    assert screen.cloud_field.text() == "sk-ant-secret" and screen.cloud_field.echoMode() == QLineEdit.EchoMode.Password
    assert screen.language_combo.currentData() == service.settings.language


def test_the_switches_and_the_results_count_are_saved(qapp, service):
    screen, controller, _, _ = make(service)
    seen = []
    controller.large_text_changed.connect(seen.append)

    screen.large_text_check.setChecked(True)
    screen.results_combo.setCurrentIndex(screen.results_combo.findData(100))

    assert service.settings.large_text is True and seen == [True]
    assert service.settings.results_count == 100


def test_large_text_restyles_the_whole_application(qapp, service):
    apply_theme(True)
    large = qapp.styleSheet()
    apply_theme(False)

    assert large == stylesheet(True) and qapp.styleSheet() == stylesheet(False) and large != qapp.styleSheet()


def test_fixture_folders_and_the_cloud_key_are_saved_when_editing_finishes(qapp, service):
    screen, _, _, _ = make(service)

    screen.ma3_field.setText(" C:/ma3 ")
    screen.ma3_field.editingFinished.emit()
    screen.ma2_field.setText("C:/ma2")
    screen.ma2_field.editingFinished.emit()
    screen.cloud_field.setText("  sk-ant-x  ")
    screen.cloud_field.editingFinished.emit()

    assert (service.settings.ma3_fixture_dir, service.settings.ma2_fixture_dir) == ("C:/ma3", "C:/ma2")
    assert service.settings.anthropic_api_key == "sk-ant-x"


def test_choosing_a_language_saves_it_applies_it_and_asks_the_window_to_rebuild(qapp, service):
    screen, controller, _, _ = make(service)
    asked = []
    controller.language_changed.connect(asked.append)

    screen.language_combo.setCurrentIndex(screen.language_combo.findData("en"))

    assert service.settings.language == "en" and i18n.current_language() == "en" and asked == ["en"]


def test_the_window_is_rebuilt_in_the_new_language_keeping_the_services(qapp, service):
    from gmagc_desktop import lang_en  # noqa: F401 - регистрирует английские переводы

    server = FakeServer()
    window = build_window(service, InlineExecutor(), server=server)
    old_service = window.controller.service
    window.controller.set_language("en")

    fresh = rebuild_window(window)

    assert fresh is not window and fresh.controller.service is old_service and fresh.current == "settings"
    assert fresh.nav_buttons["library"].text() == "Library" and fresh.breadcrumb.text() == "GMAGC / Settings"
    assert fresh.controller.server is server


def test_export_writes_the_settings_without_the_cloud_key_and_import_restores_them(qapp, service, tmp_path):
    service.set_cloud_key("sk-ant-secret")
    service.set_results_count(20)
    target = tmp_path / "out.json"
    screen, controller, _, _ = make(service, saves=[str(target)], opens=[str(target)])
    banners = []
    controller.banner_shown.connect(lambda text, error: banners.append((text, error)))

    screen.export_button.click()

    saved = json.loads(target.read_text(encoding="utf-8"))
    assert saved["results_count"] == 20 and saved["anthropic_api_key"] == ""
    assert banners[-1][0].startswith("Настройки сохранены") and banners[-1][1] is False

    service.set_results_count(100)
    screen.import_button.click()

    assert service.settings.results_count == 20 and service.settings.anthropic_api_key == "sk-ant-secret"
    assert banners[-1][0].startswith("Настройки импортированы") and screen.results_combo.currentData() == 20


def test_cancelling_the_file_dialogs_changes_nothing(qapp, service):
    screen, controller, _, _ = make(service, saves=[""], opens=[""])
    banners = []
    controller.banner_shown.connect(lambda text, error: banners.append(text))

    screen.export_button.click()
    screen.import_button.click()

    assert banners == []


def test_unreadable_and_unwritable_files_are_reported(qapp, service, tmp_path):
    screen, controller, _, _ = make(service, saves=[str(tmp_path)], opens=[str(tmp_path / "gone.json")])
    banners = []
    controller.banner_shown.connect(lambda text, error: banners.append((text, error)))

    screen.export_button.click()  # запись в каталог
    screen.import_button.click()

    assert banners[0][0].startswith("Не удалось записать файл") and banners[0][1] is True
    assert banners[1][0].startswith("Не удалось прочитать файл") and banners[1][1] is True


def test_the_core_check_shows_the_result_and_the_versions(qapp, service):
    info = {"ok": True, "versions": {"numpy": "2.0", "cv2": "4.10"}}
    screen, _, _, _ = make(service, check=lambda: info)

    screen.check_button.click()
    assert screen.check_label.text() == "ОК: ядро работает, numpy: 2.0, cv2: 4.10"

    info["ok"] = False
    screen.check_button.click()
    assert screen.check_label.text().startswith("ОШИБКА: ядро не сработало")


def test_sending_the_log_opens_a_mail_draft_and_reveals_the_log_file(qapp, service, tmp_path):
    log = tmp_path / "gmagc.log"
    log.write_text("ошибка", encoding="utf-8")
    screen, controller, opened, revealed = make(service, log_path=log)

    screen.log_button.click()

    assert opened and opened[0].startswith("mailto:yodayodaspace@gmail.com?") and "subject=" in opened[0]
    assert revealed == [str(log)]


def test_an_empty_log_is_not_revealed_and_says_so(qapp, service, tmp_path):
    screen, controller, opened, revealed = make(service, log_path=tmp_path / "missing.log")
    banners = []
    controller.banner_shown.connect(lambda text, error: banners.append((text, error)))

    screen.log_button.click()

    assert opened and revealed == [] and banners == [("Файл лога пока пуст: ошибок в этой сессии не было", False)]


def test_autostart_is_switched_with_the_application_path_and_refused_without_it(qapp, service, monkeypatch):
    calls = []
    monkeypatch.setattr(controller_module.autostart, "set_autostart", lambda enabled, exe: calls.append((enabled, exe)))
    monkeypatch.setattr(controller_module, "current_executable", lambda: "C:/app/GMAGC.exe")
    screen, controller, _, _ = make(service)
    banners = []
    controller.banner_shown.connect(lambda text, error: banners.append((text, error)))

    assert controller.set_autostart(True) is True and calls == [(True, "C:/app/GMAGC.exe")]

    monkeypatch.setattr(controller_module, "current_executable", lambda: None)
    assert controller.set_autostart(True) is False
    assert banners == [("Не удалось определить путь к приложению", True)]


def test_the_extra_sections_are_placed_on_the_screen(qapp, service):
    from PySide6.QtWidgets import QLabel

    controller = AppController(service, InlineExecutor(), server=FakeServer())
    marker = QLabel("Обновления")
    screen = SettingsScreen(controller, extra_sections=[marker])

    assert marker.parent() is not None and marker in screen.findChildren(QLabel)


@pytest.fixture(autouse=True)
def restore_language():
    yield
    i18n.set_language("ru")
    QApplication.instance().setStyleSheet("") if QApplication.instance() else None
