"""Drag audio files (or folders of them) from Explorer onto the window to add them."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import customtkinter as ctk

from ..library import AUDIO_EXTENSIONS
from . import theme as t

if TYPE_CHECKING:
    from .app import App

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:  # drag and drop is a nice-to-have; the app works without it
    DND_FILES = TkinterDnD = None

MAX_LISTED = 8

# Mixed into the main window so it can be a drop target too (child widgets get the methods from tkinterdnd2).
WindowMixin = TkinterDnD.DnDWrapper if TkinterDnD is not None else object


def enable(app: "App", targets: list) -> bool:
    """Load tkdnd into the window and register drop targets. Returns False if unavailable."""
    if TkinterDnD is None:
        return False
    try:
        app.TkdndVersion = TkinterDnD._require(app)
    except Exception:
        return False
    overlay = DropOverlay(app)
    for widget in targets:
        widget.drop_target_register(DND_FILES)
        widget.dnd_bind("<<DropEnter>>", overlay.enter)
        widget.dnd_bind("<<DropPosition>>", overlay.enter)
        widget.dnd_bind("<<DropLeave>>", overlay.leave)
        widget.dnd_bind("<<Drop>>", lambda e: overlay.drop(e))
    return True


def split_drop(app, data: str) -> tuple[list[Path], list[Path]]:
    """Turn tkdnd's file list into (audio files, skipped files). Folders are searched recursively."""
    audio, skipped = [], []
    for raw in app.tk.splitlist(data):
        path = Path(raw)
        candidates = sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else [path]
        for p in candidates:
            (audio if p.suffix.lower() in AUDIO_EXTENSIONS else skipped).append(p)
    return audio, skipped


class DropOverlay:
    """A banner shown while files are dragged over the window."""

    def __init__(self, app: "App"):
        self.app = app
        self.banner = ctk.CTkLabel(app, text="", font=t.font(16, "bold"), fg_color=t.TEXT, text_color=t.CONSOLE,
                                   corner_radius=10, height=44, padx=22)
        self._hide_job = None

    def enter(self, event):
        if self._hide_job is not None:
            self.app.after_cancel(self._hide_job)
            self._hide_job = None
        folder = self.app.target_folder()
        self.banner.configure(text=f"Drop to add to {folder}" if folder else "Drop to add to My sounds")
        self.banner.place(relx=0.5, rely=0.5, anchor="center")
        self.banner.lift()
        return event.action

    def leave(self, event):
        # Moving between drop targets fires leave+enter; hide only if no enter follows.
        self._hide_job = self.app.after(80, self._hide)
        return event.action

    def _hide(self) -> None:
        self._hide_job = None
        self.banner.place_forget()

    def drop(self, event):
        self._hide()
        audio, skipped = split_drop(self.app, event.data)
        if not audio:
            self.app.toast("Only audio files can be added (MP3, WAV, OGG, FLAC, M4A…)", error=True)
        else:
            # Open the dialog after the drop finishes so Explorer isn't left waiting on us.
            self.app.after(10, lambda: AddFilesDialog(self.app, audio, skipped))
        return event.action


class AddFilesDialog(ctk.CTkToplevel):
    def __init__(self, app: "App", files: list[Path], skipped: list[Path]):
        super().__init__(app)
        self.app = app
        self.files = files
        count = len(files)
        self.title("Add sounds")
        self.configure(fg_color=t.CONSOLE)
        self.resizable(False, False)
        self.transient(app)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(padx=24, pady=20, fill="both")
        t.label(body, f"Add {count} sound{'s' if count != 1 else ''}?", size=18, weight="bold").pack(anchor="w")

        listing = ctk.CTkFrame(body, fg_color=t.PANEL, corner_radius=8)
        listing.pack(fill="x", pady=(10, 4))
        for path in files[:MAX_LISTED]:
            t.label(listing, path.stem, size=13, anchor="w").pack(anchor="w", padx=12, pady=1)
        if count > MAX_LISTED:
            t.label(listing, f"and {count - MAX_LISTED} more", size=13, color=t.MUTED).pack(anchor="w", padx=12)
        listing.pack_configure(ipady=6)
        if skipped:
            t.label(body, f"Skipping {len(skipped)} file{'s' if len(skipped) != 1 else ''} that "
                          f"{'aren’t' if len(skipped) != 1 else 'isn’t'} audio.", size=12, color=t.MUTED).pack(anchor="w")

        t.label(body, "Folder", color=t.MUTED, size=13).pack(anchor="w", pady=(12, 0))
        self.folder = ctk.CTkOptionMenu(body, values=["Unsorted"] + app.library.folders, width=360, font=t.font(13),
                                        dropdown_font=t.font(13), fg_color=t.RAISED, button_color=t.RAISED_HOVER,
                                        button_hover_color=t.LINE, text_color=t.TEXT, dropdown_fg_color=t.PANEL,
                                        dropdown_hover_color=t.RAISED, dropdown_text_color=t.TEXT,
                                        dynamic_resizing=False)
        self.folder.set(app.target_folder() or "Unsorted")
        self.folder.pack(anchor="w", pady=(4, 18))

        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill="x")
        t.button(row, f"Add {count} sound{'s' if count != 1 else ''}", self._add, kind="primary").pack(side="right")
        t.button(row, "Cancel", self.destroy, kind="ghost", width=80).pack(side="right", padx=6)
        self.bind("<Return>", lambda _e: self._add())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.after(100, self._focus)

    def _focus(self) -> None:
        self.lift()
        self.focus_force()
        self.grab_set()

    def _add(self) -> None:
        choice = self.folder.get()
        folder = "" if choice == "Unsorted" else choice
        added, failed = 0, []
        for path in self.files:
            try:
                self.app.library.add_file(path, folder=folder)
                added += 1
            except (ValueError, OSError) as exc:
                failed.append(str(exc))
        self.destroy()
        if added:
            self.app.library_changed()
            self.app.show("library")
            where = f" to {folder}" if folder else ""
            self.app.toast(f"Added {added} sound{'s' if added != 1 else ''}{where}")
        if failed:
            self.app.toast(failed[0] if len(failed) == 1 else f"{len(failed)} files couldn't be added", error=True)
