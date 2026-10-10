"""My sounds: folder tabs over a grid of pads. Click a pad to play it (again to stop); right-click for more."""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog
from typing import TYPE_CHECKING

import customtkinter as ctk

from ..library import AUDIO_EXTENSIONS, Sound
from . import theme as t
from .sound_dialog import ConfirmDialog, SoundDialog, TextPromptDialog

if TYPE_CHECKING:
    from .app import App

ALL = None  # folder filter meaning "every sound"
UNSORTED = ""


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
                                  command=lambda: view.open_menu(self.sound_id))
        self.more.place(relx=1.0, rely=1.0, x=-8, y=-8, anchor="se")
        self._wire(self)
        self._wire(self.name)
        self.refresh(sound)

    def _wire(self, widget) -> None:
        widget.bind("<Button-1>", lambda _e: self.view.app.toggle_sound(self.sound_id))
        widget.bind("<Button-3>", lambda e: self.view.open_menu(self.sound_id, e))
        widget.bind("<Enter>", lambda _e: self._hover(True))
        widget.bind("<Leave>", lambda _e: self._hover(False))

    def refresh(self, sound: Sound) -> None:
        self.name.configure(text=sound.name)
        self.key.destroy()
        self.key = t.keycap(self, sound.hotkey)
        self.key.place(x=10, rely=1.0, y=-10, anchor="sw")
        self._wire(self.key)

    def set_live(self, live: bool) -> None:
        if live != self.live:
            self.live = live
            self.configure(border_color=t.AMBER if live else t.RAISED)

    def _hover(self, inside: bool) -> None:
        self.configure(fg_color=t.RAISED_HOVER if inside else t.RAISED)


class FolderTabs(ctk.CTkFrame):
    """All · Unsorted · <folders> · New folder. Right-click a folder to rename or delete it."""

    def __init__(self, master, view: "LibraryView"):
        super().__init__(master, fg_color="transparent", height=36)
        self.view = view
        self.buttons: list[ctk.CTkButton] = []

    def render(self) -> None:
        for b in self.buttons:
            b.destroy()
        self.buttons.clear()
        lib = self.view.app.library
        tabs: list[tuple[str | None, str]] = [(ALL, "All")]
        if lib.folders and lib.folder_count(UNSORTED):
            tabs.append((UNSORTED, "Unsorted"))
        tabs += [(f, f) for f in lib.folders]

        for folder, text in tabs:
            selected = folder == self.view.folder
            count = lib.folder_count(folder)
            btn = ctk.CTkButton(
                self, text=f"{text}  {count}", height=30, width=0, corner_radius=8, font=t.font(13),
                fg_color=t.RAISED_HOVER if selected else "transparent", hover_color=t.RAISED,
                text_color=t.TEXT if selected else t.MUTED, command=lambda f=folder: self.view.select_folder(f),
            )
            if folder:  # real folders only
                btn.bind("<Button-3>", lambda e, f=folder: self.view.open_folder_menu(f, e))
            btn.pack(side="left", padx=(0, 4))
            self.buttons.append(btn)

        new = ctk.CTkButton(self, text="＋ New folder", height=30, width=0, corner_radius=8, font=t.font(13),
                            fg_color="transparent", hover_color=t.RAISED, text_color=t.MUTED,
                            command=self.view.new_folder)
        new.pack(side="left", padx=(6, 0))
        self.buttons.append(new)


class LibraryView(ctk.CTkFrame):
    def __init__(self, master, app: "App"):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.pads: dict[str, Pad] = {}
        self.folder: str | None = ALL
        self._columns = 0

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=24, pady=(22, 10))
        top.grid_columnconfigure(0, weight=1)
        self.search = t.entry(top, "Search your sounds")
        self.search.grid(row=0, column=0, sticky="ew")
        self.search.bind("<KeyRelease>", lambda _e: self.render())
        self.search.bind("<Escape>", lambda _e: (self.search.delete(0, "end"), self.render()))
        t.button(top, "Import audio files", self.import_files, kind="primary").grid(row=0, column=1, padx=(10, 0))

        self.tabs = FolderTabs(self, self)
        self.tabs.grid(row=1, column=0, sticky="ew", padx=24, pady=(0, 6))

        self.grid_area = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.grid_area.grid(row=2, column=0, sticky="nsew", padx=(18, 8), pady=(0, 12))
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

        self.no_match = t.label(self.grid_area, "", color=t.MUTED, justify="left")

    # --- rendering -------------------------------------------------------------------------
    def render(self) -> None:
        lib = self.app.library
        if self.folder and self.folder not in lib.folders:
            self.folder = ALL
        if self.folder == UNSORTED and not lib.folder_count(UNSORTED):
            self.folder = ALL  # its tab is hidden once it's empty
        self.tabs.render()
        query = self.search.get().strip()
        visible = lib.search(query, self.folder)

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
            if query:
                text = f"Nothing matches “{query}” here."
            else:
                text = (f"“{self.folder}” is empty.\nRight-click a sound and choose Move to folder, "
                        "or add new sounds while this folder is open.")
            self.no_match.configure(text=text)
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

    def target_folder(self) -> str:
        """Where newly added sounds go: the open folder, or unsorted."""
        return self.folder or UNSORTED

    # --- folders ---------------------------------------------------------------------------
    def select_folder(self, folder: str | None) -> None:
        self.folder = folder
        self.render()

    def new_folder(self, then_move: str | None = None) -> None:
        dialog = TextPromptDialog(self.app, "New folder", "Folder name", "Create",
                                  validate=self.app.library.add_folder)
        self.wait_window(dialog)
        if dialog.result:
            if then_move:
                self.app.library.update(then_move, folder=dialog.result)
                self.app.library_changed()
            else:
                self.select_folder(dialog.result)

    def rename_folder(self, folder: str) -> None:
        dialog = TextPromptDialog(self.app, "Rename folder", "Folder name", "Rename", initial=folder,
                                  validate=lambda name: self.app.library.rename_folder(folder, name))
        self.wait_window(dialog)
        if dialog.result:
            if self.folder == folder:
                self.folder = dialog.result
            self.render()

    def delete_folder(self, folder: str) -> None:
        count = self.app.library.folder_count(folder)
        detail = (f"Its {count} sound{'s' if count != 1 else ''} move to Unsorted." if count
                  else "It's empty.")
        confirm = ConfirmDialog(self.app, f"Delete the “{folder}” folder?", detail, "Delete folder")
        self.wait_window(confirm)
        if confirm.confirmed:
            self.app.library.delete_folder(folder)
            if self.folder == folder:
                self.folder = ALL
            self.render()

    def open_folder_menu(self, folder: str, event) -> None:
        menu = t.menu(self)
        menu.add_command(label="Rename…", command=lambda: self.rename_folder(folder))
        menu.add_command(label="Delete folder…", command=lambda: self.delete_folder(folder))
        menu.tk_popup(event.x_root, event.y_root)

    # --- sounds ----------------------------------------------------------------------------
    def open_menu(self, sound_id: str, event=None) -> None:
        sound = self.app.library.get(sound_id)
        if sound is None:
            return
        menu = t.menu(self)
        playing = sound_id in self.app.engine.playing()
        menu.add_command(label="Stop" if playing else "Play", command=lambda: self.app.toggle_sound(sound_id))
        menu.add_command(label="Edit…", command=lambda: self.edit(sound_id))

        move = t.menu(menu)
        move.current = tk.StringVar(move, sound.folder)  # kept on the menu so it isn't garbage-collected
        targets = [(UNSORTED, "Unsorted")] + [(f, f) for f in self.app.library.folders]
        for folder, text in targets:
            move.add_radiobutton(label=text, value=folder, variable=move.current,
                                 command=lambda f=folder: self.move_to(sound_id, f))
        move.add_separator()
        move.add_command(label="New folder…", command=lambda: self.new_folder(then_move=sound_id))
        menu.add_cascade(label="Move to folder", menu=move)

        menu.add_separator()
        menu.add_command(label="Delete…", command=lambda: self.delete_sound(sound_id))
        if event is not None:
            x, y = event.x_root, event.y_root
        else:
            pad = self.pads[sound_id]
            x, y = pad.more.winfo_rootx(), pad.more.winfo_rooty() + pad.more.winfo_height()
        menu.tk_popup(x, y)

    def move_to(self, sound_id: str, folder: str) -> None:
        self.app.library.update(sound_id, folder=folder)
        self.app.library_changed()

    def edit(self, sound_id: str) -> None:
        sound = self.app.library.get(sound_id)
        if sound:
            SoundDialog(self.app, sound)

    def delete_sound(self, sound_id: str) -> None:
        sound = self.app.library.get(sound_id)
        if sound is None:
            return
        confirm = ConfirmDialog(self.app, f"Delete “{sound.name}”?", "The sound file is removed from your library.", "Delete")
        self.wait_window(confirm)
        if confirm.confirmed:
            self.app.remove_sound(sound_id)

    def import_files(self) -> None:
        patterns = " ".join(f"*{ext}" for ext in sorted(AUDIO_EXTENSIONS))
        files = filedialog.askopenfilenames(title="Import audio files",
                                            filetypes=[("Audio files", patterns), ("All files", "*.*")])
        folder = self.target_folder()
        added, failed = 0, []
        for name in files:
            try:
                self.app.library.add_file(Path(name), folder=folder)
                added += 1
            except (ValueError, OSError) as exc:
                failed.append(str(exc))
        if added:
            self.app.library_changed()
            where = f" to {folder}" if folder else ""
            self.app.toast(f"Added {added} sound{'s' if added != 1 else ''}{where}")
        if failed:
            self.app.toast(failed[0] if len(failed) == 1 else f"{len(failed)} files couldn't be imported", error=True)
