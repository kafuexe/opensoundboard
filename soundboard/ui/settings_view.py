"""Where sounds go: mic route, headphone device, global keys."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

import customtkinter as ctk

from .. import paths
from ..micplugin import admin as plugin_admin
from ..micplugin import mics as plugin_mics
from ..audio.outputs import list_output_devices
from ..settings import MIC_MODE_DEVICE, MIC_MODE_PLUGIN
from . import theme as t
from .sound_dialog import HotkeyField

if TYPE_CHECKING:
    from .app import App

DEFAULT_DEVICE = "System default"
MINIMIZE_LABELS = {"taskbar": "Keep it in the taskbar", "tray": "Hide it in the tray"}
CLOSE_LABELS = {"quit": "Quit Soundboard", "tray": "Keep running in the tray"}
NO_MIC = "Pick a microphone"
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
        # One of these two rows shows, depending on the mode.
        self.mic_target = ctk.CTkFrame(body, fg_color="transparent")
        self.mic_target.pack(anchor="w", fill="x", padx=6)

        self.plugin_row = ctk.CTkFrame(self.mic_target, fg_color="transparent")
        t.label(self.plugin_row, "Microphone", color=t.MUTED, size=13).pack(anchor="w")
        picker = ctk.CTkFrame(self.plugin_row, fg_color="transparent")
        picker.pack(anchor="w", pady=(4, 0))
        self.mic_picker = self._menu(picker, [NO_MIC], self._mic_picked)
        self.mic_picker.pack(side="left")
        self.add_plugin = t.button(picker, "Add the plugin to this mic", self._add_plugin, kind="primary", width=200)
        self.plugin_status = t.label(self.plugin_row, "", color=t.MUTED, size=13, justify="left", wraplength=560)
        self.plugin_status.pack(anchor="w", pady=(6, 0))
        self.remove_plugin = t.button(self.plugin_row, "Remove the plugin from every mic", self._remove_plugin,
                                      kind="ghost", width=230)
        self._mics: list[plugin_mics.Microphone] = []
        self._busy = False

        self.mic_device_row = ctk.CTkFrame(self.mic_target, fg_color="transparent")
        t.label(self.mic_device_row, "Device", color=t.MUTED, size=13).pack(anchor="w")
        self.mic_device = self._device_menu(self.mic_device_row, s.mic_device, self._mic_device_changed)
        self.mic_device.pack(anchor="w", pady=(4, 0))

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

        self._section(body, "Window")
        t.label(body, "When I minimize the window", color=t.MUTED, size=13).pack(anchor="w", padx=6)
        self.minimize_to = self._choice(body, MINIMIZE_LABELS, s.minimize_to,
                                        lambda v: self.app.update_settings(minimize_to=v))
        t.label(body, "When I close the window", color=t.MUTED, size=13).pack(anchor="w", padx=6, pady=(12, 0))
        self.close_to = self._choice(body, CLOSE_LABELS, s.close_to, lambda v: self.app.update_settings(close_to=v))
        t.label(body, "In the tray, Soundboard keeps running and your hotkeys keep working. Click its tray "
                      "icon to bring the window back, or right-click it to quit.",
                color=t.MUTED, size=13, justify="left", wraplength=560).pack(anchor="w", padx=6, pady=(8, 0))

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

        self._refresh_mics()
        self._update_mode_ui()

    def _choice(self, parent, labels: dict[str, str], current: str, on_change) -> ctk.CTkSegmentedButton:
        """A row of options; on_change gets the chosen key."""
        button = ctk.CTkSegmentedButton(parent, values=list(labels.values()), font=t.font(13), fg_color=t.PANEL,
                                        selected_color=t.RAISED_HOVER, selected_hover_color=t.RAISED_HOVER,
                                        unselected_color=t.PANEL, unselected_hover_color=t.RAISED, text_color=t.TEXT,
                                        command=lambda label: on_change(next(k for k, v in labels.items() if v == label)))
        button.set(labels.get(current, next(iter(labels.values()))))
        button.pack(anchor="w", padx=6, pady=(4, 0))
        return button

    def _section(self, parent, title: str) -> None:
        ctk.CTkFrame(parent, fg_color=t.LINE, height=1).pack(fill="x", padx=6, pady=(22, 14))
        t.label(parent, title, size=16, weight="bold").pack(anchor="w", padx=6, pady=(0, 8))

    def _device_names(self) -> list[str]:
        try:
            return [DEFAULT_DEVICE] + [d.name for d in list_output_devices()]
        except Exception:
            return [DEFAULT_DEVICE]

    def _menu(self, parent, values: list[str], command) -> ctk.CTkOptionMenu:
        return ctk.CTkOptionMenu(parent, values=values, command=command, width=420, font=t.font(13),
                                 dropdown_font=t.font(13), fg_color=t.RAISED, button_color=t.RAISED_HOVER,
                                 button_hover_color=t.LINE, text_color=t.TEXT, dropdown_fg_color=t.PANEL,
                                 dropdown_hover_color=t.RAISED, dropdown_text_color=t.TEXT, dynamic_resizing=False)

    def _device_menu(self, parent, current: str, command) -> ctk.CTkOptionMenu:
        names = self._device_names()
        if current and current not in names:
            names.append(current)  # remember a device that's unplugged right now
        menu = self._menu(parent, names, command)
        menu.set(current or DEFAULT_DEVICE)
        return menu

    def _refresh_devices(self) -> None:
        names = self._device_names()
        for menu in (self.mic_device, self.monitor_device):
            current = menu.get()
            menu.configure(values=names + ([current] if current not in names else []))
        self._refresh_mics()

    def _update_mode_ui(self) -> None:
        mode = self.app.settings.mic_mode
        self.mode_help.configure(text=MODE_HELP[mode])
        show, hide = (self.mic_device_row, self.plugin_row) if mode == MIC_MODE_DEVICE else (self.plugin_row, self.mic_device_row)
        hide.pack_forget()
        show.pack(anchor="w", fill="x")

    # --- mic plugin --------------------------------------------------------------------------
    def _selected_mic(self) -> plugin_mics.Microphone | None:
        return next((m for m in self._mics if m.id == self.app.engine.mic_plugin.mic_id), None)

    def _refresh_mics(self) -> None:
        """Re-read the mics and which have the plugin, and show the one sounds go into."""
        self._mics = plugin_mics.list_microphones()
        self.mic_picker.configure(values=[m.name for m in self._mics] or [NO_MIC])
        mic = self._selected_mic()
        self.mic_picker.set(mic.name if mic else NO_MIC)
        if mic is None:
            self.add_plugin.pack_forget()
            self._set_plugin_status("Pick the mic you talk into.")
        elif mic.has_plugin:
            self.add_plugin.pack_forget()
            self._set_plugin_status(f"Sounds go into {mic.name}. Switching mics is instant.")
        else:
            self.add_plugin.pack(side="left", padx=(10, 0))
            self._set_plugin_status("The plugin isn't on this mic yet. Adding it asks Windows for permission "
                                    "once, and audio cuts out for a second.")
        if any(m.has_plugin for m in self._mics):
            self.remove_plugin.pack(anchor="w", pady=(10, 0))
        else:
            self.remove_plugin.pack_forget()

    def _set_plugin_status(self, text: str, error: bool = False) -> None:
        self.plugin_status.configure(text=text, text_color=t.DANGER if error else t.MUTED)

    def _set_busy(self, busy: bool, text: str = "") -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        for widget in (self.mic_picker, self.add_plugin, self.remove_plugin):
            widget.configure(state=state)
        if text:
            self._set_plugin_status(text)

    def _mic_picked(self, name: str) -> None:
        mic = next((m for m in self._mics if m.name == name), None)
        if self._busy or mic is None:
            self._refresh_mics()
            return
        self.app.update_settings(plugin_mic=mic.id)  # reconnects to that mic's ring
        self._refresh_mics()

    def _add_plugin(self) -> None:
        mic = self._selected_mic()
        if self._busy or mic is None:
            return
        self._set_busy(True, f"Adding the plugin to {mic.name}… allow the Windows prompt.")
        self.app.dispatch.run_in_background(lambda: plugin_admin.run_elevated(["add", mic.id]),
                                            lambda _: self._plugin_changed(f"Sounds now go into {mic.name}"),
                                            self._plugin_failed)

    def _remove_plugin(self) -> None:
        if self._busy:
            return
        self._set_busy(True, "Removing the plugin… allow the Windows prompt.")
        self.app.dispatch.run_in_background(lambda: plugin_admin.run_elevated(["uninstall"]),
                                            lambda _: self._plugin_changed("Removed the mic plugin from every mic"),
                                            self._plugin_failed)

    def _plugin_changed(self, message: str) -> None:
        self._set_busy(False)
        self.app.engine.reopen_outputs(self.app.settings)  # Windows audio just restarted
        self._refresh_mics()
        self.app.toast(message)

    def _plugin_failed(self, exc: Exception) -> None:
        self._set_busy(False)
        self.app.engine.reopen_outputs(self.app.settings)
        self._refresh_mics()
        self._set_plugin_status(str(exc), error=True)

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
        owner = self.app.library.hotkey_owner(combo) if combo else ""
        if owner:
            for sound in self.app.library.sounds:
                if sound.hotkey == combo:
                    self.app.library.update(sound.id, hotkey="")
            for folder in [f for f, k in self.app.library.folder_hotkeys.items() if k == combo]:
                self.app.library.set_folder_hotkey(folder, "")
            self.app.toast(f"Moved {t.format_hotkey(combo)} from {owner} to Stop all")
        self.app.update_settings(stop_hotkey=combo)
        self.app.library_changed()

    def _hotkeys_toggled(self) -> None:
        self.app.update_settings(hotkeys_enabled=bool(self.hotkeys_on.get()))

    def _one_at_a_time_toggled(self) -> None:
        self.app.update_settings(one_at_a_time=bool(self.one_at_a_time.get()))
