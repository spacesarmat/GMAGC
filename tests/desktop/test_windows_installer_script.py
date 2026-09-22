"""Проверки .iss-скрипта установщика Windows (Inno Setup).

Настоящую сборку установщика (ISCC.exe) в тестах не запускаем — это внешний инструмент, доступный
только на Windows-раннере CI. Здесь только текстовые проверки настроек, которые легко сломать
случайно и которые не бросятся в глаза при чтении диффа."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ISS = ROOT / "packaging" / "windows" / "gmagc.iss"
ICO = ROOT / "packaging" / "windows" / "gmagc.ico"


def text() -> str:
    return ISS.read_text(encoding="utf-8")


def test_the_installer_requires_no_administrator_rights():
    # Автообновление подменяет файлы там же, где программа лежит, и прав администратора взять неоткуда —
    # установка обязана быть per-user, иначе автообновление после установки через .exe перестанет работать.
    assert "PrivilegesRequired=lowest" in text()


def test_the_installer_targets_the_per_user_programs_folder():
    assert r"DefaultDirName={localappdata}\Programs\GMAGC" in text()


def test_the_app_id_is_a_stable_guid():
    # AppId нельзя менять между версиями: иначе установщик не увидит прежнюю установку (второй значок
    # в «Пуск», путаница с обновлением) — тот же класс проблем, что и дубликат в Launchpad на macOS.
    match = re.search(r"AppId=\{\{([0-9A-Fa-f-]{36})\}", text())
    assert match, "AppId должен быть постоянным GUID"


def test_version_and_source_dir_are_configurable_from_the_command_line():
    body = text()
    assert '#ifndef AppVersion' in body and '#ifndef SourceDir' in body
    assert "OutputBaseFilename=GMAGC-Setup-{#AppVersion}" in body


def test_the_icon_file_exists_and_looks_like_a_real_ico():
    assert ICO.is_file() and ICO.stat().st_size > 0
    assert ICO.read_bytes()[:4] == b"\x00\x00\x01\x00"  # сигнатура формата .ico
