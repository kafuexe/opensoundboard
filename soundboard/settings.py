"""User settings persisted as JSON."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from . import paths

MIC_MODE_PLUGIN = "plugin"  # mix into the real mic via the Soundboard mic plugin
MIC_MODE_DEVICE = "device"  # play to an output device (e.g. a virtual cable) instead


@dataclass
class Settings:
    monitor_device: str = ""  # "" = system default output
    monitor_volume: float = 0.6
    mic_mode: str = MIC_MODE_PLUGIN
    mic_device: str = ""  # used when mic_mode == device
    plugin_mic: str = ""  # endpoint id of the mic sounds go into when mic_mode == plugin; "" = Windows default
    mic_volume: float = 0.8
    stop_hotkey: str = ""
    one_at_a_time: bool = True
    hotkeys_enabled: bool = True
    minimize_to: str = "taskbar"  # taskbar | tray
    close_to: str = "quit"  # quit | tray (keep running in the tray)
    theme: str = "soundboard"  # a CSS file in soundboard/themes or %APPDATA%/Soundboard/themes
    theme_mode: str = "dark"  # dark | light

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or paths.settings_file()
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        known = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in raw.items() if k in known})

    def save(self, path: Path | None = None) -> None:
        path = path or paths.settings_file()
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
