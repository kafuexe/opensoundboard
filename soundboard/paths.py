"""Where the app keeps its data. Override with SOUNDBOARD_HOME (used by tests)."""
from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    override = os.environ.get("SOUNDBOARD_HOME")
    base = Path(override) if override else Path(os.environ.get("APPDATA", Path.home())) / "Soundboard"
    base.mkdir(parents=True, exist_ok=True)
    return base


def sounds_dir() -> Path:
    path = data_dir() / "sounds"
    path.mkdir(parents=True, exist_ok=True)
    return path


def library_file() -> Path:
    return data_dir() / "library.json"


def settings_file() -> Path:
    return data_dir() / "settings.json"
