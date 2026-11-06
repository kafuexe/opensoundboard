"""Decode audio files to stereo float32 at the engine's sample rate."""
from __future__ import annotations

import threading
from collections import OrderedDict
from pathlib import Path

import numpy as np
import soundfile as sf

ENGINE_RATE = 48000


def to_stereo(data: np.ndarray) -> np.ndarray:
    if data.ndim == 1:
        data = data[:, None]
    if data.shape[1] == 1:
        return np.repeat(data, 2, axis=1)
    return data[:, :2]


def resample(data: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Linear-interpolation resample; good enough for short sound effects."""
    if src_rate == dst_rate or len(data) == 0:
        return data.astype(np.float32, copy=False)
    out_len = max(1, int(round(len(data) * dst_rate / src_rate)))
    src_pos = np.linspace(0, len(data) - 1, out_len)
    idx = np.arange(len(data))
    return np.stack([np.interp(src_pos, idx, data[:, c]) for c in range(data.shape[1])], axis=1).astype(np.float32)


def decode_file(path: Path, rate: int = ENGINE_RATE) -> np.ndarray:
    try:
        data, file_rate = sf.read(str(path), dtype="float32", always_2d=True)
    except sf.LibsndfileError:
        data, file_rate = _decode_with_ffmpeg(path)
    return resample(to_stereo(data), file_rate, rate)


def _decode_with_ffmpeg(path: Path) -> tuple[np.ndarray, int]:
    """Fallback for formats libsndfile can't read (m4a, aac, opus in webm...)."""
    import subprocess

    from ..tools import find

    ffmpeg = find("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(f"Can't read {path.name}: ffmpeg is missing (reinstall Soundboard)")
    proc = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "2", "-ar", str(ENGINE_RATE), "-"],
        capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Can't read {path.name}: {proc.stderr.decode(errors='replace').strip()}")
    return np.frombuffer(proc.stdout, dtype=np.float32).reshape(-1, 2).copy(), ENGINE_RATE


class DecodeCache:
    """Keeps recently played sounds decoded so hotkeys fire instantly."""

    def __init__(self, max_items: int = 64):
        self._items: OrderedDict[str, np.ndarray] = OrderedDict()
        self._lock = threading.Lock()
        self._max = max_items

    def get(self, path: Path) -> np.ndarray:
        key = str(path)
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
                return self._items[key]
        data = decode_file(path)
        with self._lock:
            self._items[key] = data
            while len(self._items) > self._max:
                self._items.popitem(last=False)
        return data

    def forget(self, path: Path) -> None:
        with self._lock:
            self._items.pop(str(path), None)
