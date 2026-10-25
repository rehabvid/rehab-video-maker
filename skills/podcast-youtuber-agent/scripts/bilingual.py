#!/usr/bin/env python3
"""Build and optionally upload English + Mandarin versions of a deck.

The English build is the existing slideshow pipeline.  Mandarin reuses the
same visual track and adds translated narration and captions, so no LinkZag
scenes need to be rendered twice.  The script also creates ``dub.zh.m4a``,
time-fitted to the English video, for YouTube Studio's multi-language audio
track (the public Data API does not yet expose an audio-track insert method).

Typical flow::

    # 1. Translate the finished deck and metadata with the OpenCode agent.
    uv run python skills/podcast-youtuber-agent/scripts/translate.py \\
      --slides build/ep01/slides.json --youtube build/ep01/youtube.json

    # 2. Build both language versions and upload them privately.
    uv run python skills/podcast-youtuber-agent/scripts/bilingual.py build \\
      --slides build/ep01/slides.json \\
      --slides-zh build/ep01/slides.zh.json \\
      --metadata build/ep01/youtube.json \\
      --metadata-zh build/ep01/youtube.zh.json \\
      --work build/ep01 --out-dir out/ep01-bilingual --upload

The English and Mandarin videos share the same edit and visuals.  Uploading
both is the fully automated option.  To get one YouTube URL with an audio
language selector, attach ``dub.zh.m4a`` in YouTube Studio -> Languages; use
booth audio and subtitles in the generated ``bilingual.json`` manifest.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SHARED = ROOT / "skills" / "podcast-avatar-commentary" / "scripts"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from lib import ffprobe_duration, load_json, save_json, write_srt  # noqa: E402

NARRATE = HERE / "narrate.py"
THUMBNAIL = HERE / "thumbnail.py"
UPLOAD = HERE / "youtube_upload.py"
TECH_BUILD = ROOT / "skills" / "tech-commentary-slideshow" / "scripts" / "build.py"
PODCAST_BUILD = HERE / "build.py"
ASSEMBLE = SHARED / "assemble.py"


def log(message: str) -> None:
    print(message, flush=True)


def run(cmd: list[str]) -> int:
    log("+ " + " ".join(str(part) for part in cmd))
    return subprocess.run(cmd, cwd=ROOT).returncode


def _build_english(args, out_en: Path) -> int:
    builder = TECH_BUILD if args.builder == "tech" else PODCAST_BUILD
    cmd = [
        sys.executable, str(builder),
        "--slides", str(args.slides),
        "--out", str(out_en),
        "--work", str(args.work),
        "--voice-profile", args.voice_profile,
        "--engine", args.engine,
        "--preset", args.preset,
        "--crf", str(args.crf),
    ]
    if args.builder == "tech":
        cmd += ["--ref-text-file", args.ref_text_file, "--voice-python", args.voice_python]
    if args.max_seconds:
        cmd += ["--max-seconds", str(args.max_seconds)]
    return run(cmd)


def _fit_clip(src: Path, dst: Path, seconds: float) -> Path:
    """Make a clip exactly ``seconds`` long, time-stretching if necessary."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    source = ffprobe_duration(src)
    if source <= 0 or seconds <= 0:
        raise ValueError(f"invalid clip duration: {src}={source}, target={seconds}")
    if source > seconds + 0.02:
        speed = source / seconds
        # atempo is reliable across 0.5-2.0; a Mandarin clip is rarely outside it.
        filters = []
        while speed > 2.0:
            filters.append("atempo=2.0")
            speed /= 2.0
        while speed < 0.5:
            filters.append("atempo=0.5")
            speed /= 0.5
        filters.append(f"atempo={speed:.6f}")
        audio_filter = ",".join(filters)
    else:
        audio_filter = "apad"
    code = run([
        "ffmpeg", "-hide_banner", "-v", "error", "-y",
        "-i", str(src), "-af", audio_filter, "-t", f"{seconds:.3f}",
        "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(dst),
    ])
    if code:
        raise RuntimeError(f"could not fit audio clip {src} to {seconds:.3f}s")
    return dst


def _make_chinese_assets(args, out_zh: Path) -> int:
    work_zh = args.work_zh
    work_zh.mkdir(parents=True, exist_ok=True)
    narrate = [
        sys.executable, str(NARRATE),
        "--slides", str(args.slides_zh),
        "--out", str(work_zh),
        "--voice-profile", args.voice_profile,
        "--engine", args.engine,
        "--voice-python", args.voice_python,
        "--ref-text-file", args.ref_text_file,
        "--device", args.device,
        "--speed", str(args.speed_zh),
        "--seed", str(args.seed),
    ]
    if run(narrate):
        return 1

    en_timing_path = args.work / "timing-visuals.json"
    if not en_timing_path.exists():
        en_timing_path = args.work / "timing.json"
    en_timing = load_json(en_timing_path)
    zh_timing = load_json(work_zh / "timing.json")
    en_by_id = {str(s["id"]): s for s in en_timing.get("shots", [])}
    zh_shots = zh_timing.get("shots", [])
    for shot in zh_shots:
        en = en_by_id.get(str(shot.get("id")))
        if not en:
            print(f"error: Chinese shot {shot.get('id')} has no English counterpart", file=sys.stderr)
            return 1
        # Reuse the English visual decisions and exact visual paths.
        for key in ("visual", "visual_type", "kind"):
            if key in en:
                shot[key] = en[key]
    zh_timing["language"] = "zh-Hans"
    zh_timing["title"] = args.slides_zh_title or zh_timing.get("title")
    save_json(work_zh / "timing-visuals.json", zh_timing)

    if run([
        sys.executable, str(ASSEMBLE),
        "--timing", str(work_zh / "timing-visuals.json"),
        "--out", str(out_zh),
        "--root", str(ROOT),
        "--preset", args.preset,
        "--crf", str(args.crf),
    ]):
        return 1

    # Captions for the English video use the English shot clock.
    zh_caption_timeline = []
    for en in en_timing.get("shots", []):
        zh = next((s for s in zh_shots if str(s.get("id")) == str(en.get("id"))), None)
        if not zh:
            continue
        item = dict(en)
        item["narration"] = zh.get("narration", "")
        item["audio_seconds"] = en.get("audio_seconds", en.get("duration", 0))
        item["captions"] = True
        zh_caption_timeline.append(item)
    write_srt(zh_caption_timeline, work_zh / "captions-for-english.srt")

    en_caption_timeline = []
    for zh in zh_shots:
        en = en_by_id.get(str(zh.get("id")))
        if not en:
            continue
        item = dict(zh)
        item["narration"] = en.get("narration", "")
        item["audio_seconds"] = zh.get("audio_seconds", zh.get("duration", 0))
        item["captions"] = True
        en_caption_timeline.append(item)
    write_srt(en_caption_timeline, work_zh / "captions-en-for-zh.srt")

    # Time-fit the Chinese voice to the English video length. This is the
    # alt-audio file for YouTube Studio multi-language audio.
    dub_dir = work_zh / "dub"
    fitted = []
    for en in en_timing.get("shots", []):
        zh = next((s for s in zh_shots if str(s.get("id")) == str(en.get("id"))), None)
        if not zh:
            print(f"error: missing Chinese shot {en.get('id')} for dub", file=sys.stderr)
            return 1
        src = work_zh / zh["audio"]
        slot = float(en.get("audio_seconds") or 0)
        if slot <= 0:
            slot = max(1.0, float(en.get("duration") or 1.0) - float(en.get("lead") or 0) - float(en.get("tail") or 0))
        dest = dub_dir / f"shot-{en['id']}.wav"
        _fit_clip(src, dest, slot)
        fitted.append({
            "id": en["id"],
            "audio": f"dub/shot-{en['id']}.wav",
            "start": en["start"],
            "lead": en.get("lead", 0.0),
            "duration": en["duration"],
            "audio_seconds": slot,
            "tail": en.get("tail", 0.0),
        })
    # Reuse narrate's measured master builder by feeding it a fitted timeline.
    from narrate import _build_master

    master_wav = work_zh / "dub" / "master-zh.wav"
    _build_master(
        fitted, master_wav, work_zh, work_zh / "dub" / "tmp",
        float(en_timing["total_seconds"]),
    )
    dub_m4a = work_zh / "dub" / "dub.zh.m4a"
    run([
        "ffmpeg", "-hide_banner", "-v", "error", "-y",
        "-i", str(master_wav), "-c:a", "aac", "-b:a", "192k",
        "-ar", "48000", "-ac", "2", str(dub_m4a),
    ])
    return 0


def _thumbnail(slides: Path, out: Path) -> int:
    return run([
        sys.executable, str(THUMBNAIL), "--slides", str(slides),
        "--out", str(out), "--root", str(ROOT),
    ])


def _localizations(metadata: Path, language: str) -> dict:
    data = load_json(metadata)
    return {
        language: {
            "title": data.get("title", ""),
            "description": data.get("description", ""),
        }
    }


def _upload(args, video: Path, metadata: Path, thumbnail: Path, captions: list[tuple[str, Path, str]], receipt: Path) -> int:
    if not video.exists():
        print(f"error: video not found: {video}", file=sys.stderr)
        return 1
    cmd = [
        sys.executable, str(UPLOAD), "--video", str(video),
        "--metadata", str(metadata), "--privacy", "private",
        "--thumbnail", str(thumbnail), "--receipt", str(receipt),
    ]
    for language, path, name in captions:
        cmd += ["--caption-track", f"{language}={path}|{name}"]
    # Give each upload a localized title/description in the other language.
    if args.metadata and args.metadata_zh:
        if video == args.out_en:
            source, language = args.metadata_zh, "zh-Hans"
        elif video == args.out_zh:
            source, language = args.metadata, "en"
        else:
            source, language = None, ""
        if source:
            temp = args.out_dir / f"localizations.{language}.json"
            temp.write_text(
                json.dumps(_localizations(source, language), ensure_ascii=False, indent=2) + "\n"
            )
            cmd += ["--localizations", str(temp)]
    return run(cmd)


def build(args) -> int:
    args.work = Path(args.work).resolve()
    args.work_zh = Path(args.work_zh).resolve() if args.work_zh else args.work / "zh"
    args.out_dir = Path(args.out_dir).resolve()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    args.out_en = Path(args.out_en).resolve() if args.out_en else args.out_dir / "final.en.mp4"
    args.out_zh = Path(args.out_zh).resolve() if args.out_zh else args.out_dir / "final.zh.mp4"
    args.slides = Path(args.slides).resolve()
    args.slides_zh = Path(args.slides_zh).resolve()
    args.metadata = Path(args.metadata).resolve() if args.metadata else None
    args.metadata_zh = Path(args.metadata_zh).resolve() if args.metadata_zh else None

    if not args.slides_zh.exists():
        print(f"error: Chinese slides not found: {args.slides_zh}", file=sys.stderr)
        return 1
    if args.build_en and not args.out_en.exists():
        if _build_english(args, args.out_en):
            return 1
    if not args.out_en.exists():
        print(f"error: English video not found: {args.out_en}", file=sys.stderr)
        return 1
    if _make_chinese_assets(args, args.out_zh):
        return 1
    zh_duration = ffprobe_duration(args.out_zh)
    if args.max_seconds and zh_duration > args.max_seconds:
        print(
            f"error: Mandarin video is {zh_duration:.1f}s, over the {args.max_seconds:.0f}s limit",
            file=sys.stderr,
        )
        return 1

    thumb_en = args.thumbnail or (args.out_dir / "thumbnail.en.png")
    if not thumb_en.exists():
        _thumbnail(args.slides, thumb_en)
    thumb_zh = args.out_dir / "thumbnail.zh.png"
    if not thumb_zh.exists():
        _thumbnail(args.slides_zh, thumb_zh)

    manifest = {
        "english": {
            "video": str(args.out_en),
            "duration": ffprobe_duration(args.out_en),
            "captions": str(args.work / "captions.srt"),
            "thumbnail": str(thumb_en),
        },
        "mandarin": {
            "video": str(args.out_zh),
            "duration": ffprobe_duration(args.out_zh),
            "captions": str(args.work_zh / "captions.srt"),
            "captions_for_english": str(args.work_zh / "captions-for-english.srt"),
            "captions_en_for_mandarin": str(args.work_zh / "captions-en-for-zh.srt"),
            "thumbnail": str(thumb_zh),
            "dub_for_studio": str(args.work_zh / "dub" / "dub.zh.m4a"),
        },
        "note": (
            "YouTube has no public Data API for alternate audio tracks. "
            "Upload both videos, or attach dub_for_studio in Studio -> Languages "
            "to one English video to expose the audio language selector."
        ),
    }
    (args.out_dir / "bilingual.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")

    if args.upload:
        if not args.metadata or not args.metadata_zh:
            print("error: --upload requires --metadata and --metadata-zh", file=sys.stderr)
            return 1
        en_captions = [
            ("en", args.work / "captions.srt", "English"),
            ("zh-Hans", args.work_zh / "captions-for-english.srt", "中文（普通话）"),
        ]
        zh_captions = [
            ("zh-Hans", args.work_zh / "captions.srt", "中文（普通话）"),
            ("en", args.work_zh / "captions-en-for-zh.srt", "English"),
        ]
        if _upload(args, args.out_en, args.metadata, thumb_en, en_captions, args.out_dir / "youtube-en.json"):
            return 1
        if _upload(args, args.out_zh, args.metadata_zh, thumb_zh, zh_captions, args.out_dir / "youtube-zh.json"):
            return 1
    log(f"English: {args.out_en}")
    log(f"Mandarin: {args.out_zh}")
    log(f"Manifest: {args.out_dir / 'bilingual.json'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("build", help="build English + Mandarin videos")
    p.add_argument("--slides", required=True)
    p.add_argument("--slides-zh", required=True)
    p.add_argument("--metadata")
    p.add_argument("--metadata-zh")
    p.add_argument("--work", required=True)
    p.add_argument("--work-zh")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--out-en")
    p.add_argument("--out-zh")
    p.add_argument("--builder", choices=["tech", "podcast"], default="tech")
    p.add_argument("--voice-profile", default="voices/me")
    p.add_argument("--engine", default="qwen3", choices=["qwen3", "chatterbox", "edge"])
    p.add_argument("--voice-python", default=str(ROOT / ".venv-voice" / "bin" / "python"))
    p.add_argument("--ref-text-file", default=str(ROOT / "skills" / "podcast-youtuber-agent" / "config" / "sample-passage.txt"))
    p.add_argument("--device", default="mps", choices=["mps", "cpu"])
    p.add_argument("--speed-zh", type=float, default=1.0)
    p.add_argument("--seed", type=int, default=43)
    p.add_argument("--preset", default="veryfast")
    p.add_argument("--crf", type=int, default=20)
    p.add_argument("--max-seconds", type=float, default=895.0)
    p.add_argument("--thumbnail")
    p.add_argument("--build-en", action="store_true", default=True)
    p.add_argument("--no-build-en", dest="build_en", action="store_false")
    p.add_argument("--upload", action="store_true")
    p.add_argument("--slides-zh-title")
    p.set_defaults(func=build)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
