"""Камера телефона: единый интерфейс для настоящей камеры (QtMultimedia) и подделки для тестов.

Кадры предпросмотра приходят сигналом `frame` (QImage) — экран рисует их сам и берёт для чтения QR; снимок приходит
сигналом `photo` уже как JPEG. Разрешение на камеру запрашивается через систему Qt (на Android — диалог телефона)."""

from __future__ import annotations

from PySide6.QtCore import QBuffer, QByteArray, QCoreApplication, QIODevice, QObject, QPointF, Qt, Signal
from PySide6.QtGui import QImage

from gmagc_common.i18n import t

JPEG_QUALITY = 92


def _jpeg(image: QImage) -> bytes:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "JPEG", JPEG_QUALITY)
    return bytes(buffer.data())


class CameraBackend(QObject):
    frame = Signal(QImage)
    photo = Signal(bytes)
    error = Signal(str)
    ready_changed = Signal(bool)

    ready = False
    min_zoom = 1.0
    max_zoom = 1.0
    zoom = 1.0

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def capture(self) -> None: ...

    def set_zoom(self, zoom: float) -> None: ...

    def focus_at(self, x: float, y: float) -> bool:
        """Фокус по точке (координаты 0..1 от кадра); False — камера так не умеет."""
        return False


class FakeCamera(CameraBackend):
    """Камера для тестов: кадры и снимки подаются вручную."""

    def __init__(self, max_zoom: float = 4.0, fail: str = ""):
        super().__init__()
        self.max_zoom = max_zoom
        self.fail = fail
        self.started = 0
        self.stopped = 0
        self.captures = 0
        self.focus_points: list[tuple[float, float]] = []
        self.next_photo = b"jpeg"

    def start(self) -> None:
        self.started += 1
        if self.fail:
            self.error.emit(self.fail)
            return
        self.ready = True
        self.ready_changed.emit(True)

    def stop(self) -> None:
        self.stopped += 1
        self.ready = False

    def capture(self) -> None:
        self.captures += 1
        self.photo.emit(self.next_photo)

    def set_zoom(self, zoom: float) -> None:
        self.zoom = max(self.min_zoom, min(self.max_zoom, zoom))

    def focus_at(self, x: float, y: float) -> bool:
        self.focus_points.append((x, y))
        return True


class QtCamera(CameraBackend):
    """Задняя камера через QtMultimedia. Модули импортируются при создании: на ПК без камеры класс просто не нужен."""

    def __init__(self):
        super().__init__()
        from PySide6.QtMultimedia import QCamera, QImageCapture, QMediaCaptureSession, QMediaDevices, QVideoSink

        self._devices = QMediaDevices
        self._camera_cls = QCamera
        self._camera: QCamera | None = None
        self._session = QMediaCaptureSession(self)
        self._sink = QVideoSink(self)
        self._sink.videoFrameChanged.connect(self._on_frame)
        self._capture = QImageCapture(self)
        self._capture.imageCaptured.connect(self._on_captured)
        self._capture.errorOccurred.connect(self._on_capture_error)
        self._session.setVideoSink(self._sink)
        self._session.setImageCapture(self._capture)

    def start(self) -> None:
        from PySide6.QtCore import QCameraPermission

        app = QCoreApplication.instance()
        permission = QCameraPermission()
        status = app.checkPermission(permission)
        if status == Qt.PermissionStatus.Granted:
            self._open()
        elif status == Qt.PermissionStatus.Undetermined:
            app.requestPermission(permission, self, self._permission_answered)
        else:
            self.error.emit(t("Нет доступа к камере: разрешите его в настройках телефона"))

    def _permission_answered(self, permission) -> None:
        if QCoreApplication.instance().checkPermission(permission) == Qt.PermissionStatus.Granted:
            self._open()
        else:
            self.error.emit(t("Нет доступа к камере: разрешите его в настройках телефона"))

    def _open(self) -> None:
        if self._camera is not None:
            return
        devices = self._devices.videoInputs()
        if not devices:
            self.error.emit(t("Камера не найдена"))
            return
        back = [d for d in devices if d.position() == d.Position.BackFace]
        self._camera = self._camera_cls(back[0] if back else self._devices.defaultVideoInput())
        self._camera.errorOccurred.connect(lambda _err, text: self.error.emit(t("Ошибка камеры: {error}", error=text)))
        self._session.setCamera(self._camera)
        self.min_zoom = max(1.0, float(self._camera.minimumZoomFactor()))
        self.max_zoom = max(self.min_zoom, float(self._camera.maximumZoomFactor()))
        self._camera.start()
        self.ready = True
        self.ready_changed.emit(True)

    def stop(self) -> None:
        if self._camera is not None:
            self._camera.stop()
            self._session.setCamera(None)
            self._camera.deleteLater()
            self._camera = None
        self.ready = False
        self.zoom = 1.0

    def _on_frame(self, video_frame) -> None:
        image = video_frame.toImage()
        if not image.isNull():
            self.frame.emit(image)

    def capture(self) -> None:
        if self._camera is None:
            self.error.emit(t("Камера недоступна"))
            return
        self._capture.capture()

    def _on_captured(self, _request_id: int, image: QImage) -> None:
        self.photo.emit(_jpeg(image))

    def _on_capture_error(self, _request_id: int, _error, text: str) -> None:
        self.error.emit(t("Не удалось снять: {error}", error=text))

    def set_zoom(self, zoom: float) -> None:
        self.zoom = max(self.min_zoom, min(self.max_zoom, zoom))
        if self._camera is not None:
            self._camera.setZoomFactor(self.zoom)

    def focus_at(self, x: float, y: float) -> bool:
        camera = self._camera
        if camera is None or not camera.isFocusPointSupported():
            return False
        camera.setFocusPoint(QPointF(x, y))
        return True


def qt_camera_available() -> bool:
    """Есть ли у Qt мультимедиа (на ПК без модуля или без камер интерфейс просто предложит выбрать фото)."""
    try:
        from PySide6.QtMultimedia import QMediaDevices
    except ImportError:
        return False
    return bool(QMediaDevices.videoInputs())


def as_bytearray(data: bytes) -> QByteArray:
    return QByteArray(data)
