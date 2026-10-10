"""Plays sounds to two places at once: your headphones (monitor) and your mic."""
from __future__ import annotations

import threading
from pathlib import Path

from ..settings import MIC_MODE_DEVICE, Settings
from .decode import DecodeCache
from .mixer import Mixer
from .outputs import DeviceOutput, PluginMicOutput

PREVIEW_KEY = "__preview__"


class AudioEngine:
    def __init__(self, settings: Settings):
        self.cache = DecodeCache()
        self.monitor_mixer = Mixer(settings.monitor_volume)
        self.mic_mixer = Mixer(settings.mic_volume)
        self.monitor = DeviceOutput(self.monitor_mixer)
        self.mic_device = DeviceOutput(self.mic_mixer)
        self.mic_plugin = PluginMicOutput(self.mic_mixer)
        self.one_at_a_time = settings.one_at_a_time
        self._mic_mode = ""
        self._lock = threading.Lock()
        self.apply(settings)

    def apply(self, settings: Settings) -> None:
        """Re-open outputs after the user changes devices or mic mode."""
        self.monitor_mixer.gain = settings.monitor_volume
        self.mic_mixer.gain = settings.mic_volume
        self.one_at_a_time = settings.one_at_a_time
        if self.monitor.device_name != settings.monitor_device or self.monitor._stream is None:
            self.monitor.open(settings.monitor_device)
        if settings.mic_mode == MIC_MODE_DEVICE:
            self.mic_plugin.close()
            if self._mic_mode != MIC_MODE_DEVICE or self.mic_device.device_name != settings.mic_device:
                self.mic_device.open(settings.mic_device)
        else:
            self.mic_device.close()
            if self._mic_mode != settings.mic_mode:
                self.mic_plugin.open()
        self._mic_mode = settings.mic_mode

    def set_volumes(self, monitor: float | None = None, mic: float | None = None) -> None:
        if monitor is not None:
            self.monitor_mixer.gain = monitor
        if mic is not None:
            self.mic_mixer.gain = mic

    def play(self, key: str, path: Path, gain: float = 1.0) -> None:
        """Decode (cached) and start a sound on both outputs. Raises on unreadable files."""
        data = self.cache.get(path)
        with self._lock:
            if self.one_at_a_time:
                self.stop_all()
            else:
                self.stop(key)
            self.monitor_mixer.add(key, data, gain)
            self.mic_mixer.add(key, data, gain)

    def preview(self, path: Path) -> None:
        """Play only in your headphones, e.g. to try a sound before adding it."""
        data = self.cache.get(path)
        self.monitor_mixer.stop(PREVIEW_KEY)
        self.monitor_mixer.add(PREVIEW_KEY, data, 1.0)

    def stop_preview(self) -> None:
        self.monitor_mixer.stop(PREVIEW_KEY)

    def previewing(self) -> bool:
        return PREVIEW_KEY in self.monitor_mixer.active_keys()

    def stop(self, key: str) -> None:
        self.monitor_mixer.stop(key)
        self.mic_mixer.stop(key)

    def stop_all(self) -> None:
        self.monitor_mixer.stop()
        self.mic_mixer.stop()

    def playing(self) -> set[str]:
        return (self.monitor_mixer.active_keys() | self.mic_mixer.active_keys()) - {PREVIEW_KEY}

    def progress(self, key: str) -> float | None:
        p = self.monitor_mixer.progress(key)
        return p if p is not None else self.mic_mixer.progress(key)

    def status(self) -> dict[str, str]:
        """Human-readable problems per output, empty string when fine."""
        if self._mic_mode == MIC_MODE_DEVICE:
            mic = self.mic_device.error
        else:
            mic = "" if self.mic_plugin.connected else (self.mic_plugin.error or "connecting to the mic plugin…")
        return {"monitor": self.monitor.error, "mic": mic}

    def shutdown(self) -> None:
        self.monitor.close()
        self.mic_device.close()
        self.mic_plugin.close()
