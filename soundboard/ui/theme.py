"""Design tokens. Slate console surfaces; amber is reserved for 'live' (something is playing).

The values below are the built-in dark theme. setup() replaces them with the chosen theme
(themes.py) before any widget is made, so every view picks the theme up by reading t.<ROLE>.
"""
import tkinter as tk
import tkinter.font as tkfont

import customtkinter as ctk

from .themes import Palette

CONSOLE = "#1B2130"  # window background
PANEL = "#232B3B"  # sidebar, bars
RAISED = "#2E3850"  # pads, inputs
RAISED_HOVER = "#38445F"
LINE = "#3A465E"
TEXT = "#E8EBF1"
TEXT_HOVER = "#FFFFFF"  # hover on text-colored (primary) buttons
MUTED = "#8D97AA"
AMBER = "#F2B33D"  # on air
AMBER_INK = "#2A1E05"  # text on amber
DANGER = "#E2604B"
DANGER_INK = "#FFFFFF"  # text on danger
DANGER_HOVER = "#4A2A2A"
OK = "#7FC79A"
RADIUS = 8

FAMILY = "Bahnschrift"
FAMILY_NARROW = "Bahnschrift SemiCondensed"

PAD_W = 168
PAD_H = 104
GAP = 10


def font(size: int = 14, weight: str = "normal", narrow: bool = False) -> ctk.CTkFont:
    return ctk.CTkFont(family=FAMILY_NARROW if narrow else FAMILY, size=size, weight=weight)


def setup(theme: str = "soundboard", mode: str = "dark") -> None:
    """Load the theme (call before making any widget)."""
    from . import themes
    ctk.set_appearance_mode(mode)
    ctk.set_default_color_theme("dark-blue")
    apply(themes.load(theme, mode))


def apply(p: Palette) -> None:
    global CONSOLE, PANEL, RAISED, RAISED_HOVER, LINE, TEXT, TEXT_HOVER, MUTED, AMBER, AMBER_INK
    global DANGER, DANGER_INK, DANGER_HOVER, OK, RADIUS, FAMILY, FAMILY_NARROW
    CONSOLE, PANEL, RAISED, RAISED_HOVER, LINE = p.console, p.panel, p.raised, p.raised_hover, p.line
    TEXT, TEXT_HOVER, MUTED, AMBER, AMBER_INK = p.text, p.text_hover, p.muted, p.live, p.live_ink
    DANGER, DANGER_INK, DANGER_HOVER, OK, RADIUS = p.danger, p.danger_ink, p.danger_hover, p.ok, p.radius
    if p.font and p.font != FAMILY and _installed(p.font):
        FAMILY = FAMILY_NARROW = p.font


def _installed(family: str) -> bool:
    try:
        return family.lower() in {f.lower() for f in tkfont.families()}
    except (RuntimeError, tk.TclError):  # no Tk root yet
        root = tk.Tk()
        root.withdraw()
        try:
            return family.lower() in {f.lower() for f in tkfont.families(root)}
        finally:
            root.destroy()


def button(master, text: str, command=None, kind: str = "secondary", **kw) -> ctk.CTkButton:
    styles = {
        "primary": dict(fg_color=TEXT, hover_color=TEXT_HOVER, text_color=CONSOLE),
        "secondary": dict(fg_color=RAISED, hover_color=RAISED_HOVER, text_color=TEXT),
        "ghost": dict(fg_color="transparent", hover_color=RAISED, text_color=MUTED),
        "danger": dict(fg_color="transparent", hover_color=DANGER_HOVER, text_color=DANGER, border_width=1, border_color=DANGER),
    }
    opts = dict(corner_radius=RADIUS, height=34, font=font(14))
    opts.update(styles[kind])
    opts.update(kw)
    return ctk.CTkButton(master, text=text, command=command, **opts)


def entry(master, placeholder: str = "", **kw) -> ctk.CTkEntry:
    opts = dict(fg_color=RAISED, border_color=LINE, border_width=1, text_color=TEXT,
                placeholder_text_color=MUTED, corner_radius=RADIUS, height=36, font=font(14))
    opts.update(kw)
    return ctk.CTkEntry(master, placeholder_text=placeholder, **opts)


def label(master, text: str = "", size: int = 14, color: str | None = None, weight: str = "normal", **kw) -> ctk.CTkLabel:
    return ctk.CTkLabel(master, text=text, text_color=color or TEXT, font=font(size, weight), **kw)


def menu(master) -> tk.Menu:
    """A native popup menu in the app's colors."""
    return tk.Menu(master, tearoff=False, bg=PANEL, fg=TEXT, activebackground=RAISED_HOVER,
                   activeforeground=TEXT, selectcolor=TEXT, bd=0, relief="flat", font=(FAMILY, 11))


def keycap(master, hotkey: str) -> ctk.CTkLabel:
    """A hotkey drawn like a key: the pad's identity in the grid."""
    text = format_hotkey(hotkey) if hotkey else "no key"
    return ctk.CTkLabel(
        master, text=text, font=font(11, narrow=True), text_color=TEXT if hotkey else MUTED,
        fg_color=CONSOLE if hotkey else "transparent", corner_radius=5, height=20, padx=6,
    )


def format_hotkey(hotkey: str) -> str:
    return "+".join(part.capitalize() if len(part) > 1 else part.upper() for part in hotkey.split("+"))


class Spinner(ctk.CTkFrame):
    """A rotating arc with an optional caption. Animates only between start() and stop()."""

    SIZE = 18

    def __init__(self, master, text: str = "", bg: str | None = None):
        super().__init__(master, fg_color="transparent")
        self.canvas = tk.Canvas(self, width=self.SIZE, height=self.SIZE, bg=bg or CONSOLE, highlightthickness=0, bd=0)
        self.canvas.pack(side="left")
        self.arc = self.canvas.create_arc(2, 2, self.SIZE - 2, self.SIZE - 2, start=90, extent=270,
                                          style="arc", outline=TEXT, width=2)
        self.caption = label(self, text, size=13, color=MUTED)
        self.caption.pack(side="left", padx=(8, 0))
        self._angle = 90
        self._job = None

    def start(self, text: str | None = None) -> None:
        if text is not None:
            self.caption.configure(text=text)
        if self._job is None:
            self._spin()

    def stop(self) -> None:
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None

    def _spin(self) -> None:
        self._angle = (self._angle - 12) % 360
        self.canvas.itemconfigure(self.arc, start=self._angle)
        self._job = self.after(30, self._spin)

    def destroy(self) -> None:
        self.stop()
        super().destroy()
