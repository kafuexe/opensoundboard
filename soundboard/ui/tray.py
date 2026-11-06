"""The notification-area (tray) icon, shown while the window is hidden in the tray.

pystray runs its own message loop on a background thread; every menu action is handed to the Tk
thread through the app's Dispatcher, because Tk isn't thread-safe.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import pystray
from PIL import Image


class Tray:
    def __init__(self, icon_path: Path, run_on_ui: Callable[[Callable[[], None]], None],
                 on_show: Callable[[], None], on_stop_all: Callable[[], None], on_quit: Callable[[], None]):
        def ui(action: Callable[[], None]):
            return lambda _icon=None, _item=None: run_on_ui(action)

        menu = pystray.Menu(
            pystray.MenuItem("Show Soundboard", ui(on_show), default=True),  # also a left click
            pystray.MenuItem("Stop all sounds", ui(on_stop_all)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", ui(on_quit)),
        )
        self._icon = pystray.Icon("Soundboard", Image.open(icon_path), "Soundboard", menu)
        # pystray's default setup shows the icon; ours keeps it hidden until the window goes to the tray.
        self._icon.run_detached(setup=lambda icon: None)

    def show(self) -> None:
        self._icon.visible = True

    def notify(self, title: str, message: str) -> None:
        try:
            self._icon.notify(message, title)
        except Exception:
            pass  # notifications are a nicety; some Windows setups turn them off

    def hide(self) -> None:
        self._icon.visible = False

    def stop(self) -> None:
        self._icon.visible = False
        self._icon.stop()
