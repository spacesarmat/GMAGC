"""Выбор файлов и «Поделиться»: системный диалог Qt и намерение Android (с запасным вариантом — буфер обмена)."""

from __future__ import annotations

import sys

from PySide6.QtCore import QFile, QIODevice
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFileDialog

from gmagc_common.i18n import t
from gmagc_phone.imaging import prepare_upload


def read_file(path: str) -> bytes:
    file = QFile(path)  # QFile понимает и обычные пути, и content:// на Android
    if not file.open(QIODevice.OpenModeFlag.ReadOnly):
        raise OSError(file.errorString())
    try:
        return bytes(file.readAll())
    finally:
        file.close()


def pick_bytes(title: str, name_filter: str) -> bytes | None:
    """Содержимое выбранного файла; None — диалог закрыт или файл не удалось прочитать."""
    path, _ = QFileDialog.getOpenFileName(None, title, "", name_filter)
    if not path:
        return None
    try:
        return read_file(path)
    except OSError:
        return None


def pick_scan_file() -> bytes | None:
    return pick_bytes(t("Инструкция прибора (фото или PDF)"), "Instruction (*.jpg *.jpeg *.png *.pdf)")


def pick_photo() -> bytes | None:
    data = pick_bytes(t("Фото проекции"), "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
    if data is None:
        return None
    try:
        return prepare_upload(data)
    except ValueError:
        return None


def pick_json() -> bytes | None:
    return pick_bytes(t("Профиль прибора"), "Profile (*.json)")


def share_files(files: list[tuple[str, str | bytes, str]], subject: str) -> None:
    """Текстовые файлы (JSON, XML) уходят системным «Поделиться» как текст; двоичные на телефоне не поддерживаются.

    Вне Android (отладка на ПК) текст кладётся в буфер обмена. Ошибки пробрасываются: редактор покажет их."""
    texts = []
    for name, data, _mime in files:
        if isinstance(data, bytes):
            raise ValueError(t("двоичные файлы недоступны: отправьте профиль на ПК"))
        texts.append(f"# {name}\n{data}" if len(files) > 1 else data)
    text = "\n\n".join(texts)
    if sys.platform == "android":
        _android_send_text(subject, text)
    else:
        QGuiApplication.clipboard().setText(text)


def _android_send_text(subject: str, text: str) -> None:
    from PySide6.QtCore import QJniObject, QNativeInterface

    intent = QJniObject("android/content/Intent", "(Ljava/lang/String;)V", "android.intent.action.SEND")
    intent.callObjectMethod(
        "setType", "(Ljava/lang/String;)Landroid/content/Intent;", QJniObject.fromString("text/plain").object()
    )
    for key, value in (("android.intent.extra.SUBJECT", subject), ("android.intent.extra.TEXT", text)):
        intent.callObjectMethod(
            "putExtra",
            "(Ljava/lang/String;Ljava/lang/String;)Landroid/content/Intent;",
            QJniObject.fromString(key).object(),
            QJniObject.fromString(value).object(),
        )
    chooser = QJniObject.callStaticObjectMethod(
        "android/content/Intent",
        "createChooser",
        "(Landroid/content/Intent;Ljava/lang/CharSequence;)Landroid/content/Intent;",
        intent.object(),
        QJniObject.fromString(subject).object(),
    )
    context = QNativeInterface.QAndroidApplication.context()
    context.callMethod("startActivity", "(Landroid/content/Intent;)V", chooser.object())
