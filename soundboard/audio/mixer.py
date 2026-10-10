"""Sums the sounds that are currently playing into one stereo stream."""
from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np


@dataclass
class Voice:
    key: str
    data: np.ndarray  # (frames, 2) float32
    gain: float
    pos: int = 0


class Mixer:
    def __init__(self, gain: float = 1.0):
        self.gain = gain
        self._voices: list[Voice] = []
        self._lock = threading.Lock()

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
        out *= self.gain
        np.clip(out, -1.0, 1.0, out=out)
        return out
