"""My sounds: a grid of pads. Click a pad to play it; right-click or ⋯ to edit."""
from __future__ import annotations

from pathlib import Path
from tkinter import filedialog
from typing import TYPE_CHECKING

import customtkinter as ctk

from ..library import AUDIO_EXTENSIONS, Sound
from . import theme as t
from .sound_dialog import SoundDialog

if TYPE_CHECKING:
    from .app import App


class Pad(ctk.CTkFrame):
    def __init__(self, master, view: "LibraryView", sound: Sound):
        super().__init__(master, width=t.PAD_W, height=t.PAD_H, fg_color=t.RAISED, corner_radius=10,
                         border_width=2, border_color=t.RAISED)
        self.view = view
        self.sound_id = sound.id
        self.live = False

        # place() keeps every pad exactly PAD_W x PAD_H whatever its contents.
        self.name = ctk.CTkLabel(self, text="", font=t.font(15, "bold"), text_color=t.TEXT,
                                 wraplength=t.PAD_W - 26, justify="left", anchor="nw")
        self.name.place(x=12, y=10)
        self.key = t.keycap(self, "")
        self.more = ctk.CTkButton(self, text="⋯", width=28, height=24, corner_radius=6, fg_color="transparent",
                                  hover_color=t.RAISED_HOVER, text_color=t.MUTED, font=t.font(16),
                                  command=lambda: view.edit(self.sound_id))
        self.more.place(relx=1.0, rely=1.0, x=-8, y=-8, anchor="se")

        for widget in (self, self.name, self.key):
            widget.bind("<Button-1>", lambda _e: view.app.play_sound(self.sound_id))
            widget.bind("<Button-3>", lambda _e: view.edit(self.sound_id))
            widget.bind("<Enter>", lambda _e: self._hover(True))
            widget.bind("<Leave>", lambda _e: self._hover(False))
        self.refresh(sound)

    def refresh(self, sound: Sound) -> None:
        self.name.configure(text=sound.name)
        self.key.destroy()
        self.key = t.keycap(self, sound.hotkey)
        self.key.place(x=10, rely=1.0, y=-10, anchor="sw")
        for event, handler in (("<Button-1>", lambda _e: self.view.app.play_sound(self.sound_id)),
                               ("<Button-3>", lambda _e: self.view.edit(self.sound_id)),
                               ("<Enter>", lambda _e: self._hover(True)),
                               ("<Leave>", lambda _e: self._hover(False))):
            self.key.bind(event, handler)

    def set_live(self, live: bool) -> None:
        if live != self.live:
            self.live = live
            self.configure(border_color=t.AMBER if live else t.RAISED)

    def _hover(self, inside: bool) -> None:
        self.configure(fg_color=t.RAISED_HOVER if inside else t.RAISED)


class LibraryView(ctk.CTkFrame):
    def __init__(self, master, app: "App"):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.pads: dict[str, Pad] = {}
        self._columns = 0

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=24, pady=(22, 12))
        top.grid_columnconfigure(0, weight=1)
        self.search = t.entry(top, "Search your sounds")
        self.search.grid(row=0, column=0, sticky="ew")
        self.search.bind("<KeyRelease>", lambda _e: self.render())
        self.search.bind("<Escape>", lambda _e: (self.search.delete(0, "end"), self.render()))
        t.button(top, "Import audio files", self.import_files, kind="primary").grid(row=0, column=1, padx=(10, 0))

        self.grid_area = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.grid_area.grid(row=1, column=0, sticky="nsew", padx=(18, 8), pady=(0, 12))
        self.grid_area.bind("<Configure>", self._on_resize)

        self.empty = ctk.CTkFrame(self.grid_area, fg_color="transparent")
        t.label(self.empty, "No sounds yet", size=22, weight="bold").pack(anchor="w")
        t.label(self.empty, "Import audio files from your computer, or grab sounds from\n"
                            "Sound Buttons World or a YouTube video.", color=t.MUTED, justify="left").pack(anchor="w", pady=(6, 14))
        row = ctk.CTkFrame(self.empty, fg_color="transparent")
        row.pack(anchor="w")
        t.button(row, "Import audio files", self.import_files, kind="primary").pack(side="left")
        t.button(row, "Browse Sound Buttons World", lambda: app.show("browse")).pack(side="left", padx=8)
        t.button(row, "From YouTube", lambda: app.show("youtube")).pack(side="left")

        self.no_match = t.label(self.grid_area, "", color=t.MUTED)

    # --- rendering -------------------------------------------------------------------------
    def render(self) -> None:
        lib = self.app.library
        visible = lib.search(self.search.get())

        for sound_id in list(self.pads):
            if lib.get(sound_id) is None:
                self.pads.pop(sound_id).destroy()
        for pad in self.pads.values():
            pad.grid_forget()
        self.empty.grid_forget()
        self.no_match.grid_forget()

        if not lib.sounds:
            self.empty.grid(row=0, column=0, sticky="w", padx=6, pady=20)
            return
        if not visible:
            self.no_match.configure(text=f"Nothing matches “{self.search.get().strip()}”.")
            self.no_match.grid(row=0, column=0, sticky="w", padx=6, pady=20)
            return

        cols = max(1, self._columns or 4)
        for i, sound in enumerate(visible):
            pad = self.pads.get(sound.id)
            if pad is None:
                pad = self.pads[sound.id] = Pad(self.grid_area, self, sound)
            else:
                pad.refresh(sound)
            pad.grid(row=i // cols, column=i % cols, padx=t.GAP // 2, pady=t.GAP // 2, sticky="nw")

    def _on_resize(self, event) -> None:
        cols = max(1, (event.width - 10) // (t.PAD_W + t.GAP))
        if cols != self._columns:
            self._columns = cols
            self.render()

    def set_live(self, playing: set[str]) -> None:
        for sound_id, pad in self.pads.items():
            pad.set_live(sound_id in playing)

    # --- actions ---------------------------------------------------------------------------
    def import_files(self) -> None:
        patterns = " ".join(f"*{ext}" for ext in sorted(AUDIO_EXTENSIONS))
        files = filedialog.askopenfilenames(title="Import audio files",
                                            filetypes=[("Audio files", patterns), ("All files", "*.*")])
        added, failed = 0, []
        for name in files:
            try:
                self.app.library.add_file(Path(name))
                added += 1
            except (ValueError, OSError) as exc:
                failed.append(str(exc))
        if added:
            self.app.library_changed()
            self.app.toast(f"Added {added} sound{'s' if added != 1 else ''}")
        if failed:
            self.app.toast(failed[0] if len(failed) == 1 else f"{len(failed)} files couldn't be imported", error=True)

    def edit(self, sound_id: str) -> None:
        sound = self.app.library.get(sound_id)
        if sound:
            SoundDialog(self.app, sound)
