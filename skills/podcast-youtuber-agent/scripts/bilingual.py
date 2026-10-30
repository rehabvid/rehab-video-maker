#!/usr/bin/env python3
"""Build Mandarin by default, with an optional English upload.

The English build is the existing slideshow pipeline and supplies the reference
edit/timing.  Mandarin renders its own charts, DAGs and diagrams from the
translated deck so every human-visible visual label matches the published
language.  The script also creates ``dub.zh.m4a``, time-fitted to the English
video, for YouTube Studio's multi-language audio track (the public Data API
does not yet expose an audio-track insert method).

The default upload is Mandarin only: English audiences use YouTube auto-dub
from the Mandarin primary audio.  Upload English only when the user explicitly
asks for an English narration; use ``--upload-languages both`` for both.

Typical flow::

    # 1. Translate the finished deck and metadata with the OpenCode agent.
    uv run python skills/podcast-youtuber-agent/scripts/translate.py \\
      --slides build/ep01/slides.json --youtube build/ep01/youtube.json

    # 2. Build both language masters and upload the Mandarin one privately.
    uv run python skills/podcast-youtuber-agent/scripts/bilingual.py build \\
      --slides build/ep01/slides.json \\
      --slides-zh build/ep01/slides.zh.json \\
      --metadata build/ep01/youtube.json \\
      --metadata-zh build/ep01/youtube.zh.json \\
      --work build/ep01 --out-dir out/ep01-bilingual --upload

The English and Mandarin videos share the same edit/timing, but each language
gets its own localized visual track.  To get one YouTube URL with an audio
language selector, attach ``dub.zh.m4a`` in YouTube Studio -> Languages; use
both audio and subtitles in the generated ``bilingual.json`` manifest.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SHARED = ROOT / "skills" / "podcast-avatar-commentary" / "scripts"
TECH_SCRIPTS = ROOT / "skills" / "tech-commentary-slideshow" / "scripts"
LINKZAG_MODULE = ROOT / "modules" / "linkZagShow"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from lib import ffprobe_duration, load_json, save_json, write_srt  # noqa: E402

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import youtube_upload  # noqa: E402

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
    voice_profile = args.voice_profile_en or args.voice_profile
    ref_text = args.ref_text_file_en or args.ref_text_file
    cmd = [
        sys.executable, str(builder),
        "--slides", str(args.slides),
        "--out", str(out_en),
        "--work", str(args.work),
        "--voice-profile", voice_profile,
        "--engine", args.engine,
        "--speed", str(args.speed_en),
        "--target-wpm", str(args.target_wpm_en),
        "--target-syllables-per-sec", str(args.target_syllables_en),
        "--preset", args.preset,
        "--crf", str(args.crf),
    ]
    if args.builder == "tech":
        cmd += ["--ref-text-file", ref_text, "--voice-python", args.voice_python]
    if args.reuse_en_narration and (args.work / "timing.json").exists():
        cmd += ["--timing", str(args.work / "timing.json")]
    if args.max_seconds:
        cmd += ["--max-seconds", str(args.max_seconds)]
    # The English master needs its own cover art too. The finished cover is the
    # YouTube thumbnail; build.py derives the untexted plate for card and
    # LinkZag scene backgrounds.
    if args.thumbnail:
        cover_en = str(Path(args.thumbnail).expanduser())
        cmd += ["--cover", cover_en, "--thumbnail", cover_en]
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


CHAPTER_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how",
    "in", "is", "it", "of", "on", "or", "the", "to", "what", "when", "where",
    "who", "why", "with",
}


def _chapter_seconds(stamp: str) -> float:
    parts = [int(part) for part in str(stamp).split(":")]
    while parts and len(parts) < 3:
        parts.insert(0, 0)
    hours, minutes, seconds = parts[-3:]
    return float(hours * 3600 + minutes * 60 + seconds)


def _chapter_stamp(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def _chapter_tokens(text: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9]+", str(text).lower())
        if token not in CHAPTER_STOPWORDS
    }


def _retime_chapters(
    metadata_en: Path, metadata_zh: Path, en_timing: dict, zh_timing: dict
) -> None:
    """Map translated chapter titles back to the Chinese shot clock.

    The Mandarin narration is usually shorter than English. Keeping the
    English timestamps would leave late chapters beyond the end of the video,
    so match each English chapter to the best English shot heading, then use
    that same shot's Mandarin start time.
    """
    en_meta = load_json(metadata_en)
    zh_meta = load_json(metadata_zh)
    en_shots = en_timing.get("shots", [])
    zh_by_id = {str(shot.get("id")): shot for shot in zh_timing.get("shots", [])}
    chapters = zh_meta.get("chapters")
    en_chapters = en_meta.get("chapters") or []
    if not isinstance(chapters, list) or len(chapters) != len(en_chapters):
        return

    previous = -10.0
    for chapter, en_chapter in zip(chapters, en_chapters):
        title = str(en_chapter.get("title") or "")
        en_start = _chapter_seconds(str(en_chapter.get("start") or "0:00"))
        query = _chapter_tokens(title)
        best = None
        best_key = None
        for shot in en_shots:
            heading = str(shot.get("heading") or "")
            overlap = len(query & _chapter_tokens(heading)) if query else 0
            distance = abs(float(shot.get("start") or 0) - en_start)
            # Chapter timestamps are approximate anchors. The nearest shot is
            # the reliable match; title overlap only breaks near-ties. A token
            # match on a later shot (for example "agent") used to pull the
            # first chapter several minutes into the video.
            key = (-distance, overlap)
            if best_key is None or key > best_key:
                best = shot
                best_key = key
        if best is None:
            continue
        zh = zh_by_id.get(str(best.get("id")))
        if not zh:
            continue
        start = float(zh.get("start") or 0)
        if start < previous + 10:
            start = previous + 10
        chapter["start"] = _chapter_stamp(start)
        previous = start
    save_json(metadata_zh, zh_meta)


def _render_zh_visuals(args, work_zh: Path, zh_timing: dict, background: Path | None = None) -> int:
    """Render Mandarin charts, DAGs and diagrams from the Chinese deck.

    The English master is only a timing/reference cut.  Reusing its rendered
    visuals inside the Mandarin video would leave English chart titles and axis
    labels on a Chinese video.  Plan and render the translated deck separately,
    using a language-specific slug so the two scene sets do not overwrite each
    other.
    """
    plan_path = work_zh / "visual-plan.json"
    scenes_path = work_zh / "scenes.json"
    visuals_dir = work_zh / "visuals"
    if run([
        sys.executable, str(TECH_SCRIPTS / "plan_visuals.py"),
        "--slides", str(args.slides_zh),
        "--timing", str(work_zh / "timing.json"),
        "--out", str(plan_path),
    ]):
        return 1
    plan = load_json(plan_path)
    plan["slug"] = f"{plan.get('slug') or 'episode'}-zh"
    save_json(plan_path, plan)
    if run([
        sys.executable, str(TECH_SCRIPTS / "make_scenes.py"),
        "--plan", str(plan_path),
        "--module", str(LINKZAG_MODULE),
        "--out", str(scenes_path),
        *(["--background", str(background)] if background and background.exists() else []),
    ]):
        return 1
    if run([
        sys.executable, str(TECH_SCRIPTS / "render_scenes.py"),
        "--manifest", str(scenes_path),
        "--visuals", str(visuals_dir),
        "--module", str(LINKZAG_MODULE),
        "--keep-scenes",
    ]):
        return 1

    scenes = load_json(scenes_path)
    by_id = {str(scene.get("id")): scene for scene in scenes.get("scenes", [])}
    for shot in zh_timing.get("shots", []):
        sid = str(shot.get("id"))
        scene = by_id.get(sid)
        if not scene:
            if isinstance(shot.get("visual"), dict):
                shot.pop("visual", None)
            continue
        suffix = ".mp4" if scene.get("animated") else ".png"
        visual = visuals_dir / f"shot-{sid}{suffix}"
        if not visual.exists():
            print(f"warning: missing Mandarin visual {visual}", file=sys.stderr)
            if isinstance(shot.get("visual"), dict):
                shot.pop("visual", None)
            continue
        shot["kind"] = "broll"
        shot["visual"] = os.path.relpath(visual, ROOT).replace(os.sep, "/")
        shot["visual_type"] = scene.get("type")
    return 0


def _make_chinese_assets(args, out_zh: Path) -> int:
    work_zh = args.work_zh
    work_zh.mkdir(parents=True, exist_ok=True)
    narrate = [
        sys.executable, str(NARRATE),
        "--slides", str(args.slides_zh),
        "--out", str(work_zh),
        "--voice-profile", args.voice_profile,
        "--engine", args.engine_zh,
        "--voice-python", args.voice_python,
        "--ref-text-file", args.ref_text_file,
        "--device", args.device,
        "--speed", str(args.speed_zh),
        "--seed", str(args.seed),
    ]
    if (
        args.reuse_zh_narration
        and (work_zh / "timing.json").exists()
        and (work_zh / "master.wav").exists()
    ):
        log(f"reusing Mandarin narration in {work_zh}")
    elif run(narrate):
        return 1

    # Gate Mandarin audio before rendering any LinkZag scenes. This is the
    # second half of the same bad-seed guard used for English: never spend
    # render time on a deck whose TTS output cannot pass ASR.
    if args.engine_zh == "qwen3" and not args.reuse_zh_narration:
        preflight = work_zh / "audio-qa-preflight-zh.json"
        if run([
            sys.executable, str(TECH_SCRIPTS / "retry_audio.py"),
            "--slides", str(args.slides_zh),
            "--audio-dir", str(work_zh / "audio"),
            "--language", "zh",
            "--reference", str(Path(args.voice_profile) / "reference.wav"),
            "--ref-text", str(args.ref_text_file),
            "--voice-python", args.voice_python,
            "--attempts", "2",
            "--qa-out", str(preflight),
        ]):
            log("Mandarin audio preflight failed; not rendering")
            return 1
        if run(narrate + ["--reuse-audio"]):
            return 1

    en_timing_path = args.work / "timing-visuals.json"
    if not en_timing_path.exists():
        en_timing_path = args.work / "timing.json"
    en_timing = load_json(en_timing_path)
    zh_timing = load_json(work_zh / "timing.json")
    en_by_id = {str(s["id"]): s for s in en_timing.get("shots", [])}
    zh_shots = zh_timing.get("shots", [])
    for shot in zh_shots:
        if str(shot.get("id")) not in en_by_id:
            print(f"error: Chinese shot {shot.get('id')} has no English counterpart", file=sys.stderr)
            return 1
    if args.metadata and args.metadata_zh:
        _retime_chapters(args.metadata, args.metadata_zh, en_timing, zh_timing)
    zh_timing["language"] = "zh-Hans"
    zh_timing["title"] = args.slides_zh_title or zh_timing.get("title")
    cover_path = (
        Path(args.thumbnail_zh).expanduser()
        if args.thumbnail_zh
        else out_zh.parent / "cover.zh.png"
    )
    cover_plate = cover_path.with_name(cover_path.stem + ".plate.png")
    if not cover_plate.exists():
        cover_plate = cover_path
    if args.builder == "tech":
        if _render_zh_visuals(args, work_zh, zh_timing, cover_plate):
            return 1
    else:
        # The legacy podcast builder has no LinkZag scene pass; retain its old
        # panel/card behaviour rather than passing unrenderable visual dicts.
        for shot in zh_shots:
            en = en_by_id.get(str(shot.get("id"))) or {}
            for key in ("visual", "visual_type", "kind"):
                if isinstance(en.get(key), str):
                    shot[key] = en[key]
                elif key in {"visual_type", "kind"} and key in en:
                    shot[key] = en[key]
    if args.no_burn_captions:
        for shot in zh_shots:
            shot["captions"] = False
    save_json(work_zh / "timing-visuals.json", zh_timing)
    timing_path = work_zh / "timing-visuals.json"
    if args.builder == "tech" and not args.no_scene_backgrounds:
        cover = cover_path
        if cover.exists():
            story_timing = work_zh / "timing-story.json"
            story_code = run([
                sys.executable, str(TECH_SCRIPTS / "story_backgrounds.py"),
                "--slides", str(args.slides_zh),
                "--scene-slides", str(args.slides),
                "--timing", str(timing_path),
                "--cover", str(cover),
                "--out", str(story_timing),
                "--language", "zh-Hans",
                "--render-style", "sketch",
                "--max-scenes", "6",
            ])
            if story_code == 0:
                timing_path = story_timing
            else:
                log("story backgrounds failed; keeping dark cards")
            qa_path = work_zh / "background-qa.json"
            qa_code = run([
                sys.executable, str(TECH_SCRIPTS / "qa_backgrounds.py"),
                "--timing", str(timing_path),
                "--scenes", str(work_zh / "scenes.json"),
                "--cover", str(cover_plate),
                "--out", str(qa_path),
            ])
            if qa_code:
                log("background QA failed; see background-qa.json")
                return 1
        else:
            log(f"no cover art at {cover}; keeping dark cards")
    if run([
        sys.executable, str(ASSEMBLE),
        "--timing", str(timing_path),
        "--out", str(out_zh),
        "--root", str(ROOT),
        "--preset", args.preset,
        "--crf", str(args.crf),
    ]):
        return 1

    # Speech QA is deliberately after assembly so it sees the actual cue files
    # used by the video. A failure blocks upload; a human still reviews accent.
    for language, audio_dir, slides_path, qa_name in (
        ("en", args.work / "audio", args.slides, "audio-qa-en.json"),
        ("zh", args.work_zh / "audio", args.slides_zh, "audio-qa-zh.json"),
    ):
        qa_code = run([
            sys.executable, str(TECH_SCRIPTS / "qa_audio.py"),
            "--audio-dir", str(audio_dir),
            "--slides", str(slides_path),
            "--language", language,
            "--voice-python", str(args.voice_python),
            "--out", str(work_zh / qa_name) if language == "zh" else str(args.work / qa_name),
        ])
        if qa_code:
            log(f"audio QA failed for {language}; blocking upload")
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


def _align_chapter_starts(entries: object, starts: object) -> object:
    """Keep localized chapter titles but move them to the target video clock."""
    if not isinstance(entries, list) or not isinstance(starts, list):
        return entries
    if len(entries) != len(starts):
        return entries
    aligned = []
    for entry, source in zip(entries, starts):
        item = dict(entry) if isinstance(entry, dict) else entry
        if isinstance(item, dict) and isinstance(source, dict) and source.get("start"):
            item["start"] = str(source["start"])
        aligned.append(item)
    return aligned


def _localizations(
    metadata: Path,
    language: str,
    chapters: object = None,
) -> dict:
    data = load_json(metadata)
    description = str(data.get("description") or "")
    if chapters:
        description = youtube_upload._with_chapters(description, chapters)
    return {
        language: {
            "title": data.get("title", ""),
            "description": description,
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
    # Chapter titles come from the translated metadata, but their starts must
    # follow the video being uploaded, not the other language master.
    if args.metadata and args.metadata_zh:
        en_chapters = load_json(args.metadata).get("chapters") or []
        zh_chapters = load_json(args.metadata_zh).get("chapters") or []
        if video == args.out_en:
            source, language = args.metadata_zh, "zh-Hans"
            localized_chapters = _align_chapter_starts(zh_chapters, en_chapters)
        elif video == args.out_zh:
            source, language = args.metadata, "en"
            localized_chapters = _align_chapter_starts(en_chapters, zh_chapters)
        else:
            source, language, localized_chapters = None, "", None
        if source:
            temp = args.out_dir / f"localizations.{language}.json"
            temp.write_text(
                json.dumps(
                    _localizations(source, language, localized_chapters),
                    ensure_ascii=False,
                    indent=2,
                ) + "\n"
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

    if args.thumbnail is None:
        default_en_cover = args.out_dir / "cover.en.png"
        if default_en_cover.exists():
            args.thumbnail = str(default_en_cover)
    thumb_en = Path(args.thumbnail).expanduser() if args.thumbnail else (args.out_dir / "thumbnail.en.png")
    if not thumb_en.exists():
        _thumbnail(args.slides, thumb_en)
    thumb_zh = Path(args.thumbnail_zh).expanduser() if args.thumbnail_zh else args.out_dir / "thumbnail.zh.png"
    if not thumb_zh.exists():
        _thumbnail(args.slides_zh, thumb_zh)

    # The English video must use the same LinkZag cover plate as its YouTube
    # thumbnail. Catch a failed story-background pass before upload rather than
    # silently publishing dark/legacy cards.
    if args.builder == "tech" and not args.no_scene_backgrounds and args.thumbnail:
        en_story = args.work / "timing-story.json"
        en_scenes = args.work / "scenes.json"
        en_cover = Path(args.thumbnail).expanduser()
        en_plate = en_cover.with_name(en_cover.stem + ".plate.png")
        if not en_plate.exists():
            en_plate = en_cover
        if not en_story.exists() or not en_scenes.exists():
            print("error: English story backgrounds are missing", file=sys.stderr)
            return 1
        if run([
            sys.executable, str(TECH_SCRIPTS / "qa_backgrounds.py"),
            "--timing", str(en_story),
            "--scenes", str(en_scenes),
            "--cover", str(en_plate),
            "--out", str(args.work / "background-qa-en.json"),
        ]):
            log("English background QA failed; blocking upload")
            return 1

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
            "Mandarin is the default published narration. English can come from "
            "YouTube auto-dub on the Mandarin primary audio, or upload the "
            "optional English master when the user explicitly requested an "
            "English narration. YouTube has no public Data API for alternate "
            "audio tracks; attach dub_for_studio in Studio -> Languages if you "
            "want an in-player audio selector."
        ),
    }
    (args.out_dir / "bilingual.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")

    if args.upload:
        upload_en = args.upload_languages in {"both", "en"}
        upload_zh = args.upload_languages in {"both", "zh"}
        if upload_en and not args.metadata:
            print("error: --upload requires --metadata for the English upload", file=sys.stderr)
            return 1
        if upload_zh and not args.metadata_zh:
            print("error: --upload requires --metadata-zh for the Mandarin upload", file=sys.stderr)
            return 1
        if upload_en:
            en_captions = [
                ("en", args.work / "captions.srt", "English"),
                ("zh-Hans", args.work_zh / "captions-for-english.srt", "中文（普通话）"),
            ]
            if _upload(args, args.out_en, args.metadata, thumb_en, en_captions, args.out_dir / "youtube-en.json"):
                return 1
        if upload_zh:
            zh_captions = [
                ("zh-Hans", args.work_zh / "captions.srt", "中文（普通话）"),
                ("en", args.work_zh / "captions-en-for-zh.srt", "English"),
            ]
            if _upload(args, args.out_zh, args.metadata_zh, thumb_zh, zh_captions, args.out_dir / "youtube-zh.json"):
                return 1
    log(f"English: {args.out_en}")
    log(f"Mandarin: {args.out_zh}")
    log(f"Manifest: {args.out_dir / 'bilingual.json'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("build", help="build Mandarin primary with optional English master")
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
    p.add_argument("--voice-profile-en", help="optional English-only profile, e.g. a US-accent reference")
    p.add_argument("--ref-text-file-en", help="exact transcript for the English-only reference")
    p.add_argument("--engine", default="qwen3", choices=["qwen3", "chatterbox", "edge"], help="English voice engine")
    p.add_argument("--engine-zh", default="qwen3", choices=["qwen3", "chatterbox", "edge"], help="Mandarin voice engine")
    p.add_argument("--voice-python", default=str(ROOT / ".venv-voice" / "bin" / "python"))
    p.add_argument("--ref-text-file", default=str(ROOT / "skills" / "podcast-youtuber-agent" / "config" / "sample-passage.txt"))
    p.add_argument("--device", default="mps", choices=["mps", "cpu"])
    p.add_argument("--speed-zh", type=float, default=1.0)
    p.add_argument("--speed-en", type=float, default=1.0, help="English Qwen model speed; keep 1.0")
    p.add_argument("--target-wpm-en", type=float, default=170.0, help="English Qwen post-speed target")
    p.add_argument("--target-syllables-en", type=float, default=5.15, help="English speech-only syllables/sec")
    p.add_argument(
        "--reuse-en-narration", action="store_true",
        help="use the existing English timing.json/master.wav instead of synthesising again",
    )
    p.add_argument(
        "--reuse-zh-narration", action="store_true",
        help="reuse work-zh/timing.json and master.wav instead of synthesising again",
    )
    p.add_argument("--seed", type=int, default=44)
    p.add_argument("--preset", default="veryfast")
    p.add_argument("--crf", type=int, default=20)
    p.add_argument("--max-seconds", type=float, default=895.0)
    p.add_argument("--thumbnail")
    p.add_argument(
        "--thumbnail-zh",
        help="pre-rendered Mandarin cover/thumbnail; skips thumbnail.py for zh",
    )
    p.add_argument("--build-en", action="store_true", default=True)
    p.add_argument("--no-build-en", dest="build_en", action="store_false")
    p.add_argument("--upload", action="store_true")
    p.add_argument(
        "--upload-languages", choices=["both", "en", "zh"], default="zh",
        help=(
            "with --upload: default zh (Mandarin primary; English via YouTube "
            "auto-dub); use en or both only when English narration is explicit"
        ),
    )
    p.add_argument(
        "--no-burn-captions", action="store_true",
        help="keep burned captions out of the Mandarin master; upload SRT tracks only",
    )
    p.add_argument(
        "--no-scene-backgrounds", action="store_true",
        help="keep the old dark card backgrounds; default uses cover art and story cards",
    )
    p.add_argument("--slides-zh-title")
    p.set_defaults(func=build)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
