from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from gmagc_desktop.service.autostart import (
    APP_NAME,
    LAUNCH_AGENT_LABEL,
    is_autostart_enabled,
    is_supported,
    set_autostart,
)


class FakeRegistry:
    """Замена WinRegistry: словарь вместо настоящего реестра — проверяется на любой ОС."""

    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, name):
        return self.values.get(name)

    def set(self, name, value):
        self.values[name] = value

    def delete(self, name):
        self.values.pop(name, None)


def test_supported_platforms():
    assert is_supported("win32") is True and is_supported("darwin") is True
    assert is_supported("linux") is False


# ---- Windows ------------------------------------------------------------------------------------
def test_enabling_on_windows_writes_the_quoted_exe_path_to_the_registry():
    # PureWindowsPath, а не Path: путь Windows форматируется с обратной косой чертой независимо от того,
    # на какой ОС реально выполняется тест (на Linux/macOS обычный Path сохранил бы прямые слэши)
    registry = FakeRegistry()

    set_autostart(True, PureWindowsPath("C:/Apps/GMAGC/gmagc-desktop.exe"), platform="win32", registry=registry)

    assert registry.values[APP_NAME] == '"C:\\Apps\\GMAGC\\gmagc-desktop.exe"'
    assert is_autostart_enabled(platform="win32", registry=registry) is True


def test_disabling_on_windows_removes_the_registry_value():
    registry = FakeRegistry({APP_NAME: '"C:\\old\\path.exe"'})

    set_autostart(False, Path("unused"), platform="win32", registry=registry)

    assert APP_NAME not in registry.values
    assert is_autostart_enabled(platform="win32", registry=registry) is False


def test_disabling_on_windows_when_nothing_was_set_does_not_raise():
    set_autostart(False, Path("unused"), platform="win32", registry=FakeRegistry())


def test_windows_is_disabled_by_default():
    assert is_autostart_enabled(platform="win32", registry=FakeRegistry()) is False


# ---- macOS --------------------------------------------------------------------------------------
def test_enabling_on_macos_writes_a_launch_agent_plist(tmp_path):
    exe = PurePosixPath("/Applications/GMAGC.app/Contents/MacOS/gmagc-desktop")

    set_autostart(True, exe, platform="darwin", agents_dir=tmp_path)

    plist = tmp_path / f"{LAUNCH_AGENT_LABEL}.plist"
    assert plist.exists()
    text = plist.read_text(encoding="utf-8")
    assert LAUNCH_AGENT_LABEL in text and str(exe) in text and "RunAtLoad" in text
    assert is_autostart_enabled(platform="darwin", agents_dir=tmp_path) is True


def test_disabling_on_macos_removes_the_plist(tmp_path):
    exe = PurePosixPath("/Applications/GMAGC.app/Contents/MacOS/gmagc-desktop")
    set_autostart(True, exe, platform="darwin", agents_dir=tmp_path)

    set_autostart(False, Path("unused"), platform="darwin", agents_dir=tmp_path)

    assert not (tmp_path / f"{LAUNCH_AGENT_LABEL}.plist").exists()
    assert is_autostart_enabled(platform="darwin", agents_dir=tmp_path) is False


def test_disabling_on_macos_when_nothing_was_set_does_not_raise(tmp_path):
    set_autostart(False, Path("unused"), platform="darwin", agents_dir=tmp_path)


def test_enabling_on_macos_creates_the_launch_agents_folder_if_missing(tmp_path):
    agents_dir = tmp_path / "Library" / "LaunchAgents"
    exe = PurePosixPath("/Applications/GMAGC.app/Contents/MacOS/gmagc-desktop")

    set_autostart(True, exe, platform="darwin", agents_dir=agents_dir)

    assert agents_dir.is_dir() and (agents_dir / f"{LAUNCH_AGENT_LABEL}.plist").exists()


# ---- прочие платформы -----------------------------------------------------------------------------
@pytest.mark.parametrize("platform", ["linux", "web"])
def test_unsupported_platforms_do_nothing_and_report_disabled(platform):
    set_autostart(True, Path("unused"), platform=platform)  # не должно падать

    assert is_autostart_enabled(platform=platform) is False
