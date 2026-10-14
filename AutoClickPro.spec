# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-folder build for AutoClick Pro.

The EXE version resource is generated from autoclick_pro/__init__.py, so the
version lives in one place. installer.iss reads it back from the built EXE.
"""

import os
import re

from PyInstaller.utils.hooks import collect_all
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

ICON = os.path.join(SPECPATH, "assets", "icon.ico")

with open(os.path.join(SPECPATH, "autoclick_pro", "__init__.py"), encoding="utf-8") as fh:
    VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', fh.read()).group(1)
_parts = tuple(int(p) for p in re.findall(r"\d+", VERSION)[:4])
VERSION_TUPLE = _parts + (0,) * (4 - len(_parts))

version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=VERSION_TUPLE, prodvers=VERSION_TUPLE),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "040904B0",
                    [
                        StringStruct("CompanyName", "AutoClick Pro"),
                        StringStruct("FileDescription", "AutoClick Pro"),
                        StringStruct("FileVersion", VERSION),
                        StringStruct("InternalName", "AutoClickPro"),
                        StringStruct("OriginalFilename", "AutoClickPro.exe"),
                        StringStruct("ProductName", "AutoClick Pro"),
                        StringStruct("ProductVersion", VERSION),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)

pynput_datas, pynput_binaries, pynput_hiddenimports = collect_all("pynput")

# The app only uses QtCore/QtGui/QtWidgets. Everything below is pulled in by
# the generic PySide6 hooks and roughly doubles the folder size.
EXCLUDED_MODULES = [
    "PySide6.QtNetwork",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtPdf",
    "PySide6.QtOpenGL",
    "PySide6.QtSvg",
    "PySide6.QtVirtualKeyboard",
    "ssl",
    "_ssl",
    "_hashlib",
    "tkinter",
    "unittest",
    "pydoc",
]
EXCLUDED_BINARY_PATTERNS = [
    "opengl32sw",
    "qt6network",
    "qt6qml",
    "qt6quick",
    "qt6pdf",
    "qt6opengl",
    "qt6svg",
    "qt6virtualkeyboard",
    "libssl-3-x64",
    "libcrypto-3-x64",
    "/plugins/tls/",
    "/plugins/networkinformation/",
    "/plugins/platforminputcontexts/",
    "/plugins/generic/",
    "/plugins/iconengines/",
    "/plugins/imageformats/qpdf",
    "/plugins/imageformats/qsvg",
    "/plugins/imageformats/qtiff",
    "/plugins/imageformats/qwebp",
    "/plugins/imageformats/qgif",
    "/plugins/imageformats/qjpeg",
    "/plugins/imageformats/qicns",
    "/plugins/imageformats/qtga",
    "/plugins/imageformats/qwbmp",
    "/plugins/platforms/qdirect2d",
    "/plugins/platforms/qminimal",
    "/plugins/platforms/qoffscreen",
]


def _keep(entry):
    dest = entry[0].replace("\\", "/").lower()
    if "pyside6/translations/" in dest:
        return False
    return not any(pattern in dest for pattern in EXCLUDED_BINARY_PATTERNS)


a = Analysis(
    ["main.py"],
    pathex=[SPECPATH],
    binaries=pynput_binaries,
    datas=pynput_datas + [(os.path.join(SPECPATH, "assets"), "assets")],
    hiddenimports=pynput_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDED_MODULES,
    noarchive=False,
    optimize=0,
)
a.binaries = [entry for entry in a.binaries if _keep(entry)]
a.datas = [entry for entry in a.datas if _keep(entry)]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AutoClickPro",
    icon=ICON,
    version=version_info,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
app = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AutoClickPro",
)
