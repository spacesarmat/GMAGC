"""Точка входа Android-приложения для `flet build apk`."""

import flet as ft

from gmagc_mobile.app import build_page

ft.run(build_page)
