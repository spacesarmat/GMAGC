import hashlib
import io
import shlex
import sys
import zipfile
from pathlib import Path, PurePosixPath

import pytest

from gmagc_common.updates import Asset
from gmagc_desktop.update import installer
from gmagc_desktop.update.installer import (
    InstallCancelled,
    InstallError,
    backup_dir,
    current_executable,
    download,
    install_target,
    is_writable,
    launch_helper,
    macos_script,
    platform_key,
    sha256_of,
    stage,
    windows_script,
    write_helper,
)
from tests.updates_stub import stub_server


def make_zip(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def serve(body, sha=None, name="GMAGC-desktop-windows-0.6.0.zip", **route):
    """Сервер с файлом и его .sha256; возвращает (контекст, asset, checksum_asset-фабрика)."""
    digest = sha or hashlib.sha256(body).hexdigest()
    routes = {
        f"/{name}": {"body": body, **route},
        f"/{name}.sha256": {"body": f"{digest}  {name}\n".encode()},
    }
    return routes, name


def assets(base, name, size=0):
    return Asset(name, f"{base}/{name}", size), Asset(name + ".sha256", f"{base}/{name}.sha256", 100)


# ---- определение папки приложения ---------------------------------------------------------
def test_the_windows_install_target_is_the_folder_of_the_app_exe():
    exe = Path("C:/Apps/GMAGC/gmagc-desktop.exe")

    assert install_target(exe, "windows") == exe.parent
    assert install_target(Path("C:/Apps/GMAGC/GMAGC-desktop.EXE"), "windows") == exe.parent


def test_a_foreign_executable_is_not_an_install_target():
    assert install_target(Path("C:/Python312/python.exe"), "windows") is None
    assert install_target(None, "windows") is None
    assert install_target(Path("/usr/bin/python3"), "linux") is None


def test_the_macos_install_target_is_the_app_bundle():
    exe = Path("/Applications/GMAGC.app/Contents/MacOS/gmagc-desktop")

    assert install_target(exe, "macos") == Path("/Applications/GMAGC.app")
    assert install_target(Path("/usr/local/bin/python3"), "macos") is None


def test_the_platform_key_and_current_executable_are_sane_here():
    assert platform_key() in {"windows", "macos", None}
    if sys.platform == "win32":
        assert platform_key() == "windows"
        executable = current_executable()
        assert executable is not None and executable.is_file()


def test_writability_is_tested_by_creating_a_file(tmp_path):
    assert is_writable(tmp_path)
    assert not is_writable(tmp_path / "missing" / "deeper")


def test_the_backup_folder_sits_next_to_the_app():
    assert backup_dir(Path("C:/Apps/GMAGC")) == Path("C:/Apps/GMAGC.previous")


def test_the_macos_backup_is_hidden_and_not_indexed_as_its_own_app():
    """.previous рядом с .app-пакетом Launchpad и Spotlight показывают как отдельное приложение."""
    assert backup_dir(Path("/Applications/GMAGC.app")) == Path("/Applications/.GMAGC.previous")


def test_sha256_of_a_file(tmp_path):
    path = tmp_path / "f.bin"
    path.write_bytes(b"hello")

    assert sha256_of(path) == hashlib.sha256(b"hello").hexdigest()


# ---- загрузка ---------------------------------------------------------------------------------
def test_a_verified_download_is_saved_and_reports_progress(tmp_path):
    body = b"x" * 600_000
    routes, name = serve(body)
    steps = []
    with stub_server(routes) as base:
        asset, checksum = assets(base, name, size=len(body))

        path = download(
            asset, checksum, tmp_path / "dl", progress=lambda done, total: steps.append((done, total)), allow_local=True
        )

    assert path == tmp_path / "dl" / name and path.read_bytes() == body
    assert steps[-1] == (600_000, 600_000) and steps == sorted(steps) and len(steps) >= 3
    assert not list((tmp_path / "dl").glob("*.part"))


def test_a_wrong_checksum_removes_the_file_and_refuses_the_update(tmp_path):
    routes, name = serve(b"payload", sha="0" * 64)
    with stub_server(routes) as base:
        asset, checksum = assets(base, name)
        with pytest.raises(InstallError) as error:
            download(asset, checksum, tmp_path / "dl", allow_local=True)

    assert "Контрольная сумма не совпала" in str(error.value)
    assert list((tmp_path / "dl").glob("*")) == []


def test_a_release_without_a_checksum_is_refused(tmp_path):
    routes, name = serve(b"payload")
    with stub_server(routes) as base:
        asset, _ = assets(base, name)
        with pytest.raises(InstallError) as error:
            download(asset, None, tmp_path / "dl", allow_local=True)

    assert "нет контрольной суммы" in str(error.value)


def test_a_broken_checksum_file_is_refused(tmp_path):
    routes, name = serve(b"payload")
    routes[f"/{name}.sha256"] = {"body": b"this is not a hash\n"}
    with stub_server(routes) as base:
        asset, checksum = assets(base, name)
        with pytest.raises(InstallError) as error:
            download(asset, checksum, tmp_path / "dl", allow_local=True)

    assert "повреждена" in str(error.value)


def test_a_truncated_download_is_refused(tmp_path):
    routes, name = serve(b"short", declared_length=5000)
    with stub_server(routes) as base:
        asset, checksum = assets(base, name)
        with pytest.raises(InstallError):
            download(asset, checksum, tmp_path / "dl", allow_local=True)

    assert list((tmp_path / "dl").glob("*")) == []


def test_cancelling_stops_the_download_and_leaves_nothing(tmp_path):
    routes, name = serve(b"x" * 600_000)
    with stub_server(routes) as base:
        asset, checksum = assets(base, name)
        with pytest.raises(InstallCancelled):
            download(asset, checksum, tmp_path / "dl", cancel=lambda: True, allow_local=True)

    assert list((tmp_path / "dl").glob("*")) == []


def test_a_file_over_the_size_limit_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "MAX_DOWNLOAD_BYTES", 1000)
    routes, name = serve(b"x" * 5000)
    with stub_server(routes) as base:
        asset, checksum = assets(base, name)
        with pytest.raises(InstallError) as error:
            download(asset, checksum, tmp_path / "dl", allow_local=True)

    assert "слишком большой" in str(error.value)


def test_a_redirect_to_a_foreign_host_is_refused(tmp_path):
    routes, name = serve(b"payload")
    routes[f"/{name}"] = {"status": 302, "headers": {"Location": "https://evil.example/x.zip"}}
    with stub_server(routes) as base:
        asset, checksum = assets(base, name)
        with pytest.raises(InstallError) as error:
            download(asset, checksum, tmp_path / "dl", allow_local=True)

    assert "недопустим" in str(error.value)


def test_a_local_address_is_refused_unless_allowed(tmp_path):
    routes, name = serve(b"payload")
    with stub_server(routes) as base:
        asset, checksum = assets(base, name)
        with pytest.raises(InstallError):
            download(asset, checksum, tmp_path / "dl")


# ---- распаковка -----------------------------------------------------------------------------------
def write_archive(tmp_path, files):
    path = tmp_path / "update.zip"
    path.write_bytes(make_zip(files))
    return path


def test_a_windows_archive_is_unpacked_with_its_folders(tmp_path):
    archive = write_archive(tmp_path, {"gmagc-desktop.exe": b"MZ", "data/app.bin": b"1", "Lib/x/y.pyc": b"2"})

    root = stage(archive, tmp_path / "staged", "windows")

    assert root == (tmp_path / "staged").resolve() and (root / "gmagc-desktop.exe").read_bytes() == b"MZ"
    assert (root / "data" / "app.bin").read_bytes() == b"1" and (root / "Lib" / "x" / "y.pyc").read_bytes() == b"2"


@pytest.mark.parametrize("evil", ["../evil.txt", "a/../../evil.txt", "/abs/evil.txt", "C:/evil.txt", "..\\evil.txt"])
def test_an_unsafe_path_in_the_archive_stops_the_installation(tmp_path, evil):
    archive = write_archive(tmp_path, {"gmagc-desktop.exe": b"MZ", evil: b"x"})

    with pytest.raises(InstallError) as error:
        stage(archive, tmp_path / "staged", "windows")

    assert "небезопасный путь" in str(error.value)
    assert not (tmp_path / "evil.txt").exists() and not Path("/abs/evil.txt").exists()


def test_an_archive_without_the_app_is_refused(tmp_path):
    with pytest.raises(InstallError) as error:
        stage(write_archive(tmp_path, {"readme.txt": b"hi"}), tmp_path / "staged", "windows")

    assert "нет приложения" in str(error.value)


def test_a_file_that_is_not_an_archive_is_refused(tmp_path):
    path = tmp_path / "update.zip"
    path.write_bytes(b"not a zip")

    with pytest.raises(InstallError) as error:
        stage(path, tmp_path / "staged", "windows")

    assert "не архив" in str(error.value)


def test_an_archive_that_unpacks_to_too_much_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "MAX_UNPACKED_BYTES", 100)
    archive = write_archive(tmp_path, {"gmagc-desktop.exe": b"x" * 1000})

    with pytest.raises(InstallError) as error:
        stage(archive, tmp_path / "staged", "windows")

    assert "слишком велик" in str(error.value)


# ---- скрипты-помощники ----------------------------------------------------------------------------
WIN = {
    "pid": 4242,
    "staged": r"C:\Users\Иван Петров\AppData\Local\@ANDY_BUM\GMAGC\updates\0.6.0\staged",
    "target": r"C:\Apps\GMAGC гобо 100%",
    "backup": r"C:\Apps\GMAGC гобо 100%.previous",
    "exe": r"C:\Apps\GMAGC гобо 100%\gmagc-desktop.exe",
    "log": r"C:\Users\Иван Петров\AppData\Local\@ANDY_BUM\GMAGC\update.log",
}


def test_the_windows_script_waits_backs_up_copies_restores_and_restarts():
    script = windows_script(**WIN)

    assert 'set "PID=4242"' in script and "tasklist" in script and "goto wait" in script
    assert script.count("robocopy") == 3 and "if errorlevel 8 goto restore" in script and ":restore" in script
    assert 'start "" "%EXE%"' in script and "chcp 65001" in script
    assert script.endswith("\r\n") and "\n" not in script.replace("\r\n", "")


def test_the_windows_script_keeps_cyrillic_and_spaces_and_doubles_percent_signs():
    script = windows_script(**WIN)

    assert r'set "DST=C:\Apps\GMAGC гобо 100%%"' in script
    assert r'set "SRC=C:\Users\Иван Петров\AppData\Local\@ANDY_BUM\GMAGC\updates\0.6.0\staged"' in script
    assert "100%%.previous" in script and "100%.previous" not in script.replace("100%%.previous", "")


def test_the_macos_script_quotes_every_path():
    target = "/Applications/My App's/GMAGC.app"
    script = macos_script(
        pid=77, staged="/tmp/up date/GMAGC.app", target=target, backup=target + ".previous", log="/tmp/u.log"
    )

    assert script.startswith("#!/bin/sh") and "PID=77" in script and "ditto" in script and "kill -0" in script
    assert f"DST={shlex.quote(target)}" in script and f"SRC={shlex.quote('/tmp/up date/GMAGC.app')}" in script
    assert 'open "$DST"' in script and script.endswith("\n") and "\r" not in script


def test_the_helper_is_written_next_to_the_staged_files(tmp_path):
    fields = {**WIN, "staged": tmp_path / "staged", "target": tmp_path / "app", "backup": tmp_path / "app.previous",
              "exe": tmp_path / "app" / "gmagc-desktop.exe", "log": tmp_path / "update.log"}

    script = write_helper("windows", tmp_path / "work", **fields)

    assert script == tmp_path / "work" / "apply-update.cmd"
    data = script.read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf") and b'set "PID=4242"' in data and str(tmp_path).encode() in data


def test_the_macos_helper_is_executable(tmp_path):
    script = write_helper("macos", tmp_path / "work", pid=5, staged=tmp_path / "s", target=tmp_path / "GMAGC.app",
                          exe=tmp_path / "x", backup=tmp_path / "GMAGC.app.previous", log=tmp_path / "l")

    assert script.name == "apply-update.sh" and script.read_text(encoding="utf-8").startswith("#!/bin/sh")
    if sys.platform != "win32":
        assert script.stat().st_mode & 0o111


def test_an_unsupported_platform_has_no_helper(tmp_path):
    with pytest.raises(InstallError):
        write_helper("linux", tmp_path, pid=1, staged=tmp_path, target=tmp_path, exe=tmp_path, backup=tmp_path, log=tmp_path)


def test_the_helper_is_launched_detached_without_a_window(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(installer.subprocess, "Popen", lambda *args, **kwargs: calls.append((args, kwargs)))
    script = tmp_path / "apply-update.cmd"

    launch_helper(script, "windows")
    launch_helper(tmp_path / "apply-update.sh", "macos")

    (win_args, win_kwargs), (mac_args, mac_kwargs) = calls
    assert win_args[0][:4] == ["cmd.exe", "/d", "/c", "call"] and win_args[0][4] == str(script)
    assert win_kwargs["close_fds"] is True and "creationflags" in win_kwargs
    assert mac_args[0][0] == "/bin/sh" and mac_kwargs["start_new_session"] is True


def test_a_failing_launch_is_reported(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("нет доступа")

    monkeypatch.setattr(installer.subprocess, "Popen", boom)

    with pytest.raises(InstallError) as error:
        launch_helper(tmp_path / "apply-update.cmd", "windows")

    assert "Не удалось запустить" in str(error.value)


def test_posix_style_paths_are_pure_and_do_not_need_a_disk():
    assert PurePosixPath("/Applications/GMAGC.app").suffix == ".app"
