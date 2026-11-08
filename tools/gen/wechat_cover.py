#!/usr/bin/env python3
"""WeChat Channels cover: big, high-contrast title that survives small tiles.

The feed shows covers as small tiles, so the title gets 100-140px type, a solid
cream panel, and an outline/halo.  Art stays visible at the bottom; the title is
limited to 2-3 lines and the copy is the short editorial title, not the full
YouTube headline.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parents[2]
SHARED = ROOT / "skills" / "podcast-avatar-commentary" / "scripts"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))
from lib import find_font  # noqa: E402

W, H = 1080, 1440
INK = (16, 18, 22)
PAPER = (247, 243, 234)
ACCENT = (178, 92, 48)
MUTED = (78, 80, 84)


def _wrap(draw, text, font, max_width):
    lines, current = [], ""
    for char in text:
        candidate = current + char
        if current and draw.textlength(candidate, font=font) > max_width:
            lines.append(current)
            current = char
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def build(plate: Path, out: Path, title: str, kicker: str, subtitle: str) -> Path:
    with Image.open(plate) as raw:
        image = ImageOps.fit(raw.convert("RGB"), (W, H), method=Image.Resampling.LANCZOS)

    # cream panel over the top 62%; art shows below
    panel = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(panel)
    draw.rounded_rectangle([40, 70, W - 40, 900], radius=26, fill=PAPER + (238,))
    # soft shadow under the panel
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle([48, 910, W - 48, 990], radius=30, fill=(0, 0, 0, 70))
    image = Image.alpha_composite(image.convert("RGBA"), shadow.filter(ImageFilter.GaussianBlur(18)))
    image = Image.alpha_composite(image, panel).convert("RGB")
    draw = ImageDraw.Draw(image)

    draw.rectangle([82, 120, 94, 420], fill=ACCENT)
    draw.text((120, 112), kicker.upper(), font=find_font(34, bold=True, text=kicker), fill=ACCENT)

    size = 140 if len(title) <= 7 else 124 if len(title) <= 10 else 108
    font = find_font(size, bold=True, text=title)
    lines = _wrap(draw, title, font, W - 260)[:3]
    y = 210
    for line in lines:
        # cream halo separates the ink from any busy edge
        draw.text((120, y), line, font=font, fill=PAPER,
                  stroke_width=10, stroke_fill=PAPER)
        draw.text((120, y), line, font=font, fill=INK,
                  stroke_width=2, stroke_fill=(255, 255, 255))
        y += int(size * 1.16)

    if subtitle:
        draw.text((122, min(y + 18, 820)), subtitle, font=find_font(38, text=subtitle), fill=MUTED)

    # footer
    draw.rounded_rectangle([72, H - 96, W - 72, H - 36], radius=14, fill=PAPER + (225,))
    draw.text((100, H - 84), "AI 生成语音 · 独立评论", font=find_font(24, text="AI 生成语音 · 独立评论"), fill=MUTED)
    draw.text((W - 250, H - 84), "LINKZAG.SHOW", font=find_font(24, text="LINKZAG.SHOW"), fill=MUTED)

    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out, "PNG")
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plate", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--kicker", default="独立评论")
    parser.add_argument("--subtitle", default="")
    args = parser.parse_args(argv)
    print(build(Path(args.plate), Path(args.out), args.title, args.kicker, args.subtitle))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
