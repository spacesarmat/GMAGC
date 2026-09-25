"""Точка входа ПК-приложения (Qt); она же вход для сборки PyInstaller."""

import sys

from gmagc_desktop.qt.app import run

if __name__ == "__main__":
    sys.exit(run())
