"""Global hotkeys (work while a game or Discord is focused) via the `keyboard` library."""
from __future__ import annotations

import queue
import threading
from typing import Callable

import keyboard


def normalize(hotkey: str) -> str:
    """Canonical form so 'Ctrl+Shift+A' and 'shift+ctrl+a' compare equal."""
    if not hotkey:
        return ""
    return keyboard.get_hotkey_name(hotkey.lower().split("+"))


class HotkeyManager:
    """Owns all registered hotkeys. Callbacks run on a worker thread, never the keyboard hook thread,
    so decoding a sound can't stall your keyboard."""

    def __init__(self):
        self._handles: list = []
        self._jobs: queue.Queue[Callable[[], None]] = queue.Queue()
        self.enabled = True
        threading.Thread(target=self._worker, name="hotkey-actions", daemon=True).start()

    def _worker(self) -> None:
        while True:
            job = self._jobs.get()
            try:
                job()
            except Exception as exc:  # keep the worker alive whatever a callback does
                print(f"hotkey action failed: {exc}")

    def set_bindings(self, bindings: dict[str, Callable[[], None]]) -> list[str]:
        """Replace all hotkeys. Returns hotkeys that couldn't be registered."""
        self.clear()
        failed = []
        for hotkey, action in bindings.items():
            if not hotkey:
                continue
            try:
                handle = keyboard.add_hotkey(hotkey, self._dispatch(action), suppress=False, trigger_on_release=False)
                self._handles.append(handle)
            except (ValueError, KeyError):
                failed.append(hotkey)
        return failed

    def _dispatch(self, action: Callable[[], None]) -> Callable[[], None]:
        def fire() -> None:
            if self.enabled:
                self._jobs.put(action)
        return fire

    def clear(self) -> None:
        for handle in self._handles:
            try:
                keyboard.remove_hotkey(handle)
            except (KeyError, ValueError):
                pass
        self._handles.clear()

    @staticmethod
    def capture(on_done: Callable[[str], None]) -> None:
        """Wait (in a thread) for the user to press a key combo. Esc cancels (returns "")."""
        def run() -> None:
            combo = keyboard.read_hotkey(suppress=False)
            on_done("" if combo == "esc" else normalize(combo))
        threading.Thread(target=run, name="hotkey-capture", daemon=True).start()
