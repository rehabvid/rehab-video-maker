#!/usr/bin/env python3
"""Normalize a cover for WeChat Channels personal-card 3:4 without cropping art.

Landscape 16:9 covers are contained on a blurred, darkened version of the same
image. This is the preferred alternative to rotating or hard-cropping a
landscape title page.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

W, H = 1080, 1440


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cover", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--width", type=int, default=1000)
    args = parser.parse_args(argv)
    source = Path(args.cover).expanduser()
    if not source.exists():
        raise SystemExit(f"cover not found: {source}")
    image = Image.open(source).convert("RGB")
    background = ImageOps.fit(image, (W, H), method=Image.Resampling.LANCZOS)
    background = background.filter(ImageFilter.GaussianBlur(26))
    veil = Image.new("RGBA", (W, H), (4, 7, 11, 0))
    draw = ImageDraw.Draw(veil)
    for y in range(H):
        alpha = int(92 + 92 * (y / H))
        draw.line([(0, y), (W, y)], fill=(4, 7, 11, alpha))
    background = Image.alpha_composite(background.convert("RGBA"), veil).convert("RGB")
    art = ImageOps.contain(image, (args.width, H - 160), method=Image.Resampling.LANCZOS)
    x = (W - art.width) // 2
    y = (H - art.height) // 2
    background.paste(art, (x, y))
    draw = ImageDraw.Draw(background)
    draw.rounded_rectangle([x - 6, y - 6, x + art.width + 6, y + art.height + 6],
                           radius=18, outline=(242, 184, 75), width=3)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    background.save(out, "PNG")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
