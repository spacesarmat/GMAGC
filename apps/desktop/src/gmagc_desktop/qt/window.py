"""Главное окно: боковая навигация, хлебные крошки, баннер, подсказка первого запуска, стек экранов, статус-строка."""

from __future__ import annotations

import platform

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from gmagc_common.i18n import t
from gmagc_common.theme import DESKTOP_MUTED, DESKTOP_OK
from gmagc_desktop.about import AUTHOR, NAME, VERSION
from gmagc_desktop.qt.controller import AppController
from gmagc_desktop.qt.icons import icon

SCREENS = ("search", "phone", "library", "settings")


def screen_label(name: str) -> str:
    """Название экрана на текущем языке (для навигации и хлебных крошек)."""
    labels = {"search": t("Поиск гобо"), "phone": t("Телефон"), "library": t("Библиотека"), "settings": t("Настройки")}
    return labels[name]


def onboarding_text() -> str:
    return t(
        "Добро пожаловать! Откройте экран «Библиотека» слева, чтобы выбрать папку гобо и построить индекс — "
        "после этого можно искать по фото (файл или буфер обмена) или подключить телефон на экране «Телефон»."
    )


def _line() -> QFrame:
    line = QFrame()
    line.setProperty("role", "line")
    return line


class Banner(QFrame):
    """Сообщение над экранами: жёлтое — сведение, красное — ошибка."""

    def __init__(self):
        super().__init__()
        self.setProperty("role", "banner")
        self.label = QLabel()
        self.label.setWordWrap(True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(self.label)
        self.hide()

    def show_message(self, text: str, error: bool) -> None:
        self.setProperty("error", "true" if error else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        self.label.setText(text)
        self.show()


class OnboardingHint(QFrame):
    """Подсказка при первом запуске (пока не выбрана библиотека)."""

    def __init__(self, open_library):
        super().__init__()
        self.setProperty("role", "panel2")
        text = QLabel(onboarding_text())
        text.setWordWrap(True)
        self.goto_button = QPushButton(t("Перейти в «Библиотека»"))
        self.goto_button.setProperty("role", "link")
        self.dismiss_button = QPushButton(t("Понятно"))
        self.dismiss_button.setProperty("role", "link")
        buttons = QHBoxLayout()
        buttons.addWidget(self.goto_button)
        buttons.addWidget(self.dismiss_button)
        buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(2)
        layout.addWidget(text)
        layout.addLayout(buttons)
        self.goto_button.clicked.connect(open_library)
        self.dismiss_button.clicked.connect(self.dismiss)
        self.dismissed = False
        self.hide()

    def dismiss(self) -> None:
        self.dismissed = True
        self.hide()


class MainWindow(QMainWindow):
    def __init__(self, controller: AppController, screens: dict[str, QWidget]):
        super().__init__()
        self.controller = controller
        self.screens = screens
        self.current = "search"
        self.setWindowTitle(f"{NAME} {VERSION} — {AUTHOR}")
        self.resize(1100, 760)

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_sidebar())

        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)
        self.breadcrumb = QLabel()
        self.breadcrumb.setProperty("role", "muted")
        self.breadcrumb.setFixedHeight(48)
        self.breadcrumb.setContentsMargins(22, 0, 22, 0)
        content.addWidget(self.breadcrumb)
        content.addWidget(_line())

        body = QVBoxLayout()
        body.setContentsMargins(24, 24, 24, 24)
        body.setSpacing(12)
        self.banner = Banner()
        self.onboarding = OnboardingHint(lambda: self.show_screen("library"))
        self.stack = QStackedWidget()
        for name in SCREENS:
            self.stack.addWidget(self.screens[name])
        body.addWidget(self.onboarding)
        body.addWidget(self.banner)
        body.addWidget(self.stack, 1)
        content.addLayout(body, 1)
        content.addWidget(_line())
        content.addWidget(self._build_statusbar())
        outer.addLayout(content, 1)

        controller.banner_shown.connect(self.banner.show_message)
        controller.banner_hidden.connect(self.banner.hide)
        controller.library_changed.connect(self._on_library_changed)
        self._on_library_changed()
        self.show_screen("search")

    # ---- построение -------------------------------------------------------------
    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setProperty("role", "sidebar")
        sidebar.setFixedWidth(224)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        brand = QLabel(NAME)
        brand.setProperty("role", "heading")
        brand.setFixedHeight(64)
        brand.setContentsMargins(18, 0, 18, 0)
        layout.addWidget(brand)
        layout.addWidget(_line())

        self.nav_buttons: dict[str, QPushButton] = {}
        icons = {"search": "search", "phone": "phone", "library": "folder", "settings": "settings"}

        def add_group(caption: str, names: tuple[str, ...]) -> None:
            label = QLabel(caption)
            label.setProperty("role", "dim")
            label.setContentsMargins(14, 14, 0, 4)
            layout.addWidget(label)
            for name in names:
                button = QPushButton(screen_label(name))
                button.setProperty("role", "nav")
                button.setCheckable(True)
                button.setIcon(icon(icons[name], DESKTOP_MUTED))
                button.clicked.connect(lambda _checked=False, n=name: self.show_screen(n))
                self.nav_buttons[name] = button
                layout.addWidget(button)

        add_group(t("РАБОЧАЯ ОБЛАСТЬ"), ("search", "phone", "library"))
        layout.addSpacing(40)
        add_group(t("СИСТЕМА"), ("settings",))
        layout.addStretch(1)
        layout.addWidget(_line())

        footer = QWidget()
        column = QVBoxLayout(footer)
        column.setContentsMargins(16, 16, 16, 16)
        ready = QLabel("● " + t("Система готова"))
        ready.setStyleSheet(f"color: {DESKTOP_OK};")
        meta = QHBoxLayout()
        author = QLabel(AUTHOR)
        author.setProperty("role", "dim")
        version = QLabel(f"v{VERSION}")
        version.setProperty("role", "dim")
        meta.addWidget(author)
        meta.addStretch(1)
        meta.addWidget(version)
        column.addWidget(ready)
        column.addLayout(meta)
        layout.addWidget(footer)
        return sidebar

    def _build_statusbar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(30)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(16)
        self.statusbar_index = QLabel("INDEX: NOT BUILT")
        for text in ("OFFLINE MODE", None, f"DEVICE: {platform.system().upper() or 'DESKTOP'}",
                     f"PYTHON {platform.python_version()}", "QT"):
            label = self.statusbar_index if text is None else QLabel(text)
            label.setProperty("role", "dim")
            layout.addWidget(label)
        layout.addStretch(1)
        return bar

    # ---- поведение --------------------------------------------------------------
    def show_screen(self, name: str) -> None:
        self.current = name
        self.stack.setCurrentWidget(self.screens[name])
        for nav_name, button in self.nav_buttons.items():
            button.setChecked(nav_name == name)
        self.breadcrumb.setText(f"GMAGC / {screen_label(name)}")
        self._update_onboarding()

    def _on_library_changed(self) -> None:
        status = self.controller.service.status()
        self.statusbar_index.setText(
            f"INDEX: {status.files} FILES" if status is not None else "INDEX: NOT BUILT"
        )
        if self.controller.library_path:
            self.onboarding.hide()
        self._update_onboarding()

    def _update_onboarding(self) -> None:
        # подсказка нужна на экране поиска, пока библиотека не выбрана; закрытая пользователем не возвращается
        if self.controller.library_path:
            self.onboarding.hide()
        elif self.current == "search" and not self.onboarding.dismissed:
            self.onboarding.show()
        else:
            self.onboarding.hide()
