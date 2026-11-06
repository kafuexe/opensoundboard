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

        t.label(body, "Folder", color=t.MUTED, size=13).pack(anchor="w")
        self.folder = ctk.CTkOptionMenu(body, values=["Unsorted"] + app.library.folders, width=400, font=t.font(13),
                                        dropdown_font=t.font(13), fg_color=t.RAISED, button_color=t.RAISED_HOVER,
                                        button_hover_color=t.LINE, text_color=t.TEXT, dropdown_fg_color=t.PANEL,
                                        dropdown_hover_color=t.RAISED, dropdown_text_color=t.TEXT,
                                        dynamic_resizing=False)
        self.folder.set(sound.folder or "Unsorted")
        self.folder.pack(anchor="w", pady=(4, 14))

        vol_row = ctk.CTkFrame(body, fg_color="transparent")
        vol_row.pack(anchor="w", fill="x")
        t.label(vol_row, "Volume", color=t.MUTED, size=13).pack(side="left")
        self.vol_text = t.label(vol_row, "", color=t.MUTED, size=13)
        self.vol_text.pack(side="right")
        self.volume = ctk.CTkSlider(body, from_=0, to=1.5, width=400, progress_color=t.TEXT, button_color=t.TEXT,
                                    button_hover_color=t.TEXT_HOVER, fg_color=t.RAISED,
                                    command=lambda v: self.vol_text.configure(text=f"{round(v * 100)}%"))
        self.volume.set(sound.volume)
        self.vol_text.configure(text=f"{round(sound.volume * 100)}%")
        self.volume.pack(anchor="w", pady=(6, 18))

        actions = ctk.CTkFrame(body, fg_color="transparent")
        actions.pack(fill="x")
        t.button(actions, "Delete", self._delete, kind="danger", width=80).pack(side="left")
        t.button(actions, "Save", self._save, kind="primary", width=90).pack(side="right")
        t.button(actions, "Cancel", self.destroy, kind="ghost", width=80).pack(side="right", padx=6)
        self.play_btn = t.button(actions, "▶ Play", lambda: app.toggle_sound(self.sound_id), kind="secondary", width=80)
        self.play_btn.pack(side="right", padx=(0, 6))
        self._sync_play()

        self.bind("<Return>", lambda _e: self._save())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.after(120, self._focus)

    def _sync_play(self) -> None:
        if not self.winfo_exists():
            return
        playing = self.sound_id in self.app.engine.playing()
        self.play_btn.configure(text="■ Stop" if playing else "▶ Play")
        self.after(100, self._sync_play)

    def _focus(self) -> None:
        self.lift()
        self.grab_set()
        self.name.focus_set()

    def _check_conflict(self, combo: str) -> None:
        other = next((s for s in self.app.library.sounds if combo and s.hotkey == combo and s.id != self.sound_id), None)
        folder = next((f for f, k in self.app.library.folder_hotkeys.items() if combo and k == combo), None)
        if combo and combo == self.app.settings.stop_hotkey:
            self.conflict.configure(text="That's your Stop all key. Saving moves it to this sound.", text_color=t.AMBER)
        elif other:
            self.conflict.configure(text=f"“{other.name}” uses this key. Saving moves it here.", text_color=t.AMBER)
        elif folder:
            self.conflict.configure(text=f"The “{folder}” folder's random key. Saving moves it here.", text_color=t.AMBER)
        else:
            self.conflict.configure(text="")

    def _save(self) -> None:
        hotkey = self.hotkey.value
        if hotkey and hotkey == self.app.settings.stop_hotkey:
            self.app.settings.stop_hotkey = ""
            self.app.settings.save()
        folder = self.folder.get()
        old_path = self.app.library.get(self.sound_id).path
        sound = self.app.library.update(self.sound_id, name=self.name.get(), hotkey=hotkey, volume=round(self.volume.get(), 2),
                                folder="" if folder == "Unsorted" else folder)
        if sound.path != old_path:  # renaming renames the file too
            self.app.engine.cache.forget(old_path)
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
            self.app.remove_sound(self.sound_id)
            self.destroy()


class FolderHotkeyDialog(ctk.CTkToplevel):
    """Pick the key that plays a random sound from one folder. Changes apply right away."""

    def __init__(self, app: "App", folder: str):
        super().__init__(app)
        self.app = app
        self.folder = folder
        self.title("Random sound key")
        self.configure(fg_color=t.CONSOLE)
        self.resizable(False, False)
        self.transient(app)
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(padx=24, pady=20)
        t.label(body, f"Random sound from “{folder}”", size=17, weight="bold").pack(anchor="w")
        t.label(body, "Press this key anywhere, even in a game, to play one of this folder's sounds\n"
                      "at random. It never picks the same sound twice in a row.",
                color=t.MUTED, justify="left").pack(anchor="w", pady=(4, 14))
        self.field = HotkeyField(body, app, app.library.folder_hotkeys.get(folder, ""), on_change=self._changed)
        self.field.pack(anchor="w")
        self.note = t.label(body, "", color=t.MUTED, size=12)
        self.note.pack(anchor="w", pady=(6, 12))
        t.button(body, "Done", self.destroy, kind="primary", width=90).pack(anchor="e")
        self.bind("<Escape>", lambda _e: self.destroy())
        self.after(100, lambda: (self.lift(), self.grab_set()))

    def _changed(self, combo: str) -> None:
        owner = self.app.library.hotkey_owner(combo) if combo else ""
        if combo and combo == self.app.settings.stop_hotkey:
            owner = "Stop all"
        if owner == f"the “{self.folder}” folder":
            owner = ""
        self.app.set_folder_hotkey(self.folder, combo)
        self.note.configure(text=f"Moved {t.format_hotkey(combo)} here from {owner}." if owner else "",
                            text_color=t.AMBER)


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


class TextPromptDialog(ctk.CTkToplevel):
    """Ask for one line of text. validate(text) returns the value to keep, or raises ValueError with
    a message shown under the field."""

    def __init__(self, master, title: str, field: str, action: str, validate, initial: str = ""):
        super().__init__(master)
        self.result = None
        self.validate = validate
        self.title(title)
        self.configure(fg_color=t.CONSOLE)
        self.resizable(False, False)
        self.transient(master)
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(padx=24, pady=20)
        t.label(body, field, color=t.MUTED, size=13).pack(anchor="w")
        self.entry = t.entry(body, width=320)
        self.entry.insert(0, initial)
        self.entry.pack(anchor="w", pady=(4, 4))
        self.error = t.label(body, "", color=t.DANGER, size=12)
        self.error.pack(anchor="w", pady=(0, 10))
        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill="x")
        t.button(row, action, self._ok, kind="primary", width=90).pack(side="right")
        t.button(row, "Cancel", self.destroy, kind="ghost", width=80).pack(side="right", padx=6)
        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.after(100, self._focus)

    def _focus(self) -> None:
        self.lift()
        self.grab_set()
        self.entry.focus_set()
        self.entry.select_range(0, "end")

    def _ok(self) -> None:
        try:
            self.result = self.validate(self.entry.get())
        except (ValueError, KeyError) as exc:
            self.error.configure(text=str(exc).strip("'\""))
            return
        self.destroy()
