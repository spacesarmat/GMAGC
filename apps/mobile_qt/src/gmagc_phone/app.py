"""Окно телефона: стопка экранов, переключаемая контроллером; сборка и запуск приложения."""

from __future__ import annotations

import sys
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QStackedWidget, QVBoxLayout, QWidget

from gmagc_common import i18n
from gmagc_common.i18n import t
from gmagc_phone import lang_en  # noqa: F401 - при импорте регистрирует английские переводы
from gmagc_phone.camera import CameraBackend, QtCamera, qt_camera_available
from gmagc_phone.controller import PhoneController
from gmagc_phone.files import pick_json, pick_photo, pick_scan_file, share_files
from gmagc_phone.profiles import ProfilesController
from gmagc_phone.settings import PhoneSettings
from gmagc_phone.tasks import PoolExecutor
from gmagc_phone.theme import stylesheet
from gmagc_phone.widgets import Toast

BACK_TWICE_MS = 2000


class MainWindow(QWidget):
    def __init__(
        self, controller: PhoneController, screens: dict[str, QWidget], camera_screen, quit_app: Callable[[], None]
    ):
        super().__init__()
        self.setObjectName("root")
        self.setWindowTitle("GMAGC")
        self.controller = controller
        self.screens = screens
        self.camera_screen = camera_screen
        self.quit_app = quit_app
        self.stack = QStackedWidget()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.top_layout = layout
        layout.addWidget(self.stack)
        for widget in screens.values():
            self.stack.addWidget(widget)
        self.toast = Toast(self)
        self._exit_armed = False
        controller.screen_requested.connect(self.show_screen)
        controller.toast.connect(self.toast.show_text)
        controller.copied.connect(lambda path: self.toast.show_text(t("Путь скопирован: {path}", path=path)))
        self.current = ""

    def show_screen(self, name: str) -> None:
        widget = self.screens.get(name) or self.screens["connect"]
        name = name if name in self.screens else "connect"
        leaving_camera = self.current == "camera" and name != "camera"
        if leaving_camera:
            self.camera_screen.deactivate()
        self.current = name
        self.stack.setCurrentWidget(widget)
        if name == "profiles":
            widget.activate()
        if name == "camera" and not leaving_camera:
            self.camera_screen.activate()

    def go_back(self) -> None:
        """Кнопка «Назад» телефона: вложенный экран закрывается, с главных — выход по второму нажатию."""
        view = self.controller.view
        if view == "profiles":
            self.screens["profiles"]._back()
        elif view in ("gallery", "settings", "about", "help"):
            self.controller.close_overlay()
        elif view == "results":
            self.controller.show_camera()
        elif self._exit_armed:
            self.quit_app()
        else:
            self._exit_armed = True
            self.toast.show_text(t("Нажмите «Назад» ещё раз, чтобы выйти"), BACK_TWICE_MS)
            from PySide6.QtCore import QTimer

            QTimer.singleShot(BACK_TWICE_MS, lambda: setattr(self, "_exit_armed", False))

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Back, Qt.Key.Key_Escape):
            self.go_back()
            event.accept()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.toast.hide()


def build_window(
    settings: PhoneSettings,
    backend: CameraBackend | None = None,
    executor=None,
    quit_app: Callable[[], None] | None = None,
    client_factory=None,
    pick_file=None,
    profile_share=None,
) -> MainWindow:
    from gmagc_phone.screens.camera import CameraScreen
    from gmagc_phone.screens.connect import ConnectScreen
    from gmagc_phone.screens.info import AboutScreen, HelpScreen, SettingsScreen
    from gmagc_phone.screens.profiles import ProfilesScreen
    from gmagc_phone.screens.results import GalleryScreen, ResultsScreen

    clipboard = QGuiApplication.clipboard()
    kwargs = {"client_factory": client_factory} if client_factory else {}
    controller = PhoneController(settings, executor=executor or PoolExecutor(), copy_text=clipboard.setText, **kwargs)
    backend = backend or (QtCamera() if qt_camera_available() else _NoCamera())
    camera_kwargs = {"pick_file": pick_file} if pick_file else {}
    camera_screen = CameraScreen(controller, backend, executor=controller.executor, **camera_kwargs)
    profile_editor = ProfilesController(
        controller,
        share=profile_share or share_files,
        pick_scan_file=pick_scan_file,
        pick_photo=pick_photo,
        pick_json=pick_json,
    )
    screens = {
        "connect": ConnectScreen(controller),
        "camera": camera_screen,
        "results": ResultsScreen(controller, share=clipboard.setText),
        "gallery": GalleryScreen(controller),
        "settings": SettingsScreen(controller),
        "about": AboutScreen(controller),
        "help": HelpScreen(controller),
        "profiles": ProfilesScreen(controller, profile_editor),
    }
    window = MainWindow(controller, screens, camera_screen, quit_app or QApplication.quit)
    return window


class _NoCamera(CameraBackend):
    """Камеры нет (ПК без веб-камеры): экран покажет причину, фото можно выбрать из файла."""

    def start(self) -> None:
        self.error.emit(t("Камера доступна только на телефоне (Android)"))


def attach_extras(window: MainWindow, settings: PhoneSettings, update_delay: float = 3.0, support_delay: float = 8.0):
    """Обновления и просьба поддержать автора: отдельно от сборки окна, чтобы тесты не ходили в сеть."""
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QDesktopServices

    from gmagc_phone.extras import SupportPrompt, UpdateBar, UpdateController

    def open_url(url: str) -> None:
        from PySide6.QtCore import QUrl

        QDesktopServices.openUrl(QUrl(url))

    updates = UpdateController(settings, window.controller.executor, open_url, window.quit_app)
    bar = UpdateBar(updates)
    window.top_layout.insertWidget(0, bar)
    window.screens["settings"].add_update_controls(updates)
    QTimer.singleShot(int(update_delay * 1000), updates.startup)
    support = SupportPrompt(
        settings, window, open_url, delay=support_delay, busy=lambda: window.controller.busy or window.current != "camera"
    )
    support.start()
    window.updates, window.support = updates, support


def run(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    settings = PhoneSettings()
    i18n.set_language(settings.load_language())
    app.setStyleSheet(stylesheet())
    holder: dict[str, MainWindow] = {}

    def open_window() -> None:
        window = build_window(settings)
        attach_extras(window, settings)
        old = holder.get("window")
        holder["window"] = window
        window.controller.language_changed.connect(lambda _choice: _rebuild())
        window.resize(400, 800)
        window.show()
        window.controller.start()
        if old is not None:
            old.camera_screen.deactivate()
            old.deleteLater()

    def _rebuild() -> None:
        from PySide6.QtCore import QTimer

        app.setStyleSheet(stylesheet())
        QTimer.singleShot(0, open_window)  # после выхода из обработчика выбора языка

    open_window()
    return app.exec()

