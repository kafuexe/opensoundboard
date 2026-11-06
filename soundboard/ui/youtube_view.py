"""Paste a YouTube link, optionally trim it, and add the audio as a sound."""
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

        buttons = ctk.CTkFrame(form, fg_color="transparent")
        buttons.pack(anchor="w")
        self.go = t.button(buttons, "Download and add", self.start, kind="primary", width=180)
        self.go.pack(side="left")
        self.cancel_btn = t.button(buttons, "Cancel", self.cancel, kind="danger", width=90)
        self.progress = ctk.CTkProgressBar(form, width=520, height=6, progress_color=t.AMBER, fg_color=t.RAISED)
        self.status = t.label(form, "", color=t.MUTED, size=13, justify="left", wraplength=520)
        self.status.pack(anchor="w", pady=(12, 0))

        self.url.bind("<Return>", lambda _e: self.start())
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
            self._say("Paste a full video link, starting with https://", error=True)
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
