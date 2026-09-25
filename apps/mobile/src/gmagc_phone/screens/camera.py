"""Экран камеры: предпросмотр, съёмка, выбор фото из галереи, чтение QR подключения, приближение и фокус."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QFileDialog, QFrame, QHBoxLayout, QVBoxLayout, QWidget

from gmagc_common.i18n import t
from gmagc_common.phone_texts import zoom_text
from gmagc_common.protocol import parse_link
from gmagc_common.qr_decode import decode_qr
from gmagc_phone.camera import CameraBackend
from gmagc_phone.controller import MODE_SCAN, PhoneController, scan_hint
from gmagc_phone.files import read_file
from gmagc_phone.imaging import grayscale_frame, prepare_upload
from gmagc_phone.tasks import Executor, InlineExecutor
from gmagc_phone.widgets import Preview, button, label

QR_INTERVAL_MS = 350
ZOOM_STOPS = (1.0, 2.0, 4.0)


def pick_image_file() -> str:
    path, _ = QFileDialog.getOpenFileName(None, t("Выбрать фото"), "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
    return path


class CameraScreen(QWidget):
    qr_text = Signal(str)  # результат чтения QR из фонового потока

    def __init__(
        self,
        controller: PhoneController,
        backend: CameraBackend,
        executor: Executor | None = None,
        pick_file: Callable[[], str] = pick_image_file,
        read_bytes: Callable[[str], bytes] = read_file,
    ):
        super().__init__()
        self.controller = controller
        self.backend = backend
        self.executor = executor or InlineExecutor()
        self.pick_file = pick_file
        self.read_bytes = read_bytes
        self._frame: QImage | None = None
        self._decoding = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.preview = Preview()
        layout.addWidget(self.preview, 1)
        self.note = label("", "note")
        self.note.hide()
        layout.addWidget(self.note)

        controls = QFrame()
        controls.setProperty("role", "bar")
        col = QVBoxLayout(controls)
        top = QHBoxLayout()
        self.zoom_button = button(zoom_text(1.0), "chip", self._cycle_zoom)
        self.connectivity = label("", "online", wrap=False)
        top.addWidget(self.zoom_button)
        top.addWidget(self.connectivity, 1)
        col.addLayout(top)
        self.shutter = button("", "shutter", self._shoot)
        self.shutter.setAccessibleName(t("Снять"))
        shutter_row = QHBoxLayout()
        shutter_row.addStretch(1)
        shutter_row.addWidget(self.shutter)
        shutter_row.addStretch(1)
        col.addLayout(shutter_row)
        row = QHBoxLayout()
        self.pick = button(t("Выбрать фото"), "", self._pick)
        self.qr = button(t("Считать QR"), "", lambda: controller.set_mode(MODE_SCAN, scan_hint()))
        row.addWidget(self.pick)
        row.addWidget(self.qr)
        col.addLayout(row)
        row2 = QHBoxLayout()
        self.retry = button(t("Повторить"), "primary", controller.retry)
        self.retry.hide()
        row2.addWidget(self.retry)
        self.manual = button(t("Ввести вручную"), "link", lambda: controller.show("connect"))
        self.change_pc = button(t("Сменить ПК"), "link", controller.change_pc)
        row2.addWidget(self.manual)
        row2.addWidget(self.change_pc)
        col.addLayout(row2)
        row3 = QHBoxLayout()
        for text, view in ((t("Галерея"), "gallery"), (t("Профили приборов"), "profiles"), (t("Настройки"), "settings")):
            row3.addWidget(button(text, "link", lambda v=view: controller.open_overlay(v)))
        col.addLayout(row3)
        layout.addWidget(controls)

        backend.frame.connect(self._on_frame)
        backend.photo.connect(self._on_photo)
        backend.error.connect(controller.note)
        controller.camera_note.connect(self._set_note)
        controller.mode_changed.connect(self._mode_changed)
        controller.retry_changed.connect(self.retry.setVisible)
        controller.connectivity_changed.connect(self._connectivity)
        controller.busy_changed.connect(self._busy)
        self.preview.tapped.connect(self._focus)
        self.qr_text.connect(self._qr_read)
        self._timer = QTimer(self)
        self._timer.setInterval(QR_INTERVAL_MS)
        self._timer.timeout.connect(self._scan_tick)
        self._mode_changed(controller.mode)

    # ---- жизненный цикл --------------------------------------------------------------
    def activate(self) -> None:
        self.backend.start()
        self._timer.start()

    def deactivate(self) -> None:
        self._timer.stop()
        self.backend.stop()
        self._frame = None
        self.preview.set_image(None)

    # ---- состояние --------------------------------------------------------------------
    def _set_note(self, text: str) -> None:
        self.note.setText(text)
        self.note.setVisible(bool(text))

    def _mode_changed(self, mode: str) -> None:
        scanning = mode == MODE_SCAN
        self.preview.frame_visible = scanning
        self.preview.update()
        self.shutter.setVisible(not scanning)
        self.pick.setVisible(not scanning)
        self.qr.setVisible(not scanning)

    def _connectivity(self, online: bool) -> None:
        if self.controller.connection is None:
            text, role = "", "online"
        elif online:
            text, role = t("Готово к съёмке"), "online"
        else:
            text, role = t("Нет связи с ПК"), "offline"
        self.connectivity.setText(text)
        self.connectivity.setProperty("role", role)
        self.connectivity.style().unpolish(self.connectivity)
        self.connectivity.style().polish(self.connectivity)

    def _busy(self, busy: bool) -> None:
        self.shutter.setEnabled(not busy)
        self.pick.setEnabled(not busy)

    # ---- кадры и QR -----------------------------------------------------------------------
    def _on_frame(self, image: QImage) -> None:
        self._frame = image
        self.preview.set_image(image)

    def _scan_tick(self) -> None:
        if self.controller.mode != MODE_SCAN or self._frame is None or self._decoding:
            return
        gray, width, height = grayscale_frame(self._frame)
        self._decoding = True

        def work() -> None:
            try:
                text = decode_qr(gray, width, height)
            except Exception:  # noqa: BLE001 - сбой чтения кадра не должен останавливать сканирование
                text = None
            self._decoding = False
            self.qr_text.emit(text or "")

        self.executor.submit(work)

    def _qr_read(self, text: str) -> None:
        if not text or self.controller.mode != MODE_SCAN or self.controller.busy:
            return
        connection = parse_link(text)
        if connection is None:
            self.controller.note(t("QR-код не от GMAGC: наведите камеру на код в приложении на ПК."))
            return
        self.controller.connect_to(connection, announce=True)

    # ---- съёмка ------------------------------------------------------------------------------
    def _shoot(self) -> None:
        if not self.controller.busy:
            self.backend.capture()

    def _on_photo(self, data: bytes) -> None:
        self._send(data)

    def _pick(self) -> None:
        if self.controller.busy:
            return
        path = self.pick_file()
        if not path:
            return
        try:
            data = self.read_bytes(path)
        except OSError as error:
            self.controller.note(t("Не удалось прочитать файл: {error}", error=error))
            return
        self._send(data)

    def _send(self, data: bytes) -> None:
        try:
            data = prepare_upload(data)
        except ValueError as error:
            self.controller.note(t("Не удалось подготовить фото: {error}", error=error))
            return
        self.controller.search(data)

    # ---- приближение и фокус -----------------------------------------------------------------------
    def _cycle_zoom(self) -> None:
        stops = [s for s in ZOOM_STOPS if s <= self.backend.max_zoom] or [1.0]
        following = [s for s in stops if s > self.backend.zoom + 0.01]
        self.backend.set_zoom(following[0] if following else stops[0])
        self.zoom_button.setText(zoom_text(self.backend.zoom))

    def _focus(self, x: float, y: float) -> None:
        if not self.backend.focus_at(x, y):
            self._set_note(t("Фокус по точке недоступен"))

