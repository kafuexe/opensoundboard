"""Stream another app's audio (Spotify, a browser tab, a game) into the mic.

apo/src/capture.cpp builds SoundboardCapture.exe, which captures one app and its child processes
with Windows' process loopback (Windows 10 2004+) and writes raw 48 kHz stereo float32 to stdout.
We read that on a thread and feed it to the mic mixer as a LiveSource. You already hear the app
itself, so the stream only goes into the mic.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from .mixer import LiveSource, Mixer

STREAM_KEY = "__app_stream__"
_NO_WINDOW = 0x08000000
_EXIT_REASONS = {3: "closed", 4: "couldn't be captured (needs Windows 10 version 2004 or newer)", 5: ""}


def helper_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "SoundboardCapture.exe"
    return Path(__file__).resolve().parents[2] / "apo" / "build" / "SoundboardCapture.exe"


@dataclass(frozen=True)
class AudioApp:
    pid: int
    exe: str
    name: str      # "Spotify", "Google Chrome"
    playing: bool  # making sound right now


def list_apps() -> list[AudioApp]:
    """Apps with audio sessions, playing ones first. Soundboard itself is left out."""
    helper = helper_path()
    if not helper.exists():
        raise RuntimeError("The capture helper is missing (from source: run apo\\build.ps1)")
    out = subprocess.run([str(helper), "list"], capture_output=True, timeout=15, creationflags=_NO_WINDOW)
    apps = []
    ours = {os.getpid(), os.getppid()}
    for line in out.stdout.decode("utf-8", errors="replace").splitlines():
        parts = line.split("\t")
        if len(parts) != 4 or not parts[0].isdigit() or int(parts[0]) in ours:
            continue
        apps.append(AudioApp(int(parts[0]), parts[2], parts[3] or parts[2], parts[1] == "1"))
    return sorted(apps, key=lambda a: (not a.playing, a.name.lower()))


class AppStream:
    """At most one app streamed into the mic at a time."""

    def __init__(self, mixer: Mixer, gain: float = 0.6):
        self.mixer = mixer
        self.source = LiveSource(gain)
        self.app: AudioApp | None = None
        self._proc: subprocess.Popen | None = None
        self._on_end: Callable[[str], None] | None = None

    @property
    def running(self) -> bool:
        return self._proc is not None

    def set_gain(self, gain: float) -> None:
        self.source.gain = gain

    def start(self, app: AudioApp, on_end: Callable[[str], None] | None = None) -> None:
        """Start streaming. on_end(reason) is called (from a worker thread) if it stops by itself."""
        self.stop()
        helper = helper_path()
        if not helper.exists():
            raise RuntimeError("The capture helper is missing (from source: run apo\\build.ps1)")
        self.source = LiveSource(self.source.gain)
        proc = subprocess.Popen([str(helper), "capture", str(app.pid)], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, creationflags=_NO_WINDOW)
        self._proc, self.app, self._on_end = proc, app, on_end
        self.mixer.add_stream(STREAM_KEY, self.source)
        threading.Thread(target=self._pump, args=(proc, self.source), name="app-stream", daemon=True).start()

    def stop(self) -> None:
        proc, self._proc = self._proc, None
        self.mixer.remove_stream(STREAM_KEY)
        self.app = None
        if proc is not None:
            proc.kill()
            proc.wait(timeout=5)

    def _pump(self, proc: subprocess.Popen, source: LiveSource) -> None:
        leftover = b""
        while True:
            data = proc.stdout.read1(19200) if proc.stdout else b""  # ~50 ms
            if not data:
                break
            data = leftover + data
            usable = len(data) // 8 * 8
            leftover = data[usable:]
            if usable:
                source.push(np.frombuffer(data[:usable], dtype=np.float32).reshape(-1, 2).copy())
        code = proc.wait()
        if self._proc is proc:  # ended by itself, not by stop()
            name = self.app.name if self.app else "The app"
            self.stop()
            reason = _EXIT_REASONS.get(code)
            if reason is None:
                err = proc.stderr.read().decode(errors="replace").strip() if proc.stderr else ""
                reason = f"stopped ({err or f'exit code {code}'})"
            if self._on_end:
                self._on_end(f"{name} {reason}".strip() if reason else f"Stopped streaming {name}")
