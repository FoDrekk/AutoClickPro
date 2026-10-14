# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-folder build for AutoClick Pro."""

from PyInstaller.utils.hooks import collect_all
import os

ICON = os.path.join(SPECPATH, "assets", "icon.ico")

pynput_datas, pynput_binaries, pynput_hiddenimports = collect_all("pynput")

a = Analysis(
    ["main.py"],
    pathex=[SPECPATH],
    binaries=pynput_binaries,
    datas=pynput_datas + [(os.path.join(SPECPATH, "assets"), "assets")],
    hiddenimports=pynput_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AutoClickPro",
    icon=ICON,
    version=os.path.join(SPECPATH, "version_info.txt"),
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
