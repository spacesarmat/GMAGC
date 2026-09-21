import subprocess
import sys
from pathlib import Path

import pytest

from gmagc_desktop.service.reveal import reveal_in_file_manager


@pytest.fixture()
def launched(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda command, **kwargs: calls.append(command))
    return calls


def test_windows_selects_the_file_in_explorer(monkeypatch, launched):
    monkeypatch.setattr(sys, "platform", "win32")

    assert reveal_in_file_manager("D:\\Гобо\\a b\\ell.png") is True

    assert launched == ['explorer /select,"D:\\Гобо\\a b\\ell.png"']


def test_macos_reveals_the_file_in_finder(monkeypatch, launched):
    monkeypatch.setattr(sys, "platform", "darwin")

    assert reveal_in_file_manager("/lib/ell.png") is True

    assert launched == [["open", "-R", str(Path("/lib/ell.png"))]]


def test_other_systems_open_the_containing_folder(monkeypatch, launched):
    monkeypatch.setattr(sys, "platform", "linux")

    assert reveal_in_file_manager("/lib/sub/ell.png") is True

    assert launched == [["xdg-open", str(Path("/lib/sub/ell.png").parent)]]


def test_launch_failure_returns_false(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")

    def boom(command, **kwargs):
        raise FileNotFoundError("xdg-open")

    monkeypatch.setattr(subprocess, "Popen", boom)

    assert reveal_in_file_manager("/lib/ell.png") is False
