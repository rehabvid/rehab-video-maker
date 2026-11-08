#!/usr/bin/env python3
"""Grade an existing light ink/watercolour sketch into a night version.

The light-theme art is the quality reference.  Instead of asking diffusion for a
new night scene (which loses the linework), this maps the same drawing to a
night palette: cream paper -> deep navy, dark ink -> warm moonlight lines, and
the amber/teal accents are preserved and lifted.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

NAVY = np.array([7, 11, 20], dtype=np.float32)
MOON = np.array([236, 226, 202], dtype=np.float32)
TEAL = np.array([90, 196, 190], dtype=np.float32)
AMBER = np.array([232, 170, 74], dtype=np.float32)


def grade(image: Image.Image, warmth: float = 0.55, accent_strength: float = 0.55, teal_scale: float = 1.0, gloss: float = 0.55) -> Image.Image:
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    lum = rgb @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    ink = np.clip(1.0 - lum, 0, 1) ** 0.85  # paper -> 0, ink -> 1

    base = NAVY[None, None, :] + ink[..., None] * (MOON - NAVY)[None, None, :]

    # keep the original warm/cool accents, but as night lights
    maxc = rgb.max(axis=2)
    minc = rgb.min(axis=2)
    sat = np.where(maxc > 0, (maxc - minc) / np.maximum(maxc, 1e-6), 0)
    warm = (rgb[..., 0] > rgb[..., 2] + 0.06) & (sat > 0.18)
    cool = (rgb[..., 2] > rgb[..., 0] + 0.02) & (sat > 0.12)

    accent = np.zeros_like(base)
    accent[warm] = AMBER * (0.55 + 0.45 * ink[warm, None])
    accent[cool] = TEAL * teal_scale * (0.35 + 0.35 * ink[cool, None])
    mask = (warm | cool)[..., None].astype(np.float32) * accent_strength
    out = base * (1 - mask) + accent * mask

    # gentle night wash and warm highlights
    out = out * np.array([0.92, 0.97, 1.06], dtype=np.float32)
    out = out + (AMBER - MOON) * (ink[..., None] ** 3) * 0.12 * warmth
    # glossy finish: bloom only from the actual light accents, not the ink
    lights = ((warm | cool) & (lum > 0.42)).astype(np.float32)
    bloom_src = Image.fromarray((lights * 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(max(5, min(image.size) // 110))
    )
    bloom = np.asarray(bloom_src, dtype=np.float32)[..., None] / 255.0
    out = out + bloom * (AMBER * 0.65 + MOON * 0.35) * 0.55 * gloss
    out = (out - 128.0) * 1.06 + 128.0
    out = np.clip(out, 0, 255) ** 1.02
    shadow = np.clip(1.0 - out.mean(axis=2, keepdims=True) / 90.0, 0, 1)
    out = out + shadow * (TEAL - out) * 0.08 * gloss
    out = np.clip(out, 0, 255)
    result = Image.fromarray(out.astype(np.uint8))

    # vignette + paper grain
    w, h = result.size
    x = np.linspace(-1, 1, w)[None, :]
    y = np.linspace(-1, 1, h)[:, None]
    radius = np.sqrt(x * x + y * y) / np.sqrt(2)
    vignette = np.clip(1 - 0.38 * radius ** 1.6, 0, 1)[..., None]
    arr = (np.asarray(result, dtype=np.float32) * vignette)
    noise = np.random.default_rng(5).normal(0, 3.0, arr.shape[:2])[..., None]
    return Image.fromarray(np.clip(arr + noise, 0, 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(0.35)
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="source", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--warmth", type=float, default=0.55)
    parser.add_argument("--accent", type=float, default=0.55)
    parser.add_argument("--teal", type=float, default=1.0)
    parser.add_argument("--gloss", type=float, default=0.55)
    args = parser.parse_args(argv)
    src = Path(args.source).expanduser()
    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as image:
        grade(image, args.warmth, args.accent, args.teal, args.gloss).save(out, "PNG")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
