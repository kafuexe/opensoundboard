"""Paste a YouTube link (or search YouTube), optionally trim it, and add the audio as a sound."""
from __future__ import annotations

from typing import TYPE_CHECKING

import customtkinter as ctk

from ..sources import youtube
from ..sources.cancel import CancelToken, Cancelled
from . import theme as t

if TYPE_CHECKING:
    from .app import App


class YouTubeView(ctk.CTkFrame):
    def __init__(self, master, app: "App"):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.busy = False
        self.token: CancelToken | None = None

        form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack(anchor="nw", padx=28, pady=26, fill="x")

        t.label(form, "Add from YouTube", size=22, weight="bold").pack(anchor="w")
        t.label(form, "Paste a video link, or type words to search YouTube. Trim it to the part you want, or leave "
                      "the times empty for the whole thing.", color=t.MUTED, justify="left", wraplength=640).pack(
            anchor="w", pady=(4, 18))

        t.label(form, "Video link or search", color=t.MUTED, size=13).pack(anchor="w")
        link_row = ctk.CTkFrame(form, fg_color="transparent")
        link_row.pack(anchor="w", pady=(4, 14))
        self.url = t.entry(link_row, "https://www.youtube.com/watch?v=…  or  vine boom sound", width=520)
        self.url.pack(side="left")
        self.search_btn = t.button(link_row, "Search", self.search, width=90)
        self.search_btn.pack(side="left", padx=(8, 0))

        t.label(form, "Name", color=t.MUTED, size=13).pack(anchor="w")
        self.name = t.entry(form, "Leave empty to use the video title", width=520)
        self.name.pack(anchor="w", pady=(4, 14))

        times = ctk.CTkFrame(form, fg_color="transparent")
        times.pack(anchor="w", pady=(0, 18))
        for col, (text, attr) in enumerate((("Start", "start_field"), ("End", "end_field"))):
            t.label(times, text, color=t.MUTED, size=13).grid(row=0, column=col, sticky="w", padx=(0, 12))
            field = t.entry(times, "optional", width=110)
            field.grid(row=1, column=col, sticky="w", padx=(0, 12), pady=(4, 0))
            setattr(self, attr, field)

        buttons = ctk.CTkFrame(form, fg_color="transparent")
        buttons.pack(anchor="w")
        self.go = t.button(buttons, "Download and add", self.start, kind="primary", width=180)
        self.go.pack(side="left")
        self.cancel_btn = t.button(buttons, "Cancel", self.cancel, kind="danger", width=90)
        self.progress = ctk.CTkProgressBar(form, width=520, height=6, progress_color=t.AMBER, fg_color=t.RAISED)
        self.status = t.label(form, "", color=t.MUTED, size=13, justify="left", wraplength=520)
        self.status.pack(anchor="w", pady=(12, 0))

        self.results = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._hits: list[ctk.CTkFrame] = []
        self.url.bind("<Return>", lambda _e: self.start() if youtube.looks_like_url(self.url.get()) else self.search())
        if not youtube.ffmpeg_path():
            self.status.configure(text="ffmpeg is missing, so YouTube downloads won't work. Reinstall Soundboard "
                                       "(from source: run installer\build.ps1 or winget install ffmpeg).",
                                  text_color=t.DANGER)

    def on_show(self) -> None:
        self.url.focus_set()

    def start(self) -> None:
        if self.busy:
            return
        url = self.url.get().strip()
        if not youtube.looks_like_url(url):
            if url:
                self.search()
            else:
                self._say("Paste a video link, or type words and press Search.", error=True)
            return
        try:
            start = youtube.parse_time(self.start_field.get())
            end = youtube.parse_time(self.end_field.get())
        except ValueError as exc:
            self._say(str(exc), error=True)
            return

        self.busy = True
        token = self.token = CancelToken()
        self.go.configure(state="disabled", text="Working…")
        self.cancel_btn.configure(state="normal", text="Cancel")
        self.cancel_btn.pack(side="left", padx=(8, 0))
        self.progress.pack(anchor="w", pady=(14, 0), before=self.status)
        trimming = start is not None or end is not None
        if trimming:  # yt-dlp reports no progress while cutting a clip, so show a busy bar instead
            self.progress.configure(mode="indeterminate")
            self.progress.start()
            self._say("Downloading the clip…")
        else:
            self.progress.configure(mode="determinate")
            self.progress.set(0)
            self._say("Starting…")
        name = self.name.get().strip()
        folder = self.app.target_folder()

        def on_progress(frac: float, message: str) -> None:
            def show() -> None:
                if self.token is token and not token.cancelled:
                    if self.progress.cget("mode") == "indeterminate" and frac > 0:
                        self.progress.stop()
                        self.progress.configure(mode="determinate")
                    if self.progress.cget("mode") == "determinate":
                        self.progress.set(frac)
                    self._say(message)
            self.app.dispatch.call(show)

        def work():
            return youtube.download_mp3(url, start, end, on_progress, cancel=token)

        def done(result: youtube.YouTubeResult) -> None:
            self._finish()
            try:
                sound = self.app.library.add_file(result.path, name=name or result.title, origin="youtube", move=True,
                                              folder=folder)
            except (ValueError, OSError) as exc:
                self._say(f"Downloaded, but couldn't add it: {exc}", error=True)
                return
            self.app.library_changed()
            self._say(f"Added “{sound.name}” to {folder or 'My sounds'}.", ok=True)
            for field in (self.url, self.name, self.start_field, self.end_field):
                field.delete(0, "end")

        def failed(exc: Exception) -> None:
            self._finish()
            if isinstance(exc, Cancelled):
                self._say("Download cancelled.")
            else:
                self._say(_friendly(exc), error=True)

        self.app.dispatch.run_in_background(work, done, failed)

    # --- search --------------------------------------------------------------------------------
    def search(self) -> None:
        query = self.url.get().strip()
        if not query or youtube.looks_like_url(query):
            self._say("Type some words to search for, like “vine boom”.", error=True)
            return
        self.search_btn.configure(state="disabled", text="Searching…")
        self._say(f"Searching YouTube for “{query}”…")
        self.app.dispatch.run_in_background(lambda: youtube.search(query), self._show_hits, self._search_failed)

    def _show_hits(self, hits: list[youtube.SearchHit]) -> None:
        self.search_btn.configure(state="normal", text="Search")
        for row in self._hits:
            row.destroy()
        self._hits = []
        self._say(f"{len(hits)} results. Add takes the whole video; Use lets you trim it first."
                  if hits else "Nothing found. Try other words.")
        if not hits:
            self.results.pack_forget()
            return
        self.results.pack(fill="both", expand=True, padx=(28, 16), pady=(0, 16))
        for hit in hits:
            row = ctk.CTkFrame(self.results, fg_color=t.RAISED, corner_radius=t.RADIUS)
            row.pack(fill="x", pady=(0, 6))
            row.grid_columnconfigure(0, weight=1)
            t.label(row, hit.title[:90], size=14, weight="bold", anchor="w").grid(row=0, column=0, sticky="w", padx=14, pady=(8, 0))
            length = f"{int(hit.seconds // 60)}:{int(hit.seconds % 60):02d}" if hit.seconds else "live"
            t.label(row, f"{hit.channel}  ·  {length}", size=12, color=t.MUTED, anchor="w").grid(
                row=1, column=0, sticky="w", padx=14, pady=(0, 8))
            t.button(row, "Use", lambda h=hit: self._use(h), kind="ghost", width=60).grid(row=0, column=1, rowspan=2)
            t.button(row, "Add", lambda h=hit: self._use(h, add=True), width=70).grid(row=0, column=2, rowspan=2, padx=(4, 12))
            self._hits.append(row)

    def _search_failed(self, exc: Exception) -> None:
        self.search_btn.configure(state="normal", text="Search")
        self._say(f"Search failed: {_friendly(exc)}", error=True)

    def _use(self, hit: youtube.SearchHit, add: bool = False) -> None:
        if self.busy:
            self._say("Wait for the current download to finish.", error=True)
            return
        for field, value in ((self.url, hit.url), (self.name, hit.title[:80])):
            field.delete(0, "end")
            field.insert(0, value)
        if add:
            self.start()
        else:
            self._say("Set a start and end if you want part of it, then press Download and add.")
            self.start_field.focus_set()

    def cancel(self) -> None:
        if self.busy and self.token is not None:
            self.token.cancel()
            self.cancel_btn.configure(state="disabled", text="Cancelling…")
            self._say("Cancelling…")

    def _finish(self) -> None:
        self.busy = False
        self.token = None
        self.go.configure(state="normal", text="Download and add")
        self.cancel_btn.pack_forget()
        self.progress.stop()
        self.progress.pack_forget()

    def _say(self, text: str, error: bool = False, ok: bool = False) -> None:
        self.status.configure(text=text, text_color=t.DANGER if error else t.OK if ok else t.MUTED)


def _friendly(exc: Exception) -> str:
    text = str(exc)
    if "Unsupported URL" in text:
        return "That link isn't a video yt-dlp can download. Check the link and try again."
    if "Private video" in text or "Sign in" in text:
        return "That video is private or needs a sign-in, so it can't be downloaded."
    if "unavailable" in text.lower():
        return "That video is unavailable."
    return text.replace("ERROR: ", "")
