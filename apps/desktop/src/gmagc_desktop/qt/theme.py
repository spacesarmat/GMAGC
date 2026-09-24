"""Тёмная тема ПК-приложения в виде QSS: цвета из `gmagc_common.theme`, крупный текст увеличивает шрифт."""

from __future__ import annotations

from gmagc_common.theme import (
    DESKTOP_ACCENT,
    DESKTOP_BG,
    DESKTOP_DIM,
    DESKTOP_LINE,
    DESKTOP_MUTED,
    DESKTOP_OK,
    DESKTOP_PANEL,
    DESKTOP_PANEL2,
    DESKTOP_STRONG,
    DESKTOP_TEXT,
)

BASE_FONT_PX = 13
LARGE_FONT_PX = 17

BADGE = {  # цвета бейджа оценки: фон, текст
    "good": ("#c8e6c9", "#1b5e20"),
    "low": ("#ffecb3", "#e65100"),
    "bad": ("#ffcdd2", "#b71c1c"),
}


def font_px(large_text: bool) -> int:
    return LARGE_FONT_PX if large_text else BASE_FONT_PX


def stylesheet(large_text: bool = False) -> str:
    """QSS всего приложения. Классы виджетов задаются свойством `role` (panel, nav, muted, dim, title, banner...)."""
    size = font_px(large_text)
    return f"""
* {{ font-size: {size}px; color: {DESKTOP_TEXT}; }}
QMainWindow, QWidget#root {{ background: {DESKTOP_BG}; }}
QWidget {{ background: transparent; }}
QToolTip {{ background: {DESKTOP_PANEL2}; color: {DESKTOP_TEXT}; border: 1px solid {DESKTOP_STRONG}; }}

QFrame[role="panel"] {{ background: {DESKTOP_PANEL}; border: 1px solid {DESKTOP_LINE}; border-radius: 2px; }}
QFrame[role="panel2"] {{ background: {DESKTOP_PANEL2}; border: 1px solid {DESKTOP_LINE}; border-radius: 2px; }}
QFrame[role="sidebar"] {{ background: {DESKTOP_BG}; border-right: 1px solid {DESKTOP_LINE}; }}
QFrame[role="line"] {{ background: {DESKTOP_LINE}; border: none; max-height: 1px; min-height: 1px; }}
QFrame[role="card"] {{ background: {DESKTOP_PANEL}; border: 1px solid {DESKTOP_LINE}; border-radius: 2px; }}
QFrame[role="card"]:hover {{ border-color: {DESKTOP_ACCENT}; }}
QFrame[role="preview"] {{ background: {DESKTOP_BG}; border: 1px solid {DESKTOP_STRONG}; }}

QLabel[role="title"] {{ font-size: {size + 9}px; font-weight: bold; }}
QLabel[role="heading"] {{ font-size: {size + 1}px; font-weight: bold; }}
QLabel[role="muted"] {{ color: {DESKTOP_MUTED}; font-size: {size - 2}px; }}
QLabel[role="dim"] {{ color: {DESKTOP_DIM}; font-size: {size - 4}px; }}
QLabel[role="ok"] {{ color: {DESKTOP_OK}; }}
QLabel[role="metric"] {{ font-size: {size}px; }}

QPushButton {{
    background: {DESKTOP_PANEL2}; border: 1px solid {DESKTOP_STRONG}; border-radius: 2px; padding: 6px 14px;
}}
QPushButton:hover {{ border-color: {DESKTOP_ACCENT}; }}
QPushButton:disabled {{ color: {DESKTOP_DIM}; border-color: {DESKTOP_LINE}; }}
QPushButton[role="link"] {{ background: transparent; border: none; color: {DESKTOP_ACCENT}; padding: 4px 8px; }}
QPushButton[role="nav"] {{
    background: transparent; border: none; border-radius: 2px; padding: 10px; text-align: left;
}}
QPushButton[role="nav"]:hover {{ background: {DESKTOP_PANEL}; }}
QPushButton[role="nav"]:checked {{ background: {DESKTOP_PANEL2}; }}

QLineEdit, QComboBox {{
    background: {DESKTOP_PANEL2}; border: 1px solid {DESKTOP_STRONG}; border-radius: 2px; padding: 5px 8px;
    selection-background-color: {DESKTOP_ACCENT};
}}
QLineEdit:focus, QComboBox:focus {{ border-color: {DESKTOP_ACCENT}; }}
QComboBox QAbstractItemView {{ background: {DESKTOP_PANEL2}; selection-background-color: {DESKTOP_STRONG}; }}

QCheckBox {{ spacing: 8px; }}
QProgressBar {{ background: {DESKTOP_PANEL2}; border: 1px solid {DESKTOP_LINE}; height: 8px; text-align: center; }}
QProgressBar::chunk {{ background: {DESKTOP_ACCENT}; }}
QSlider::groove:horizontal {{ height: 4px; background: {DESKTOP_LINE}; }}
QSlider::handle:horizontal {{ background: {DESKTOP_ACCENT}; width: 14px; margin: -6px 0; border-radius: 7px; }}
QScrollArea {{ border: none; }}
QScrollBar:vertical {{ background: {DESKTOP_BG}; width: 10px; }}
QScrollBar::handle:vertical {{ background: {DESKTOP_STRONG}; min-height: 24px; border-radius: 4px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

QFrame[role="banner"] {{ border-radius: 2px; }}
QFrame[role="banner"][error="true"] {{ background: #ffcdd2; }}
QFrame[role="banner"][error="false"] {{ background: #ffecb3; }}
QFrame[role="banner"] QLabel {{ color: #000; }}
"""
