#!/usr/bin/env python3
"""Render a 1080x1920 commentary Short from a finished long video.

The source is a finished commentary video, not the source podcast.  The renderer
adds a blurred vertical background, a safe-area hook and a CTA.  Editorial
selection of the clip and review before publishing remain mandatory.
"""

from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = [
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]
W, H = 1080, 1920


def _font(size: int) -> ImageFont.FreeTypeFont:
    for value in FONT_CANDIDATES:
        path = Path(value)
        if not path.exists():
            continue
        try:
            return ImageFont.truetype(str(path), size=size, index=0)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for char in text:
        if char == "\n":
            lines.append(current)
            current = ""
            continue
        candidate = current + char
        if current and draw.textlength(candidate, font=font) > width:
            lines.append(current)
            current = char
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _overlay(hook: str, cta: str, path: Path) -> None:
    image = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    if hook:
        font = _font(72 if len(hook) <= 24 else 60)
        lines = _wrap(draw, hook, font, 860)[:4]
        line_h = int(font.size * 1.18)
        box_h = 42 + line_h * len(lines)
        draw.rounded_rectangle([70, 120, W - 70, 120 + box_h + 20], radius=28,
                               fill=(10, 13, 18, 205), outline=(242, 184, 75, 230), width=3)
        y = 150
        for line in lines:
            draw.text((100, y), line, font=font, fill=(255, 255, 255, 255),
                      stroke_width=3, stroke_fill=(4, 6, 10, 230))
            y += line_h
    if cta:
        font = _font(38)
        width = int(draw.textlength(cta, font=font))
        x = max(50, (W - width) // 2)
        draw.rounded_rectangle([x - 28, H - 235, x + width + 28, H - 150], radius=18,
                               fill=(10, 13, 18, 205), outline=(242, 184, 75, 220), width=2)
        draw.text((x, H - 215), cta, font=font, fill=(255, 255, 255, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PNG")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True)
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--duration", type=float, default=45.0)
    parser.add_argument("--hook", default="")
    parser.add_argument("--cta", default="完整拆解在频道里")
    parser.add_argument("--out", required=True)
    parser.add_argument("--crf", type=int, default=20)
    args = parser.parse_args(argv)
    if args.duration <= 0 or args.duration > 180:
        raise SystemExit("duration must be between 1 and 180 seconds")
    source = Path(args.video).expanduser()
    if not source.exists():
        raise SystemExit(f"video not found: {source}")
    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="short-") as tmp:
        base = Path(tmp) / "base.mp4"
        hook_png = Path(tmp) / "hook.png"
        _overlay(args.hook, args.cta, hook_png)
        subprocess.run([
            "ffmpeg", "-hide_banner", "-v", "error", "-y",
            "-ss", f"{args.start:.3f}", "-t", f"{args.duration:.3f}", "-i", str(source),
            "-filter_complex",
            "[0:v]split=2[bg][fg];"
            "[bg]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,gblur=sigma=32,eq=brightness=-0.10[bg];"
            "[fg]scale=1080:-2[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2[v]",
            "-map", "[v]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", str(args.crf),
            "-c:a", "aac", "-b:a", "160k", "-shortest",
            "-pix_fmt", "yuv420p", str(base),
        ], check=True)
        subprocess.run([
            "ffmpeg", "-hide_banner", "-v", "error", "-y",
            "-i", str(base), "-i", str(hook_png),
            "-filter_complex", "[0:v][1:v]overlay=0:0[v]",
            "-map", "[v]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", str(args.crf),
            "-c:a", "aac", "-b:a", "160k", "-shortest",
            "-pix_fmt", "yuv420p", str(out),
        ], check=True)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
