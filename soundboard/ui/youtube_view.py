"""Paste a YouTube link, optionally trim it, and add the audio as a sound."""
from __future__ import annotations

from typing import TYPE_CHECKING

import customtkinter as ctk

from ..sources import youtube
from . import theme as t

if TYPE_CHECKING:
    from .app import App


class YouTubeView(ctk.CTkFrame):
    def __init__(self, master, app: "App"):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.busy = False

        form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack(anchor="nw", padx=28, pady=26, fill="x")

        t.label(form, "Add from YouTube", size=22, weight="bold").pack(anchor="w")
        t.label(form, "Paste a video link. Trim it to the part you want, or leave the times empty for the whole thing.",
                color=t.MUTED).pack(anchor="w", pady=(4, 18))

        t.label(form, "Video link", color=t.MUTED, size=13).pack(anchor="w")
        self.url = t.entry(form, "https://www.youtube.com/watch?v=…", width=520)
        self.url.pack(anchor="w", pady=(4, 14))

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

        self.go = t.button(form, "Download and add", self.start, kind="primary", width=180)
        self.go.pack(anchor="w")
        self.progress = ctk.CTkProgressBar(form, width=520, height=6, progress_color=t.AMBER, fg_color=t.RAISED)
        self.status = t.label(form, "", color=t.MUTED, size=13, justify="left", wraplength=520)
        self.status.pack(anchor="w", pady=(12, 0))

        self.url.bind("<Return>", lambda _e: self.start())
        if not youtube.ffmpeg_path():
            self.status.configure(text="ffmpeg isn't installed, so YouTube downloads won't work yet. "
                                       "Install it with: winget install ffmpeg", text_color=t.DANGER)

    def on_show(self) -> None:
        self.url.focus_set()

    def start(self) -> None:
        if self.busy:
            return
        url = self.url.get().strip()
        if not youtube.looks_like_url(url):
            self._say("Paste a full video link, starting with https://", error=True)
            return
        try:
            start = youtube.parse_time(self.start_field.get())
            end = youtube.parse_time(self.end_field.get())
        except ValueError as exc:
            self._say(str(exc), error=True)
            return

        self.busy = True
        self.go.configure(state="disabled", text="Working…")
        self.progress.set(0)
        self.progress.pack(anchor="w", pady=(14, 0), before=self.status)
        self._say("Starting…")
        name = self.name.get().strip()

        def on_progress(frac: float, message: str) -> None:
            self.app.dispatch.call(lambda: (self.progress.set(frac), self._say(message)))

        def work():
            return youtube.download_mp3(url, start, end, on_progress)

        def done(result: youtube.YouTubeResult) -> None:
            self._finish()
            try:
                sound = self.app.library.add_file(result.path, name=name or result.title, origin="youtube", move=True)
            except (ValueError, OSError) as exc:
                self._say(f"Downloaded, but couldn't add it: {exc}", error=True)
                return
            self.app.library_changed()
            self._say(f"Added “{sound.name}” to My sounds.", ok=True)
            for field in (self.url, self.name, self.start_field, self.end_field):
                field.delete(0, "end")

        def failed(exc: Exception) -> None:
            self._finish()
            self._say(_friendly(exc), error=True)

        self.app.dispatch.run_in_background(work, done, failed)

    def _finish(self) -> None:
        self.busy = False
        self.go.configure(state="normal", text="Download and add")
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
