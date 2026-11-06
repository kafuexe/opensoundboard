"""Paste a Spotify track, album or playlist link and add its songs (found and downloaded via YouTube)."""
from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

import customtkinter as ctk

from ..sources import spotify
from ..sources.cancel import CancelToken, Cancelled
from . import theme as t

if TYPE_CHECKING:
    from .app import App


class _Row:
    def __init__(self, view: "SpotifyView", parent, track: spotify.SpotifyTrack):
        self.track = track
        self.frame = ctk.CTkFrame(parent, fg_color=t.RAISED, corner_radius=t.RADIUS)
        self.frame.pack(fill="x", pady=(0, 6))
        self.frame.grid_columnconfigure(0, weight=1)
        t.label(self.frame, track.title, size=14, weight="bold", anchor="w").grid(row=0, column=0, sticky="w", padx=14, pady=(8, 0))
        mins, secs = divmod(round(track.seconds), 60)
        t.label(self.frame, f"{track.artists}  ·  {mins}:{secs:02d}", size=12, color=t.MUTED, anchor="w").grid(
            row=1, column=0, sticky="w", padx=14, pady=(0, 8))
        self.status = t.label(self.frame, "", size=12, color=t.MUTED)
        self.status.grid(row=0, column=1, rowspan=2, padx=(0, 10))
        self.button = t.button(self.frame, "Add", lambda: view.enqueue(self), width=80)
        self.button.grid(row=0, column=2, rowspan=2, padx=(0, 12))
        self.state = "new"  # new | queued | working | added | failed

    def show(self, state: str, text: str = "", error: bool = False) -> None:
        self.state = state
        self.status.configure(text=text, text_color=t.DANGER if error else t.OK if state == "added" else t.MUTED)
        self.button.configure(state="normal" if state in ("new", "failed") else "disabled",
                              text="Retry" if state == "failed" else "Add")


class SpotifyView(ctk.CTkFrame):
    def __init__(self, master, app: "App"):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.rows: list[_Row] = []
        self.queue: deque[_Row] = deque()
        self.current: _Row | None = None
        self.token: CancelToken | None = None
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=28, pady=(26, 10))
        t.label(head, "Add from Spotify", size=22, weight="bold").pack(anchor="w")
        t.label(head, "Paste a song, album or playlist link. Spotify doesn't allow downloads, so each song is "
                      "found on YouTube by its title, artist and length, and added from there.",
                color=t.MUTED, justify="left", wraplength=640).pack(anchor="w", pady=(4, 14))
        bar = ctk.CTkFrame(head, fg_color="transparent")
        bar.pack(anchor="w", fill="x")
        self.url = t.entry(bar, "https://open.spotify.com/track/…", width=520)
        self.url.pack(side="left")
        self.look_btn = t.button(bar, "Look up", self.look_up, kind="primary", width=100)
        self.look_btn.pack(side="left", padx=(8, 0))
        self.status = t.label(head, "", color=t.MUTED, size=13, justify="left", wraplength=640)
        self.status.pack(anchor="w", pady=(10, 0))
        self.actions = ctk.CTkFrame(head, fg_color="transparent")
        self.add_all = t.button(self.actions, "Add all", self.enqueue_all, width=100)
        self.add_all.pack(side="left")
        self.cancel_btn = t.button(self.actions, "Cancel", self.cancel, kind="danger", width=90)

        self.list = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.list.grid(row=1, column=0, sticky="nsew", padx=(28, 16), pady=(0, 16))
        self.url.bind("<Return>", lambda _e: self.look_up())

    def on_show(self) -> None:
        self.url.focus_set()

    # --- looking a link up -----------------------------------------------------------------
    def look_up(self) -> None:
        url = self.url.get().strip()
        if not spotify.looks_like_spotify(url):
            self._say("Paste a Spotify song, album or playlist link (Share > Copy link in Spotify).", error=True)
            return
        if self.current is not None:
            self._say("Wait for the songs being added to finish, or cancel them first.", error=True)
            return
        self.look_btn.configure(state="disabled", text="Looking…")
        self._say("Reading the link…")
        self.app.dispatch.run_in_background(lambda: spotify.fetch(url), self._show_link, self._lookup_failed)

    def _show_link(self, link: spotify.SpotifyLink) -> None:
        self.look_btn.configure(state="normal", text="Look up")
        for row in self.rows:
            row.frame.destroy()
        self.queue.clear()
        self.rows = [_Row(self, self.list, track) for track in link.tracks]
        what = {"track": "Song", "album": "Album", "playlist": "Playlist"}[link.kind]
        count = len(link.tracks)
        self._say(f"{what}: {link.name}" + (f" · {count} songs" if count > 1 else ""))
        if count > 1:
            self.actions.pack(anchor="w", pady=(10, 0))
        else:
            self.actions.pack_forget()

    def _lookup_failed(self, exc: Exception) -> None:
        self.look_btn.configure(state="normal", text="Look up")
        self._say(f"Couldn't read that link: {exc}", error=True)

    # --- adding songs, one at a time -------------------------------------------------------
    def enqueue(self, row: _Row) -> None:
        if row.state in ("queued", "working", "added"):
            return
        row.show("queued", "Waiting…")
        self.queue.append(row)
        self._next()

    def enqueue_all(self) -> None:
        for row in self.rows:
            if row.state in ("new", "failed"):
                self.enqueue(row)

    def cancel(self) -> None:
        for row in self.queue:
            row.show("new")
        self.queue.clear()
        if self.token is not None:
            self.token.cancel()

    def _next(self) -> None:
        if self.current is not None or not self.queue:
            self.cancel_btn.pack_forget() if self.current is None else None
            return
        row = self.current = self.queue.popleft()
        token = self.token = CancelToken()
        folder = self.app.target_folder()
        self.cancel_btn.pack(side="left", padx=(8, 0))
        if not self.actions.winfo_ismapped():
            self.actions.pack(anchor="w", pady=(10, 0))
        row.show("working", "Finding it on YouTube…")

        def on_progress(frac: float, message: str) -> None:
            self.app.dispatch.call(lambda: row.state == "working" and row.show("working", f"{message} {round(frac * 100)}%"
                                                                                  if frac else message))

        def done(result) -> None:
            try:
                sound = self.app.library.add_file(result.path, name=row.track.title, origin="spotify", move=True,
                                                  folder=folder)
                self.app.library_changed()
                row.show("added", f"Added to {folder or 'My sounds'}")
                self.app.toast(self.app.added_message(sound.name, folder))
            except (ValueError, OSError) as exc:
                row.show("failed", f"Couldn't add it: {exc}", error=True)
            self._finished()

        def failed(exc: Exception) -> None:
            if isinstance(exc, Cancelled):
                row.show("new", "Cancelled")
            else:
                row.show("failed", str(exc).replace("ERROR: ", "")[:90], error=True)
            self._finished()

        self.app.dispatch.run_in_background(lambda: spotify.download(row.track, on_progress, token), done, failed)

    def _finished(self) -> None:
        self.current = None
        self.token = None
        if not self.queue:
            self.cancel_btn.pack_forget()
            if len(self.rows) <= 1:
                self.actions.pack_forget()
        self._next()

    def _say(self, text: str, error: bool = False) -> None:
        self.status.configure(text=text, text_color=t.DANGER if error else t.MUTED)
