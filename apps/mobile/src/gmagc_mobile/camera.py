"""Камера телефона: разрешение, задняя камера, приближение, фокус, снимок."""

from __future__ import annotations

import asyncio

import flet_camera as fc
import flet_permission_handler as ph

FOCUS_SETTLE_SECONDS = 0.8  # сколько ждать наведения, прежде чем зафиксировать фокус после касания


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class CameraController:
    def __init__(self, camera, permission, settle_seconds: float = FOCUS_SETTLE_SECONDS):
        self.camera = camera
        self.permission = permission
        self.settle_seconds = settle_seconds
        self.ready = False
        self.error = ""
        self.min_zoom = 1.0
        self.max_zoom = 1.0
        self.zoom = 1.0
        self.focus_locked = False

    async def start(self) -> bool:
        """Просит разрешение и включает заднюю камеру; причину неудачи кладёт в error."""
        try:
            if await self.permission.request(ph.Permission.CAMERA) != ph.PermissionStatus.GRANTED:
                self.error = "Нет доступа к камере: разрешите его в настройках телефона"
                return False
            cameras = await self.camera.get_available_cameras()
            if not cameras:
                self.error = "Камера не найдена"
                return False
            chosen = next((c for c in cameras if c.lens_direction == fc.CameraLensDirection.BACK), cameras[0])
            await self.camera.initialize(chosen, fc.ResolutionPreset.HIGH, enable_audio=False)
        except Exception as error:  # noqa: BLE001 - экран должен показать причину, а не закрыться
            self.error = f"Ошибка камеры: {error}"
            return False
        await self._read_zoom_range()
        self.ready = True
        self.error = ""
        return True

    async def _read_zoom_range(self) -> None:
        try:
            self.min_zoom = float(await self.camera.get_min_zoom_level())
            self.max_zoom = float(await self.camera.get_max_zoom_level())
        except Exception:  # noqa: BLE001 - без диапазона камера работает, но без приближения
            self.min_zoom = self.max_zoom = 1.0
        self.zoom = self.min_zoom

    async def set_zoom(self, value: float) -> float:
        """Устанавливает приближение в пределах диапазона камеры; возвращает фактическое значение."""
        if self.max_zoom <= self.min_zoom:
            return self.zoom
        target = _clamp(value, self.min_zoom, self.max_zoom)
        try:
            await self.camera.set_zoom_level(target)
        except Exception as error:  # noqa: BLE001
            self.error = f"Приближение недоступно: {error}"
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
            self.error = f"Фокус по точке недоступен: {error}"
            return False
        return True

    async def toggle_focus_lock(self) -> bool:
        """Переключает автофокус и фиксацию фокуса; возвращает True, если фокус теперь зафиксирован."""
        target = not self.focus_locked
        try:
            await self.camera.set_focus_mode(fc.FocusMode.LOCKED if target else fc.FocusMode.AUTO)
        except Exception as error:  # noqa: BLE001
            self.error = f"Фокус недоступен: {error}"
            return self.focus_locked
        self.focus_locked = target
        return target

    async def take_picture(self) -> bytes:
        if not self.ready:
            raise RuntimeError(self.error or "камера не готова")
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
