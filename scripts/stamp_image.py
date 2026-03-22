#!/usr/bin/env python3
"""
Stamp printer info (name, IP, model, date) onto a test image.
Creates a temporary copy — never modifies the original.

Usage: python3 stamp_image.py <source_image> <output_path> <printer_name> <printer_ip> [model]

The info is rendered as a small footer bar at the bottom of the image.
"""

import sys
import os
from datetime import datetime

def stamp(src, dst, name, ip, model=""):
    from PIL import Image, ImageDraw, ImageFont

    img = Image.open(src).convert("RGB")
    w, h = img.size

    # Build info line
    parts = [name, ip]
    if model:
        parts.append(model)
    parts.append(datetime.now().strftime("%Y-%m-%d %H:%M"))
    info = "  |  ".join(parts)

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 9)
    except OSError:
        font = ImageFont.load_default()

    # Measure text
    bbox = font.getbbox(info)
    text_h = bbox[3] - bbox[1] + 6  # 3px padding top+bottom
    bar_h = max(text_h, 14)

    # Extend image with a white bar at the bottom
    new_img = Image.new("RGB", (w, h + bar_h), (255, 255, 255))
    new_img.paste(img, (0, 0))
    draw = ImageDraw.Draw(new_img)

    # Light separator line
    draw.line([(0, h), (w, h)], fill=(200, 200, 200), width=1)

    # Draw text centred in the bar
    text_x = 6
    text_y = h + (bar_h - (bbox[3] - bbox[1])) // 2
    draw.text((text_x, text_y), info, fill=(100, 100, 100), font=font)

    new_img.save(dst, "PNG", optimize=True)


if __name__ == "__main__":
    if len(sys.argv) < 5:
        print(f"Usage: {sys.argv[0]} <source> <output> <name> <ip> [model]")
        sys.exit(1)

    src = sys.argv[1]
    dst = sys.argv[2]
    name = sys.argv[3]
    ip = sys.argv[4]
    model = sys.argv[5] if len(sys.argv) > 5 else ""

    if not os.path.exists(src):
        print(f"Error: source image not found: {src}")
        sys.exit(1)

    stamp(src, dst, name, ip, model)
