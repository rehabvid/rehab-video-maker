#!/usr/bin/env python3
"""Light ink/watercolour sketch plate, derived from a Marina Bay reference.

CPU-only stand-in for the default light sketch theme (normally SDXL).  The
reference photo is reduced to an ink drawing with a colour-dodge pass, then
washed onto cream paper.  It exists so a cover can still be produced when
ComfyUI is not running.

Do **not** substitute the ``minimal`` generator here: that one paints a *night*
palette, and the light card compositor then washes a dark plate into grey haze.

Output is the background plate only; text is composited by ``tools/gen/cover.py``.
"""

from __future__ import annotations

import argparse
import math
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

PAPER = np.array([250, 247, 240], dtype=np.float32) / 255.0
SKY = np.array([229, 235, 238], dtype=np.float32) / 255.0
INK = np.array([92, 108, 120], dtype=np.float32) / 255.0
TEAL = (63, 143, 138)
AMBER = (198, 148, 62)


def _sketch(source: Path, size: tuple[int, int], radius: float = 18.0) -> np.ndarray:
    """Colour-dodge pencil/ink pass: 1.0 is bare paper, 0.0 is full ink."""
    with Image.open(source) as raw:
        photo = ImageOps.fit(raw.convert("RGB"), size, method=Image.Resampling.LANCZOS)
    gray = ImageOps.grayscale(photo).filter(ImageFilter.GaussianBlur(1.2))
    inverted_blur = ImageOps.invert(gray).filter(ImageFilter.GaussianBlur(radius))
    light = np.asarray(gray, dtype=np.float32) / 255.0
    blur = np.asarray(inverted_blur, dtype=np.float32) / 255.0
    dodged = np.clip(light / np.maximum(1.0 - blur, 1e-3), 0.0, 1.0)
    return 1.0 - dodged


def _wash(ink: np.ndarray) -> np.ndarray:
    """Ink lines on cream paper, with a cool sky wash behind the headline."""
    h, _w = ink.shape
    t = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None, None]
    paper = np.broadcast_to(PAPER, (h, ink.shape[1], 3)).copy()
    sky_mix = np.clip((0.52 - t) / 0.52, 0.0, 1.0) ** 1.2
    canvas = paper * (1.0 - 0.55 * sky_mix) + SKY * (0.55 * sky_mix)
    amount = (np.clip(ink * 1.05, 0.0, 1.0) ** 0.85)[..., None]
    return canvas * (1.0 - amount) + INK * amount


def _motif(image: Image.Image, kind: str) -> Image.Image:
    """One quiet motif on the right third; no window-level detail."""
    w, h = image.size
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    if kind == "trading":
        base_y = int(h * 0.42)
        rng = random.Random(200)
        for i in range(6):
            x = int(w * 0.66 + i * w * 0.045)
            hi, lo = rng.randint(18, 46), rng.randint(6, 16)
            draw.line([(x, base_y - hi), (x, base_y + lo)], fill=AMBER + (70,), width=2)
            draw.rectangle([x - 3, base_y - hi + 10, x + 3,
                            base_y - hi + 10 + rng.randint(10, 22)],
                           fill=(TEAL if i % 2 else AMBER) + (55,))
        pts = [(int(w * 0.60 + i * w * 0.036),
                int(h * 0.30 - i * h * 0.010)) for i in range(8)]
        draw.line(pts, fill=TEAL + (55,), width=2, joint="curve")
    elif kind == "ai":
        rng = random.Random(41)
        nodes = [(rng.randint(int(w * 0.66), int(w * 0.94)),
                  rng.randint(int(h * 0.16), int(h * 0.40))) for _ in range(7)]
        for i, a in enumerate(nodes):
            for b in nodes[i + 1:]:
                if math.dist(a, b) < w * 0.15:
                    draw.line([a, b], fill=TEAL + (45,), width=1)
        for x, y in nodes:
            draw.ellipse([x - 3, y - 3, x + 3, y + 3], fill=TEAL + (110,))
    elif kind == "venture":
        pts = [(int(w * (0.62 + i * 0.055)), int(h * 0.36 - (i // 2) * h * 0.035))
               for i in range(6)]
        draw.line(pts, fill=AMBER + (75,), width=2, joint="curve")
        for x, y in pts:
            draw.ellipse([x - 3, y - 3, x + 3, y + 3], fill=TEAL + (95,))
    return Image.alpha_composite(image.convert("RGBA"), layer).convert("RGB")


def _text_wash(image: Image.Image) -> Image.Image:
    """Paper fade behind the portrait headline and the caption band."""
    w, h = image.size
    y = np.linspace(0.0, 1.0, h, dtype=np.float32)
    top = np.clip((0.50 - y) / 0.50, 0.0, 1.0) ** 0.9 * 0.80
    bottom = np.clip((y - 0.80) / 0.20, 0.0, 1.0) ** 1.3 * 0.80
    alpha = np.clip(top + bottom, 0.0, 0.85)[:, None, None]
    arr = np.asarray(image, dtype=np.float32)
    paper = PAPER * 255.0
    return Image.fromarray(
        np.clip(arr * (1.0 - alpha) + paper * alpha, 0, 255).astype(np.uint8)
    )


def _finish(image: Image.Image) -> Image.Image:
    w, h = image.size
    x = np.linspace(-1.0, 1.0, w, dtype=np.float32)[None, :]
    y = np.linspace(-1.0, 1.0, h, dtype=np.float32)[:, None]
    radius = np.sqrt(x * x + y * y) / math.sqrt(2.0)
    mask = np.clip(1.0 - 0.08 * radius ** 1.8, 0.0, 1.0)[..., None]
    arr = np.asarray(image, dtype=np.float32) * mask
    grain = np.random.default_rng(7).normal(0.0, 2.0, arr.shape[:2])[..., None]
    return Image.fromarray(np.clip(arr + grain, 0, 255).astype(np.uint8))


def render(source: Path, out: Path, size: tuple[int, int], overlay: str,
           strength: float = 1.05) -> Path:
    w, h = size
    portrait = h > w
    if portrait:
        # A portrait cover carries text over most of the frame, so the same
        # ink density would kill legibility. Fade the plate under the
        # headline and the caption band instead.
        strength *= 0.72
    ink = np.clip(_sketch(source, size) * strength, 0.0, 1.0)
    image = Image.fromarray((np.clip(_wash(ink), 0, 1) * 255).astype(np.uint8))
    if portrait:
        image = _text_wash(image)
    if overlay != "none":
        image = _motif(image, overlay)
    image = _finish(image)
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out, "PNG")
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--orientation", choices=["landscape", "portrait"],
                        default="landscape")
    parser.add_argument("--overlay", choices=["trading", "ai", "venture", "none"],
                        default="trading")
    parser.add_argument("--strength", type=float, default=1.05,
                        help="ink density multiplier; lower is paler")
    args = parser.parse_args(argv)
    size = (1920, 1080) if args.orientation == "landscape" else (1080, 1920)
    print(render(Path(args.source), Path(args.out), size, args.overlay,
                 args.strength))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
