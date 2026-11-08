#!/usr/bin/env python3
"""Minimal night skyline for commentary backgrounds.

The reference photo is used only for building massing, never for window-level
detail.  Output: flat ink masses, a thin lit roofline, a handful of amber slots,
calm water lines, and one small trading/venture/AI motif.  Deliberately quiet so
the headline and chart stay dominant.
"""

from __future__ import annotations

import argparse
import math
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

SKY_TOP = (9, 14, 26)
SKY_BOTTOM = (3, 5, 9)
MASS = (12, 18, 30)
EDGE = (118, 158, 172)
AMBER = (232, 170, 74)
TEAL = (79, 209, 197)


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _gradient(size):
    w, h = size
    image = Image.new("RGB", size)
    draw = ImageDraw.Draw(image)
    for y in range(h):
        draw.line([(0, y), (w, y)], fill=_lerp(SKY_TOP, SKY_BOTTOM, y / max(1, h - 1)))
    return image


def _massing(source: Path, columns: int = 18) -> list[float]:
    """Column heights from the photo's luminance, smoothed into blocks."""
    with Image.open(source) as raw:
        gray = ImageOps.fit(raw.convert("L"), (columns * 6, 200), method=Image.Resampling.LANCZOS)
    arr = np.array(gray, dtype=np.float32)
    heights = []
    for i in range(columns):
        col = arr[:, i * 6:(i + 1) * 6].mean(axis=1)
        rows = np.where(col > 55)[0]
        top = rows.min() if len(rows) else 110
        heights.append(min(0.62, max(0.16, 1 - top / 200)))
    # smooth so the skyline reads as buildings, not a comb
    for _ in range(2):
        heights = [0.25 * heights[max(0, i - 1)] + 0.5 * heights[i] + 0.25 * heights[min(len(heights) - 1, i + 1)]
                   for i in range(len(heights))]
    lo, hi = min(heights), max(heights)
    span = max(0.01, hi - lo)
    return [0.16 + 0.52 * ((value - lo) / span) ** 1.35 for value in heights]


def _skyline(image, source, baseline_ratio: float, scale: float = 1.0):
    w, h = image.size
    draw = ImageDraw.Draw(image)
    heights = _massing(source)
    baseline = int(h * baseline_ratio)
    n = len(heights)
    slot = w / n
    rng = random.Random(31)
    for i, height in enumerate(heights):
        bw = int(slot * rng.uniform(0.62, 0.94))
        x = int(i * slot + (slot - bw) / 2)
        top = int(baseline - h * height * scale)
        draw.rectangle([x, top, x + bw, baseline], fill=MASS)
        draw.line([(x, top), (x + bw, top)], fill=EDGE, width=2)
        draw.line([(x, top), (x, baseline)], fill=(34, 48, 62), width=1)
        # at most two quiet light slots per building
        for _ in range(2):
            if rng.random() < 0.45:
                wy = rng.randint(top + 14, max(top + 18, baseline - 24))
                ww = rng.randint(max(4, bw // 5), max(8, bw // 2))
                wx = rng.randint(x + 4, max(x + 6, x + bw - ww - 4))
                draw.line([(wx, wy), (wx + ww, wy)], fill=AMBER, width=3)
    _landmarks(draw, w, h, baseline)
    # water
    draw.line([(0, baseline), (w, baseline)], fill=(46, 70, 86), width=2)
    for i in range(6):
        y = baseline + int((h - baseline) * (i + 1) / 8)
        alpha = 70 - i * 9
        draw.line([(int(w * 0.08), y), (int(w * (0.42 + 0.05 * i)), y)],
                  fill=(30, 56, 70, alpha), width=2)
    return baseline


def _landmarks(draw, w, h, baseline):
    # Marina Bay Sands: three towers and the sky platform
    cx = int(w * 0.60)
    tower_w = max(18, int(w * 0.030))
    top = int(baseline - h * 0.52)
    for offset in (-1, 0, 1):
        x = cx + offset * int(w * 0.055)
        draw.rectangle([x, top + int(h * 0.04), x + tower_w, baseline], fill=(14, 20, 33))
        draw.line([(x, top + int(h * 0.04)), (x + tower_w, top + int(h * 0.04))], fill=EDGE, width=2)
    draw.rounded_rectangle([cx - int(w * 0.085), top, cx + int(w * 0.085), top + int(h * 0.035)],
                           radius=10, outline=EDGE, width=3)
    # ArtScience lotus
    lx, ly = int(w * 0.40), baseline
    radius = int(w * 0.045)
    draw.arc([lx - radius, ly - radius, lx + radius, ly], start=180, end=360, fill=EDGE, width=2)
    for k in range(5):
        angle = math.radians(200 + k * 35)
        draw.line([(lx, ly), (lx + radius * 0.9 * math.cos(angle), ly + radius * 0.9 * math.sin(angle))],
                  fill=(30, 46, 60), width=1)
    # a spire
    sx = int(w * 0.22)
    draw.line([(sx, baseline), (sx, int(baseline - h * 0.46))], fill=EDGE, width=2)
    draw.line([(sx, int(baseline - h * 0.46)), (sx + int(w * 0.008), int(baseline - h * 0.40))],
              fill=EDGE, width=2)


def _motif(image, kind: str, baseline: int):
    w, h = image.size
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    sky_top = int(h * 0.12)
    sky_bottom = int(baseline - h * 0.34)
    if kind == "trading":
        n = 7
        base_y = int(sky_bottom - (sky_bottom - sky_top) * 0.18)
        for i in range(n):
            x = int(w * 0.60 + i * w * 0.052)
            rng = random.Random(200 + i)
            hi, lo = rng.randint(26, 86), rng.randint(8, 30)
            draw.line([(x, base_y - hi), (x, base_y + lo)], fill=AMBER + (120,), width=2)
            draw.rectangle([x - 4, base_y - hi + 14, x + 4, base_y - hi + 14 + rng.randint(16, 40)],
                           fill=(AMBER if i % 2 else TEAL) + (95,))
        pts = [(int(w * 0.50 + i * w * 0.045), int(sky_top + (sky_bottom - sky_top) * (0.55 - 0.02 * i)))
               for i in range(9)]
        draw.line(pts, fill=TEAL + (85,), width=2, joint="curve")
    elif kind == "ai":
        rng = random.Random(41)
        nodes = [(rng.randint(int(w * 0.62), int(w * 0.94)), rng.randint(sky_top, int(sky_top + (sky_bottom - sky_top) * 0.55)))
                 for _ in range(7)]
        for i, a in enumerate(nodes):
            for b in nodes[i + 1:]:
                if math.dist(a, b) < w * 0.16:
                    draw.line([a, b], fill=TEAL + (60,), width=1)
        for x, y in nodes:
            draw.ellipse([x - 3, y - 3, x + 3, y + 3], fill=TEAL + (150,))
    elif kind == "venture":
        pts = []
        for i in range(6):
            x = int(w * (0.60 + i * 0.065))
            y = int(sky_bottom - (i // 2) * h * 0.06)
            pts.append((x, y))
        draw.line(pts, fill=AMBER + (110,), width=2, joint="curve")
        for x, y in pts:
            draw.ellipse([x - 3, y - 3, x + 3, y + 3], fill=TEAL + (130,))
    return Image.alpha_composite(image.convert("RGBA"), layer).convert("RGB")


def _finish(image):
    w, h = image.size
    x = np.linspace(-1, 1, w)[None, :]
    y = np.linspace(-1, 1, h)[:, None]
    radius = np.sqrt(x * x + y * y) / math.sqrt(2)
    mask = np.clip(1 - 0.42 * radius ** 1.6, 0, 1)[..., None]
    arr = (np.array(image) * mask).astype(np.int16)
    noise = np.random.default_rng(3).normal(0, 3.5, arr.shape[:2])[..., None]
    return Image.fromarray(np.clip(arr + noise, 0, 255).astype(np.uint8))


def render(source: Path, out: Path, size: tuple[int, int], overlay: str) -> Path:
    w, h = size
    if h > w:
        image = _gradient(size)
        baseline = _skyline(image, source, 0.78, scale=0.9)
    else:
        image = _gradient(size)
        baseline = _skyline(image, source, 0.80, scale=1.0)
    if overlay != "none":
        image = _motif(image, overlay, baseline)
    image = _finish(image)
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out, "PNG")
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
