#!/usr/bin/env python3
"""
Generate preset test images for common ink configurations.
Each image creates colour swatches that exercise the relevant ink channels.

Presets:
  4-colour:  CMYK
  6-colour:  CMYK + Light Cyan + Light Magenta
  8-colour:  CMYK + LC + LM + Light Black + Light Light Black
  11-colour: CMYK + LC + LM + LK + LLK + Red + Blue + Matte Black
  12-colour: CMYK + LC + LM + LK + LLK + Red + Blue + Green + Matte Black

Each swatch is a rectangle filled with a colour that forces the printer to fire
that specific ink channel. Gradient strips ensure partial coverage too.
"""

from PIL import Image, ImageDraw, ImageFont
import os
import sys

OUTPUT_DIR = sys.argv[1] if len(sys.argv) > 1 else "/app/presets"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Image dimensions (A4-ish aspect at 150 DPI = 1240x1754, but we keep it small)
WIDTH = 800
SWATCH_HEIGHT = 80
GRADIENT_HEIGHT = 30
PADDING = 12
LABEL_HEIGHT = 20

# Ink channel colours (RGB approximations that force specific ink channels)
CHANNELS = {
    "Cyan":           (0, 174, 239),
    "Magenta":        (236, 0, 140),
    "Yellow":         (255, 242, 0),
    "Black":          (35, 31, 32),
    "Light Cyan":     (119, 210, 243),
    "Light Magenta":  (237, 140, 196),
    "Light Black":    (128, 128, 128),
    "Light Lt Black": (190, 190, 190),
    "Red":            (237, 28, 36),
    "Blue":           (0, 68, 181),
    "Green":          (0, 148, 68),
    "Matte Black":    (60, 55, 50),
}

PRESETS = {
    "4": ["Cyan", "Magenta", "Yellow", "Black"],
    "6": ["Cyan", "Magenta", "Yellow", "Black", "Light Cyan", "Light Magenta"],
    "8": ["Cyan", "Magenta", "Yellow", "Black", "Light Cyan", "Light Magenta",
           "Light Black", "Light Lt Black"],
    "11": ["Cyan", "Magenta", "Yellow", "Black", "Light Cyan", "Light Magenta",
            "Light Black", "Light Lt Black", "Red", "Blue", "Matte Black"],
    "12": ["Cyan", "Magenta", "Yellow", "Black", "Light Cyan", "Light Magenta",
            "Light Black", "Light Lt Black", "Red", "Blue", "Green", "Matte Black"],
}


def draw_gradient(draw, x, y, w, h, colour):
    """Draw a horizontal gradient from white to the given colour."""
    r, g, b = colour
    for i in range(w):
        t = i / max(w - 1, 1)
        cr = int(255 + (r - 255) * t)
        cg = int(255 + (g - 255) * t)
        cb = int(255 + (b - 255) * t)
        draw.line([(x + i, y), (x + i, y + h - 1)], fill=(cr, cg, cb))


def generate_preset(name, channel_names):
    n = len(channel_names)
    row_height = SWATCH_HEIGHT + GRADIENT_HEIGHT + LABEL_HEIGHT + PADDING
    img_height = PADDING + n * row_height + PADDING + 40  # extra for title
    img = Image.new("RGB", (WIDTH, img_height), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Title
    title = f"Print Head Maintenance — {name}-Colour Test"
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
        font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 13)
    except OSError:
        font = ImageFont.load_default()
        font_sm = font

    draw.text((PADDING, PADDING), title, fill=(35, 31, 32), font=font)

    y = PADDING + 36
    swatch_width = WIDTH - 2 * PADDING

    for ch_name in channel_names:
        colour = CHANNELS[ch_name]

        # Label
        draw.text((PADDING, y), ch_name, fill=(80, 80, 80), font=font_sm)
        y += LABEL_HEIGHT

        # Solid swatch
        draw.rectangle(
            [(PADDING, y), (PADDING + swatch_width, y + SWATCH_HEIGHT)],
            fill=colour
        )
        y += SWATCH_HEIGHT + 2

        # Gradient strip
        draw_gradient(draw, PADDING, y, swatch_width, GRADIENT_HEIGHT, colour)
        y += GRADIENT_HEIGHT + PADDING

    # Footer
    draw.text(
        (PADDING, img_height - 28),
        "print-blockage-stopper • Automated maintenance print",
        fill=(160, 160, 160),
        font=font_sm
    )

    out_path = os.path.join(OUTPUT_DIR, f"preset-{name}.png")
    img.save(out_path, "PNG", optimize=True)
    print(f"Generated {out_path} ({img.size[0]}x{img.size[1]})")


if __name__ == "__main__":
    for name, channels in PRESETS.items():
        generate_preset(name, channels)
    print(f"All presets generated in {OUTPUT_DIR}")
