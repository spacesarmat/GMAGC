"""Автозапуск при входе в систему: реестр на Windows (HKCU\\...\\Run), LaunchAgent на macOS.

Реестр и папка LaunchAgents принимаются параметром (по умолчанию настоящие), чтобы логика обеих
платформ проверялась тестами на любой ОС, без обращения к настоящему реестру или диску пользователя."""

from __future__ import annotations

import sys
from pathlib import Path

APP_NAME = "GMAGC"
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
LAUNCH_AGENT_LABEL = "com.spacesarmat.gmagc"


def is_supported(platform: str = sys.platform) -> bool:
    return platform in ("win32", "darwin")


class WinRegistry:
    """Значение автозапуска в HKCU\\...\\Run (настоящий реестр Windows)."""

    def get(self, name: str) -> str | None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH) as key:
                value, _ = winreg.QueryValueEx(key, name)
                return str(value)
        except FileNotFoundError:
            return None

    def set(self, name: str, value: str) -> None:
        import winreg

        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)

    def delete(self, name: str) -> None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, name)
        except FileNotFoundError:
            pass


def _set_windows(enabled: bool, exe: Path, registry: WinRegistry) -> None:
    if enabled:
        registry.set(APP_NAME, f'"{exe}"')
    else:
        registry.delete(APP_NAME)


def _plist_path(agents_dir: Path) -> Path:
    return agents_dir / f"{LAUNCH_AGENT_LABEL}.plist"


def _plist_text(exe: Path) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0"><dict>\n'
        f"<key>Label</key><string>{LAUNCH_AGENT_LABEL}</string>\n"
        f"<key>ProgramArguments</key><array><string>{exe}</string></array>\n"
        "<key>RunAtLoad</key><true/>\n"
        "</dict></plist>\n"
    )


def _set_macos(enabled: bool, exe: Path, agents_dir: Path) -> None:
    path = _plist_path(agents_dir)
    if enabled:
        agents_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(_plist_text(exe), encoding="utf-8")
    else:
        path.unlink(missing_ok=True)


def _default_agents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def set_autostart(
    enabled: bool,
    exe: Path,
    *,
    platform: str = sys.platform,
    registry: WinRegistry | None = None,
    agents_dir: Path | None = None,
) -> None:
    """Включает или выключает запуск при входе в систему. Ничего не делает на платформах без поддержки."""
    if platform == "win32":
        _set_windows(enabled, exe, registry or WinRegistry())
    elif platform == "darwin":
        _set_macos(enabled, exe, agents_dir or _default_agents_dir())


def is_autostart_enabled(
    *, platform: str = sys.platform, registry: WinRegistry | None = None, agents_dir: Path | None = None
) -> bool:
    if platform == "win32":
        return (registry or WinRegistry()).get(APP_NAME) is not None
    if platform == "darwin":
        return _plist_path(agents_dir or _default_agents_dir()).exists()
    return False
