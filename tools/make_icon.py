"""Draws the app icon: a slate tile with a 2x2 grid of pads, one lit amber ("on air") with sound bars.

    .venv\\Scripts\\python tools\\make_icon.py

Writes soundboard/assets/icon.png (256 px, for the window) and icon.ico (16-256 px, for the exe,
the installer and the taskbar). Needs Pillow (requirements-dev.txt).
"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "soundboard" / "assets"
S = 1024  # drawn large, scaled down per size

TILE = "#1B2130"     # theme.CONSOLE
TILE_EDGE = "#3A465E"  # theme.LINE
PAD = "#2E3850"      # theme.RAISED
LIVE = "#F2B33D"     # theme.AMBER
LIVE_INK = "#2A1E05"  # theme.AMBER_INK


def draw(size: int) -> Image.Image:
    # Small sizes get chunkier shapes so they survive downscaling.
    small = size <= 32
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    margin = 40 if small else 56
    d.rounded_rectangle((margin, margin, S - margin, S - margin), radius=200, fill=TILE,
                        outline=TILE_EDGE, width=0 if small else 14)

    inner = 150 if small else 190
    gap = 70 if small else 56
    cell = (S - 2 * inner - gap) // 2
    radius = 70 if small else 64
    for row in range(2):
        for col in range(2):
            x0 = inner + col * (cell + gap)
            y0 = inner + row * (cell + gap)
            live = (row, col) == (0, 0)
            d.rounded_rectangle((x0, y0, x0 + cell, y0 + cell), radius=radius, fill=LIVE if live else PAD)
            if live:
                bars = [0.42, 0.78, 0.56, 0.9] if not small else [0.5, 0.9, 0.65]
                bar_w = cell * (0.13 if not small else 0.18)
                span = cell * 0.7
                step = (span - bar_w) / (len(bars) - 1)
                cx0 = x0 + (cell - span) / 2
                mid = y0 + cell / 2
                for i, h in enumerate(bars):
                    half = cell * 0.62 * h / 2
                    bx = cx0 + i * step
                    d.rounded_rectangle((bx, mid - half, bx + bar_w, mid + half), radius=bar_w / 2, fill=LIVE_INK)
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    frames = [draw(s) for s in sizes]
    frames[-1].save(OUT / "icon.png")
    frames[-1].save(OUT / "icon.ico", sizes=[(s, s) for s in sizes], append_images=frames[:-1])
    # A preview sheet of every size, for checking by eye.
    sheet = Image.new("RGBA", (sum(sizes) + 10 * len(sizes) + 10, 276), "#F4F4F4")
    x = 10
    for s, f in zip(sizes, frames):
        sheet.paste(f, (x, 266 - s), f)
        x += s + 10
    sheet.save(OUT.parent.parent / "tools" / "icon-preview.png")
    print(f"wrote {OUT / 'icon.ico'} and icon.png")


if __name__ == "__main__":
    main()
