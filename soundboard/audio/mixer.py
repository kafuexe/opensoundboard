"""Sums the sounds that are currently playing into one stereo stream."""
from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass

import numpy as np


@dataclass
class Voice:
    key: str
    data: np.ndarray  # (frames, 2) float32
    gain: float
    pos: int = 0


class LiveSource:
    """Audio that keeps arriving (another app streamed into the mic). push() from the capture thread,
    pull() from the mixer. Holds a little audio back before starting so arrival jitter doesn't crackle,
    and drops the oldest audio if it falls behind, so latency stays low."""

    def __init__(self, gain: float = 1.0, prebuffer: int = 1920, max_frames: int = 12000):
        self.gain = gain
        self._chunks: deque[np.ndarray] = deque()
        self._frames = 0
        self._prebuffer = prebuffer  # 40 ms at 48 kHz
        self._max = max_frames  # 250 ms
        self._started = False
        self._lock = threading.Lock()

    def push(self, frames: np.ndarray) -> None:
        with self._lock:
            self._chunks.append(frames)
            self._frames += len(frames)
            while self._frames > self._max and len(self._chunks) > 1:
                self._frames -= len(self._chunks.popleft())

    def pull(self, frames: int) -> np.ndarray:
        out = np.zeros((frames, 2), dtype=np.float32)
        with self._lock:
            if not self._started:
                if self._frames < self._prebuffer:
                    return out
                self._started = True
            filled = 0
            while filled < frames and self._chunks:
                chunk = self._chunks[0]
                take = min(frames - filled, len(chunk))
                out[filled:filled + take] = chunk[:take]
                filled += take
                if take == len(chunk):
                    self._chunks.popleft()
                else:
                    self._chunks[0] = chunk[take:]
                self._frames -= take
            if filled < frames:
                self._started = False  # ran dry: build the cushion up again
        return out

    @property
    def buffered(self) -> int:
        return self._frames


class Mixer:
    def __init__(self, gain: float = 1.0):
        self.gain = gain
        self._voices: list[Voice] = []
        self._streams: dict[str, LiveSource] = {}
        self._lock = threading.Lock()

    def add_stream(self, key: str, source: LiveSource) -> None:
        with self._lock:
            self._streams[key] = source

    def remove_stream(self, key: str) -> None:
        with self._lock:
            self._streams.pop(key, None)

    def has_audio(self) -> bool:
        """Anything to render: a sound playing or an app being streamed."""
        with self._lock:
            return bool(self._voices or self._streams)

    def add(self, key: str, data: np.ndarray, gain: float = 1.0) -> None:
        with self._lock:
            self._voices.append(Voice(key, data, gain))

    def stop(self, key: str | None = None) -> None:
        with self._lock:
            self._voices = [] if key is None else [v for v in self._voices if v.key != key]

    def active_keys(self) -> set[str]:
        with self._lock:
            return {v.key for v in self._voices}

    def progress(self, key: str) -> float | None:
        with self._lock:
            voice = next((v for v in self._voices if v.key == key), None)
            return None if voice is None else voice.pos / max(1, len(voice.data))

    def render(self, frames: int) -> np.ndarray:
        out = np.zeros((frames, 2), dtype=np.float32)
        with self._lock:
            alive = []
            for voice in self._voices:
                chunk = voice.data[voice.pos : voice.pos + frames]
                out[: len(chunk)] += chunk * voice.gain
                voice.pos += len(chunk)
                if voice.pos < len(voice.data):
                    alive.append(voice)
            self._voices = alive
            for stream in self._streams.values():
                out += stream.pull(frames) * stream.gain
        out *= self.gain
        np.clip(out, -1.0, 1.0, out=out)
        return out
