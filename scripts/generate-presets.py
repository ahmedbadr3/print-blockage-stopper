#!/usr/bin/env python3
"""
Generate ink-efficient maintenance test images for common ink configurations.

Design goals (inspired by Qimage One purge patterns):
  1. Exercise EVERY ink channel — pure colour patches + nozzle check lines
  2. Include blends between adjacent channels to fire nozzle combinations
  3. Use fine staggered lines (nozzle check style) not solid blocks
  4. Keep total ink coverage low — ~10-15% of page vs 40%+ for solid swatches
  5. Distribute colours so no single channel fires continuously

Layout per preset:
  ┌─────────────────────────────────────┐
  │ Title                               │
  ├─────────────────────────────────────┤
  │ NOZZLE CHECK LINES (staggered)      │
  │  Thin horizontal lines per channel  │
  ├─────────────────────────────────────┤
  │ COLOUR PATCHES (small, staggered)   │
  │  Pure + light shade per channel     │
  ├─────────────────────────────────────┤
  │ BLEND STRIPS                        │
  │  Gradients between adjacent inks    │
  ├─────────────────────────────────────┤
  │ Footer                              │
  └─────────────────────────────────────┘

Presets:
  4-colour:  CMYK
  6-colour:  CMYK + Light Cyan + Light Magenta
  8-colour:  CMYK + LC + LM + Light Black + Light Light Black
  11-colour: CMYK + LC + LM + LK + LLK + Red + Blue + Matte Black
  12-colour: CMYK + LC + LM + LK + LLK + Red + Blue + Green + Matte Black
"""

from PIL import Image, ImageDraw, ImageFont
import os
import sys

OUTPUT_DIR = sys.argv[1] if len(sys.argv) > 1 else "/app/presets"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Keep image compact — roughly half a page at 150 DPI
WIDTH = 600
MARGIN = 14

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
    "4":  ["Cyan", "Magenta", "Yellow", "Black"],
    "6":  ["Cyan", "Magenta", "Yellow", "Black", "Light Cyan", "Light Magenta"],
    "8":  ["Cyan", "Magenta", "Yellow", "Black", "Light Cyan", "Light Magenta",
            "Light Black", "Light Lt Black"],
    "11": ["Cyan", "Magenta", "Yellow", "Black", "Light Cyan", "Light Magenta",
            "Light Black", "Light Lt Black", "Red", "Blue", "Matte Black"],
    "12": ["Cyan", "Magenta", "Yellow", "Black", "Light Cyan", "Light Magenta",
            "Light Black", "Light Lt Black", "Red", "Blue", "Green", "Matte Black"],
}


def lighten(colour, factor=0.55):
    """Return a lighter version of the colour (mix towards white)."""
    return tuple(int(c + (255 - c) * factor) for c in colour)


def blend(c1, c2, t):
    """Linearly interpolate between two RGB colours."""
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def stagger_order(channels):
    """Reorder channels so adjacent ones are maximally different.
    Avoids heating the same part of the print head continuously."""
    if len(channels) <= 2:
        return channels
    evens = channels[::2]
    odds = channels[1::2]
    return evens + odds


def draw_nozzle_check(draw, x, y, w, channels, font):
    """Draw fine staggered horizontal lines per channel — nozzle check style.
    Each channel gets 4 thin lines (1px) with 2px gaps, staggered by 1px."""
    section_y = y
    label_w = 18  # short label like "C", "M", etc.
    line_x = x + label_w + 4
    line_w = w - label_w - 4
    num_lines = 4
    line_spacing = 3  # 1px line + 2px gap

    abbrevs = {
        "Cyan": "C", "Magenta": "M", "Yellow": "Y", "Black": "K",
        "Light Cyan": "LC", "Light Magenta": "LM",
        "Light Black": "LK", "Light Lt Black": "LLK",
        "Red": "R", "Blue": "B", "Green": "G", "Matte Black": "MK",
    }

    for i, ch_name in enumerate(channels):
        colour = CHANNELS[ch_name]
        abbr = abbrevs.get(ch_name, ch_name[:2])
        stagger = i % 3  # offset lines by 0-2 px to test different nozzles

        draw.text((x, section_y), abbr, fill=colour, font=font)
        for line_num in range(num_lines):
            ly = section_y + stagger + line_num * line_spacing
            draw.line([(line_x, ly), (line_x + line_w, ly)], fill=colour, width=1)

        section_y += num_lines * line_spacing + 4

    return section_y - y


def draw_colour_patches(draw, x, y, w, channels, font):
    """Draw tiny colour patches — pure + light shade in a compact 3-column grid.
    Each patch is just 6px tall to minimise ink."""
    patch_h = 6
    row_gap = 2
    cols = 3
    col_w = (w - (cols - 1) * 4) // cols
    patch_w = col_w - 30  # room for short label
    section_y = y

    abbrevs = {
        "Cyan": "C", "Magenta": "M", "Yellow": "Y", "Black": "K",
        "Light Cyan": "LC", "Light Magenta": "LM",
        "Light Black": "LK", "Light Lt Black": "LLK",
        "Red": "R", "Blue": "B", "Green": "G", "Matte Black": "MK",
    }

    for i in range(0, len(channels), cols):
        for col in range(cols):
            idx = i + col
            if idx >= len(channels):
                break
            ch_name = channels[idx]
            colour = CHANNELS[ch_name]
            light = lighten(colour)
            cx = x + col * (col_w + 4)

            abbr = abbrevs.get(ch_name, ch_name[:2])
            draw.text((cx, section_y), abbr, fill=(100, 100, 100), font=font)

            px = cx + 30
            half = patch_w // 2
            draw.rectangle([(px, section_y), (px + half - 1, section_y + patch_h)],
                           fill=colour)
            draw.rectangle([(px + half + 1, section_y),
                            (px + patch_w, section_y + patch_h)],
                           fill=light)

        section_y += patch_h + row_gap

    return section_y - y


def draw_blend_strips(draw, x, y, w, channels):
    """Draw thin horizontal gradient strips blending adjacent channels.
    Each strip is 2px tall — just enough to fire both channels at varying ratios."""
    strip_h = 2
    strip_gap = 2
    section_y = y

    # Create pairs of adjacent channels for blending
    pairs = []
    for i in range(len(channels) - 1):
        pairs.append((channels[i], channels[i + 1]))
    # Also blend first and last to close the loop
    if len(channels) > 2:
        pairs.append((channels[-1], channels[0]))

    for ch1_name, ch2_name in pairs:
        c1 = CHANNELS[ch1_name]
        c2 = CHANNELS[ch2_name]
        for px_x in range(w):
            t = px_x / max(w - 1, 1)
            c = blend(c1, c2, t)
            draw.line([(x + px_x, section_y), (x + px_x, section_y + strip_h - 1)], fill=c)
        section_y += strip_h + strip_gap

    return section_y - y


def generate_preset(name, channel_names):
    # Stagger the channel order for nozzle check section
    staggered = stagger_order(channel_names)

    try:
        font_title = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
        font_section = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 10)
        font_sm = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 9)
        font_tiny = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 8)
    except OSError:
        font_title = font_section = font_sm = font_tiny = ImageFont.load_default()

    # Calculate heights for each section
    n = len(channel_names)
    nozzle_h = n * (4 * 3 + 4)  # 4 lines * 3px spacing + 4px gap per channel
    patch_rows = (n + 2) // 3   # 3 columns now
    patch_h = patch_rows * (6 + 2)
    blend_pairs = n  # n-1 adjacent + 1 wraparound (or n-1 if <=2)
    blend_h = blend_pairs * (2 + 2)

    title_h = 28
    section_label_h = 16
    total_h = (MARGIN + title_h
               + section_label_h + nozzle_h + 6
               + section_label_h + patch_h + 6
               + section_label_h + blend_h + 6
               + 20 + MARGIN)

    img = Image.new("RGB", (WIDTH, total_h), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    content_w = WIDTH - 2 * MARGIN
    y = MARGIN

    # Title
    title = f"Maintenance Print — {name}-Colour"
    draw.text((MARGIN, y), title, fill=(35, 31, 32), font=font_title)
    y += title_h

    # Section 1: Nozzle Check Lines
    draw.text((MARGIN, y), "NOZZLE CHECK", fill=(120, 120, 120), font=font_section)
    y += section_label_h
    h = draw_nozzle_check(draw, MARGIN, y, content_w, staggered, font_tiny)
    y += h + 6

    # Section 2: Colour Patches (pure + light)
    draw.text((MARGIN, y), "COLOUR PATCHES", fill=(120, 120, 120), font=font_section)
    y += section_label_h
    h = draw_colour_patches(draw, MARGIN, y, content_w, channel_names, font_tiny)
    y += h + 6

    # Section 3: Blend Strips
    draw.text((MARGIN, y), "CHANNEL BLENDS", fill=(120, 120, 120), font=font_section)
    y += section_label_h
    h = draw_blend_strips(draw, MARGIN, y, content_w, channel_names)
    y += h + 6

    # Footer
    draw.text(
        (MARGIN, total_h - MARGIN - 10),
        "print-blockage-stopper — low-ink maintenance print",
        fill=(180, 180, 180),
        font=font_tiny
    )

    out_path = os.path.join(OUTPUT_DIR, f"preset-{name}.png")
    img.save(out_path, "PNG", optimize=True)
    print(f"Generated {out_path} ({img.size[0]}x{img.size[1]})")


if __name__ == "__main__":
    for name, channels in PRESETS.items():
        generate_preset(name, channels)
    print(f"All presets generated in {OUTPUT_DIR}")
