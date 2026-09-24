"""Камера телефона: разрешение, задняя камера, приближение, фокус, снимок."""

from __future__ import annotations

import asyncio

import flet_camera as fc
import flet_permission_handler as ph

from gmagc_common.i18n import t

FOCUS_SETTLE_SECONDS = 0.8  # сколько ждать наведения, прежде чем зафиксировать фокус после касания
RETRY_SECONDS = 0.5  # пауза перед второй попыткой запуска: виджет камеры мог ещё не появиться на экране


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class CameraController:
    def __init__(
        self,
        camera,
        permission,
        settle_seconds: float = FOCUS_SETTLE_SECONDS,
        supported: bool = True,
        retry_seconds: float = RETRY_SECONDS,
    ):
        self.camera = camera
        self.retry_seconds = retry_seconds
        self.supported = supported
        self.permission = permission
        self.settle_seconds = settle_seconds
        self.ready = False
        self.error = ""
        self.min_zoom = 1.0
        self.max_zoom = 1.0
        self.zoom = 1.0
        self.focus_locked = False
        self._scanning = False

    async def start(self) -> bool:
        """Просит разрешение и включает заднюю камеру; причину неудачи кладёт в error.

        Каждый запуск создаёт новый контроллер камеры (приближение и фокус сбрасываются). При сбое плагина
        делается вторая попытка: после возврата на экран виджет камеры мог ещё не успеть появиться.
        """
        if not self.supported:
            self.error = unsupported_text()
            return False
        self.ready = False
        for attempt in (1, 2):
            try:
                if await self.permission.request(ph.Permission.CAMERA) != ph.PermissionStatus.GRANTED:
                    self.error = t("Нет доступа к камере: разрешите его в настройках телефона")
                    return False
                cameras = await self.camera.get_available_cameras()
                if not cameras:
                    self.error = t("Камера не найдена")
                    return False
                chosen = next((c for c in cameras if c.lens_direction == fc.CameraLensDirection.BACK), cameras[0])
                await self.camera.initialize(chosen, fc.ResolutionPreset.HIGH, enable_audio=False)
            except Exception as error:  # noqa: BLE001 - экран должен показать причину, а не закрыться
                self.error = t("Ошибка камеры: {error}", error=error)
                if attempt == 1:
                    await asyncio.sleep(self.retry_seconds)
                    continue
                return False
            break
        await self._read_zoom_range()
        self.focus_locked = False
        self.ready = True
        self.error = ""
        return True

    def invalidate(self) -> None:
        """Помечает камеру неготовой: Flet убирает виджет камеры со скрытым экраном вместе с её контроллером."""
        self.ready = False
        self._scanning = False  # старый плагин камеры уже выброшен вместе с виджетом, поток на нём не остановить

    async def restart(self) -> bool:
        self.invalidate()
        return await self.start()

    async def _read_zoom_range(self) -> None:
        try:
            self.min_zoom = float(await self.camera.get_min_zoom_level())
            self.max_zoom = float(await self.camera.get_max_zoom_level())
        except Exception:  # noqa: BLE001 - без диапазона камера работает, но без приближения
            self.min_zoom = self.max_zoom = 1.0
        self.zoom = _clamp(1.0, self.min_zoom, self.max_zoom) if self.max_zoom > self.min_zoom else self.min_zoom

    async def set_zoom(self, value: float) -> float:
        """Устанавливает приближение в пределах диапазона камеры; возвращает фактическое значение."""
        if self.max_zoom <= self.min_zoom:
            return self.zoom
        target = _clamp(value, self.min_zoom, self.max_zoom)
        try:
            await self.camera.set_zoom_level(target)
        except Exception as error:  # noqa: BLE001
            self.error = t("Приближение недоступно: {error}", error=error)
            return self.zoom
        self.zoom = target
        return target

    async def zoom_by(self, delta: float) -> float:
        return await self.set_zoom(self.zoom + delta)

    async def focus_at(self, x: float, y: float, width: float, height: float) -> bool:
        """Наводит фокус и замер экспозиции в точку касания (x, y) на превью размера width×height."""
        if not self.ready or width <= 0 or height <= 0:
            return False
        point = (_clamp(x / width, 0.0, 1.0), _clamp(y / height, 0.0, 1.0))
        try:
            if self.focus_locked:
                await self.camera.set_focus_mode(fc.FocusMode.AUTO)
            await self.camera.set_focus_point(point)
            await self.camera.set_exposure_point(point)
            if self.focus_locked:
                await asyncio.sleep(self.settle_seconds)
                await self.camera.set_focus_mode(fc.FocusMode.LOCKED)
        except Exception as error:  # noqa: BLE001 - не все камеры умеют наводить по точке
            self.error = t("Фокус по точке недоступен: {error}", error=error)
            return False
        return True

    async def toggle_focus_lock(self) -> bool:
        """Переключает автофокус и фиксацию фокуса; возвращает True, если фокус теперь зафиксирован."""
        target = not self.focus_locked
        try:
            await self.camera.set_focus_mode(fc.FocusMode.LOCKED if target else fc.FocusMode.AUTO)
        except Exception as error:  # noqa: BLE001
            self.error = t("Фокус недоступен: {error}", error=error)
            return self.focus_locked
        self.focus_locked = target
        return target

    async def start_scanning(self, on_frame) -> bool:
        """Запускает поток кадров камеры для автосканирования QR; on_frame(event) вызывается на каждый кадр
        (event: width, height, encoded_format, bytes — как flet_camera.CameraImageEvent).

        False — поток недоступен на этом телефоне или камера не готова: вызывающий откатывается на снимок по кнопке.
        """
        if not self.ready:
            return False
        try:
            if not await self.camera.supports_image_streaming():
                return False
            self.camera.on_stream_image = on_frame
            await self.camera.start_image_stream()
        except Exception as error:  # noqa: BLE001 - экран остаётся рабочим, просто без автосканирования
            self.camera.on_stream_image = None
            self.error = t("Поток камеры недоступен: {error}", error=error)
            return False
        self._scanning = True
        return True

    async def stop_scanning(self) -> None:
        if not self._scanning:
            return
        self._scanning = False
        self.camera.on_stream_image = None
        try:
            await self.camera.stop_image_stream()
        except Exception:  # noqa: BLE001 - остановка не должна ронять экран
            pass

    async def take_picture(self) -> bytes:
        if not self.ready:
            raise RuntimeError(self.error or t("камера не готова"))
        return await self.camera.take_picture()

    async def pause(self) -> None:
        if self.ready:
            try:
                await self.camera.pause_preview()
            except Exception:  # noqa: BLE001 - пауза превью лишь экономит батарею
                pass

    async def resume(self) -> None:
        if self.ready:
            try:
                await self.camera.resume_preview()
            except Exception:  # noqa: BLE001
                pass


def unsupported_text() -> str:
    return t("Камера доступна только на телефоне (Android): здесь можно выбрать фото из галереи")
