#!/usr/bin/env python3
"""Cut a 9:16 Mandarin clip for WeChat Channels from a finished long video.

WeChat rewards short, vertical, hook-first posts; the horizontal master is the
source, not the post.  This picks the strongest shot from the Mandarin deck,
renders a 1080x1920 clip with a hook and CTA (via ``make_short.py``), burns the
Mandarin captions, and writes a small JSON sidecar for the manifest.

Editorial review is still required before publishing.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MAKE_SHORT = HERE / "make_short.py"
PREPARE_COVER = ROOT / "skills" / "wechat-channels-agent" / "scripts" / "prepare_cover.py"

TIME_LINE = re.compile(
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})"
)


def _load(path: Path):
    return json.loads(path.read_text())


def _seconds(parts) -> float:
    h, m, s, ms = parts
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def _stamp(value: float) -> str:
    value = max(0.0, value)
    h = int(value // 3600)
    m = int((value % 3600) // 60)
    s = int(value % 60)
    ms = int(round((value - int(value)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _shift_srt(source: Path, start: float, duration: float, out: Path) -> bool:
    """Keep cues overlapping the clip and shift them onto the clip clock."""
    if not source.exists():
        return False
    text = source.read_text(errors="ignore")
    blocks = re.split(r"\n\s*\n", text.strip())
    kept = []
    for block in blocks:
        match = TIME_LINE.search(block)
        if not match:
            continue
        a = _seconds(match.group(1, 2, 3, 4))
        b = _seconds(match.group(5, 6, 7, 8))
        if b <= start or a >= start + duration:
            continue
        body = block[match.end():].strip()
        body = re.sub(r"^\s*\d+\s*\n", "", body)
        kept.append((a, b, body))
    if not kept:
        return False
    lines = []
    for index, (a, b, body) in enumerate(kept, 1):
        lines += [str(index),
                  f"{_stamp(max(0.0, a - start))} --> {_stamp(min(duration, b - start))}",
                  body, ""]
    out.write_text("\n".join(lines))
    return True


def _duration(path: Path) -> float:
    try:
        out = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "csv=p=0", str(path),
        ], capture_output=True, text=True, check=True).stdout.strip()
        return float(out)
    except (subprocess.CalledProcessError, ValueError):
        return 0.0


def _score(text: str, heading: str) -> int:
    score = 0
    if 40 <= len(text) <= 130:
        score += 3
    if re.search(r"\d|%|百分", text):
        score += 2
    if any(word in text for word in ("不是", "而是", "真正", "关键", "危险", "错误", "问题")):
        score += 3
    if heading:
        score += 1
    return score


def pick_shot(slides: dict, timing: dict, explicit: str | None) -> dict:
    by_id = {str(s["id"]): s for s in slides.get("shots", [])}
    timed = timing.get("shots", [])
    if explicit:
        for shot in timed:
            if str(shot.get("id")) == str(explicit):
                return shot
        raise SystemExit(f"shot {explicit} not found in timing")
    best = None
    for index, shot in enumerate(timed):
        if index < 2 or index >= len(timed) - 2:
            continue
        deck = by_id.get(str(shot.get("id")), {})
        text = str(deck.get("narration") or "")
        heading = str(deck.get("heading") or "")
        score = _score(text, heading)
        if best is None or score > best[0]:
            best = (score, shot)
    if best is None:
        raise SystemExit("no suitable shot found")
    return best[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--video", required=True, help="finished Mandarin master")
    parser.add_argument("--slides-zh", required=True)
    parser.add_argument("--timing", required=True, help="Mandarin timing.json")
    parser.add_argument("--captions", required=True, help="Mandarin captions.srt")
    parser.add_argument("--out", required=True)
    parser.add_argument("--cover", help="landscape cover to normalize")
    parser.add_argument("--cover-out")
    parser.add_argument("--duration", type=float, default=75.0)
    parser.add_argument("--shot", default=None)
    parser.add_argument("--hook", default="")
    parser.add_argument("--cta", default="完整拆解在同名频道")
    parser.add_argument("--crf", type=int, default=20)
    parser.add_argument("--no-captions", action="store_true")
    args = parser.parse_args(argv)

    video = Path(args.video).expanduser()
    if not video.exists():
        raise SystemExit(f"video not found: {video}")
    slides = _load(Path(args.slides_zh))
    timing = _load(Path(args.timing))
    shot = pick_shot(slides, timing, args.shot)

    start = float(shot.get("start") or 0) + 0.2
    total = _duration(video)
    duration = args.duration
    if total:
        duration = min(duration, total - start - 0.3)
        if duration < 30:
            duration = min(args.duration, total)
            start = max(0.0, total - duration)
    deck = {str(s["id"]): s for s in slides.get("shots", [])}.get(str(shot.get("id")), {})
    hook = args.hook or str(deck.get("heading") or "")[:24]
    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="wechat-clip-") as tmp:
        raw = Path(tmp) / "clip.mp4"
        cmd = [
            sys.executable, str(MAKE_SHORT), "--video", str(video),
            "--start", f"{start:.3f}", "--duration", f"{duration:.3f}",
            "--hook", hook, "--cta", args.cta, "--out", str(raw),
            "--crf", str(args.crf),
        ]
        subprocess.run(cmd, check=True)

        srt = Path(tmp) / "clip.srt"
        burn = (not args.no_captions) and _shift_srt(Path(args.captions), start, duration, srt)
        if burn:
            style = ("FontName=PingFang SC,FontSize=17,PrimaryColour=&H00FFFFFF,"
                     "OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=1,"
                     "MarginV=240,Alignment=2")
            filters = f"subtitles=filename='{srt}':force_style='{style}'"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-v", "error", "-y",
                "-i", str(raw), "-vf", filters,
                "-c:v", "libx264", "-preset", "veryfast", "-crf", str(args.crf),
                "-c:a", "aac", "-b:a", "160k", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", str(out),
            ], check=True)
        else:
            subprocess.run(["cp", str(raw), str(out)], check=True)

    cover_out = None
    if args.cover and args.cover_out:
        cover_out = Path(args.cover_out).expanduser()
        subprocess.run([sys.executable, str(PREPARE_COVER),
                        "--cover", args.cover, "--out", str(cover_out)], check=True)

    title = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", hook)[:15] or "独立评论"
    sidecar = {
        "video": str(out),
        "cover": str(cover_out) if cover_out else None,
        "title": title,
        "hook": hook,
        "cta": args.cta,
        "shot": str(shot.get("id")),
        "start": round(start, 3),
        "duration": round(duration, 3),
        "captions_burned": bool(burn),
    }
    out.with_suffix(".json").write_text(json.dumps(sidecar, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(sidecar, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
