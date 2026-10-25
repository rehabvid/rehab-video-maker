#!/usr/bin/env python3
"""Assemble the final commentary video from the timed shot list.

Each shot becomes one uniform 1920x1080 segment at the fps recorded in
`timing.json` (25 or 30):
  avatar  -> the generated clip, first/last frame frozen for the shot's lead/tail
  broll   -> a still or video, looped/trimmed to the shot
  quote   -> a rendered quote card
  chart   -> a rendered list card
  title   -> a rendered title card
  end     -> a rendered end card

Segments are concatenated, narration is attached, captions are burned in, and
the result is loudness-normalised for YouTube. A review sheet is written
alongside the MP4.

Usage:
    python3 assemble.py --timing build/ep01/timing.json \
      --out out/ep01/final.mp4 [--music assets/music.mp3]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from lib import (
    OUT_H,
    OUT_W,
    caption_entries,
    ffprobe_duration,
    ffprobe_streams,
    load_json,
    render_caption_overlay,
    render_end_card,
    render_list_card,
    render_lower_third,
    render_quote_card,
    render_title_card,
    run_ffmpeg,
    save_card,
)

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}


def _segments(shot: dict, timing: dict, root: Path, build: Path) -> tuple[Path, bool, Path | None]:
    """Return (visual, is_video, overlay)."""
    sid = shot["id"]
    kind = shot["kind"]
    visual_value = shot.get("visual")
    background = (
        (root / visual_value).resolve()
        if isinstance(visual_value, str) and visual_value
        else None
    )
    if background is not None and not background.exists():
        background = None

    cards = build / "cards"
    cards.mkdir(parents=True, exist_ok=True)

    if kind == "quote":
        path = cards / f"shot-{sid}.png"
        render_quote_card(
            path,
            shot.get("quote") or "",
            shot.get("attribution") or "",
            shot.get("source") or "",
            background,
        )
        return path, False, None
    if kind == "chart":
        path = cards / f"shot-{sid}.png"
        render_list_card(
            path,
            shot.get("heading") or shot.get("on_screen") or "The idea",
            shot.get("bullets") or [],
            shot.get("kicker") or "THE IDEA",
            background,
        )
        return path, False, None
    if kind == "title":
        path = cards / f"shot-{sid}.png"
        render_title_card(
            path,
            shot.get("on_screen") or timing.get("title") or "",
            shot.get("subtitle") or "",
            shot.get("kicker") or "PODCAST COMMENTARY",
            background,
        )
        return path, False, None
    if kind == "end":
        path = cards / f"shot-{sid}.png"
        disclosure = None
        if timing.get("format") == "broll-slides":
            if str(timing.get("language") or "").lower().startswith(("zh", "cmn", "mandarin")):
                disclosure = "AI 语音旁白。脚本、资料与观点均属于创作者本人。"
            else:
                disclosure = "AI voice narration. The script, research and opinions are the creator's own."
        render_end_card(
            path,
            shot.get("heading") or "What do you think?",
            shot.get("question") or shot.get("narration") or "",
            shot.get("next_text") or "Subscribe for the next breakdown.",
            background,
            disclosure,
        )
        return path, False, None

    if kind == "broll":
        if background is None:
            raise FileNotFoundError(f"shot {sid}: b-roll visual not found")
        is_video = background.suffix.lower() in VIDEO_SUFFIXES
        if not is_video and background.suffix.lower() not in IMAGE_SUFFIXES:
            raise ValueError(f"shot {sid}: unsupported b-roll format {background.suffix}")
        return background, is_video, _overlay(shot, build)

    if kind == "avatar":
        clip = build / "avatar" / f"shot-{sid}.mp4"
        if not clip.exists():
            raise FileNotFoundError(
                f"shot {sid}: avatar clip missing at {clip}; run comfy_client.py first"
            )
        return clip, True, _overlay(shot, build)

    raise ValueError(f"shot {sid}: unknown kind {kind}")


def _overlay(shot: dict, build: Path) -> Path | None:
    text = (shot.get("on_screen") or "").strip()
    if not text or len(text) > 70:
        return None
    path = build / "overlays" / f"shot-{shot['id']}.png"
    return render_lower_third(path, text)


def _caption_overlays(
    shot: dict, entries: list[tuple[float, float, str]], cards: Path
) -> list[dict]:
    """Caption PNGs for one shot, with timings relative to the segment."""
    if shot.get("captions") is False:
        return []
    result: list[dict] = []
    start_at = float(shot["start"])
    end_at = start_at + float(shot["duration"])
    for index, (start, end, text) in enumerate(entries):
        if start < start_at - 1e-6 or start >= end_at - 1e-6:
            continue
        local_start = max(0.0, start - start_at)
        local_end = min(float(shot["duration"]), end - start_at)
        if local_end <= local_start:
            continue
        path = cards / f"caption-{shot['id']}-{index:03d}.png"
        render_caption_overlay(path, text)
        result.append({"path": path, "start": local_start, "end": local_end})
    return result


def _encode_segment(
    visual: Path,
    is_video: bool,
    loop_video: bool,
    overlay: Path | None,
    captions: list[dict],
    duration: float,
    lead: float,
    tail: float,
    fps: int,
    dest: Path,
    preset: str = "medium",
    crf: int = 18,
) -> Path:
    filters = [
        f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase",
        f"crop={OUT_W}:{OUT_H}",
        "setsar=1",
        f"fps={fps}",
    ]
    if lead > 0 or tail > 0:
        filters.append(
            f"tpad=start_mode=clone:start_duration={lead:.3f}:"
            f"stop_mode=clone:stop_duration={max(0.0, tail):.3f}"
        )
    filters.append("format=yuv420p")

    cmd: list[str] = []
    if is_video and loop_video:
        # B-roll may be shorter than its narration; loop it and cut at -t.
        cmd += ["-stream_loop", "-1", "-i", str(visual)]
    elif is_video:
        # Avatar clips are rendered to length. Do not loop them: a loop would
        # restart the performance inside the shot and defeat the tail freeze.
        cmd += ["-i", str(visual)]
    else:
        cmd += ["-loop", "1", "-framerate", str(fps), "-i", str(visual)]

    extra: list[tuple[Path, str | None]] = []
    if overlay is not None:
        extra.append((overlay, None))
    for caption in captions:
        enable = f"between(t,{caption['start']:.3f},{caption['end']:.3f})"
        extra.append((caption["path"], enable))
    for path, _ in extra:
        cmd += ["-loop", "1", "-framerate", str(fps), "-i", str(path)]

    if extra:
        parts = [f"[0:v]{','.join(filters)}[base]"]
        current = "base"
        for i, (_, enable) in enumerate(extra, start=1):
            parts.append(f"[{i}:v]scale={OUT_W}:{OUT_H},format=rgba[ov{i}]")
            gate = f":enable='{enable}'" if enable else ""
            parts.append(
                f"[{current}][ov{i}]overlay=0:0{gate},format=yuv420p[v{i}]"
            )
            current = f"v{i}"
        cmd += ["-filter_complex", ";".join(parts), "-map", f"[{current}]"]
    else:
        cmd += ["-vf", ",".join(filters), "-map", "0:v"]

    cmd += [
        "-t",
        f"{duration:.3f}",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(fps),
        str(dest),
    ]
    run_ffmpeg(cmd)
    return dest


def _concat(segments: list[Path], dest: Path, fps: int, preset: str = "medium", crf: int = 18) -> Path:
    listing = dest.parent / "segments.txt"
    listing.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in segments))
    try:
        run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(dest)])
    except RuntimeError:
        # Different timebases can make stream-copy concat unhappy; re-encode.
        run_ffmpeg(
            [
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(listing),
                "-c:v",
                "libx264",
                "-preset",
                preset,
                "-crf",
                str(crf),
                "-pix_fmt",
                "yuv420p",
                "-r",
                str(fps),
                str(dest),
            ]
        )
    return dest


def _finish(
    concat: Path,
    master: Path,
    dest: Path,
    total: float,
    music: Path | None,
    music_volume: float,
) -> dict:
    cmd = ["-i", str(concat), "-i", str(master)]
    filters: list[str] = []
    if music and music.exists():
        cmd += ["-stream_loop", "-1", "-i", str(music)]
        filters.append(f"[2:a]volume={music_volume:.3f}[m]")
        filters.append("[1:a][m]amix=inputs=2:duration=first:dropout_transition=2[loud]")
        filters.append("[loud]loudnorm=I=-14:TP=-1.5:LRA=11[a]")
    else:
        filters.append("[1:a]loudnorm=I=-14:TP=-1.5:LRA=11[a]")

    cmd += [
        "-filter_complex",
        ";".join(filters),
        "-map",
        "0:v",
        "-map",
        "[a]",
        # Captions are burned into each segment with the overlay filter, so the
        # video track can be stream-copied here. No libass/drawtext dependency.
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        "-t",
        f"{total:.3f}",
        str(dest),
    ]
    run_ffmpeg(cmd)
    return ffprobe_streams(dest)


def _blackdetect(path: Path) -> list[str]:
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-v",
            "info",
            "-i",
            str(path),
            "-vf",
            "blackdetect=d=0.6:pix_th=0.10",
            "-an",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    return [line for line in result.stderr.splitlines() if "black_start" in line]


def _review_md(timing: dict, checks: list[tuple[str, bool, str]], info: dict) -> str:
    shots = timing["shots"]
    avatar = sum(s["duration"] for s in shots if s["kind"] == "avatar")
    total = timing["total_seconds"]
    slides_only = timing.get("format") == "broll-slides"
    streaming = info.get("streams", [])
    video = next((s for s in streaming if s.get("codec_type") == "video"), {})
    audio = next((s for s in streaming if s.get("codec_type") == "audio"), {})
    lines = [
        f"# {timing.get('title', 'Podcast commentary')}",
        "",
    ]
    if slides_only:
        lines.append("- Format: `b-roll slides only`")
    else:
        lines.append(f"- Character: `{timing.get('character')}`")
    lines += [
        f"- Voice: `{timing.get('voice', {}).get('name')}` at `{timing.get('voice', {}).get('rate')}`",
        f"- Runtime: **{total / 60:.1f} min** ({len(shots)} shots)",
    ]
    if not slides_only:
        lines.append(f"- Avatar share: **{avatar / total:.0%}** ({avatar / 60:.1f} min)")
    lines += [
        f"- Export: {video.get('width')}x{video.get('height')} · {video.get('r_frame_rate')} · "
        f"{video.get('codec_name')} · {audio.get('codec_name')} {audio.get('sample_rate')} Hz",
        "",
        "## Shot list",
        "",
        "| # | Kind | Start | Length | On screen |",
        "| --- | --- | --- | --- | --- |",
    ]
    for shot in shots:
        note = (
            shot.get("on_screen")
            or shot.get("heading")
            or shot.get("quote")
            or ""
        )[:80].replace("|", "\\|")
        lines.append(
            f"| {shot['id']} | {shot['kind']} | {shot['start']:.1f}s | "
            f"{shot['duration']:.1f}s | {note} |"
        )

    lines += ["", "## Checks", ""]
    for name, ok, detail in checks:
        mark = "x" if ok else " "
        lines.append(f"- [{mark}] {name}" + (f" — {detail}" if detail else ""))

    if slides_only:
        disclosure = (
            "Disclosure: This video uses an AI-generated voice clone of the creator.\n"
            "The script, research and opinions are the creator's own."
        )
        note = (
            "Add the episode links, sources and timestamps to the YouTube description.\n"
            "The upload script sets YouTube's synthetic-media flag; keep the description\n"
            "disclosure as well. Use only short, credited, transformative excerpts."
        )
    else:
        disclosure = (
            "Disclosure: This video uses an AI-generated avatar of the creator.\n"
            "The script, research and opinions are the creator's own."
        )
        note = (
            "Add the episode links and timestamps to the YouTube description. If you use\n"
            "third-party podcast clips, keep them short, credit the show, and make your\n"
            "commentary the reason the excerpt is there. Use YouTube's altered/synthetic\n"
            "content disclosure when the avatar is realistic."
        )
    lines += ["", "## Upload notes", "", "```text", disclosure, "```", "", note]
    return "\n".join(lines) + "\n"


def build(args) -> int:
    timing_path = Path(args.timing).resolve()
    timing = load_json(timing_path)
    build_dir = timing_path.parent
    root = Path(args.root).resolve()
    fps = int(timing.get("fps") or 30)
    total = float(timing["total_seconds"])
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    segments_dir = build_dir / "segments"
    segments_dir.mkdir(parents=True, exist_ok=True)
    master = build_dir / "master.wav"
    ass = build_dir / "captions.ass"
    srt = build_dir / "captions.srt"
    if not master.exists():
        print(f"error: missing {master}; run tts.py first", file=sys.stderr)
        return 1
    if not ass.exists():
        print(f"error: missing {ass}; run tts.py first", file=sys.stderr)
        return 1

    segments: list[Path] = []
    checks: list[tuple[str, bool, str]] = []
    caption_track = caption_entries(timing["shots"])
    for i, shot in enumerate(timing["shots"], start=1):
        sid = shot["id"]
        print(f"[{i}/{len(timing['shots'])}] {sid} {shot['kind']}: {shot['duration']:.1f}s")
        try:
            visual, is_video, overlay = _segments(shot, timing, root, build_dir)
        except (FileNotFoundError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        captions = _caption_overlays(shot, caption_track, build_dir / "cards")
        dest = segments_dir / f"shot-{sid}.mp4"
        _encode_segment(
            visual,
            is_video,
            shot["kind"] == "broll",
            overlay,
            captions,
            float(shot["duration"]),
            float(shot.get("lead") or 0) if shot["kind"] == "avatar" else 0.0,
            float(shot.get("tail") or 0) if shot["kind"] == "avatar" else 0.0,
            fps,
            dest,
            args.preset,
            args.crf,
        )
        got = ffprobe_duration(dest)
        checks.append(
            (
                f"segment {sid} duration",
                abs(got - float(shot["duration"])) <= 0.15,
                f"{got:.2f}s vs {shot['duration']:.2f}s",
            )
        )
        segments.append(dest)

    concat = build_dir / "video-track.mp4"
    print("concatenating segments")
    _concat(segments, concat, fps, args.preset, args.crf)

    music = Path(args.music) if args.music else None
    print("mixing audio and normalising loudness")
    info = _finish(concat, master, out, total, music, args.music_volume)
    got_total = ffprobe_duration(out)
    checks.append(("final duration", abs(got_total - total) <= 0.25, f"{got_total:.2f}s vs {total:.2f}s"))

    blacks = _blackdetect(out)
    checks.append(("no black gaps over 0.6 s", not blacks, "; ".join(blacks[:2])))

    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
    checks.append(("1920x1080", video.get("width") == OUT_W and video.get("height") == OUT_H,
                   f"{video.get('width')}x{video.get('height')}"))
    checks.append(("30 fps" if fps == 30 else f"{fps} fps",
                   str(video.get("r_frame_rate")) == f"{fps}/1",
                   str(video.get("r_frame_rate"))))
    checks.append(("H.264 + AAC 48 kHz stereo",
                   video.get("codec_name") == "h264" and audio.get("codec_name") == "aac"
                   and int(audio.get("channels") or 0) == 2
                   and int(audio.get("sample_rate") or 0) == 48000,
                   f"{video.get('codec_name')} / {audio.get('codec_name')} "
                   f"{audio.get('channels')}ch {audio.get('sample_rate')}Hz"))
    checks.append(("captions", ass.exists() and srt.exists(),
                   "burned overlays + sidecar SRT/ASS"))
    if timing.get("format") == "broll-slides":
        checks.append(("b-roll slides only", all(
            shot.get("kind") != "avatar" for shot in timing["shots"]
        ), "no avatar shots"))
    else:
        checks.append(("avatar clips present", all(
            (build_dir / "avatar" / f"shot-{s['id']}.mp4").exists()
            for s in timing["shots"] if s["kind"] == "avatar"
        ), "all avatar shots rendered"))

    review = build_dir / "review.md"
    review.write_text(_review_md(timing, checks, info))

    print("\n" + "=" * 72)
    for name, ok, detail in checks:
        mark = "x" if ok else " "
        print(f" [{mark}] {name}" + (f" — {detail}" if detail else ""))
    print("=" * 72)
    print(f"final: {out} ({got_total:.1f}s, {out.stat().st_size / 1e6:.1f} MB)")
    print(f"review: {review}")
    if not all(ok for _, ok, _ in checks):
        print("status: blocked; fix the failed checks before uploading", file=sys.stderr)
        return 1
    print("status: ready for upload")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timing", required=True)
    parser.add_argument("--out", required=True, help="final MP4 path, e.g. out/ep01/final.mp4")
    parser.add_argument("--root", default=".", help="project root for visual paths")
    parser.add_argument("--music", help="optional background music file")
    parser.add_argument("--music-volume", type=float, default=0.06)
    parser.add_argument("--preset", default="medium", choices=["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow"])
    parser.add_argument("--crf", type=int, default=18)
    args = parser.parse_args(argv)
    return build(args)


if __name__ == "__main__":
    raise SystemExit(main())
