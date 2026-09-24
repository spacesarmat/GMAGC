# -*- mode: python ; coding: utf-8 -*-
"""Сборка ПК-приложения GMAGC (PySide6) в папку `gmagc-desktop` (Windows) или пакет `GMAGC.app` (macOS).

Запуск из корня репозитория:
    pyinstaller packaging/pyinstaller/gmagc-desktop.spec --noconfirm --distpath dist-app --workpath build-app

Имя исполняемого файла `gmagc-desktop(.exe)` не менять: по нему автообновление (update/installer.py) находит папку
приложения. Версия берётся из gmagc_desktop/about.py.
"""

import os
import re
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
SRC = os.path.join(ROOT, "apps", "desktop", "src")

with open(os.path.join(SRC, "gmagc_desktop", "about.py"), encoding="utf-8") as handle:
    VERSION = re.search(r'VERSION\s*=\s*"([^"]+)"', handle.read()).group(1)

datas = [(os.path.join(SRC, "assets"), "assets")]
binaries = []
# OCR: модели RapidOCR лежат файлами внутри пакета; onnxruntime и pdfium несут собственные библиотеки
for package in ("rapidocr_onnxruntime", "pypdfium2", "pypdfium2_raw", "onnxruntime", "certifi"):
    try:
        datas += collect_data_files(package)
        binaries += collect_dynamic_libs(package)
    except Exception:  # noqa: BLE001 - пакета может не быть в окружении сборки
        pass

hiddenimports = collect_submodules("gmagc_desktop") + collect_submodules("gmagc_common")
hiddenimports += ["anthropic", "PIL.Image", "cv2", "numpy"]

excludes = ["flet", "flet_desktop", "tkinter", "matplotlib", "IPython", "pytest", "PySide6.QtWebEngineCore"]

if sys.platform == "win32":
    ICON = os.path.join(ROOT, "packaging", "windows", "gmagc.ico")
else:
    ICON = os.path.join(SRC, "assets", "icon.png")  # PyInstaller сам переводит PNG в .icns (нужен Pillow)

a = Analysis(
    [os.path.join(SRC, "main.py")],
    pathex=[SRC],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="gmagc-desktop",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=ICON,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="gmagc-desktop")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="GMAGC.app",
        icon=ICON,
        bundle_identifier="com.spacesarmat.gmagc",
        version=VERSION,
        info_plist={
            "CFBundleName": "GMAGC",
            "CFBundleDisplayName": "GMAGC",
            "CFBundleShortVersionString": VERSION,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "NSPhotoLibraryUsageDescription": "GMAGC ищет гобо по выбранным вами фото.",
        },
    )
