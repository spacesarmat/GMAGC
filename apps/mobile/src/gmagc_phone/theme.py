"""Тёмная тема телефона в виде QSS: крупные области нажатия (не меньше 48 px), акцент — циан камеры."""

from __future__ import annotations

from gmagc_common.theme import MOBILE_ACCENT_COLOR

BG = "#070d1c"
PANEL = "#111a30"
PANEL2 = "#18233f"
LINE = "#26345a"
TEXT = "#eef2ff"
MUTED = "#93a0c0"
ACCENT = MOBILE_ACCENT_COLOR
DANGER = "#ff8a80"
FONT_PX = 16
TOUCH_PX = 48

BADGE = {  # цвета бейджа оценки: фон, текст
    "good": ("#c8e6c9", "#1b5e20"),
    "low": ("#ffecb3", "#e65100"),
    "bad": ("#ffcdd2", "#b71c1c"),
}


def stylesheet() -> str:
    return f"""
* {{ font-size: {FONT_PX}px; color: {TEXT}; }}
QWidget {{ background: transparent; }}
QWidget#root, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {BG}; }}
QFrame[role="card"] {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 12px; }}
QFrame[role="bar"] {{ background: {PANEL}; border-bottom: 1px solid {LINE}; }}
QLabel[role="title"] {{ font-size: {FONT_PX + 6}px; font-weight: bold; }}
QLabel[role="heading"] {{ font-size: {FONT_PX + 2}px; font-weight: bold; }}
QLabel[role="muted"] {{ color: {MUTED}; font-size: {FONT_PX - 2}px; }}
QLabel[role="error"] {{ color: {DANGER}; }}
QLabel[role="toast"] {{ background: {PANEL2}; border: 1px solid {ACCENT}; border-radius: 8px; padding: 8px 12px; }}
QLabel[role="note"] {{ background: rgba(7, 13, 28, 200); border-radius: 8px; padding: 6px 10px; }}
QLabel[role="offline"] {{ color: {DANGER}; }}
QLabel[role="online"] {{ color: {ACCENT}; }}

QLineEdit, QComboBox, QPlainTextEdit, QSpinBox {{
    background: {PANEL}; border: 1px solid {LINE}; border-radius: 8px; padding: 10px 12px; min-height: {TOUCH_PX - 24}px;
}}
QLineEdit:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox QAbstractItemView {{ background: {PANEL}; selection-background-color: {PANEL2}; }}

QPushButton {{
    background: {PANEL2}; border: 1px solid {LINE}; border-radius: 10px; padding: 10px 16px; min-height: {TOUCH_PX - 20}px;
}}
QPushButton:pressed {{ border-color: {ACCENT}; }}
QPushButton:disabled {{ color: {MUTED}; }}
QPushButton[role="primary"] {{ background: {ACCENT}; border-color: {ACCENT}; }}
QPushButton[role="primary"] {{ color: #04202a; font-weight: bold; }}
QPushButton[role="link"] {{ background: transparent; border: none; color: {ACCENT}; }}
QPushButton[role="shutter"] {{
    background: {TEXT}; border: 6px solid {ACCENT}; border-radius: 36px; min-width: 60px; max-width: 60px;
    min-height: 60px; max-height: 60px; padding: 0;
}}
QPushButton[role="shutter"]:pressed {{ background: {ACCENT}; }}
QPushButton[role="shutter"]:disabled {{ background: {MUTED}; }}
QPushButton[role="chip"] {{ padding: 6px 12px; border-radius: 16px; }}
QPushButton[role="chip"]:checked {{ border-color: {ACCENT}; color: {ACCENT}; }}

QScrollBar:vertical {{ background: transparent; width: 6px; }}
QScrollBar::handle:vertical {{ background: {LINE}; border-radius: 3px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
"""
