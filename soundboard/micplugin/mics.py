"""Microphones and which of them have the plugin. Read-only: works as the normal user."""
from __future__ import annotations

import winreg
from dataclasses import dataclass

from . import fx

CAPTURE_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Capture"
_VIEW = winreg.KEY_WOW64_64KEY
_NAME_PROP = "{a45c254e-df1c-4efd-8020-67d146a850e0},2"    # e.g. "Microphone"
_DEVICE_PROP = "{b3f8fa53-0004-438e-9003-51a46e139bfc},6"  # e.g. "Yeti Stereo Microphone"
_ACTIVE = 1
_KINDS = {winreg.REG_SZ: "String", winreg.REG_MULTI_SZ: "MultiString"}


@dataclass(frozen=True)
class Microphone:
    id: str            # capture endpoint id, lowercase "{...}"
    name: str          # what Windows sound settings show, made unique
    has_plugin: bool


def list_microphones() -> list[Microphone]:
    """Connected, enabled microphones, sorted by name."""
    found: list[tuple[str, str]] = []
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, CAPTURE_KEY, 0, winreg.KEY_READ | _VIEW)
    except OSError:
        return []
    with root:
        for i in range(winreg.QueryInfoKey(root)[0]):
            endpoint = winreg.EnumKey(root, i)
            try:
                with winreg.OpenKey(root, endpoint) as key:
                    if winreg.QueryValueEx(key, "DeviceState")[0] != _ACTIVE:
                        continue
                with winreg.OpenKey(root, endpoint + r"\Properties") as props:
                    name = _read(props, _NAME_PROP) or "Microphone"
                    device = _read(props, _DEVICE_PROP)
            except OSError:
                continue
            found.append((endpoint.lower(), f"{name} ({device})" if device else name))
    found.sort(key=lambda m: m[1].lower())
    return [Microphone(i, n, fx.has_plugin(read_fx(i))) for i, n in unique_names(found)]


def read_fx(mic_id: str) -> fx.Values:
    """The effect values (only the ones we care about) of one mic; empty if it has no FxProperties."""
    values: fx.Values = {}
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"{CAPTURE_KEY}\{mic_id}\FxProperties", 0,
                            winreg.KEY_READ | _VIEW) as key:
            for name in fx.TOUCHED:
                try:
                    data, kind = winreg.QueryValueEx(key, name)
                except OSError:
                    continue
                if kind in _KINDS:
                    values[name] = (_KINDS[kind], data)
    except OSError:
        pass
    return values


def default_mic_id(mics: list[Microphone]) -> str | None:
    """The mic Windows records from by default, matched by name; else the first one with the plugin."""
    try:
        import sounddevice as sd
        wasapi = next(api for api in sd.query_hostapis() if "WASAPI" in api["name"])
        default_name = sd.query_devices(wasapi["default_input_device"])["name"]
    except Exception:
        default_name = ""
    for mic in mics:
        if default_name and mic.name.lower() == default_name.lower():
            return mic.id
    return next((m.id for m in mics if m.has_plugin), None)


def unique_names(mics: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: dict[str, int] = {}
    out = []
    for mic_id, name in mics:
        seen[name] = seen.get(name, 0) + 1
        out.append((mic_id, name if seen[name] == 1 else f"{name} {seen[name]}"))
    return out


def _read(key, name: str) -> str:
    try:
        return str(winreg.QueryValueEx(key, name)[0]).strip()
    except OSError:
        return ""
