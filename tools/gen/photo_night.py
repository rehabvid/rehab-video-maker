#!/usr/bin/env python3
"""Cinematic night grade of a Marina Bay reference photo.

A glossy alternative to the ink theme: keep the photograph, push teal shadows
and amber highlights, bloom the city lights, add a vignette and a text-safe
gradient.  Use when the brief asks for the reference-photo look.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

TEAL = np.array([18, 52, 66], dtype=np.float32)
AMBER = np.array([255, 186, 92], dtype=np.float32)


def grade(image: Image.Image, portrait: bool = False) -> Image.Image:
    image = ImageOps.fit(image.convert("RGB"), (1080, 1920) if portrait else (1920, 1080),
                         method=Image.Resampling.LANCZOS)
    arr = np.asarray(image, dtype=np.float32) / 255.0

    # contrast + saturation, then split tone
    arr = np.clip((arr - 0.5) * 1.12 + 0.5, 0, 1)
    lum = arr @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    shadow = np.clip(1.0 - lum / 0.45, 0, 1)[..., None]
    high = np.clip((lum - 0.55) / 0.45, 0, 1)[..., None]
    arr = arr * (1 - 0.22 * shadow) + (TEAL / 255.0) * 0.22 * shadow
    arr = arr + (AMBER / 255.0) * 0.10 * high
    arr = np.clip(arr, 0, 1)

    # glossy bloom around lights
    bright = (lum > 0.62).astype(np.float32)
    bloom_src = Image.fromarray((bright * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(18))
    bloom = np.asarray(bloom_src, dtype=np.float32)[..., None] / 255.0
    arr = np.clip(arr + bloom * (AMBER / 255.0) * 0.30, 0, 1)

    image = Image.fromarray((arr * 255).astype(np.uint8))
    image = ImageEnhance.Color(image).enhance(0.9)
    image = image.filter(ImageFilter.GaussianBlur(0.6))
    image = image.filter(ImageFilter.UnsharpMask(radius=1.0, percent=45, threshold=3))

    # text-safe gradient
    w, h = image.size
    veil = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(veil)
    if portrait:
        for y in range(h):
            t = y / h
            alpha = int(120 + 100 * max(0.0, (t - 0.35)) / 0.65)
            draw.line([(0, y), (w, y)], fill=(4, 7, 12, alpha))
    else:
        for x in range(w):
            alpha = int(215 * max(0.0, (0.68 - x / w)) / 0.68)
            draw.line([(x, 0), (x, h)], fill=(4, 7, 12, alpha))
    image = Image.alpha_composite(image.convert("RGBA"), veil).convert("RGB")

    # vignette + grain
    x = np.linspace(-1, 1, w)[None, :]
    y = np.linspace(-1, 1, h)[:, None]
    radius = np.sqrt(x * x + y * y) / np.sqrt(2)
    mask = np.clip(1 - 0.55 * radius ** 1.6, 0, 1)[..., None]
    out = np.asarray(image, dtype=np.float32) * mask
    out += np.random.default_rng(9).normal(0, 2.2, out.shape[:2])[..., None]
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--orientation", choices=["landscape", "portrait"], default="landscape")
    args = parser.parse_args(argv)
    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(Path(args.source).expanduser()) as image:
        grade(image, args.orientation == "portrait").save(out, "PNG")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
