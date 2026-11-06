"""Stream another app's audio (Spotify, a browser, a game) into the mic."""
from __future__ import annotations

from typing import TYPE_CHECKING

import customtkinter as ctk

from ..audio.app_stream import AudioApp, list_apps
from . import theme as t

if TYPE_CHECKING:
    from .app import App


class StreamView(ctk.CTkFrame):
    def __init__(self, master, app: "App"):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.stream = app.engine.app_stream
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=28, pady=(26, 10))
        t.label(head, "Stream an app into your mic", size=22, weight="bold").pack(anchor="w")
        t.label(head, "Send everything an app plays (Spotify, a browser tab, a game) into your mic, so Discord "
                      "hears it too. You keep hearing the app as usual. Your sounds still play on top.",
                color=t.MUTED, justify="left", wraplength=640).pack(anchor="w", pady=(4, 0))

        self.now = ctk.CTkFrame(self, fg_color=t.RAISED, corner_radius=t.RADIUS)
        self.now.grid_columnconfigure(0, weight=1)
        self.now_label = t.label(self.now, "", size=15, weight="bold", anchor="w")
        self.now_label.grid(row=0, column=0, sticky="w", padx=16, pady=(12, 2))
        self.volume_label = t.label(self.now, "", size=12, color=t.MUTED, anchor="w")
        self.volume_label.grid(row=1, column=0, sticky="w", padx=16)
        self.volume = ctk.CTkSlider(self.now, from_=0, to=1, progress_color=t.AMBER, button_color=t.TEXT,
                                    button_hover_color=t.TEXT_HOVER, fg_color=t.CONSOLE, height=16, width=320,
                                    command=self._volume_changed)
        self.volume.set(app.settings.stream_volume)
        self.volume.grid(row=2, column=0, sticky="w", padx=12, pady=(4, 12))
        self.volume.bind("<ButtonRelease-1>", lambda _e: self.app.update_settings(stream_volume=round(self.volume.get(), 2)))
        t.button(self.now, "Stop streaming", self.stop, kind="danger", width=140).grid(row=0, column=1, rowspan=3, padx=16)

        lists = ctk.CTkFrame(self, fg_color="transparent")
        lists.grid(row=2, column=0, sticky="nsew", padx=(28, 16), pady=(10, 16))
        lists.grid_columnconfigure(0, weight=1)
        lists.grid_rowconfigure(1, weight=1)
        top = ctk.CTkFrame(lists, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew")
        t.label(top, "Apps with sound", size=13, color=t.MUTED).pack(side="left")
        t.button(top, "Refresh", self.refresh, kind="ghost", width=80).pack(side="right")
        self.status = t.label(lists, "", size=13, color=t.MUTED, justify="left", wraplength=640, anchor="w")
        self.status.grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.list = ctk.CTkScrollableFrame(lists, fg_color="transparent")
        self.list.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        self._rows: list[ctk.CTkFrame] = []
        self._show_now()

    def on_show(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        self.status.configure(text="Looking for apps…", text_color=t.MUTED)
        self.app.dispatch.run_in_background(list_apps, self._show_apps, self._list_failed)

    def _show_apps(self, apps: list[AudioApp]) -> None:
        for row in self._rows:
            row.destroy()
        self._rows = []
        for audio_app in apps:
            row = ctk.CTkFrame(self.list, fg_color=t.RAISED, corner_radius=t.RADIUS)
            row.pack(fill="x", pady=(0, 6))
            row.grid_columnconfigure(0, weight=1)
            t.label(row, audio_app.name, size=14, weight="bold", anchor="w").grid(row=0, column=0, sticky="w", padx=14, pady=(8, 0))
            note = "Playing now" if audio_app.playing else "Quiet right now"
            t.label(row, f"{note}  ·  {audio_app.exe}", size=12, color=t.AMBER if audio_app.playing else t.MUTED,
                    anchor="w").grid(row=1, column=0, sticky="w", padx=14, pady=(0, 8))
            streaming = self.stream.app is not None and self.stream.app.pid == audio_app.pid
            t.button(row, "Streaming" if streaming else "Stream", lambda a=audio_app: self.start(a),
                     kind="secondary", width=100, state="disabled" if streaming else "normal").grid(
                row=0, column=1, rowspan=2, padx=12)
            self._rows.append(row)
        self.status.configure(text="" if apps else "No app is using sound right now. Start playing something, "
                                                   "then press Refresh.", text_color=t.MUTED)

    def _list_failed(self, exc: Exception) -> None:
        self.status.configure(text=str(exc), text_color=t.DANGER)

    def start(self, audio_app: AudioApp) -> None:
        def ended(reason: str) -> None:
            self.app.dispatch.call(lambda: (self._show_now(), self.app.toast(reason, error=True), self.refresh()))
        try:
            self.stream.set_gain(self.volume.get())
            self.stream.start(audio_app, on_end=ended)
        except (OSError, RuntimeError) as exc:
            self.status.configure(text=f"Couldn't start: {exc}", text_color=t.DANGER)
            return
        self._show_now()
        self.refresh()

    def stop(self) -> None:
        self.stream.stop()
        self._show_now()
        self.refresh()

    def _show_now(self) -> None:
        if self.stream.app is None:
            self.now.grid_forget()
            return
        self.now_label.configure(text=f"Streaming {self.stream.app.name} into your mic")
        self._volume_changed(self.volume.get())
        self.now.grid(row=1, column=0, sticky="ew", padx=28, pady=(6, 0))

    def _volume_changed(self, value: float) -> None:
        self.stream.set_gain(value)
        self.volume_label.configure(text=f"Volume in your mic: {round(value * 100)}%")
