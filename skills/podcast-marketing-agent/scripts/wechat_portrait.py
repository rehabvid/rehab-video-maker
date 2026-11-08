#!/usr/bin/env python3
"""Compose a native 9:16 Mandarin clip from the deck, not from the 16:9 master.

The horizontal master is letterboxed on WeChat; this builds the clip the way a
portrait channel expects: dark portrait background, headline and bullets sized
for 1080x1920, the shot's chart contained (never cropped), per-shot Mandarin
audio, and burned captions.  No 16:9 frame is embedded.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SHARED = ROOT / "skills" / "podcast-avatar-commentary" / "scripts"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))
from lib import find_font, draw_paragraph  # noqa: E402

sys.path.insert(0, str(HERE))
import wechat_clip  # noqa: E402
import yaml  # noqa: E402

W, H = 1080, 1920
THEME = "light"
INK = (24, 26, 30)
MUTED = (78, 80, 84)
ACCENT = (178, 92, 48)
ACCENT2 = (24, 116, 112)
PAPER = (247, 243, 234)


def _palette():
    if THEME == "dark":
        return ((244, 241, 234), (166, 173, 184), (242, 184, 75), (79, 209, 197), (6, 8, 12))
    return (INK, MUTED, ACCENT, ACCENT2, PAPER)


def _load(path: Path):
    return json.loads(path.read_text())


def _fit(path: Path, size=(W, H)) -> Image.Image:
    with Image.open(path) as raw:
        image = raw.convert("RGB")
    scale = max(size[0] / image.width, size[1] / image.height)
    resized = image.resize((max(size[0], int(image.width * scale)),
                            max(size[1], int(image.height * scale))), Image.LANCZOS)
    left = (resized.width - size[0]) // 2
    top = (resized.height - size[1]) // 2
    return resized.crop((left, top, left + size[0], top + size[1]))


def _background(plate: Path, tmp: Path) -> Image.Image:
    if plate.exists():
        image = _fit(plate)
        if THEME == "dark":
            image = image.filter(ImageFilter.GaussianBlur(10))
            veil = Image.new("RGBA", (W, H), (6, 8, 12, 75))
        else:
            image = image.filter(ImageFilter.GaussianBlur(1.2))
            veil = Image.new("RGBA", (W, H), (247, 243, 234, 26))
        image = Image.alpha_composite(image.convert("RGBA"), veil).convert("RGB")
    else:
        image = Image.new("RGB", (W, H), (247, 243, 234) if THEME == "light" else (8, 10, 14))
    return image


def _visual(visuals: Path, sid: str, tmp: Path) -> Path | None:
    for suffix in (".mp4", ".png"):
        candidate = visuals / f"shot-{sid}{suffix}"
        if candidate.exists():
            if suffix == ".png":
                return candidate
            frame = tmp / f"frame-{sid}.png"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-v", "error", "-y",
                "-ss", "0.5", "-i", str(candidate), "-frames:v", "1", str(frame),
            ], check=True)
            return frame if frame.exists() else None
    return None


def _portrait_scenes(ids: list[str], scenes_path: Path, tmp: Path,
                     out_dir: Path | None = None) -> dict[str, Path]:
    """Re-render the selected charts at 1080x1920, dark theme."""
    data = _load(scenes_path)
    module = Path(data["module"])
    slug = f"{data.get('slug') or 'episode'}-portrait"
    outdir = module / "content" / "scenes" / "generated" / slug
    outdir.mkdir(parents=True, exist_ok=True)
    entries = []
    for scene in data.get("scenes", []):
        sid = str(scene.get("id"))
        if sid not in ids:
            continue
        source = module / str(scene.get("scene"))
        try:
            doc = yaml.safe_load(source.read_text())
        except (OSError, yaml.YAMLError):
            continue
        doc["width"], doc["height"] = W, 1340
        doc["theme"] = THEME
        doc["orientation"] = "portrait"
        # keep the source scene's image backdrop; only fall back to theme
        doc["padding"] = 56
        for item in doc.get("items") or []:
            item["x"] = 56
            item["width"] = W - 112
            item["y"] = 150
            item["height"] = 1080
        target = outdir / source.name
        target.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False))
        entries.append({
            "id": sid, "scene_id": target.stem,
            "scene": str(target.relative_to(module)),
            "type": scene.get("type"), "animated": False,
            "duration": 5.0, "theme": THEME,
        })
    if not entries:
        return {}
    manifest = tmp / "portrait-scenes.json"
    manifest.write_text(json.dumps({
        "slug": slug, "module": str(module), "scenes": entries,
    }, ensure_ascii=False, indent=2))
    subprocess.run([
        sys.executable, str(ROOT / "skills" / "tech-commentary-slideshow" / "scripts" / "render_scenes.py"),
        "--manifest", str(manifest), "--visuals", str(out_dir or (tmp / "visuals")),
        "--module", str(module), "--keep-scenes", "--animation-seconds", "1",
    ], check=True)
    base = out_dir or (tmp / "visuals")
    return {e["id"]: base / f"shot-{e['id']}.png" for e in entries}


ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,PingFang SC,40,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,3,1,2,60,60,300,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ass_time(value: float) -> str:
    h = int(value // 3600)
    m = int((value % 3600) // 60)
    s = value % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _ass_header() -> str:
    if THEME == "light":
        style = ("Style: Default,PingFang SC,40,&H00101216,&H000000FF,&H00F4F1EA,&H00F4F1EA,"
                 "0,0,0,0,100,100,0,0,3,10,0,2,60,60,300,1")
    else:
        style = ("Style: Default,PingFang SC,40,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
                 "0,0,0,0,100,100,0,0,1,3,1,2,60,60,300,1")
    return ASS_HEADER.replace("Style: Default,PingFang SC,40,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,3,1,2,60,60,300,1", style)


def _srt_to_ass(srt: Path, ass: Path) -> bool:
    import re
    text = srt.read_text(errors="ignore")
    blocks = re.split(r"\n\s*\n", text.strip())
    lines = []
    for block in blocks:
        match = wechat_clip.TIME_LINE.search(block)
        if not match:
            continue
        a = wechat_clip._seconds(match.group(1, 2, 3, 4))
        b = wechat_clip._seconds(match.group(5, 6, 7, 8))
        body = block[match.end():].strip().replace("\n", " ")
        if any("\u4e00" <= ch <= "\u9fff" for ch in body):
            chunks = [body[i:i + 20] for i in range(0, len(body), 20)]
            body = "\\N".join(chunks)
        else:
            body = "\\N".join(body[i:i + 38] for i in range(0, len(body), 38))
        lines.append(f"Dialogue: 0,{_ass_time(a)},{_ass_time(b)},Default,,0,0,0,,{body}")
    if not lines:
        return False
    ass.write_text(_ass_header() + "\n".join(lines) + "\n")
    return True


def _card(heading: str, bullets: list[str], kicker: str, visual: Path | None,
          index: int, total: int, plate: Path, tmp: Path) -> Path:
    image = _background(plate, tmp)
    # keep the skyline visible: scrim only top and bottom, plus behind text-only cards
    ink, muted, accent, accent2, panel = _palette()
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    scrim = (247, 243, 234) if THEME == "light" else (5, 7, 11)
    for y in range(380):
        sd.line([(0, y), (W, y)], fill=scrim + (int(25 + 115 * (y / 380)),))
    for y in range(H - 470, H):
        t = (y - (H - 470)) / 470
        sd.line([(0, y), (W, y)], fill=scrim + (int(150 * t),))
    image = Image.alpha_composite(image.convert("RGBA"), shade).convert("RGB")
    draw = ImageDraw.Draw(image)
    margin = 64
    if not visual:
        # measure the text first so the panel hugs the content
        scratch = ImageDraw.Draw(Image.new("RGBA", (W, H)))
        probe = 150
        title_size = (78 if len(heading) <= 16 else 68) if index == 1 else (
            60 if len(heading) <= 18 else 52)
        hfont = find_font(title_size, bold=True, text=heading)
        probe = draw_paragraph(scratch, heading, hfont, (margin + 30, probe),
                               W - 2 * margin - 60, ink, 12, 4) + 50
        for bullet in bullets[:3]:
            probe = draw_paragraph(scratch, str(bullet), find_font(38, text=str(bullet)),
                                   (margin + 68, probe), W - 2 * margin - 92, ink, 10, 3) + 40
        panel_bottom = min(H - 470, max(760, probe + 40))
        draw.rounded_rectangle([32, 150, W - 32, panel_bottom], radius=36,
                               fill=panel + ((238 if THEME == "light" else 226),))
    draw.rectangle([margin, 118, margin + 10, 330], fill=accent)
    draw.text((margin + 30, 112), kicker.upper()[:24],
              font=find_font(30, bold=True, text=kicker), fill=accent)

    if visual:
        with Image.open(visual) as raw:
            art = raw.convert("RGB")
        max_w, max_h = W - 2 * margin - 40, H - 700
        scale = min(max_w / art.width, max_h / art.height)
        art = art.resize((max(1, int(art.width * scale)), max(1, int(art.height * scale))), Image.LANCZOS)
        x = (W - art.width) // 2
        y = 360
        frame = ImageDraw.Draw(image)
        frame.rounded_rectangle([x - 8, y - 8, x + art.width + 8, y + art.height + 8],
                                radius=18, fill=(8, 10, 14, 250), outline=ACCENT2, width=3)
        image.paste(art, (x, y))
    else:
        y = 200
        title_size = (78 if len(heading) <= 16 else 68) if index == 1 else (
            60 if len(heading) <= 18 else 52)
        heading_font = find_font(title_size, bold=True, text=heading)
        y = draw_paragraph(draw, heading, heading_font, (margin + 30, y),
                           W - 2 * margin - 60, ink, 12, 4) + 50
        for bullet in bullets[:3]:
            draw.ellipse([margin + 22, y + 12, margin + 44, y + 34], fill=accent2)
            y = draw_paragraph(draw, str(bullet), find_font(38, text=str(bullet)),
                               (margin + 68, y), W - 2 * margin - 92, ink, 10, 3) + 40

    draw.text((margin + 30, H - 170), "AI 生成语音 · 独立评论",
              font=find_font(22, text="AI 生成语音 · 独立评论"), fill=muted)
    draw.text((W - 220, H - 170), f"{index}/{total}", font=find_font(22, text="1/4"), fill=muted)
    out = tmp / f"card-{index}.png"
    image.save(out, "PNG")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slides-zh", required=True)
    parser.add_argument("--timing", required=True, help="Mandarin timing.json")
    parser.add_argument("--audio-dir", required=True, help="zh/dub (per-shot wav)")
    parser.add_argument("--visuals", required=True, help="zh/visuals")
    parser.add_argument("--captions", required=True, help="zh/captions.srt")
    parser.add_argument("--cover", required=True, help="cover plate for the background")
    parser.add_argument("--out", required=True)
    parser.add_argument("--target", type=float, default=68.0)
    parser.add_argument("--max", type=float, default=88.0)
    parser.add_argument("--shot", default=None)
    parser.add_argument("--keep-temp", action="store_true")
    parser.add_argument("--full", action="store_true",
                        help="render the whole episode, not a 60-90s clip")
    parser.add_argument("--theme", choices=["light", "dark"], default="light")
    args = parser.parse_args(argv)

    global THEME
    THEME = args.theme
    slides = _load(Path(args.slides_zh))
    timing = _load(Path(args.timing))
    by_id = {str(s["id"]): s for s in slides.get("shots", [])}
    shots = timing.get("shots", [])
    if args.full:
        first = shots[0]
        start_index = 0
        chosen = list(shots)
        total = sum(float(shot.get("duration") or 0) for shot in chosen)
    else:
        first = wechat_clip.pick_shot(slides, timing, args.shot)
        start_index = next(i for i, s in enumerate(shots) if str(s["id"]) == str(first["id"]))
        chosen = []
        total = 0.0
        for shot in shots[start_index:]:
            chosen.append(shot)
            total += float(shot.get("duration") or 0)
            if total >= args.target:
                break
        total = min(total, args.max)
    if total < 45:
        raise SystemExit(f"selected only {total:.0f}s of narration")

    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    audio_dir = Path(args.audio_dir)
    visuals = Path(args.visuals)
    plate = Path(args.cover)

    with tempfile.TemporaryDirectory(prefix="wechat-portrait-") as tmpdir:
        tmp = Path(tmpdir)
        scenes_json = Path(args.timing).with_name("scenes.json")
        portrait_dir = Path(args.timing).parent / "visuals-portrait"
        portrait = (_portrait_scenes([str(s["id"]) for s in chosen], scenes_json, tmp,
                                     out_dir=portrait_dir)
                    if scenes_json.exists() else {})
        segments = []
        elapsed = 0.0
        for index, shot in enumerate(chosen, 1):
            sid = str(shot["id"])
            deck = by_id.get(sid, {})
            heading = str(deck.get("heading") or deck.get("on_screen") or deck.get("title") or "")
            bullets = [str(x) for x in deck.get("bullets") or []][:3]
            kicker = str(deck.get("kicker") or "独立评论")
            art = portrait.get(sid) or _visual(visuals, sid, tmp)
            card = _card(heading, bullets, kicker, art, index, len(chosen), plate, tmp)
            audio = audio_dir / f"shot-{sid}.wav"
            if not audio.exists():
                continue
            dur = float(shot.get("duration") or 0)
            dur = min(dur, max(2.0, total - elapsed))
            if dur <= 0.5:
                break
            seg = tmp / f"seg-{index}.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-v", "error", "-y",
                "-loop", "1", "-i", str(card), "-i", str(audio),
                "-t", f"{dur:.3f}", "-r", "30",
                "-vf", f"scale={W}:{H},format=yuv420p",
                "-af", "apad",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                str(seg),
            ], check=True)
            segments.append(seg)
            elapsed += dur
            if elapsed >= total:
                break

        concat_list = tmp / "concat.txt"
        concat_list.write_text("".join(f"file '{seg}'\n" for seg in segments))
        joined = tmp / "joined.mp4"
        # Re-encode instead of stream-copy: per-segment AAC/H.264 parameters
        # can differ slightly and make `-c copy` fail with exit 183, which used
        # to drop us back to the dark direct-master cover.
        subprocess.run([
            "ffmpeg", "-hide_banner", "-v", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_list),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(joined),
        ], check=True)

        srt = tmp / "clip.srt"
        ass = tmp / "clip.ass"
        start = float(first.get("start") or 0)
        burn = wechat_clip._shift_srt(Path(args.captions), start, elapsed, srt)
        burn = burn and _srt_to_ass(srt, ass)
        if burn:
            subprocess.run([
                "ffmpeg", "-hide_banner", "-v", "error", "-y",
                "-i", str(joined), "-vf", f"subtitles=filename='{ass}'",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-c:a", "copy", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                str(out),
            ], check=True)
        else:
            subprocess.run(["cp", str(joined), str(out)], check=True)

    import re as _re
    title_source = (str(by_id.get(str(first["id"]), {}).get("heading") or "")
                    or str(slides.get("title") or "独立评论"))
    title = _re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", title_source)[:15]
    sidecar = {
        "video": str(out), "format": "portrait-native", "title": title[:15],
        "shots": [str(s["id"]) for s in chosen], "start": float(first.get("start") or 0),
        "duration": round(elapsed, 3), "width": W, "height": H,
    }
    out.with_suffix(".json").write_text(json.dumps(sidecar, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(sidecar, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
