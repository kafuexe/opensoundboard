"""Where sounds go: mic route, headphone device, global keys."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

import customtkinter as ctk

from .. import paths
from ..audio.outputs import list_output_devices
from ..settings import MIC_MODE_DEVICE, MIC_MODE_PLUGIN
from . import theme as t
from .sound_dialog import HotkeyField

if TYPE_CHECKING:
    from .app import App

DEFAULT_DEVICE = "System default"
MODE_LABELS = {MIC_MODE_PLUGIN: "Mic plugin", MIC_MODE_DEVICE: "Output device"}
MODE_HELP = {
    MIC_MODE_PLUGIN: "Mixes sounds straight into your real microphone, so Discord and games hear them "
                     "with no extra setup. Needs the Soundboard mic plugin installed on that mic.",
    MIC_MODE_DEVICE: "Plays the mic share of each sound to an output device you pick, like a virtual "
                     "cable. Use this if the mic plugin isn't installed.",
}


class SettingsView(ctk.CTkFrame):
    def __init__(self, master, app: "App"):
        super().__init__(master, fg_color="transparent")
        self.app = app
        s = app.settings

        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=(22, 8), pady=20)

        t.label(body, "Settings", size=22, weight="bold").pack(anchor="w", padx=6)

        self._section(body, "Into my mic")
        self.mode = ctk.CTkSegmentedButton(body, values=list(MODE_LABELS.values()), command=self._mode_changed,
                                           font=t.font(13), fg_color=t.PANEL, selected_color=t.RAISED_HOVER,
                                           selected_hover_color=t.RAISED_HOVER, unselected_color=t.PANEL,
                                           unselected_hover_color=t.RAISED, text_color=t.TEXT)
        self.mode.set(MODE_LABELS.get(s.mic_mode, MODE_LABELS[MIC_MODE_PLUGIN]))
        self.mode.pack(anchor="w", padx=6)
        self.mode_help = t.label(body, "", color=t.MUTED, size=13, justify="left", wraplength=560)
        self.mode_help.pack(anchor="w", padx=6, pady=(8, 8))
        self.mic_device_row = ctk.CTkFrame(body, fg_color="transparent")
        t.label(self.mic_device_row, "Device", color=t.MUTED, size=13).pack(anchor="w")
        self.mic_device = self._device_menu(self.mic_device_row, s.mic_device, self._mic_device_changed)
        self.mic_device.pack(anchor="w", pady=(4, 0))
        self.mic_device_row.pack(anchor="w", padx=6)

        self._section(body, "In my headphones")
        t.label(body, "Device", color=t.MUTED, size=13).pack(anchor="w", padx=6)
        self.monitor_device = self._device_menu(body, s.monitor_device, self._monitor_device_changed)
        self.monitor_device.pack(anchor="w", padx=6, pady=(4, 0))
        t.button(body, "Refresh device list", self._refresh_devices, kind="ghost", width=150).pack(anchor="w", padx=0, pady=(6, 0))

        self._section(body, "Keys")
        t.label(body, "Stop all sounds", color=t.MUTED, size=13).pack(anchor="w", padx=6)
        self.stop_key = HotkeyField(body, app, s.stop_hotkey, on_change=self._stop_key_changed)
        self.stop_key.pack(anchor="w", padx=6, pady=(4, 12))
        self.hotkeys_on = ctk.CTkCheckBox(body, text="Hotkeys work everywhere, even in games", font=t.font(14),
                                          text_color=t.TEXT, fg_color=t.TEXT, hover_color="#FFFFFF",
                                          checkmark_color=t.CONSOLE, border_color=t.LINE,
                                          command=self._hotkeys_toggled)
        if s.hotkeys_enabled:
            self.hotkeys_on.select()
        self.hotkeys_on.pack(anchor="w", padx=6)

        self._section(body, "Playback")
        self.one_at_a_time = ctk.CTkCheckBox(body, text="Starting a sound stops the one already playing",
                                             font=t.font(14), text_color=t.TEXT, fg_color=t.TEXT,
                                             hover_color="#FFFFFF", checkmark_color=t.CONSOLE, border_color=t.LINE,
                                             command=self._one_at_a_time_toggled)
        if s.one_at_a_time:
            self.one_at_a_time.select()
        self.one_at_a_time.pack(anchor="w", padx=6)

        self._section(body, "Library")
        t.button(body, "Open sounds folder", lambda: os.startfile(paths.sounds_dir()), width=170).pack(anchor="w", padx=6)

        self._update_mode_ui()

    def _section(self, parent, title: str) -> None:
        ctk.CTkFrame(parent, fg_color=t.LINE, height=1).pack(fill="x", padx=6, pady=(22, 14))
        t.label(parent, title, size=16, weight="bold").pack(anchor="w", padx=6, pady=(0, 8))

    def _device_names(self) -> list[str]:
        try:
            return [DEFAULT_DEVICE] + [d.name for d in list_output_devices()]
        except Exception:
            return [DEFAULT_DEVICE]

    def _device_menu(self, parent, current: str, command) -> ctk.CTkOptionMenu:
        names = self._device_names()
        if current and current not in names:
            names.append(current)  # remember a device that's unplugged right now
        menu = ctk.CTkOptionMenu(parent, values=names, command=command, width=420, font=t.font(13),
                                 dropdown_font=t.font(13), fg_color=t.RAISED, button_color=t.RAISED_HOVER,
                                 button_hover_color=t.LINE, text_color=t.TEXT, dropdown_fg_color=t.PANEL,
                                 dropdown_hover_color=t.RAISED, dropdown_text_color=t.TEXT, dynamic_resizing=False)
        menu.set(current or DEFAULT_DEVICE)
        return menu

    def _refresh_devices(self) -> None:
        names = self._device_names()
        for menu in (self.mic_device, self.monitor_device):
            current = menu.get()
            menu.configure(values=names + ([current] if current not in names else []))

    def _update_mode_ui(self) -> None:
        mode = self.app.settings.mic_mode
        self.mode_help.configure(text=MODE_HELP[mode])
        self.mic_device.configure(state="normal" if mode == MIC_MODE_DEVICE else "disabled")

    # --- handlers --------------------------------------------------------------------------
    def _mode_changed(self, label: str) -> None:
        mode = next(k for k, v in MODE_LABELS.items() if v == label)
        self.app.update_settings(mic_mode=mode)
        self._update_mode_ui()

    def _mic_device_changed(self, name: str) -> None:
        self.app.update_settings(mic_device="" if name == DEFAULT_DEVICE else name)

    def _monitor_device_changed(self, name: str) -> None:
        self.app.update_settings(monitor_device="" if name == DEFAULT_DEVICE else name)

    def _stop_key_changed(self, combo: str) -> None:
        if combo:
            for sound in self.app.library.sounds:
                if sound.hotkey == combo:
                    self.app.library.update(sound.id, hotkey="")
                    self.app.toast(f"Moved {t.format_hotkey(combo)} from “{sound.name}” to Stop all")
        self.app.update_settings(stop_hotkey=combo)
        self.app.library_changed()

    def _hotkeys_toggled(self) -> None:
        self.app.update_settings(hotkeys_enabled=bool(self.hotkeys_on.get()))

    def _one_at_a_time_toggled(self) -> None:
        self.app.update_settings(one_at_a_time=bool(self.one_at_a_time.get()))
