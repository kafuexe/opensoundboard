"""Edit one sound: name, hotkey, volume, delete."""
from __future__ import annotations

from typing import TYPE_CHECKING

import customtkinter as ctk

from ..hotkeys import HotkeyManager
from ..library import Sound
from . import theme as t

if TYPE_CHECKING:
    from .app import App


class HotkeyField(ctk.CTkFrame):
    """A keycap-style button: click it, press a combo, done. Esc cancels."""

    def __init__(self, master, app: "App", value: str, on_change=None):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.value = value
        self.on_change = on_change
        self.btn = t.button(self, "", self._capture, width=180)
        self.btn.pack(side="left")
        self.clear_btn = t.button(self, "Clear", self._clear, kind="ghost", width=60)
        self.clear_btn.pack(side="left", padx=(6, 0))
        self._show()

    def _show(self) -> None:
        self.btn.configure(text=t.format_hotkey(self.value) if self.value else "Set hotkey", text_color=t.TEXT,
                           fg_color=t.RAISED)
        self.clear_btn.configure(state="normal" if self.value else "disabled")

    def _capture(self) -> None:
        self.btn.configure(text="Press keys… (Esc cancels)", fg_color=t.AMBER, text_color=t.AMBER_INK)
        self.app.hotkeys.enabled = False

        def done(combo: str) -> None:
            def apply() -> None:
                self.app.hotkeys.enabled = self.app.settings.hotkeys_enabled
                if combo:
                    self.value = combo
                    if self.on_change:
                        self.on_change(combo)
                if self.winfo_exists():
                    self._show()
            self.app.dispatch.call(apply)

        HotkeyManager.capture(done)

    def _clear(self) -> None:
        self.value = ""
        if self.on_change:
            self.on_change("")
        self._show()


class SoundDialog(ctk.CTkToplevel):
    def __init__(self, app: "App", sound: Sound):
        super().__init__(app)
        self.app = app
        self.sound_id = sound.id
        self.title("Edit sound")
        self.configure(fg_color=t.CONSOLE)
        self.resizable(False, False)
        self.transient(app)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(padx=24, pady=22, fill="both")

        t.label(body, "Name", color=t.MUTED, size=13).pack(anchor="w")
        self.name = t.entry(body, width=400)
        self.name.insert(0, sound.name)
        self.name.pack(anchor="w", pady=(4, 14))

        t.label(body, "Hotkey", color=t.MUTED, size=13).pack(anchor="w")
        self.hotkey = HotkeyField(body, app, sound.hotkey)
        self.hotkey.pack(anchor="w", pady=(4, 4))
        self.conflict = t.label(body, "", color=t.MUTED, size=12)
        self.conflict.pack(anchor="w", pady=(0, 10))
        self.hotkey.on_change = self._check_conflict

        vol_row = ctk.CTkFrame(body, fg_color="transparent")
        vol_row.pack(anchor="w", fill="x")
        t.label(vol_row, "Volume", color=t.MUTED, size=13).pack(side="left")
        self.vol_text = t.label(vol_row, "", color=t.MUTED, size=13)
        self.vol_text.pack(side="right")
        self.volume = ctk.CTkSlider(body, from_=0, to=1.5, width=400, progress_color=t.TEXT, button_color=t.TEXT,
                                    button_hover_color="#FFFFFF", fg_color=t.RAISED,
                                    command=lambda v: self.vol_text.configure(text=f"{round(v * 100)}%"))
        self.volume.set(sound.volume)
        self.vol_text.configure(text=f"{round(sound.volume * 100)}%")
        self.volume.pack(anchor="w", pady=(6, 18))

        actions = ctk.CTkFrame(body, fg_color="transparent")
        actions.pack(fill="x")
        t.button(actions, "Delete", self._delete, kind="danger", width=80).pack(side="left")
        t.button(actions, "Save", self._save, kind="primary", width=90).pack(side="right")
        t.button(actions, "Cancel", self.destroy, kind="ghost", width=80).pack(side="right", padx=6)
        t.button(actions, "▶ Play", lambda: app.play_sound(self.sound_id), kind="secondary", width=80).pack(side="right", padx=(0, 6))

        self.bind("<Return>", lambda _e: self._save())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.after(120, self._focus)

    def _focus(self) -> None:
        self.lift()
        self.grab_set()
        self.name.focus_set()

    def _check_conflict(self, combo: str) -> None:
        other = next((s for s in self.app.library.sounds if combo and s.hotkey == combo and s.id != self.sound_id), None)
        if combo and combo == self.app.settings.stop_hotkey:
            self.conflict.configure(text="That's your Stop all key. Saving moves it to this sound.", text_color=t.AMBER)
        elif other:
            self.conflict.configure(text=f"“{other.name}” uses this key. Saving moves it here.", text_color=t.AMBER)
        else:
            self.conflict.configure(text="")

    def _save(self) -> None:
        hotkey = self.hotkey.value
        if hotkey and hotkey == self.app.settings.stop_hotkey:
            self.app.settings.stop_hotkey = ""
            self.app.settings.save()
        self.app.library.update(self.sound_id, name=self.name.get(), hotkey=hotkey, volume=round(self.volume.get(), 2))
        self.app.library_changed()
        self.destroy()

    def _delete(self) -> None:
        sound = self.app.library.get(self.sound_id)
        if sound is None:
            self.destroy()
            return
        confirm = ConfirmDialog(self, f"Delete “{sound.name}”?", "The sound file is removed from your library.", "Delete")
        self.wait_window(confirm)
        if confirm.confirmed:
            self.app.engine.stop(self.sound_id)
            self.app.engine.cache.forget(sound.path)
            self.app.library.remove(self.sound_id)
            self.app.library_changed()
            self.destroy()


class ConfirmDialog(ctk.CTkToplevel):
    def __init__(self, master, title: str, detail: str, action: str):
        super().__init__(master)
        self.confirmed = False
        self.title(action)
        self.configure(fg_color=t.CONSOLE)
        self.resizable(False, False)
        self.transient(master)
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(padx=24, pady=20)
        t.label(body, title, size=17, weight="bold").pack(anchor="w")
        t.label(body, detail, color=t.MUTED).pack(anchor="w", pady=(4, 16))
        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill="x")
        t.button(row, action, self._yes, kind="danger", width=90).pack(side="right")
        t.button(row, "Cancel", self.destroy, kind="ghost", width=80).pack(side="right", padx=6)
        self.bind("<Escape>", lambda _e: self.destroy())
        self.after(100, lambda: (self.lift(), self.grab_set()))

    def _yes(self) -> None:
        self.confirmed = True
        self.destroy()
