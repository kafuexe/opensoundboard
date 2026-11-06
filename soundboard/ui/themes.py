"""Themes from shadcn/ui CSS files, the format tweakcn.com exports.

A theme file has CSS variables in a `:root { }` block (light) and a `.dark { }` block (dark). We read
only the variables we need, in any color syntax tweakcn uses (hex, rgb(), hsl(), oklch(), var()),
and map them onto the app's color roles. Everything else in the file (@import, @theme, @layer) is
ignored, so a file copied straight from tweakcn works.

Built-in themes ship in soundboard/themes/; imported ones are copied to %APPDATA%\\Soundboard\\themes.
"""
from __future__ import annotations

import math
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .. import paths

BUILTIN_DIR = Path(__file__).resolve().parents[1] / "themes"
DEFAULT_THEME = "soundboard"


def user_dir() -> Path:
    path = paths.data_dir() / "themes"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass(frozen=True)
class Palette:
    """The app's color roles (see theme.py)."""
    console: str      # window background            <- --background
    panel: str        # sidebar and bars             <- --sidebar (else --card)
    raised: str       # pads, inputs                 <- --muted
    raised_hover: str  # derived: raised toward the text color
    line: str         # borders                      <- --border
    text: str         #                              <- --foreground
    text_hover: str   # derived: hover on text-colored (primary) buttons
    muted: str        # secondary text               <- --muted-foreground
    live: str         # "on air": something playing  <- --primary
    live_ink: str     # text on live                 <- --primary-foreground
    danger: str       #                              <- --destructive
    danger_ink: str   #                              <- --destructive-foreground
    danger_hover: str  # derived: a faint danger tint
    ok: str           # "connected"                  <- --chart-2 is unreliable, so --success or a green
    font: str | None  # first family of --font-sans, if any
    radius: int       # --radius in px (rem x 16)


# --- colors ---------------------------------------------------------------------------------
_NAMED = {"white": (255, 255, 255), "black": (0, 0, 0), "transparent": (0, 0, 0)}


def _num(token: str, scale: float = 1.0) -> float:
    token = token.strip()
    if token.endswith("%"):
        return float(token[:-1]) / 100 * scale
    if token.endswith("deg"):
        return float(token[:-3])
    return float(token)


def _args(body: str) -> list[str]:
    """'0.5 0.1 200 / 0.5' or '128, 64, 32' -> the color channels (alpha dropped)."""
    body = body.split("/")[0]
    return [p for p in re.split(r"[\s,]+", body.strip()) if p]


def _srgb_gamma(c: float) -> float:
    c = max(0.0, min(1.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def _oklab_to_rgb(L: float, a: float, b: float) -> tuple[int, int, int]:
    l_ = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    r = 4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_
    g = -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_
    bl = -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_
    return tuple(round(_srgb_gamma(x) * 255) for x in (r, g, bl))  # type: ignore[return-value]


def parse_color(value: str) -> str:
    """Any CSS color tweakcn emits -> '#rrggbb'. Raises ValueError otherwise."""
    v = value.strip().lower()
    if v in _NAMED:
        return "#%02x%02x%02x" % _NAMED[v]
    if v.startswith("#"):
        h = v[1:]
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h[:3])
        if len(h) in (6, 8) and re.fullmatch(r"[0-9a-f]+", h):
            return "#" + h[:6]
        raise ValueError(value)
    m = re.fullmatch(r"(rgba?|hsla?|oklch|oklab)\((.*)\)", v)
    if not m:
        raise ValueError(value)
    fn, parts = m.group(1), _args(m.group(2))
    if len(parts) < 3:
        raise ValueError(value)
    if fn.startswith("rgb"):
        rgb = [round(_num(p, 255)) for p in parts[:3]]
    elif fn.startswith("hsl"):
        h, s, l = _num(parts[0]) % 360, _num(parts[1], 1), _num(parts[2], 1)
        if not parts[1].endswith("%") and s > 1:
            s /= 100
        if not parts[2].endswith("%") and l > 1:
            l /= 100
        c = (1 - abs(2 * l - 1)) * s
        x = c * (1 - abs((h / 60) % 2 - 1))
        r, g, b = [(c, x, 0), (x, c, 0), (0, c, x), (0, x, c), (x, 0, c), (c, 0, x)][int(h // 60) % 6]
        rgb = [round((ch + l - c / 2) * 255) for ch in (r, g, b)]
    else:
        L = _num(parts[0], 1)
        if fn == "oklch":
            C, H = _num(parts[1], 0.4), math.radians(_num(parts[2]) if parts[2] != "none" else 0)
            rgb = _oklab_to_rgb(L, C * math.cos(H), C * math.sin(H))
        else:
            rgb = _oklab_to_rgb(L, _num(parts[1], 0.4), _num(parts[2], 0.4))
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(c))) for c in rgb)


def mix(a: str, b: str, amount: float) -> str:
    """a moved `amount` (0..1) of the way to b."""
    ra, rb = [int(a[i:i + 2], 16) for i in (1, 3, 5)], [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * amount) for x, y in zip(ra, rb))


def _is_dark(color: str) -> bool:
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.299 * r + 0.587 * g + 0.114 * b < 128


# --- CSS ------------------------------------------------------------------------------------
def _blocks(css: str) -> dict[str, dict[str, str]]:
    """Top-level ':root' and '.dark' blocks -> {name: value}. Later blocks win, like CSS."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out: dict[str, dict[str, str]] = {":root": {}, ".dark": {}}
    for m in re.finditer(r"(^|[}\s;])(:root|\.dark)\s*\{", css):
        start, depth, i = m.end(), 1, m.end()
        while i < len(css) and depth:
            depth += {"{": 1, "}": -1}.get(css[i], 0)
            i += 1
        for name, value in re.findall(r"--([\w-]+)\s*:\s*([^;]+);", css[start:i - 1]):
            out[m.group(2)][name] = value.strip()
    return out


def _resolve(name: str, own: dict[str, str], fallback: dict[str, str], depth: int = 0) -> str | None:
    value = own.get(name, fallback.get(name))
    if value is None or depth > 10:
        return None
    ref = re.fullmatch(r"var\(\s*--([\w-]+)\s*(?:,\s*(.+))?\)", value)
    if ref:
        return _resolve(ref.group(1), own, fallback, depth + 1) or ref.group(2)
    return value


def palette_from_css(css: str, mode: str = "dark") -> Palette:
    """Raises ValueError if the file has no usable colors."""
    blocks = _blocks(css)
    own = blocks[".dark"] if mode == "dark" and blocks[".dark"] else blocks[":root"]
    if not own:
        raise ValueError("No :root or .dark block with CSS variables in this file")

    def color(*names: str, default: str | None = None) -> str:
        for name in names:
            value = _resolve(name, own, blocks[":root"])
            if value:
                try:
                    return parse_color(value)
                except ValueError:
                    continue
        if default is None:
            raise ValueError(f"The theme has no usable --{names[0]} color")
        return default

    background = color("background")
    text = color("foreground")
    raised = color("muted", "secondary", "card")
    danger = color("destructive", default="#e2604b")
    font = None
    font_value = _resolve("font-sans", own, blocks[":root"])
    if font_value:
        font = font_value.split(",")[0].strip().strip("'\"") or None
    radius = 8
    radius_value = _resolve("radius", own, blocks[":root"])
    if radius_value:
        try:
            radius = round(_num(radius_value.replace("rem", "").replace("px", "")) * (16 if "rem" in radius_value else 1))
        except ValueError:
            pass
    return Palette(
        console=background,
        panel=color("sidebar", "card", default=mix(background, text, 0.04)),
        raised=raised,
        raised_hover=mix(raised, text, 0.06),
        line=color("border", default=mix(background, text, 0.18)),
        text=text,
        text_hover=mix(text, "#ffffff" if _is_dark(background) else "#000000", 0.5),  # away from the background
        muted=color("muted-foreground", default=mix(text, background, 0.4)),
        live=color("primary"),
        live_ink=color("primary-foreground", default=background),
        danger=danger,
        danger_ink=color("destructive-foreground", default="#ffffff"),
        danger_hover=mix(background, danger, 0.18),
        ok=color("success", default="#7fc79a" if _is_dark(background) else "#2f8f57"),
        font=font,
        radius=max(0, min(radius, 20)),
    )


# --- theme files ----------------------------------------------------------------------------
def available() -> dict[str, Path]:
    """Theme name -> file. Imported themes can't hide built-in ones."""
    found = {p.stem: p for p in sorted(user_dir().glob("*.css"))}
    found.update({p.stem: p for p in sorted(BUILTIN_DIR.glob("*.css"))})
    return found


def load(name: str, mode: str) -> Palette:
    """The named theme, falling back to the built-in one if it's missing or broken."""
    path = available().get(name) or available()[DEFAULT_THEME]
    try:
        return palette_from_css(path.read_text(encoding="utf-8"), mode)
    except (OSError, ValueError):
        return palette_from_css((BUILTIN_DIR / f"{DEFAULT_THEME}.css").read_text(encoding="utf-8"), mode)


def import_file(source: Path) -> str:
    """Check a CSS file is a usable theme and copy it in. Returns its theme name."""
    css = Path(source).read_text(encoding="utf-8")
    palette_from_css(css, "dark")  # raises ValueError with a readable message if it isn't
    stem = re.sub(r"[^\w -]+", "", Path(source).stem).strip() or "theme"
    name, n = stem, 1
    while name in available():
        n += 1
        name = f"{stem} {n}"
    shutil.copyfile(source, user_dir() / f"{name}.css")
    return name
