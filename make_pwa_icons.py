"""One-off generator for the BrightSteps PWA icons in static/ (kept for regeneration)."""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent / "static"
OUT.mkdir(exist_ok=True)

VIOLET = (124, 58, 237)  # #7C3AED — brand primary
BLUE = (37, 99, 235)     # #2563EB — gradient end
WHITE = (255, 255, 255)

# Pulse polyline from the brand-mark SVG (24x24 viewBox): M3 16h4l3-9 4 13 3-9h4
PULSE = [(3, 16), (7, 16), (10, 7), (14, 20), (17, 11), (21, 11)]


def gradient(size: int) -> Image.Image:
    """135deg violet→blue gradient tile, fully opaque."""
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    t = (x + y) / (2 * (size - 1))
    arr = np.zeros((size, size, 4), dtype=np.uint8)
    for c in range(3):
        arr[..., c] = (VIOLET[c] + (BLUE[c] - VIOLET[c]) * t).astype(np.uint8)
    arr[..., 3] = 255
    return Image.fromarray(arr, "RGBA")


def draw_pulse(img: Image.Image, content: float) -> None:
    """White pulse line; `content` = width the 24-unit grid maps onto."""
    size = img.size[0]
    scale = content / 24.0
    offset = (size - content) / 2.0
    pts = [(offset + px * scale, offset + py * scale) for px, py in PULSE]
    stroke = max(2, round(2.2 * scale))
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw.line(pts, fill=WHITE + (255,), width=stroke, joint="curve")
    radius = stroke / 2.0
    for cx, cy in (pts[0], pts[-1]):
        draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=WHITE + (255,))
    img.alpha_composite(layer)


def rounded_tile(size: int, radius: int, content_ratio: float) -> Image.Image:
    img = gradient(size)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=radius, fill=255
    )
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    draw_pulse(out, size * content_ratio)
    return out


def full_bleed(size: int, content_ratio: float) -> Image.Image:
    img = gradient(size)
    draw_pulse(img, size * content_ratio)
    return img


def save(img: Image.Image, name: str) -> None:
    img.save(OUT / name, "PNG")
    print("wrote", OUT / name, img.size)


# Manifest "any" icons — rounded tile, pulse in the middle
save(rounded_tile(192, 42, 0.62), "icon-192.png")
save(rounded_tile(512, 112, 0.62), "icon-512.png")
# Maskable — full bleed; pulse kept inside the 80% safe zone
save(full_bleed(512, 0.40), "icon-maskable-512.png")
# iOS home screen — 180px, NO transparency (iOS fills alpha with black)
save(full_bleed(180, 0.58), "apple-touch-icon.png")
