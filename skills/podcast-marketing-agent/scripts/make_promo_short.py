#!/usr/bin/env python3
"""Build a native vertical (1080x1920) commentary Short.

Unlike a crop of the long 16:9 video, this compositor builds a vertical canvas:
- a native 1080x1920 blurred/toned background;
- an optional chart/diagram visual from the long video's visuals;
- transcript-derived captions;
- a hook and CTA.

The audio is the creator's commentary from the source video. Do not use source
podcast audio as the primary soundtrack.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

W, H = 1080, 1920
FONT_CANDIDATES = [
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]
VIDEO_SUFFIXES = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}


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
    text = text.replace("\n", " ").strip()
    if " " not in text:
        # CJK has no inter-word spaces; keep character wrapping.
        lines: list[str] = []
        current = ""
        for char in text:
            candidate = current + char
            if current and draw.textlength(candidate, font=font) > width:
                lines.append(current)
                current = char
            else:
                current = candidate
        if current:
            lines.append(current)
        return lines
    lines = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and draw.textlength(candidate, font=font) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _boxed_text(path: Path, text: str, font_size: int, top: int, width: int = 920) -> None:
    image = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    font = _font(font_size)
    lines = _wrap(draw, text, font, width)[:4]
    line_h = int(font.size * 1.2)
    box_h = 34 + line_h * len(lines)
    draw.rounded_rectangle([58, top, W - 58, top + box_h], radius=24,
                           fill=(8, 11, 16, 210), outline=(242, 184, 75, 230), width=3)
    y = top + 17
    for line in lines:
        draw.text((86, y), line, font=font, fill=(255, 255, 255, 255),
                  stroke_width=3, stroke_fill=(4, 6, 10, 230))
        y += line_h
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PNG")


def _background(source: Path, cover: Path | None, start: float, out: Path) -> None:
    if cover and cover.exists():
        image = Image.open(cover).convert("RGB")
    else:
        frame = out.with_suffix(".frame.png")
        subprocess.run([
            "ffmpeg", "-hide_banner", "-v", "error", "-y", "-ss", f"{start:.3f}",
            "-i", str(source), "-frames:v", "1", str(frame),
        ], check=True)
        image = Image.open(frame).convert("RGB")
    image = ImageOps.fit(image, (W, H), method=Image.Resampling.LANCZOS)
    image = image.filter(ImageFilter.GaussianBlur(24))
    veil = Image.new("RGBA", (W, H), (5, 8, 12, 0))
    draw = ImageDraw.Draw(veil)
    for y in range(H):
        alpha = int(70 + 105 * (y / H))
        draw.line([(0, y), (W, y)], fill=(5, 8, 12, alpha))
    image = Image.alpha_composite(image.convert("RGBA"), veil).convert("RGB")
    image.save(out, "PNG")


def _captions_paths(srt: Path, start: float, duration: float, out_dir: Path) -> list[tuple[Path, float, float, str]]:
    text = srt.read_text(errors="replace")
    blocks = re.split(r"\n\s*\n", text.strip())
    result: list[tuple[Path, float, float, str]] = []
    for block in blocks:
        lines = block.splitlines()
        if len(lines) < 3:
            continue
        match = re.match(r"(\d+):(\d+):([\d,.]+) --> (\d+):(\d+):([\d,.]+)", lines[1])
        if not match:
            continue
        a = int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3).replace(",", "."))
        z = int(match.group(4)) * 3600 + int(match.group(5)) * 60 + float(match.group(6).replace(",", "."))
        if z <= start or a >= start + duration:
            continue
        a = max(0.0, a - start)
        z = min(duration, z - start)
        if z <= a:
            continue
        cue_text = " ".join(lines[2:]).replace("\n", " ")
        path = out_dir / f"caption-{len(result):03d}.png"
        _boxed_text(path, cue_text, 42, 1280, 960)
        result.append((path, a, z, cue_text))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True, help="long commentary video; supplies audio")
    parser.add_argument("--background", help="cover plate or image for the vertical background")
    parser.add_argument("--visual", help="chart/diagram visual (image or video) to inset")
    parser.add_argument("--srt", help="transcript SRT for burned captions")
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--duration", type=float, default=40.0)
    parser.add_argument("--hook", default="")
    parser.add_argument("--cta", default="完整拆解在频道里")
    parser.add_argument("--out", required=True)
    parser.add_argument("--crf", type=int, default=20)
    parser.add_argument("--allow-incomplete", action="store_true", help="allow a final caption without terminal punctuation")
    args = parser.parse_args(argv)
    if args.duration <= 0 or args.duration > 180:
        raise SystemExit("duration must be between 1 and 180 seconds")
    source = Path(args.video).expanduser()
    if not source.exists():
        raise SystemExit(f"video not found: {source}")
    background = Path(args.background).expanduser() if args.background else None
    visual = Path(args.visual).expanduser() if args.visual else None
    srt = Path(args.srt).expanduser() if args.srt else None
    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="short-") as tmp:
        tmp = Path(tmp)
        bg = tmp / "background.png"
        _background(source, background, args.start, bg)
        hook = tmp / "hook.png"
        cta = tmp / "cta.png"
        if args.hook:
            _boxed_text(hook, args.hook, 64, 100)
        if args.cta:
            _boxed_text(cta, args.cta, 38, 1740)
        captions = _captions_paths(srt, args.start, args.duration, tmp) if srt and srt.exists() else []
        if captions and not args.allow_incomplete:
            last_text = captions[-1][3].strip()
            if not re.search(r'[.!?。？！]["”\']?$', last_text):
                print(f"warning: last caption does not end a sentence: {last_text}", file=sys.stderr)
                print("choose a later end time or pass --allow-incomplete", file=sys.stderr)
                return 2

        inputs = ["-loop", "1", "-t", f"{args.duration:.3f}", "-i", str(bg)]
        next_index = 1
        visual_index = None
        if visual:
            visual_index = next_index
            next_index += 1
            if visual.suffix.lower() in VIDEO_SUFFIXES:
                inputs += ["-stream_loop", "-1", "-t", f"{args.duration:.3f}", "-i", str(visual)]
            else:
                inputs += ["-loop", "1", "-t", f"{args.duration:.3f}", "-i", str(visual)]
        source_index = next_index
        next_index += 1
        inputs += ["-ss", f"{args.start:.3f}", "-t", f"{args.duration:.3f}", "-i", str(source)]
        hook_index = None
        cta_index = None
        if args.hook:
            hook_index = next_index
            next_index += 1
            inputs += ["-loop", "1", "-t", f"{args.duration:.3f}", "-i", str(hook)]
        if args.cta:
            cta_index = next_index
            next_index += 1
            inputs += ["-loop", "1", "-t", f"{args.duration:.3f}", "-i", str(cta)]
        cap_indexes = []
        for path, _, _, _text in captions:
            cap_indexes.append(next_index)
            next_index += 1
            inputs += ["-loop", "1", "-t", f"{args.duration:.3f}", "-i", str(path)]

        filters = ["[0:v]setsar=1[bg]"]
        current = "bg"
        if visual_index is not None:
            filters.append(f"[{visual_index}:v]scale=1000:-2,setsar=1[vis]")
            filters.append(f"[{current}][vis]overlay=(W-w)/2:470[v1]")
            current = "v1"
        if hook_index is not None:
            filters.append(f"[{current}][{hook_index}:v]overlay=0:0[v2]")
            current = "v2"
        if cta_index is not None:
            filters.append(f"[{current}][{cta_index}:v]overlay=0:0[v3]")
            current = "v3"
        for index, (_, a, z, _text) in enumerate(captions):
            nxt = f"v{4 + index}"
            filters.append(f"[{current}][{cap_indexes[index]}:v]overlay=0:0:enable='between(t,{a:.3f},{z:.3f})'[{nxt}]")
            current = nxt
        command = ["ffmpeg", "-hide_banner", "-v", "error", "-y", *inputs,
                   "-filter_complex", ";".join(filters),
                   "-map", f"[{current}]", "-map", f"{source_index}:a?",
                   "-t", f"{args.duration:.3f}", "-c:v", "libx264", "-preset", "veryfast",
                   "-crf", str(args.crf), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
                   str(out)]
        subprocess.run(command, check=True)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
