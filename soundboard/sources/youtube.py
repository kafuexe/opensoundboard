"""YouTube (and anything else yt-dlp supports) to MP3, with optional trimming."""
from __future__ import annotations

import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .. import tools
from .cancel import CancelToken, Cancelled

_TIME = re.compile(r"^\s*(?:(\d+):)?(?:(\d+):)?(\d+(?:\.\d+)?)\s*$")


def parse_time(text: str) -> float | None:
    """'1:23', '83', '0:01:23.5' -> seconds. Empty -> None. Raises ValueError on junk."""
    if not text or not text.strip():
        return None
    m = _TIME.match(text)
    if not m:
        raise ValueError(f"'{text}' isn't a time. Use seconds or m:ss, like 1:23")
    a, b, sec = m.groups()
    hours, minutes = (int(a), int(b)) if b is not None else (0, int(a or 0))
    return hours * 3600 + minutes * 60 + float(sec)


def looks_like_url(text: str) -> bool:
    return bool(re.match(r"^https?://\S+$", text.strip()))


@dataclass
class YouTubeResult:
    path: Path
    title: str


def ffmpeg_path() -> str | None:
    return tools.find("ffmpeg")


def download_mp3(
    url: str,
    start: float | None = None,
    end: float | None = None,
    on_progress: Callable[[float, str], None] | None = None,
    cancel: CancelToken | None = None,
) -> YouTubeResult:
    """Download the audio of one video as MP3 into a temp folder. on_progress(fraction, message).
    Raises Cancelled if cancel is triggered (checked on every progress update)."""
    import yt_dlp
    from yt_dlp.utils import DownloadCancelled, download_range_func

    if not ffmpeg_path():
        raise RuntimeError("ffmpeg is missing. Reinstall Soundboard, or from source run installer\\build.ps1 "
                           "(or winget install ffmpeg).")
    if start is not None and end is not None and end <= start:
        raise ValueError("The end time has to be after the start time")

    out_dir = Path(tempfile.mkdtemp(prefix="yt-"))

    def hook(d: dict) -> None:
        if cancel and cancel.cancelled:
            raise DownloadCancelled("cancelled")
        if not on_progress:
            return
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            frac = (d.get("downloaded_bytes", 0) / total) if total else 0.0
            on_progress(min(frac, 1.0) * 0.9, "Downloading…")
        elif d.get("status") == "finished":
            on_progress(0.92, "Converting to MP3…")

    opts = {
        "format": "bestaudio/best",
        "outtmpl": str(out_dir / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "progress_hooks": [hook],
        "postprocessor_hooks": [lambda _d: hook({})],  # lets cancel land between download and conversion
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
        "ffmpeg_location": str(Path(ffmpeg_path()).parent),  # ffmpeg and ffprobe live together
    }
    deno = tools.find("deno")  # YouTube needs a JavaScript runtime; the installer ships deno
    if deno:
        opts["js_runtimes"] = {"deno": {"path": deno}}
    # yt-dlp's check for trimmed downloads ignores ffmpeg_location and only looks on PATH, unless this
    # is set (its own command line does the same). A context variable, so set in this thread.
    from yt_dlp.postprocessor.ffmpeg import FFmpegPostProcessor
    FFmpegPostProcessor._ffmpeg_location.set(opts["ffmpeg_location"])
    if start is not None or end is not None:
        opts["download_ranges"] = download_range_func(None, [(start or 0, end if end is not None else float("inf"))])
        opts["force_keyframes_at_cuts"] = True

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
        if cancel:
            cancel.check()
    except BaseException as exc:
        shutil.rmtree(out_dir, ignore_errors=True)
        if cancel and cancel.cancelled:
            raise Cancelled() from exc
        raise
    if info is None:
        raise RuntimeError("Couldn't read that link")
    if "entries" in info:  # a playlist link slipped through; take the first video
        info = next(iter(info["entries"] or []), None) or {}
    mp3s = sorted(out_dir.glob("*.mp3"))
    if not mp3s:
        raise RuntimeError("The download finished but no MP3 was produced")
    if on_progress:
        on_progress(1.0, "Done")
    return YouTubeResult(mp3s[0], info.get("title") or mp3s[0].stem)
