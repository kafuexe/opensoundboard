from pathlib import Path

import pytest

from soundboard.ui import themes
from soundboard.ui.themes import mix, palette_from_css, parse_color

# The example from tweakcn the user pasted (trimmed to the parts we read).
TWEAKCN_SAMPLE = """
@import "tailwindcss";
@custom-variant dark (&:is(.dark *));
:root {
  --background: #f8fafc; --foreground: #1e293b; --card: #ffffff; --primary: #155dfc;
  --primary-foreground: #ffffff; --secondary: #00bc7d; --muted: #e2e8f0; --muted-foreground: #475569;
  --accent: #06b6d4; --destructive: #e7000b; --destructive-foreground: #ffffff; --border: #cbd5e1;
  --sidebar: #fafafa; --font-sans: Inter, ui-sans-serif, sans-serif, system-ui; --radius: 0.625rem;
  --shadow-color: oklch(0 0 0); --shadow-2xs: 0 1px 3px 0px hsl(0 0% 0% / 0.05);
}
.dark {
  --background: #11161f; --foreground: #f4f9ff; --card: #1a2029; --primary: #409cff;
  --primary-foreground: #11161f; --secondary: #00c47f; --muted: #232933; --muted-foreground: #95a0ab;
  --accent: #00ced9; --destructive: #cc272e; --destructive-foreground: #f4f9ff; --border: #282828;
  --sidebar: #171717;
}
@theme inline { --color-background: var(--background); --radius-sm: calc(var(--radius) - 4px); }
@layer base { * { @apply border-border outline-ring/50; } body { @apply bg-background text-foreground; } }
"""


@pytest.mark.parametrize("css, expected", [
    ("#abc", "#aabbcc"),
    ("#155DFC", "#155dfc"),
    ("#155dfc80", "#155dfc"),           # alpha dropped
    ("rgb(21, 93, 252)", "#155dfc"),
    ("rgb(21 93 252 / 50%)", "#155dfc"),
    ("hsl(210 40% 98%)", "#f8fafc"),    # shadcn's default --background
    ("hsl(222.2 84% 4.9%)", "#020817"),  # shadcn's default --foreground
    ("oklch(1 0 0)", "#ffffff"),
    ("oklch(0 0 0)", "#000000"),
    ("oklch(62.8% 0.2577 29.23)", "#ff0000"),  # sRGB red
    ("oklch(0.145 0 0)", "#0a0a0a"),    # shadcn v4's default dark background
    ("white", "#ffffff"),
])
def test_parse_color(css, expected):
    assert parse_color(css) == expected


@pytest.mark.parametrize("bad", ["", "blue-ish", "#12", "rgb(1, 2)", "calc(1px + 2px)"])
def test_parse_color_rejects_junk(bad):
    with pytest.raises(ValueError):
        parse_color(bad)


def test_reads_the_tweakcn_sample_in_dark_and_light():
    dark = palette_from_css(TWEAKCN_SAMPLE, "dark")
    assert (dark.console, dark.panel, dark.raised, dark.line) == ("#11161f", "#171717", "#232933", "#282828")
    assert (dark.text, dark.muted, dark.live, dark.live_ink) == ("#f4f9ff", "#95a0ab", "#409cff", "#11161f")
    assert (dark.danger, dark.danger_ink) == ("#cc272e", "#f4f9ff")
    assert dark.font == "Inter" and dark.radius == 10  # .dark has none: falls back to :root
    light = palette_from_css(TWEAKCN_SAMPLE, "light")
    assert (light.console, light.text, light.live) == ("#f8fafc", "#1e293b", "#155dfc")


def test_oklch_theme_and_var_references():
    css = """:root { --background: oklch(1 0 0); --foreground: oklch(0.145 0 0); --muted: oklch(0.97 0 0);
                     --primary: var(--accent-color); --accent-color: oklch(0.6 0.2 30); }
             .dark { --background: oklch(0.145 0 0); --foreground: oklch(0.985 0 0); --muted: var(--background); }"""
    dark = palette_from_css(css, "dark")
    assert dark.console == "#0a0a0a" and dark.raised == "#0a0a0a"  # var() into its own block
    assert dark.live == parse_color("oklch(0.6 0.2 30)")  # var() into :root from .dark


def test_only_root_is_used_for_dark_too():
    p = palette_from_css(":root { --background: #000; --foreground: #fff; --muted: #222; --primary: #f00; }", "dark")
    assert p.console == "#000000" and p.live == "#ff0000"


def test_missing_essentials_is_a_readable_error():
    with pytest.raises(ValueError, match="background"):
        palette_from_css(":root { --foreground: #fff; }", "dark")
    with pytest.raises(ValueError, match=":root"):
        palette_from_css("body { color: red; }", "dark")


def test_built_in_theme_keeps_the_current_look():
    dark = themes.load("soundboard", "dark")
    assert (dark.console, dark.panel, dark.raised, dark.line, dark.text, dark.muted, dark.live, dark.danger, dark.ok) == \
        ("#1b2130", "#232b3b", "#2e3850", "#3a465e", "#e8ebf1", "#8d97aa", "#f2b33d", "#e2604b", "#7fc79a")
    assert themes.load("soundboard", "light").console == "#f3f4f7"


def test_import_copies_a_valid_theme_and_rejects_junk(tmp_path):
    good = tmp_path / "Ocean Blue.css"
    good.write_text(TWEAKCN_SAMPLE, encoding="utf-8")
    assert themes.import_file(good) == "Ocean Blue"
    assert themes.import_file(good) == "Ocean Blue 2"  # never overwrites
    assert themes.load("Ocean Blue", "dark").console == "#11161f"
    bad = tmp_path / "nope.css"
    bad.write_text("body { color: red }", encoding="utf-8")
    with pytest.raises(ValueError):
        themes.import_file(bad)
    assert "nope" not in themes.available()


def test_a_missing_theme_falls_back_to_the_built_in_one():
    assert themes.load("deleted theme", "dark") == themes.load("soundboard", "dark")


def test_mix():
    assert mix("#000000", "#ffffff", 0.5) == "#808080"
