"""
infrastructure/app_paths.py - filesystem paths for user data.

All mutable user data lives in the OS-local app folder, not next to the code.
"""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "WorkTimer"


def get_app_data_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if not base:
        base = str(Path.home() / "AppData" / "Local")
    return os.path.join(base, APP_NAME)


def ensure_app_data_dir() -> str:
    path = get_app_data_dir()
    os.makedirs(path, exist_ok=True)
    return path


def get_settings_path() -> str:
    return os.path.join(ensure_app_data_dir(), "settings.json")


def get_journal_path() -> str:
    return os.path.join(ensure_app_data_dir(), "journal.json")


def get_legacy_project_settings_path(project_root: str) -> str:
    return os.path.join(project_root, "data", "settings.json")
