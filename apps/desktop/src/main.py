"""Точка входа ПК-приложения для `flet build`."""

import flet as ft

from gmagc_desktop.app import build_page

ft.run(build_page)
