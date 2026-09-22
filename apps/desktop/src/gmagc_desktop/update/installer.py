"""Загрузка, проверка и установка обновления ПК-приложения (без Flet)."""

from __future__ import annotations

import ctypes
import hashlib
import http.client
import os
import shlex
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path

from gmagc_common.updates import Asset, UpdateCheckError, open_url, parse_sha256

MAX_DOWNLOAD_BYTES = 400 * 1024 * 1024
MAX_UNPACKED_BYTES = 1024 * 1024 * 1024
CHUNK_BYTES = 256 * 1024
WINDOWS_EXE = "gmagc-desktop.exe"


class InstallError(Exception):
    """Обновление не установлено; текст можно показывать пользователю."""


class InstallCancelled(Exception):
    """Пользователь отменил загрузку."""


def platform_key() -> str | None:
    return {"win32": "windows", "darwin": "macos"}.get(sys.platform)


def current_executable() -> Path | None:
    """Путь к исполняемому файлу процесса (у собранного приложения это gmagc-desktop)."""
    try:
        if sys.platform == "win32":
            buffer = ctypes.create_unicode_buffer(32768)
            length = ctypes.windll.kernel32.GetModuleFileNameW(None, buffer, len(buffer))
            return Path(buffer.value) if length else None
        if sys.platform == "darwin":
            size = ctypes.c_uint32(4096)
            buffer = ctypes.create_string_buffer(4096)
            if ctypes.CDLL(None)._NSGetExecutablePath(buffer, ctypes.byref(size)) == 0:
                return Path(os.fsdecode(buffer.value)).resolve()
    except (OSError, AttributeError):
        return None
    return None


def install_target(executable: Path | None, platform: str | None) -> Path | None:
    """Что заменять: папка приложения (Windows) или пакет .app (macOS); None, если запуск не из сборки."""
    if executable is None:
        return None
    if platform == "windows":
        return executable.parent if executable.name.lower() == WINDOWS_EXE else None
    if platform == "macos":
        for parent in executable.parents:
            if parent.suffix == ".app":
                return parent
    return None


def is_writable(path: Path) -> bool:
    """Можно ли создать файл в папке (проверка реальным созданием: права Windows не видны через os.access)."""
    try:
        with tempfile.TemporaryFile(dir=path):
            return True
    except OSError:
        return False


def backup_dir(target: Path) -> Path:
    """Папка/пакет рядом с приложением для резервной копии перед обновлением.

    На macOS резерв не должен сам оканчиваться на .app: иначе Launchpad и Spotlight показывают его как отдельное
    приложение. Убираем расширение и прячем точкой в начале имени (скрытый файл, как и на Windows он не мешает)."""
    if target.suffix == ".app":
        return target.with_name(f".{target.stem}.previous")
    return target.with_name(target.name + ".previous")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expected_checksum(asset: Asset | None, allow_local: bool, timeout: float) -> str:
    if asset is None:
        raise InstallError("В релизе нет контрольной суммы: обновление не установлено, скачайте его вручную")
    try:
        with open_url(asset.url, allow_local=allow_local, timeout=timeout) as response:
            text = response.read(4096).decode("utf-8", "replace")
    except UpdateCheckError as error:
        raise InstallError(str(error)) from error
    except (OSError, http.client.HTTPException) as error:
        raise InstallError(f"Не удалось получить контрольную сумму: {error}") from error
    checksum = parse_sha256(text)
    if checksum is None:
        raise InstallError("Контрольная сумма в релизе повреждена: обновление не установлено")
    return checksum


def download(
    asset: Asset,
    checksum_asset: Asset | None,
    dest_dir: Path,
    *,
    progress: Callable[[int, int], None] | None = None,
    cancel: Callable[[], bool] | None = None,
    allow_local: bool = False,
    timeout: float = 30.0,
) -> Path:
    """Скачивает файл релиза, сверяет SHA-256 с файлом .sha256 и возвращает путь; при любом сбое ничего не остаётся."""
    expected = _expected_checksum(checksum_asset, allow_local, timeout)
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / asset.name
    part = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    done = 0
    total = 0
    try:
        with open_url(asset.url, allow_local=allow_local, timeout=timeout) as response, part.open("wb") as out:
            total = int(response.headers.get("Content-Length") or asset.size or 0)
            if total > MAX_DOWNLOAD_BYTES:
                raise InstallError("Файл обновления слишком большой")
            while True:
                if cancel is not None and cancel():
                    raise InstallCancelled()
                chunk = response.read(CHUNK_BYTES)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if done > MAX_DOWNLOAD_BYTES:
                    raise InstallError("Файл обновления слишком большой")
                if progress is not None:
                    progress(done, total)
        if total and done != total:
            raise InstallError("Загрузка оборвалась: файл получен не полностью")
        if digest.hexdigest() != expected:
            raise InstallError("Контрольная сумма не совпала: файл повреждён, обновление не установлено")
        part.replace(target)
        return target
    except UpdateCheckError as error:
        raise InstallError(str(error)) from error
    except (OSError, http.client.HTTPException) as error:
        raise InstallError(f"Не удалось скачать обновление: {error}") from error
    finally:
        part.unlink(missing_ok=True)


def _ditto(zip_path: Path, dest: Path) -> None:
    """macOS: распаковка с сохранением прав и ссылок (zipfile теряет бит исполнения)."""
    try:
        subprocess.run(["ditto", "-x", "-k", str(zip_path), str(dest)], check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as error:
        raise InstallError(f"Не удалось распаковать обновление: {error}") from error


def _is_unsafe_name(name: str) -> bool:
    """Путь из архива, опасный на любой ОС: абсолютный, с диском, с «..» или с обратной косой чертой."""
    if "\\" in name or name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        return True
    return ".." in name.split("/")


def stage(zip_path: Path, staging_dir: Path, platform: str) -> Path:
    """Распаковывает архив во временную папку (без выхода за её пределы) и возвращает распакованное приложение."""
    root = staging_dir.resolve()
    try:
        archive = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError) as error:
        raise InstallError("Файл обновления повреждён: это не архив") from error
    with archive:
        infos = archive.infolist()
        if sum(info.file_size for info in infos) > MAX_UNPACKED_BYTES:
            raise InstallError("Архив обновления слишком велик после распаковки")
        for info in infos:
            destination = (root / info.filename).resolve()
            if _is_unsafe_name(info.filename) or (destination != root and root not in destination.parents):
                raise InstallError("Архив обновления содержит небезопасный путь: установка отменена")
        root.mkdir(parents=True, exist_ok=True)
        if platform == "macos":
            _ditto(zip_path, root)
        else:
            archive.extractall(root)
    if platform == "windows":
        if not (root / WINDOWS_EXE).is_file():
            raise InstallError("В архиве нет приложения GMAGC")
        return root
    apps = [item for item in root.iterdir() if item.suffix == ".app"]
    if len(apps) != 1:
        raise InstallError("В архиве нет приложения GMAGC")
    return apps[0]


def windows_script(*, pid: int, staged: str, target: str, backup: str, exe: str, log: str) -> str:
    """Пакетный файл: ждёт выхода приложения, переименовывает прежнюю версию в резерв и новую версию — на её
    место. Переименование папки на одном диске — мгновенная операция (в отличие от покопирования файл за
    файлом через robocopy, которую легко прервать на середине, оставив папку в смешанном состоянии), при
    сбое возвращает резерв."""

    def value(text: str) -> str:
        return text.replace("%", "%%")  # процент в пути иначе разворачивается cmd

    lines = [
        "@echo off",
        "chcp 65001 >nul",
        f'set "PID={int(pid)}"',
        f'set "SRC={value(staged)}"',
        f'set "DST={value(target)}"',
        f'set "BAK={value(backup)}"',
        f'set "EXE={value(exe)}"',
        f'set "LOG={value(log)}"',
        'echo waiting for the application to exit > "%LOG%"',
        ":wait",
        'tasklist /FI "PID eq %PID%" /NH 2>nul | findstr /C:" %PID% " >nul',
        "if not errorlevel 1 (",
        "  ping -n 2 127.0.0.1 >nul",
        "  goto wait",
        ")",
        'if exist "%BAK%" rmdir /s /q "%BAK%"',
        'move "%DST%" "%BAK%" >> "%LOG%" 2>&1',
        "if errorlevel 1 goto launch",
        'move "%SRC%" "%DST%" >> "%LOG%" 2>&1',
        "if errorlevel 1 goto restore",
        'echo updated >> "%LOG%"',
        "goto launch",
        ":restore",
        'echo update failed, restoring the previous version >> "%LOG%"',
        'move "%BAK%" "%DST%" >> "%LOG%" 2>&1',
        ":launch",
        'start "" "%EXE%"',
        'rmdir /s /q "%SRC%" 2>nul',
        '(goto) 2>nul & del "%~f0"',
    ]
    return "\r\n".join(lines) + "\r\n"


def macos_script(*, pid: int, staged: str, target: str, backup: str, log: str) -> str:
    quote = shlex.quote
    lines = [
        "#!/bin/sh",
        f"PID={int(pid)}",
        f"SRC={quote(staged)}",
        f"DST={quote(target)}",
        f"BAK={quote(backup)}",
        f"LOG={quote(log)}",
        'while kill -0 "$PID" 2>/dev/null; do sleep 1; done',
        'rm -rf "$BAK"',
        'if ! mv "$DST" "$BAK"; then echo "cannot move the old version" >> "$LOG"; open "$DST"; exit 1; fi',
        'if ! mv "$SRC" "$DST" >> "$LOG" 2>&1; then',
        '  echo "update failed, restoring the previous version" >> "$LOG"',
        '  rm -rf "$DST"; mv "$BAK" "$DST"',
        "fi",
        'open "$DST"',
        'rm -rf "$SRC"',
        'rm -f -- "$0"',
    ]
    return "\n".join(lines) + "\n"


def write_helper(
    platform: str, work_dir: Path, *, pid: int, staged: Path, target: Path, exe: Path, backup: Path, log: Path
) -> Path:
    work_dir.mkdir(parents=True, exist_ok=True)
    if platform == "windows":
        script = work_dir / "apply-update.cmd"
        text = windows_script(
            pid=pid, staged=str(staged), target=str(target), backup=str(backup), exe=str(exe), log=str(log)
        )
        script.write_bytes(text.encode("utf-8"))  # UTF-8 без BOM: cmd читает его после chcp 65001
        return script
    if platform == "macos":
        script = work_dir / "apply-update.sh"
        script.write_text(
            macos_script(pid=pid, staged=str(staged), target=str(target), backup=str(backup), log=str(log)),
            encoding="utf-8",
            newline="\n",
        )
        script.chmod(0o755)
        return script
    raise InstallError("Обновление из приложения на этой платформе не поддерживается")


def launch_helper(script: Path, platform: str) -> None:
    """Запускает помощника отдельным процессом без окна: он переживёт закрытие приложения."""
    quiet = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    try:
        if platform == "windows":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            subprocess.Popen(
                ["cmd.exe", "/d", "/c", "call", str(script)],
                creationflags=flags,
                close_fds=True,
                cwd=tempfile.gettempdir(),
                **quiet,
            )
        else:
            subprocess.Popen(
                ["/bin/sh", str(script)], start_new_session=True, close_fds=True, cwd=tempfile.gettempdir(), **quiet
            )
    except OSError as error:
        raise InstallError(f"Не удалось запустить установщик обновления: {error}") from error
