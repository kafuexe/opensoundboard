"""Main window: sidebar (navigation + the two volume faders), content, and the on-air bar."""
from __future__ import annotations

import ctypes
from pathlib import Path

import customtkinter as ctk

from ..audio.engine import AudioEngine
from ..hotkeys import HotkeyManager
from ..library import Library
from ..settings import Settings
from . import drop
from . import theme as t
from .browse_view import BrowseView
from .dispatch import Dispatcher
from .library_view import LibraryView
from .settings_view import SettingsView
from .tray import Tray
from .youtube_view import YouTubeView

ICON = Path(__file__).resolve().parents[1] / "assets" / "icon.ico"

NAV = [("library", "My sounds"), ("browse", "Sound Buttons World"), ("youtube", "YouTube"), ("settings", "Settings")]


class Fader(ctk.CTkFrame):
    """A labelled volume slider with its value."""

    def __init__(self, master, title: str, value: float, on_change, on_release):
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)
        t.label(self, title, size=13, color=t.MUTED).grid(row=0, column=0, sticky="w")
        self.value_label = t.label(self, "", size=13, color=t.TEXT)
        self.value_label.grid(row=0, column=1, sticky="e")
        self.slider = ctk.CTkSlider(self, from_=0, to=1, progress_color=t.TEXT, button_color=t.TEXT,
                                    button_hover_color="#FFFFFF", fg_color=t.RAISED, height=16,
                                    command=lambda v: (self._show(v), on_change(v)))
        self.slider.set(value)
        self.slider.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self.slider.bind("<ButtonRelease-1>", lambda _e: on_release(self.slider.get()))
        self._show(value)

    def _show(self, v: float) -> None:
        self.value_label.configure(text=f"{round(v * 100)}%")


class App(ctk.CTk, drop.WindowMixin):
    def __init__(self):
        t.setup()
        super().__init__()
        self.title("Soundboard")
        self.iconbitmap(str(ICON))  # also stops customtkinter swapping in its own icon
        self.geometry("1080x700")
        self.minsize(820, 520)
        self.configure(fg_color=t.CONSOLE)

        self.settings = Settings.load()
        self.library = Library.load()
        self.dispatch = Dispatcher(self)
        self.engine = AudioEngine(self.settings)
        self.hotkeys = HotkeyManager()
        self.hotkeys.enabled = self.settings.hotkeys_enabled

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)
        self.views = {
            "library": LibraryView(self.content, self),
            "browse": BrowseView(self.content, self),
            "youtube": YouTubeView(self.content, self),
            "settings": SettingsView(self.content, self),
        }
        self._build_on_air_bar()
        self._toast = None
        self._current = ""
        self._last_random: dict[str, str] = {}  # folder -> sound id last picked at random
        # Every big area is a drop target; Windows delivers a drop to the nearest registered ancestor.
        drop.enable(self, [self, self.content, self.sidebar, self.bar, *self.views.values(),
                           self.views["library"].grid_area])

        self.show("library")
        self.library_changed()
        self.tray = Tray(ICON, self.dispatch.call, on_show=self.show_window, on_stop_all=self.engine.stop_all,
                         on_quit=self._quit)
        self._told_about_tray = False
        self.protocol("WM_DELETE_WINDOW", self._close_clicked)
        self.bind("<Unmap>", self._on_unmap)
        self.after(80, self._tick)

    # --- layout ----------------------------------------------------------------------------
    def _build_sidebar(self) -> None:
        side = self.sidebar = ctk.CTkFrame(self, fg_color=t.PANEL, corner_radius=0, width=236)
        side.grid(row=0, column=0, sticky="nsw")
        side.grid_propagate(False)
        side.grid_columnconfigure(0, weight=1)
        side.grid_rowconfigure(5, weight=1)

        t.label(side, "Soundboard", size=22, weight="bold").grid(row=0, column=0, sticky="w", padx=20, pady=(22, 18))
        self.nav_buttons = {}
        for i, (key, text) in enumerate(NAV, start=1):
            btn = ctk.CTkButton(side, text=text, anchor="w", height=36, corner_radius=8, font=t.font(14),
                                fg_color="transparent", hover_color=t.RAISED, text_color=t.MUTED,
                                command=lambda k=key: self.show(k))
            btn.grid(row=i, column=0, sticky="ew", padx=12, pady=1)
            self.nav_buttons[key] = btn

        mix = ctk.CTkFrame(side, fg_color="transparent")
        mix.grid(row=6, column=0, sticky="ew", padx=20, pady=(0, 20))
        mix.grid_columnconfigure(0, weight=1)
        self.mic_fader = Fader(mix, "Into my mic", self.settings.mic_volume,
                               lambda v: self.engine.set_volumes(mic=v), lambda v: self.update_settings(mic_volume=round(v, 2)))
        self.mic_fader.grid(row=0, column=0, sticky="ew")
        self.mic_status = t.label(mix, "", size=12, color=t.MUTED, justify="left", wraplength=196, anchor="w")
        self.mic_status.grid(row=1, column=0, sticky="w", pady=(2, 12))
        self.monitor_fader = Fader(mix, "In my headphones", self.settings.monitor_volume,
                                   lambda v: self.engine.set_volumes(monitor=v),
                                   lambda v: self.update_settings(monitor_volume=round(v, 2)))
        self.monitor_fader.grid(row=2, column=0, sticky="ew")
        self.monitor_status = t.label(mix, "", size=12, color=t.DANGER, justify="left", wraplength=196, anchor="w")
        self.monitor_status.grid(row=3, column=0, sticky="w", pady=(2, 0))

    def _build_on_air_bar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color=t.PANEL, corner_radius=0, height=58)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew")
        bar.grid_propagate(False)
        bar.grid_columnconfigure(2, weight=1)
        bar.grid_rowconfigure(0, weight=1)
        self.bar = bar
        self.lamp = ctk.CTkLabel(bar, text="On air", font=t.font(13, "bold"), corner_radius=6, width=72, height=26,
                                 fg_color=t.RAISED, text_color=t.MUTED)
        self.lamp.grid(row=0, column=0, padx=(20, 14))
        self.now_playing = t.label(bar, "Nothing playing", size=15, color=t.MUTED, anchor="w")
        self.now_playing.grid(row=0, column=1, sticky="w")
        self.bar_progress = ctk.CTkProgressBar(bar, height=4, progress_color=t.AMBER, fg_color=t.RAISED)
        self.bar_progress.set(0)
        self.bar_progress.grid(row=0, column=2, sticky="ew", padx=20)
        self.stop_btn = t.button(bar, "Stop all", self.engine.stop_all, width=120)
        self.stop_btn.grid(row=0, column=3, padx=(0, 20))

    # --- navigation / feedback ---------------------------------------------------------------
    def show(self, key: str) -> None:
        if key == self._current:
            return
        for name, view in self.views.items():
            view.grid_forget()
            self.nav_buttons[name].configure(fg_color="transparent", text_color=t.MUTED)
        self.views[key].grid(row=0, column=0, sticky="nsew")
        self.nav_buttons[key].configure(fg_color=t.RAISED, text_color=t.TEXT)
        self._current = key
        on_show = getattr(self.views[key], "on_show", None)
        if on_show:
            on_show()

    def toast(self, text: str, error: bool = False) -> None:
        if self._toast is not None:
            self._toast.destroy()
        self._toast = ctk.CTkLabel(self, text=text, font=t.font(13), corner_radius=8, height=34, padx=14,
                                   fg_color=t.DANGER if error else t.TEXT, text_color="#FFFFFF" if error else t.CONSOLE)
        self._toast.place(relx=1.0, rely=1.0, x=-20, y=-72, anchor="se")
        toast = self._toast
        self.after(4500 if error else 2600, lambda: toast.winfo_exists() and toast.destroy())

    # --- state changes -----------------------------------------------------------------------
    def play_sound(self, sound_id: str) -> None:
        sound = self.library.get(sound_id)
        if sound is None:
            return
        try:
            self.engine.play(sound.id, sound.path, sound.volume)
        except Exception as exc:
            self.dispatch.call(lambda: self.toast(f"Can't play “{sound.name}”: {exc}", error=True))

    def toggle_sound(self, sound_id: str) -> None:
        """Click behavior: start the sound, or stop it if it's already playing."""
        if sound_id in self.engine.playing():
            self.engine.stop(sound_id)
        else:
            self.play_sound(sound_id)

    def remove_sound(self, sound_id: str) -> None:
        sound = self.library.get(sound_id)
        if sound is None:
            return
        self.engine.stop(sound_id)
        self.engine.cache.forget(sound.path)
        self.library.remove(sound_id)
        self.library_changed()

    def target_folder(self) -> str:
        """Folder for newly added sounds: whichever folder is open in My sounds."""
        return self.views["library"].target_folder()

    def added_message(self, name: str, folder: str) -> str:
        return f"Added “{name}” to {folder}" if folder else f"Added “{name}”"

    def library_changed(self) -> None:
        self.views["library"].render()
        self._bind_hotkeys()

    def update_settings(self, **changes) -> None:
        for key, value in changes.items():
            setattr(self.settings, key, value)
        self.settings.save()
        self.hotkeys.enabled = self.settings.hotkeys_enabled
        self.engine.apply(self.settings)
        if "stop_hotkey" in changes:
            self._bind_hotkeys()
        self._refresh_stop_label()

    def play_random(self, folder: str) -> None:
        """Play a random sound from a folder (never the same one twice in a row)."""
        sound = self.library.random_sound(folder, avoid=self._last_random.get(folder))
        if sound is None:
            self.dispatch.call(lambda: self.toast(f"“{folder}” has no sounds yet", error=True))
            return
        self._last_random[folder] = sound.id
        self.play_sound(sound.id)

    def set_folder_hotkey(self, folder: str, hotkey: str) -> None:
        if hotkey and hotkey == self.settings.stop_hotkey:
            self.update_settings(stop_hotkey="")  # one key, one job
        self.library.set_folder_hotkey(folder, hotkey)
        self.library_changed()

    def _bind_hotkeys(self) -> None:
        bindings = {s.hotkey: (lambda sid=s.id: self.play_sound(sid)) for s in self.library.sounds if s.hotkey}
        for folder, hotkey in self.library.folder_hotkeys.items():
            bindings[hotkey] = lambda f=folder: self.play_random(f)
        if self.settings.stop_hotkey:
            bindings[self.settings.stop_hotkey] = self.engine.stop_all
        failed = self.hotkeys.set_bindings(bindings)
        if failed:
            self.toast(f"Couldn't register {', '.join(failed)}", error=True)
        self._refresh_stop_label()

    def _refresh_stop_label(self) -> None:
        key = self.settings.stop_hotkey
        self.stop_btn.configure(text=f"Stop all  ({t.format_hotkey(key)})" if key else "Stop all",
                                width=170 if key else 120)

    def _tick(self) -> None:
        """Poll playback state ~12x a second to drive the pads and the on-air bar."""
        playing = self.engine.playing()
        self.views["library"].set_live(playing)
        self.views["browse"].tick()
        if playing:
            names = [s.name for s in self.library.sounds if s.id in playing]
            first = next((s for s in self.library.sounds if s.id in playing), None)
            self.lamp.configure(fg_color=t.AMBER, text_color=t.AMBER_INK)
            self.now_playing.configure(text=" + ".join(names) or "Playing", text_color=t.TEXT)
            self.bar_progress.grid()
            self.bar_progress.set((first and self.engine.progress(first.id)) or 0)
        else:
            self.lamp.configure(fg_color=t.RAISED, text_color=t.MUTED)
            self.now_playing.configure(text="Nothing playing", text_color=t.MUTED)
            self.bar_progress.grid_remove()

        status = self.engine.status()
        if status["mic"]:
            waiting = status["mic"].startswith(("connecting", "waiting"))
            text = status["mic"][0].upper() + status["mic"][1:]
            self.mic_status.configure(text=text, text_color=t.MUTED if waiting else t.DANGER)
        else:
            self.mic_status.configure(text="Connected", text_color=t.OK)
        self.monitor_status.configure(text=status["monitor"])
        self.after(80, self._tick)

    # --- window and tray --------------------------------------------------------------------
    def _on_unmap(self, event) -> None:
        if event.widget is self and self.state() == "iconic" and self.settings.minimize_to == "tray":
            self.after_idle(self.hide_to_tray)

    def _close_clicked(self) -> None:
        if self.settings.close_to == "tray":
            self.hide_to_tray()
        else:
            self._quit()

    def hide_to_tray(self) -> None:
        """Hide the window; hotkeys keep working and the tray icon brings it back."""
        self.withdraw()
        self.tray.show()
        if not self._told_about_tray:
            self._told_about_tray = True
            self.tray.notify("Soundboard is still running", "Your hotkeys still work. Click the tray icon to open it.")

    def show_window(self) -> None:
        self.tray.hide()
        self.deiconify()
        self.state("normal")
        self.lift()
        self.focus_force()

    def _quit(self) -> None:
        self.tray.stop()
        self.hotkeys.clear()
        self.engine.shutdown()
        self.destroy()


def main() -> None:
    # Our own taskbar identity, so Windows shows our icon rather than grouping us under Python's.
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Soundboard.App")
    app = App()
    try:
        app.mainloop()
    finally:
        app.tray.stop()  # its thread would otherwise keep the process alive after a crash
