#!/usr/bin/env python3
"""Deterministic night ink-skyline background from a Marina Bay photo.

Diffusion at night tends to produce muddy, low-contrast sketches.  This treats
the reference as geometry instead: edge extraction gives the skyline, a navy
gradient and amber window lights give the night palette, and vector overlays add
the trading / venture / AI motif.  Fast, reproducible, and no GPU.
"""

from __future__ import annotations

import argparse
import math
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

NAVY_TOP = (12, 18, 32)
NAVY_BOTTOM = (4, 6, 10)
LINE = (150, 190, 202)
TEAL = (79, 209, 197)
AMBER = (242, 184, 75)


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _base(size):
    w, h = size
    image = Image.new("RGB", size)
    draw = ImageDraw.Draw(image)
    for y in range(h):
        draw.line([(0, y), (w, y)], fill=_lerp(NAVY_TOP, NAVY_BOTTOM, y / max(1, h - 1)))
    return image


def _glow(image, center, radius, color, strength=0.55):
    w, h = image.size
    layer = Image.new("RGB", (w, h), (0, 0, 0))
    draw = ImageDraw.Draw(layer)
    cx, cy = center
    steps = 24
    for i in range(steps, 0, -1):
        r = int(radius * i / steps)
        alpha = strength * (1 - i / steps) ** 1.6
        tint = tuple(int(c * alpha) for c in color)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=tint)
    layer = layer.filter(ImageFilter.GaussianBlur(radius * 0.08))
    return Image.fromarray(
        np.clip(np.array(image).astype(np.int16) + np.array(layer).astype(np.int16), 0, 255).astype(np.uint8)
    )


def _vignette(image, strength=0.55):
    w, h = image.size
    x = np.linspace(-1, 1, w)[None, :]
    y = np.linspace(-1, 1, h)[:, None]
    radius = np.sqrt(x * x + y * y) / math.sqrt(2)
    mask = np.clip(1 - strength * radius ** 1.7, 0, 1)[..., None]
    return Image.fromarray((np.array(image) * mask).astype(np.uint8))


def _grain(image, amount=7):
    arr = np.array(image).astype(np.int16)
    noise = np.random.default_rng(7).normal(0, amount, arr.shape[:2])[..., None]
    return Image.fromarray(np.clip(arr + noise, 0, 255).astype(np.uint8))


def _skyline(path: Path, size):
    w, h = size
    photo = ImageOps.fit(Image.open(path).convert("RGB"), size, method=Image.Resampling.LANCZOS)
    gray = photo.convert("L").filter(ImageFilter.GaussianBlur(1.1))
    edges = ImageOps.autocontrast(gray.filter(ImageFilter.FIND_EDGES), cutoff=1)
    arr = np.array(edges)
    mask = (arr > 26).astype(np.uint8) * 255
    mask = Image.fromarray(mask).filter(ImageFilter.MedianFilter(3))
    mask = mask.filter(ImageFilter.GaussianBlur(0.5))
    lines = Image.new("RGB", size, LINE)
    return photo, gray, mask, lines


def _lights(base, gray, size):
    w, h = size
    arr = np.array(gray)
    ys, xs = np.where(arr > 205)
    keep = ys > size[1] * 0.18
    ys, xs = ys[keep], xs[keep]
    layer = Image.new("RGB", size, (0, 0, 0))
    draw = ImageDraw.Draw(layer)
    rng = random.Random(11)
    for x, y in zip(xs[::14], ys[::14]):
        r = rng.choice((1, 1, 2, 3))
        draw.ellipse([x - r, y - r, x + r, y + r], fill=(210, 150, 54))
    layer = layer.filter(ImageFilter.GaussianBlur(1.4))
    return Image.fromarray(
        np.clip(np.array(base).astype(np.int16) + np.array(layer).astype(np.int16), 0, 255).astype(np.uint8)
    )


def _overlay(image, kind: str):
    w, h = image.size
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    if kind == "trading":
        # candlesticks in the lower third
        base_y = int(h * 0.40)
        n = 12
        for i in range(n):
            x = int(w * 0.58 + i * w * 0.032)
            rng = random.Random(100 + i)
            high = rng.randint(20, 120)
            low = rng.randint(20, 120)
            top = base_y - high
            bottom = base_y + low // 3
            color = AMBER + (120,) if i % 3 else TEAL + (100,)
            draw.line([(x, top), (x, bottom)], fill=color, width=2)
            body = rng.randint(10, 46)
            draw.rectangle([x - 5, top + body // 3, x + 5, top + body], fill=color)
        # yield curve
        pts = [(int(w * 0.05 + i * w * 0.065), int(h * (0.30 - 0.010 * i + 0.008 * math.sin(i))))
               for i in range(14)]
        draw.line(pts, fill=TEAL + (130,), width=3, joint="curve")
    elif kind == "ai":
        rng = random.Random(23)
        nodes = [(rng.randint(int(w * 0.55), int(w * 0.95)), rng.randint(int(h * 0.08), int(h * 0.42)))
                 for _ in range(16)]
        for i, a in enumerate(nodes):
            for b in nodes[i + 1:]:
                if math.dist(a, b) < w * 0.18:
                    draw.line([a, b], fill=TEAL + (80,), width=2)
        for x, y in nodes:
            r = 3
            draw.ellipse([x - r, y - r, x + r, y + r], fill=TEAL + (190,))
        for i in range(4):
            x = int(w * (0.10 + i * 0.055))
            draw.rectangle([x, int(h * 0.72), x + int(w * 0.038), int(h * 0.86)],
                           outline=AMBER + (80,), width=2)
    elif kind == "venture":
        pts = []
        for i in range(9):
            x = int(w * (0.06 + i * 0.105))
            y = int(h * (0.78 - (i // 3) * 0.08 - (i % 3) * 0.015))
            pts.append((x, y))
        draw.line(pts, fill=AMBER + (90,), width=3, joint="curve")
        for x, y in pts:
            draw.ellipse([x - 4, y - 4, x + 4, y + 4], fill=TEAL + (110,))
    return Image.alpha_composite(image.convert("RGBA"), layer).convert("RGB")


def _portrait_canvas(source: Path, size: tuple[int, int], overlay: str):
    """Clean sky at the top, ink skyline anchored in the lower third."""
    w, h = size
    land = _render_flat(source, (1920, 1080), "none")
    band = land.resize((w, int(w * 1080 / 1920)), Image.Resampling.LANCZOS)
    canvas = _base(size)
    canvas = _glow(canvas, (int(w * 0.62), int(h * 0.62)), int(w * 0.95), (26, 44, 68), 0.55)
    y = h - band.height - 110
    fade = Image.new("L", band.size, 255)
    fd = ImageDraw.Draw(fade)
    for row in range(min(160, band.height)):
        fd.line([(0, row), (band.width, row)], fill=int(255 * row / 160))
    canvas.paste(band, (0, y), fade)
    if overlay and overlay != "none":
        canvas = _overlay(canvas, overlay)
    return canvas


def _render_flat(source: Path, size: tuple[int, int], overlay: str = "none"):
    photo, gray, mask, lines = _skyline(source, size)
    base = _base(size)
    base = _glow(base, (int(size[0] * 0.62), int(size[1] * 0.40)),
                 int(max(size) * 0.55), (26, 44, 68), 0.75)
    base = Image.composite(lines, base, mask)
    # soften the ink so it reads as watercolour, then lift the lights
    base = base.filter(ImageFilter.GaussianBlur(0.4))
    base = _lights(base, gray, size)
    if overlay and overlay != "none":
        base = _overlay(base, overlay)
    base = _vignette(base, 0.55)
    base = _grain(base, 6)
    return base


def render(source: Path, out: Path, size: tuple[int, int], overlay: str = "trading") -> Path:
    if size[1] > size[0]:
        base = _portrait_canvas(source, size, overlay)
    else:
        base = _render_flat(source, size, overlay)
    out.parent.mkdir(parents=True, exist_ok=True)
    base.save(out, "PNG")
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--orientation", choices=["landscape", "portrait"], default="landscape")
    parser.add_argument("--overlay", choices=["trading", "ai", "venture", "none"], default="trading")
    args = parser.parse_args(argv)
    size = (1920, 1080) if args.orientation == "landscape" else (1080, 1920)
    print(render(Path(args.source), Path(args.out), size, args.overlay))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
