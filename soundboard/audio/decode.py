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


def to_int16(data: np.ndarray) -> np.ndarray:
    """Half the memory of float32 and CD quality; the mixer converts back as it plays."""
    return (np.clip(data, -1.0, 1.0) * 32767).astype(np.int16)


class DecodeCache:
    """Keeps recently played short sounds decoded so hotkeys fire instantly.

    Capped by size, not count: one decoded minute is ~11 MB even as 16-bit, so a handful of songs
    would otherwise sit in memory for good. Sounds longer than `max_cached_seconds` (songs) aren't
    kept: they use memory while playing and give it back when they end.
    """

    def __init__(self, max_bytes: int = 32 * 2**20, max_cached_seconds: float = 30.0):
        self._items: OrderedDict[str, np.ndarray] = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()
        self.max_bytes = max_bytes
        self.max_frames = int(max_cached_seconds * ENGINE_RATE)

    def get(self, path: Path) -> np.ndarray:
        """The sound as (frames, 2) int16 at ENGINE_RATE."""
        key = str(path)
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
                return self._items[key]
        data = to_int16(decode_file(path))
        if len(data) <= self.max_frames and data.nbytes <= self.max_bytes:
            with self._lock:
                if key not in self._items:
                    self._items[key] = data
                    self._bytes += data.nbytes
                while self._bytes > self.max_bytes:
                    self._bytes -= self._items.popitem(last=False)[1].nbytes
        return data

    def forget(self, path: Path) -> None:
        with self._lock:
            data = self._items.pop(str(path), None)
            if data is not None:
                self._bytes -= data.nbytes

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._bytes = 0

    @property
    def size_bytes(self) -> int:
        return self._bytes
