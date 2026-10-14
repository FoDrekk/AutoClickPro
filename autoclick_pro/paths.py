"""Filesystem locations used by the app, valid from source and from a frozen build."""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "AutoClick Pro"


def package_root() -> Path:
    # Source checkout: the project folder. PyInstaller build: the _internal folder.
    return Path(__file__).resolve().parent.parent


def asset_path(name: str) -> Path:
    return package_root() / "assets" / name


def data_dir() -> Path:
    base = os.environ.get("APPDATA")
    return Path(base) / APP_NAME if base else Path.home() / ".autoclick_pro"


def settings_path() -> Path:
    return data_dir() / "settings.json"


def log_path() -> Path:
    return Path.home() / ".autoclick_pro.log"
