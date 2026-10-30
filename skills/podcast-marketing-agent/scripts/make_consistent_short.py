#!/usr/bin/env python3
"""Build a consistent vertical Short from an English commentary build.

The Short always uses the episode's approved cover plate as the background and
an actual LinkZag chart/DAG/diagram from the same English build as the inset
visual. It selects a 45-75 second contiguous shot window, preferring a window
that contains a rendered visual, then delegates composition to
``make_promo_short.py``.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PROMO = HERE / "make_promo_short.py"
VIDEO_SUFFIXES = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}


def _load(path: Path):
    return json.loads(path.read_text())


def _srt_end_is_terminal(srt: Path, start: float, duration: float) -> bool:
    text = srt.read_text(errors="replace") if srt.exists() else ""
    last = ""
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.splitlines()
        if len(lines) < 3:
            continue
        match = re.match(
            r"(\d+):(\d+):([\d,.]+) --> (\d+):(\d+):([\d,.]+)",
            lines[1],
        )
        if not match:
            continue
        z = (
            int(match.group(4)) * 3600
            + int(match.group(5)) * 60
            + float(match.group(6).replace(",", "."))
        )
        if z <= start or z > start + duration + 0.5:
            continue
        last = " ".join(lines[2:]).strip()
    return bool(re.search(r'[.!?。？！]["”\']?$', last))


def _visual_for(shot_ids: set[str], scenes: dict, visuals: Path) -> Path | None:
    ranked = []
    for scene in scenes.get("scenes", []):
        sid = str(scene.get("id"))
        if sid not in shot_ids:
            continue
        for suffix in (".mp4", ".png"):
            path = visuals / f"shot-{sid}{suffix}"
            if path.exists():
                score = 2 if scene.get("animated") else 1
                if str(scene.get("type")) in {"chart", "dag", "diagram", "petrinet", "svg"}:
                    score += 2
                ranked.append((score, path))
                break
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1] if ranked else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--start", type=float)
    parser.add_argument("--cta", default="Full breakdown on the channel")
    args = parser.parse_args(argv)

    build = ROOT / "build" / "autopilot" / args.slug
    out_dir = ROOT / "out" / "autopilot" / args.slug
    source = out_dir / "final.en.mp4"
    timing_path = build / "timing.json"
    scenes_path = build / "scenes.json"
    srt = build / "captions.srt"
    if not source.exists() or not timing_path.exists():
        print(f"error: missing English master or timing for {args.slug}", file=sys.stderr)
        return 1
    timing = _load(timing_path)
    scenes = _load(scenes_path) if scenes_path.exists() else {"scenes": []}
    shots = [s for s in timing.get("shots", []) if str(s.get("id"))]
    if len(shots) < 3:
        return 1
    visuals = build / "visuals"

    cover = None
    for candidate in (
        out_dir / "cover.en.plate.png",
        build / "cover.en.plate.png",
        out_dir / "cover.zh.plate.png",
        build / "cover.zh.plate.png",
    ):
        if candidate.exists():
            cover = candidate
            break
    if cover is None:
        print(f"error: no approved cover plate for {args.slug}", file=sys.stderr)
        return 1

    candidates: list[tuple[float, float, int, str, Path | None]] = []
    for index, shot in enumerate(shots[1:-1], start=1):
        start = float(shot.get("start") or 0.0)
        if args.start is not None and abs(start - args.start) > 0.6:
            continue
        end = start
        ids: set[str] = set()
        for later in shots[index:]:
            ids.add(str(later.get("id")))
            end = float(later.get("start") or end) + float(
                later.get("audio_seconds") or later.get("duration") or 0.0
            )
            length = end - start
            if length >= args.duration - 3:
                break
        length = end - start
        if length < 45 or length > 78:
            continue
        if not _srt_end_is_terminal(srt, start, length):
            continue
        start_visual = _visual_for({str(shot.get("id"))}, scenes, visuals)
        visual = start_visual or _visual_for(ids, scenes, visuals)
        if visual is None:
            continue
        heading = str(shot.get("heading") or shot.get("on_screen") or "").strip()
        score = (2 if visual.suffix.lower() in VIDEO_SUFFIXES else 1) + (2 if 55 <= length <= 68 else 0)
        score += 4 if start_visual is not None else 0
        score += min(3, len(heading.split()) / 4)
        candidates.append((score, start, length, heading, visual))
    if not candidates:
        print(f"error: no 45-75s finite thesis window with a visual for {args.slug}", file=sys.stderr)
        return 1
    candidates.sort(key=lambda item: item[0], reverse=True)
    _score, start, duration, hook, visual = candidates[0]
    if not hook:
        hook = str(timing.get("title") or "").strip()

    out = ROOT / args.out
    cmd = [
        sys.executable, str(PROMO),
        "--video", str(source),
        "--background", str(cover),
        "--visual", str(visual),
        "--srt", str(srt),
        "--start", f"{start:.3f}",
        "--duration", f"{duration:.3f}",
        "--hook", hook,
        "--cta", args.cta,
        "--out", str(out),
    ]
    if subprocess.run(cmd, cwd=ROOT).returncode:
        return 1

    metadata = _load(build / "youtube.json") if (build / "youtube.json").exists() else {}
    title = str(metadata.get("title") or timing.get("title") or args.slug)
    title = re.sub(r"\s+", " ", title).strip()
    if len(title) > 88:
        title = title[:85].rstrip(" ,.;:") + "..."
    source_url = ""
    for receipt in (out_dir / "youtube-en.json", out_dir / "pending-upload.uploaded.json"):
        if receipt.exists():
            try:
                source_url = str(_load(receipt).get("url") or "")
            except Exception:
                source_url = ""
            if source_url:
                break
    description = (
        f"{hook}\n\n"
        "This Short is one complete thesis from my independent commentary on the source podcast. "
        "It is not an episode of the original show; I was not a participant.\n\n"
        + (f"Full breakdown: {source_url}\n\n" if source_url else "")
        + "AI-assisted narration; research, script and opinions are my own. "
        "Commentary, not financial advice.\n\n"
        "#Shorts #PodcastCommentary #AI #Investing"
    )
    meta = {
        "title": (title + " #Shorts")[:100],
        "description": description,
        "tags": list(dict.fromkeys((metadata.get("tags") or []) + ["Shorts", "podcast commentary"])),
        "categoryId": "27",
        "privacyStatus": "public",
        "selfDeclaredMadeForKids": False,
        "containsSyntheticMedia": True,
        "defaultLanguage": "en",
        "defaultAudioLanguage": "en",
    }
    meta_path = out.with_suffix(".json")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "slug": args.slug, "out": str(out), "start": start, "duration": duration,
        "hook": hook, "visual": str(visual), "background": str(cover), "metadata": str(meta_path),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
