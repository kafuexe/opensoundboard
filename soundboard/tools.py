"""External programs the app uses: ffmpeg/ffprobe (YouTube conversion, unusual audio formats) and
deno (the JavaScript runtime yt-dlp needs for YouTube).

The installed app ships them in tools\\ next to Soundboard.exe (installer/build.ps1 fetches them),
so nothing has to be installed separately. From source, a `installer\\build\\tools` folder from a
previous build is used if present, otherwise whatever is on PATH.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path


def bundled_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "tools"
    return Path(__file__).resolve().parents[1] / "installer" / "build" / "tools"


def find(name: str) -> str | None:
    """Full path of ffmpeg, ffprobe or deno, or None if there's none."""
    for candidate in (bundled_dir() / "ffmpeg" / f"{name}.exe", bundled_dir() / f"{name}.exe"):
        if candidate.is_file():
            return str(candidate)
    return shutil.which(name)
