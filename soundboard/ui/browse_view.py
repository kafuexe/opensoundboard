"""Search soundbuttonsworld.com, preview in your headphones, add with one click."""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import customtkinter as ctk

from ..sources.cancel import CancelToken, Cancelled
from ..sources.soundbuttonsworld import Page, RemoteSound, SoundButtonsWorld
from . import theme as t

if TYPE_CHECKING:
    from .app import App


class ResultRow(ctk.CTkFrame):
    def __init__(self, master, view: "BrowseView", sound: RemoteSound):
        super().__init__(master, fg_color=t.PANEL, corner_radius=8, height=48)
        self.view = view
        self.sound = sound
        self.adding: CancelToken | None = None  # set while Add is downloading; the button cancels it
        self.grid_columnconfigure(1, weight=1)

        self.play = ctk.CTkButton(self, text="▶", width=34, height=30, corner_radius=6, fg_color=t.RAISED,
                                  hover_color=t.RAISED_HOVER, text_color=t.TEXT, font=t.font(13),
                                  command=lambda: view.toggle_preview(self))
        self.play.grid(row=0, column=0, padx=(8, 10), pady=8)
        t.label(self, sound.name, size=14, anchor="w").grid(row=0, column=1, sticky="w")
        t.label(self, sound.category, size=12, color=t.MUTED).grid(row=0, column=2, padx=12)
        self.add = t.button(self, "Add", lambda: view.add(self), width=86, height=30)
        self.add.grid(row=0, column=3, padx=(0, 8))
        if view.app.library.has_origin("soundbuttonsworld", sound.file_name):
            self.mark_added()

    def mark_added(self) -> None:
        self.add.configure(text="Added", state="disabled", fg_color="transparent", text_color_disabled=t.OK)


class BrowseView(ctk.CTkFrame):
    def __init__(self, master, app: "App"):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.client = SoundButtonsWorld()
        self.cache_dir = Path(tempfile.mkdtemp(prefix="sbw-cache-"))
        self.rows: list[ResultRow] = []
        self.query = ""
        self.feed = "Trending"
        self.page = 0
        self.loaded_once = False
        self._request = 0  # ignore late responses from older searches
        self._preview_request = 0
        self._preview_token: CancelToken | None = None
        self.preview_row: ResultRow | None = None  # the row whose button shows a stop square right now

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=24, pady=(22, 8))
        top.grid_columnconfigure(0, weight=1)
        self.search = t.entry(top, "Search Sound Buttons World")
        self.search.grid(row=0, column=0, sticky="ew")
        self.search.bind("<Return>", lambda _e: self.run_search())
        t.button(top, "Search", self.run_search, kind="primary", width=90).grid(row=0, column=1, padx=(10, 0))

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", padx=24, pady=(0, 8))
        self.feeds = ctk.CTkSegmentedButton(bar, values=["Trending", "New"], command=self.show_feed, font=t.font(13),
                                            fg_color=t.PANEL, selected_color=t.RAISED_HOVER,
                                            selected_hover_color=t.RAISED_HOVER, unselected_color=t.PANEL,
                                            unselected_hover_color=t.RAISED, text_color=t.TEXT)
        self.feeds.set("Trending")
        self.feeds.pack(side="left")
        self.status = t.label(bar, "", color=t.MUTED, size=13)
        self.status.pack(side="left", padx=14)

        self.results = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.results.grid(row=2, column=0, sticky="nsew", padx=(18, 8), pady=(0, 12))
        self.results.grid_columnconfigure(0, weight=1)
        self.more = t.button(self.results, "Load more", self.load_more, width=140)
        self.spinner = t.Spinner(self.results)
        self.after(400, self._prefetch)

    def _prefetch(self) -> None:
        if not self.loaded_once:
            self.loaded_once = True
            self.show_feed("Trending")

    def on_show(self) -> None:
        self._prefetch()
        self.search.focus_set()

    # --- loading ---------------------------------------------------------------------------
    def run_search(self) -> None:
        query = self.search.get().strip()
        if not query:
            self.show_feed(self.feeds.get() or "Trending")
            return
        self.query = query
        self.feeds.set("")
        self._load(reset=True)

    def show_feed(self, feed: str) -> None:
        self.query = ""
        self.feed = feed
        self.feeds.set(feed)
        self._load(reset=True)

    def load_more(self) -> None:
        self._load(reset=False)

    def _load(self, reset: bool) -> None:
        if reset:
            self._reset_preview_row()
            for row in self.rows:
                row.destroy()
            self.rows.clear()
            self.page = 0
        self.more.grid_forget()
        self._request += 1
        request, page, query, feed = self._request, self.page + 1, self.query, self.feed
        if reset:
            self.status.configure(text="")
            caption = "Searching…" if query else f"Loading {feed.lower()} sounds…"
        else:
            caption = "Loading more…"
        self.spinner.grid(row=len(self.rows), column=0, pady=14)
        self.spinner.start(caption)

        def work() -> Page:
            if query:
                return self.client.search(query, page)
            return self.client.trending(page) if feed == "Trending" else self.client.newest(page)

        def done(result: Page) -> None:
            if request != self._request:
                return
            self._hide_spinner()
            self.page = result.page
            for sound in result.sounds:
                row = ResultRow(self.results, self, sound)
                row.grid(row=len(self.rows), column=0, sticky="ew", padx=4, pady=3)
                self.rows.append(row)
            if not self.rows:
                self.status.configure(text=f"No sounds found for “{query}”. Try a shorter search." if query else "Nothing here right now.")
            elif result.total is not None:
                self.status.configure(text=f"{result.total:,} results for “{query}”" if query else "")
            else:
                self.status.configure(text="")
            if result.has_more:
                self.more.grid(row=len(self.rows), column=0, pady=10)

        def failed(exc: Exception) -> None:
            if request == self._request:
                self._hide_spinner()
                self.status.configure(text="Can't reach soundbuttonsworld.com. Check your connection and try again.",
                                      text_color=t.DANGER)
                if self.rows:  # let them retry the page that failed
                    self.more.grid(row=len(self.rows), column=0, pady=10)

        self.app.dispatch.run_in_background(work, done, failed)

    def _hide_spinner(self) -> None:
        self.spinner.stop()
        self.spinner.grid_forget()
        self.status.configure(text_color=t.MUTED)

    # --- row actions -----------------------------------------------------------------------
    def toggle_preview(self, row: ResultRow) -> None:
        """Play plays the sound in your headphones; stop (the square) stops it."""
        if row is self.preview_row:
            self.app.engine.stop_preview()
            self._reset_preview_row()
            return
        self.app.engine.stop_preview()
        self._reset_preview_row()
        self.preview_row = row
        row.play.configure(text="…")
        self._preview_request += 1
        request = self._preview_request
        token = self._preview_token = CancelToken()

        def work() -> Path:
            path = self.client.download(row.sound, self.cache_dir, cancel=token)
            if request == self._preview_request:  # still the one they asked for
                self.app.engine.preview(path)
            return path

        def done(_path) -> None:
            if request == self._preview_request and row.winfo_exists():
                row.play.configure(text="■")

        def failed(exc: Exception) -> None:
            if request == self._preview_request:
                self._reset_preview_row()
            if not isinstance(exc, Cancelled):
                self.app.toast(f"Couldn't play “{row.sound.name}”: {exc}", error=True)

        self.app.dispatch.run_in_background(work, done, failed)

    def _reset_preview_row(self) -> None:
        if self._preview_token is not None:
            self._preview_token.cancel()  # stops a preview that's still downloading
            self._preview_token = None
        row, self.preview_row = self.preview_row, None
        self._preview_request += 1
        if row is not None and row.winfo_exists():
            row.play.configure(text="▶")

    def tick(self) -> None:
        """Called by the app's poll: flip the stop square back to play when a preview ends on its own."""
        row = self.preview_row
        if (row is not None and row.winfo_exists() and row.play.cget("text") == "■"
                and not self.app.engine.previewing()):
            self._reset_preview_row()

    def add(self, row: ResultRow) -> None:
        """Add downloads the sound into the library; while it's downloading the button cancels."""
        if row.adding is not None:
            row.adding.cancel()
            return
        token = row.adding = CancelToken()
        row.add.configure(text="Cancel", fg_color="transparent", text_color=t.DANGER, hover_color=t.DANGER_HOVER)
        folder = self.app.target_folder()

        def reset_button() -> None:
            row.adding = None
            if row.winfo_exists():
                row.add.configure(text="Add", state="normal", fg_color=t.RAISED, text_color=t.TEXT,
                                  hover_color=t.RAISED_HOVER)

        def work() -> Path:
            return self.client.download(row.sound, self.cache_dir, cancel=token)

        def done(path: Path) -> None:
            reset_button()
            try:
                self.app.library.add_file(path, name=row.sound.name, origin="soundbuttonsworld",
                                         origin_id=row.sound.file_name, folder=folder)
            except (ValueError, OSError) as exc:
                failed(exc)
                return
            self.app.library_changed()
            if row.winfo_exists():
                row.mark_added()
            self.app.toast(self.app.added_message(row.sound.name, folder))

        def failed(exc: Exception) -> None:
            reset_button()
            if isinstance(exc, Cancelled):
                return
            self.app.toast(f"Couldn't add “{row.sound.name}”: {exc}", error=True)

        self.app.dispatch.run_in_background(work, done, failed)
