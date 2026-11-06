"""Steps that need admin: registering the plugin DLL and attaching it to mics.

Run as `soundboard --admin <command>` (from source: `python -m soundboard --admin <command>`):

    install [MIC_ID ...]   register the DLL and put it on these mics (default: every mic)
    add MIC_ID             put it on one more mic
    uninstall              take it off every mic, restore what each had, unregister it

The app runs these through run_elevated() (one Windows permission prompt); the installer runs
them directly. Windows audio restarts for a second each time, so the change takes effect.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import winreg
from ctypes import wintypes
from pathlib import Path

from . import CLSID, fx
from .mics import CAPTURE_KEY, list_microphones, read_fx

BACKUP_KEY = r"SOFTWARE\Soundboard\Apo"  # one subkey per mic, value "Original" = JSON of its old values
DATA_DIR = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Soundboard"  # also the plugin's log
ERROR_FILE = DATA_DIR / "admin-error.txt"
SOURCE_DLL = Path(__file__).resolve().parents[2] / "apo" / "build" / "SoundboardApo.dll"
SOURCE_INSTALL_DIR = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Soundboard"
_VIEW = winreg.KEY_WOW64_64KEY
_REG_KINDS = {"String": winreg.REG_SZ, "MultiString": winreg.REG_MULTI_SZ}
_NO_WINDOW = 0x08000000
_ERROR_CANCELLED = 1223


class AdminError(Exception):
    pass


# --- where the DLL lives --------------------------------------------------------------------
def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def installed_dll() -> Path:
    """Installed app: the DLL ships next to Soundboard.exe. From source: it's copied to Program Files,
    because audiodg (LocalService) can't read a user's folders."""
    if frozen():
        return Path(sys.executable).parent / "SoundboardApo.dll"
    return SOURCE_INSTALL_DIR / "SoundboardApo.dll"


# --- registry -------------------------------------------------------------------------------
def _fx_key(mic_id: str):
    # Admins only get "set value" + "read" on FxProperties, so ask for exactly that.
    return winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"{CAPTURE_KEY}\{mic_id}\FxProperties", 0,
                          winreg.KEY_READ | winreg.KEY_SET_VALUE | _VIEW)


def _write_fx(mic_id: str, old: fx.Values, new: fx.Values) -> None:
    with _fx_key(mic_id) as key:
        for name in fx.TOUCHED:
            if name in new and new.get(name) != old.get(name):
                kind, data = new[name]
                winreg.SetValueEx(key, name, 0, _REG_KINDS[kind], data)
            elif name not in new and name in old:
                winreg.DeleteValue(key, name)


def _load_backup(mic_id: str) -> fx.Values | None:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"{BACKUP_KEY}\{mic_id}", 0, winreg.KEY_READ | _VIEW) as key:
            raw = json.loads(winreg.QueryValueEx(key, "Original")[0] or "{}")
    except (OSError, ValueError):
        return None
    out: fx.Values = {}
    for name, entry in raw.items():
        kind, data = entry["Kind"], entry["Data"]
        out[name] = (kind, list(data) if kind == "MultiString" else (data[0] if isinstance(data, list) else data))
    return out


def _save_backup(mic_id: str, values: fx.Values) -> None:
    raw = {name: {"Kind": kind, "Data": data if isinstance(data, list) else [data]}
           for name, (kind, data) in fx.backup_of(values).items()}
    with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, rf"{BACKUP_KEY}\{mic_id}", 0, winreg.KEY_WRITE | _VIEW) as key:
        winreg.SetValueEx(key, "Original", 0, winreg.REG_SZ, json.dumps(raw))


def _backed_up_mics() -> list[str]:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, BACKUP_KEY, 0, winreg.KEY_READ | _VIEW) as key:
            return [winreg.EnumKey(key, i).lower() for i in range(winreg.QueryInfoKey(key)[0])]
    except OSError:
        return []


def _delete_tree(path: str) -> None:
    try:
        winreg.DeleteKeyEx(winreg.HKEY_LOCAL_MACHINE, path, _VIEW)  # leaf
    except OSError:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_ALL_ACCESS | _VIEW) as key:
                for i in reversed(range(winreg.QueryInfoKey(key)[0])):
                    _delete_tree(rf"{path}\{winreg.EnumKey(key, i)}")
            winreg.DeleteKeyEx(winreg.HKEY_LOCAL_MACHINE, path, _VIEW)
        except OSError:
            pass


def attach(mic_id: str) -> None:
    _fx_key(mic_id).Close()  # raises OSError for mics without effect settings, before we back anything up
    old = read_fx(mic_id)
    if _load_backup(mic_id) is None and not fx.has_plugin(old):  # never back up our own values
        _save_backup(mic_id, old)
    _write_fx(mic_id, old, fx.attached(old))


def detach(mic_id: str) -> None:
    old = read_fx(mic_id)
    _write_fx(mic_id, old, fx.restored(old, _load_backup(mic_id)))
    _delete_tree(rf"{BACKUP_KEY}\{mic_id}")


# --- system steps ---------------------------------------------------------------------------
def _run(args: list[str]) -> int:
    return subprocess.run(args, creationflags=_NO_WINDOW, capture_output=True).returncode


def stop_audio() -> None:
    _run(["net", "stop", "audiosrv", "/y"])


def start_audio() -> None:
    _run(["net", "start", "audiosrv"])


def _prepare_files() -> Path:
    dll = installed_dll()
    if not frozen():
        if not SOURCE_DLL.exists():
            raise AdminError("The plugin isn't built yet: run apo\\build.ps1 first.")
        dll.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SOURCE_DLL, dll)
    if not dll.exists():
        raise AdminError(f"Can't find the plugin at {dll}")
    # A log folder audiodg (LocalService) can write to.
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _run(["icacls", str(DATA_DIR), "/grant", "*S-1-5-19:(OI)(CI)M"])
    return dll


def install(mic_ids: list[str]) -> list[str]:
    """Register the DLL and attach it to these mics (every mic with effect settings if empty)."""
    targets = [m.lower() for m in mic_ids] or [m.id for m in list_microphones()]
    attached = []
    stop_audio()  # audiodg keeps the DLL loaded; replacing it needs audio stopped
    try:
        dll = _prepare_files()
        if _run(["regsvr32", "/s", str(dll)]):
            raise AdminError("Registering the plugin failed (regsvr32)")
        for mic_id in targets:
            try:
                attach(mic_id)
                attached.append(mic_id)
            except OSError:
                pass  # mics without effect settings (some virtual ones) can't take the plugin
    finally:
        start_audio()  # never leave the PC without sound
    if not attached:
        raise AdminError("None of these mics accept audio effects.")
    return attached


def uninstall() -> None:
    for mic_id in _backed_up_mics():
        try:
            detach(mic_id)
        except OSError:
            pass
    for mic in list_microphones():  # anything still listing us without a backup
        if mic.has_plugin:
            try:
                detach(mic.id)
            except OSError:
                pass
    _delete_tree(r"SOFTWARE\Soundboard")
    stop_audio()
    try:
        dll = installed_dll()
        if dll.exists():
            _run(["regsvr32", "/u", "/s", str(dll)])
            if not frozen():
                dll.unlink(missing_ok=True)  # the installed app's uninstaller removes its own files
                try:
                    dll.parent.rmdir()  # only if nothing else is in it
                except OSError:
                    pass
        # In case the DLL was already gone.
        _delete_tree(rf"SOFTWARE\Classes\CLSID\{CLSID}")
        _delete_tree(rf"SOFTWARE\Microsoft\AudioEngine\AudioProcessingObjects\{CLSID}")
    finally:
        start_audio()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="soundboard --admin")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("install").add_argument("mics", nargs="*")
    sub.add_parser("add").add_argument("mic")
    sub.add_parser("uninstall")
    args = parser.parse_args(argv)
    ERROR_FILE.unlink(missing_ok=True)
    try:
        if not ctypes.windll.shell32.IsUserAnAdmin():
            raise AdminError("This needs to run as administrator.")
        if args.command == "install":
            install(args.mics)
        elif args.command == "add":
            install([args.mic])
        else:
            uninstall()
    except Exception as exc:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        ERROR_FILE.write_text(str(exc) or type(exc).__name__, encoding="utf-8")
        return 1
    return 0


# --- the app's side: run a command elevated -------------------------------------------------
class _ShellExecuteInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD), ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE),
    ]


def admin_command(args: list[str]) -> tuple[str, str]:
    """(program, parameters) that run `soundboard --admin <args>` in this install."""
    if frozen():
        return sys.executable, subprocess.list2cmdline(["--admin", *args])
    return sys.executable, subprocess.list2cmdline(["-m", "soundboard", "--admin", *args])


def run_elevated(args: list[str]) -> None:
    """Run an admin command with one Windows permission prompt. Blocks: call it off the UI thread."""
    program, params = admin_command(args)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    info = _ShellExecuteInfo(cbSize=ctypes.sizeof(_ShellExecuteInfo), fMask=0x40 | 0x100,  # NOCLOSEPROCESS | NOASYNC
                             lpVerb="runas", lpFile=program, lpParameters=params,
                             lpDirectory=str(Path(__file__).resolve().parents[2]), nShow=0)
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        if ctypes.get_last_error() == _ERROR_CANCELLED:
            raise AdminError("Cancelled: Windows needs your permission to change the mic.")
        raise AdminError(f"Couldn't start the change (error {ctypes.get_last_error()})")
    try:
        kernel32.WaitForSingleObject(info.hProcess, 0xFFFFFFFF)
        code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
    finally:
        kernel32.CloseHandle(info.hProcess)
    if code.value:
        try:
            reason = ERROR_FILE.read_text(encoding="utf-8").strip()
        except OSError:
            reason = ""
        raise AdminError(reason or f"The change failed (exit code {code.value})")
