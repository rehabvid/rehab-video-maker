#!/usr/bin/env python3
"""Autonomous commentary queue: select, write, render and upload.

This is intentionally a thin coordinator. It uses OpenCode itself as the
editorial writer, then hands the result to the existing content and slideshow
skills. The default published narration is Mandarin (``zh-Hans``); the English
deck is the working visual/timing track and is not uploaded unless English is
explicitly requested. English audiences can use YouTube auto-dubbing from the
Mandarin primary audio. Every upload is private by default.

Run from the repository root::

    nohup .venv/bin/python skills/podcast-youtuber-agent/scripts/autopilot.py \
      --episodes 1 > build/autopilot/autopilot.log 2>&1 &

Use ``--source investment`` to select a fresh episode from the curated RSS
feeds (Top Traders Unplugged, Macro Voices, Invest Like the Best, The Compound,
Odd Lots, Forward Guidance). RSS audio is downloaded and transcribed locally
with MLX Whisper before the writer runs.

Use ``--language en`` only when the user explicitly wants an English narration.
Use ``--language both`` (or the legacy ``--bilingual``) to publish both.

Stop after the current episode by creating ``build/autopilot/STOP``.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from fetch_popular import load_used, used_source_ids

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CONTENT_SCRIPTS = ROOT / "skills" / "podcast-content-agent" / "scripts"
TECH_SCRIPTS = ROOT / "skills" / "tech-commentary-slideshow" / "scripts"
REF_TEXT = ROOT / "skills" / "podcast-youtuber-agent" / "config" / "sample-passage.txt"
AUTOPILOT = ROOT / "build" / "autopilot"
STOP = AUTOPILOT / "STOP"
DEFAULT_MODEL = "opencode-go/deepseek-v4.1-flash"


def log(message: str) -> None:
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    print(f"[{stamp}] {message}", flush=True)


def run(cmd: list[str], *, quiet: bool = False) -> int:
    log("+ " + " ".join(str(part) for part in cmd))
    if quiet:
        result = subprocess.run(cmd, cwd=ROOT, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True)
        if result.returncode:
            log(result.stdout[-4000:])
        return result.returncode
    return subprocess.run(cmd, cwd=ROOT).returncode


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:64] or "episode"


def _load(path: Path):
    return json.loads(path.read_text())


def select_candidate() -> dict | None:
    AUTOPILOT.mkdir(parents=True, exist_ok=True)
    candidates = AUTOPILOT / "candidates.json"
    code = run([
        sys.executable, str(CONTENT_SCRIPTS / "trending.py"),
        "list", "--skip-youtube", "--limit", "20",
        "--no-transcript-check", "--out", str(candidates),
    ], quiet=True)
    if code:
        return None
    items = _load(candidates)
    ranked = []
    for item in items:
        duration = int(item.get("duration_seconds") or 0)
        if duration < 40 * 60:
            continue
        topics = set(item.get("topics") or [])
        if not topics.intersection({"ai", "technology", "tech", "market", "stock", "startup"}):
            continue
        title = str(item.get("title") or "").lower()
        ai_bonus = 12 if any(word in title for word in (
            " ai ", "artificial intelligence", "system design", "agent", "model",
        )) else 0
        market_bonus = 4 if any(word in title for word in (
            "stock", "market", "trading",
        )) else 0
        ranked.append((float(item.get("score") or 0) + ai_bonus + market_bonus, item))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return ranked[0][1] if ranked else None


def _duration_seconds(value: str) -> int:
    value = str(value or "").strip()
    if not value:
        return 0
    if value.isdigit():
        return int(value)
    parts = value.split(":")
    try:
        parts = [int(float(part)) for part in parts]
    except ValueError:
        return 0
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + part
    return seconds


def select_investment_candidate() -> dict | None:
    out = AUTOPILOT / "investment.json"
    code = run([
        sys.executable, str(CONTENT_SCRIPTS / "investment_sources.py"),
        "list", "--per-feed", "2", "--out", str(out),
    ], quiet=True)
    if code:
        return None
    items = _load(out)
    used = used_source_ids(load_used(ROOT / "state" / "used-episodes.json"))
    for item in items:
        if set(str(x) for x in item.get("source_ids", [])) & used:
            continue
        if _duration_seconds(item.get("duration")) < 40 * 60:
            continue
        return item
    return None


def _rss_source_file(candidate: dict, work: Path, asr_model: str) -> Path | None:
    transcript = work / "transcript.txt"
    audio_cache = work / "audio.mp3"
    code = run([
        sys.executable, str(CONTENT_SCRIPTS / "investment_sources.py"),
        "transcript", "--audio-url", candidate.get("audio_url", ""),
        "--out", str(transcript), "--audio-cache", str(audio_cache),
        "--model", asr_model, "--voice-python", str(ROOT / ".venv-voice" / "bin" / "python"),
    ])
    if code or not transcript.exists():
        return None
    text = transcript.read_text().strip()
    source = {
        "transcription": {
            "id": candidate.get("source_ids", [""])[0],
            "slug": slugify(candidate.get("title", "")),
            "title": candidate.get("title", ""),
            "description": "",
            "audio_url": candidate.get("audio_url", ""),
            "image": "",
            "duration": _duration_seconds(candidate.get("duration")),
            "language": "English",
            "category": "investment",
            "created_at": candidate.get("published_at", ""),
            "summary": "",
            "long_summary": "",
            "faqs": [],
            "transcript": text,
        }
    }
    path = work / "source.json"
    path.write_text(json.dumps(source, indent=2, ensure_ascii=False) + "\n")
    return path


def writer_prompt(candidate: dict, work: Path) -> str:
    title = candidate.get("title") or "Podcast commentary"
    source_url = candidate.get("url") or ""
    return f"""You are the podcast-content-agent for this repository. Work only inside:
{work}

You are writing for an **independent commentator reviewing the podcast**. The
creator is not the podcast host, interviewer, or guest. The original host and
guest are third-person subjects of the video. Never write in their voices or
imply the creator was present, asked the questions, supplied the answers, or
was part of the original recording.

Source metadata is in {work / 'source.json'}. The full transcript is in the
`transcription.transcript` field. Read enough of it to verify names, numbers,
dates, and claims. You may use web research for the host/guest.

Role rules for all spoken and written output:
- Refer to the original host and guest by name or as "the host" and "the
  guest." Use first person only for the creator's commentary and analysis.
- Never use "my guest," "joining me," "I sat down with," "I interviewed,"
  "welcome back to the show," or "thank you for joining me."
- Attribute the source conversation explicitly: "As [guest] tells [host]...",
  "The episode argues...", or "In the interview...."
- The opening must identify the original host and guest and make clear this is
  independent commentary, not a host intro.
- Titles and descriptions must read as commentary, analysis or critique, not as
  an episode of the original podcast. Never title it "Interview with..." unless
  the creator actually conducted the interview.

Editorial rules:
- Make an argument, not a recap. At least half the beats must add the creator's
  framework, evidence, counterpoint, implication or a falsifiable call. Do not
  walk through the episode in order.
- Cold open (5-10 seconds) with the thesis, tension or number. Then a compact
  independent-commentary frame (10-15 seconds) naming the host and guests.
  Credentials never come before the hook.
- Every section answers: what the source says, what I think, why it matters,
  and what would change my mind. Keep source attribution separate from the
  creator's judgment.
- Confidence discipline: do not add a claim scorecard, "verified" label or
  external fact-check unless confidence is very high and the claim has a cited
  primary source or reputable web research. Otherwise attribute it to the
  episode ("Alhajji argues...") and do not score it.
- Visual language must match the published video. For the Mandarin deck every
  chart title, category, series name, unit and source line must be Chinese;
  proper names, tickers and URLs may stay. The translated deck's `visual`
  labels are rendered into the Mandarin video, so translate them, not just the
  narration.
- Keep beats short enough for natural TTS (roughly 45-65 English words). Use
  30-45 slides, not a card every ten seconds. Hold important charts longer.

Produce:
1. `script.txt` - 1,850-2,000 words of continuous spoken commentary. At the
   measured Qwen3 slide-by-slide pace of roughly 145-150 wpm this is roughly
   12.5-14 minutes. Do not exceed 2,000 words. Open with the hook/thesis, then
   the compact setup, 3-5 ideas with the creator's own analysis, and a low-key
   close. No headings, bullets, stage directions, or invented facts. Cite
   claims in the metadata; do not put citations in the spoken text.
2. `people.json` - original host/guest names, roles, 2-4 sentence verified
   notes, source URLs. These are third-person subjects, not the creator's
   roles. If the host is unnamed, say so and use `the host`.
3. `slides.json` - run:
   `uv run python skills/podcast-content-agent/scripts/slides.py draft --script {work / 'script.txt'} --out {work / 'slides.json'} --title "{title}" --voice-profile voices/me --engine qwen3 --fps 30 --wpm 150`
   Then edit it: 30-45 slides, headings that state a claim, first title and last
   end card. Replace the deck title and first title card with a
   commentary-framed title; do not simply reuse the source episode title. Keep
   `"format": "broll-slides"` and `"engine": "qwen3"`. Add explicit `visual`
   hints to 6-10 technical slides. Use only real data in chart data, include a
   source/date line, and use ranges rather than invented midpoints; DAG/
   diagram/PetriNet hints are allowed for workflows, architectures and causal
   chains.
4. `youtube.json` - private upload metadata: commentary-framed title that
   promises a payoff, 2-3 paragraph description, source URL ({source_url}),
   chapters, AI-voice disclosure, tags, `"containsSyntheticMedia": true`,
   `"privacyStatus": "private"`. The description must state that this is
   independent commentary, not an episode of the source podcast, and that the
   creator was not a participant. Put verified external sources in a Sources
   block; keep unverified claims attributed to the episode. Chapters may be
   approximate at this stage. Add a `"cover"` object with the most specific
   topic (`energy`, `europe`, `ai_advances`, `ai_power`, `macro`, `investor`),
   one content-specific `subject` for the foreground, the single strongest
   `stat` if one exists, and an `angle` from the Marina Bay pack. The cover
   generator will otherwise infer these from the title and tags.
5. Run `uv run python skills/podcast-content-agent/scripts/slides.py validate
   {work / 'slides.json'} --root . --wpm 150` and fix all errors and warnings.

Do not run narrate.py, build.py, render_scenes.py, or upload anything. Stop
after the files validate. Work efficiently; read the transcript in chunks.
"""


def _resolve_language(parser: argparse.ArgumentParser, args) -> None:
    """Normalise the language flags and enforce the primary-language pairing."""
    if args.english and args.bilingual:
        parser.error("--english and --bilingual are mutually exclusive")
    if args.english:
        args.language = "en"
    if args.bilingual:
        args.language = "both"
    if args.primary_language is None:
        args.primary_language = "en" if args.language == "en" else "zh-Hans"
    if args.language == "en" and args.primary_language != "en":
        parser.error("--language en requires --primary-language en")
    if args.language == "zh-Hans" and args.primary_language != "zh-Hans":
        parser.error("--language zh-Hans requires --primary-language zh-Hans")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episodes", type=int, default=1)
    parser.add_argument("--source", choices=["pt", "investment"], default="pt")
    parser.add_argument(
        "--language", choices=["zh-Hans", "en", "both"], default="zh-Hans",
        help=(
            "published narration language; default zh-Hans (Mandarin). "
            "Use en only when the user explicitly asks for English narration, "
            "or both to publish Mandarin and English"
        ),
    )
    parser.add_argument(
        "--english", action="store_true",
        help="alias for --language en (explicit English narration request)",
    )
    parser.add_argument(
        "--bilingual", action="store_true",
        help="legacy alias for --language both (publish English and Mandarin)",
    )
    parser.add_argument(
        "--primary-language", choices=["en", "zh-Hans"], default=None,
        help="which upload to mark as primary (default follows --language)",
    )
    parser.add_argument("--asr-model", default="mlx-community/whisper-large-v3-turbo-asr-fp16")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--sleep", type=int, default=15)
    parser.add_argument(
        "--no-playlists", action="store_true",
        help="skip automatic series-playlist assignment after upload",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    _resolve_language(parser, args)
    AUTOPILOT.mkdir(parents=True, exist_ok=True)
    if STOP.exists():
        log(f"stop file exists: {STOP}")
        return 0

    completed = 0
    while completed < args.episodes:
        if STOP.exists():
            log("stop file detected; exiting")
            break
        candidate = select_investment_candidate() if args.source == "investment" else select_candidate()
        if candidate is None:
            log("no fresh transcript-backed candidate at >=40 minutes; stopping")
            break
        source_ids = [str(x) for x in candidate.get("source_ids") or [] if x]
        if not source_ids:
            log("candidate has no source id; stopping")
            break
        source_id = source_ids[0]
        title = candidate.get("title") or "Podcast commentary"
        slug = slugify(title)[:52]
        work = AUTOPILOT / slug
        work.mkdir(parents=True, exist_ok=True)
        log(f"selected {source_id}: {title} ({work})")
        prompt = writer_prompt(candidate, work)
        (work / "writer-prompt.txt").write_text(prompt + "\n")
        if args.dry_run:
            log("dry-run: writer prompt written; not invoking OpenCode or ASR")
            return 0
        source_file = work / "source.json"
        if candidate.get("source") == "rss":
            if _rss_source_file(candidate, work, args.asr_model) is None:
                log(f"ASR/transcript failed for {slug}; stopping")
                break
        else:
            with source_file.open("w") as handle:
                subprocess.run(
                    [sys.executable, str(CONTENT_SCRIPTS / "fetch_popular.py"), "get", source_id],
                    cwd=ROOT, stdout=handle, stderr=subprocess.PIPE, text=True, check=False,
                )
            if not source_file.exists() or source_file.stat().st_size < 100:
                log("empty source file; stopping")
                break

        write_code = 1
        writer_log = work / "writer.log"
        for attempt in range(1, 5):
            with writer_log.open("a") as handle:
                handle.write(f"\n=== writer attempt {attempt} ===\n")
                handle.flush()
                write_code = subprocess.run(
                    [
                        "opencode", "run", "--auto", "--model", args.model,
                        "--title", f"autopilot-writer-{slug}-{attempt}", prompt,
                    ],
                    cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT, text=True,
                ).returncode
            if write_code == 0:
                break
            tail = writer_log.read_text(errors="replace")[-2000:].lower()
            transient = any(marker in tail for marker in (
                "ttft_admission_refused", "capacity", "upstream request failed",
                "rate limit", "429", "timeout",
            ))
            if not transient or attempt == 4:
                break
            log(f"writer transient failure (attempt {attempt}); retrying in {attempt * 60}s")
            time.sleep(attempt * 60)
        if write_code:
            log(f"writer failed for {slug}; stopping")
            break
        if not (work / "script.txt").exists() or not (work / "slides.json").exists():
            log(f"writer did not produce script/slides for {slug}; stopping")
            break
        validate = run([
            sys.executable, str(CONTENT_SCRIPTS / "slides.py"),
            "validate", str(work / "slides.json"), "--root", ".", "--wpm", "150",
        ], quiet=True)
        if validate:
            log(f"slides failed validation for {slug}; stopping")
            break

        out_dir = ROOT / "out" / "autopilot" / slug
        out_dir.mkdir(parents=True, exist_ok=True)
        out_note = ""
        if args.language in {"zh-Hans", "both"}:
            translate_code = run([
                sys.executable, str(HERE / "translate.py"),
                "--slides", str(work / "slides.json"),
                "--youtube", str(work / "youtube.json"),
                "--out-dir", str(work),
                "--model", args.model,
            ])
            if translate_code:
                log(f"Mandarin translation failed for {slug}; stopping")
                break
            zh_validate = run([
                sys.executable, str(CONTENT_SCRIPTS / "slides.py"),
                "validate", str(work / "slides.zh.json"), "--root", ".", "--wpm", "150",
            ], quiet=True)
            if zh_validate:
                log(f"Mandarin slides failed validation for {slug}; stopping")
                break
            build_code = run([
                sys.executable, str(HERE / "bilingual.py"), "build",
                "--slides", str(work / "slides.json"),
                "--slides-zh", str(work / "slides.zh.json"),
                "--metadata", str(work / "youtube.json"),
                "--metadata-zh", str(work / "youtube.zh.json"),
                "--work", str(work),
                "--out-dir", str(out_dir),
                "--out-en", str(out_dir / "final.en.mp4"),
                "--out-zh", str(out_dir / "final.zh.mp4"),
                "--engine", "qwen3",
                "--ref-text-file", str(REF_TEXT),
                "--voice-python", str(ROOT / ".venv-voice" / "bin" / "python"),
                "--max-seconds", "895",
                "--preset", "veryfast",
                "--upload",
                "--upload-languages", "both" if args.language == "both" else "zh",
            ])
            if args.language == "both":
                out_note = (
                    f"English {out_dir / 'final.en.mp4'}; "
                    f"Mandarin {out_dir / 'final.zh.mp4'}; uploaded both"
                )
            else:
                out_note = (
                    f"Mandarin {out_dir / 'final.zh.mp4'}; "
                    f"English reference {out_dir / 'final.en.mp4'} not uploaded; "
                    "YouTube auto-dub handles English"
                )
            receipt_path = out_dir / (
                "youtube-zh.json" if args.primary_language == "zh-Hans" else "youtube-en.json"
            )
        else:
            build_code = run([
                sys.executable, str(TECH_SCRIPTS / "build.py"),
                "--slides", str(work / "slides.json"),
                "--out", str(out_dir / "final.mp4"),
                "--work", str(work),
                "--engine", "qwen3",
                "--ref-text-file", str(REF_TEXT),
                "--upload",
                "--metadata", str(work / "youtube.json"),
                "--privacy", "private",
                "--max-seconds", "895",
                "--preset", "veryfast",
            ])
            out_note = f"output {out_dir / 'final.mp4'}"
            receipt_path = out_dir / "youtube-upload.json"
        if build_code:
            log(f"build/upload failed for {slug}; stopping")
            break
        video_id = ""
        if receipt_path.exists():
            try:
                receipt = _load(receipt_path)
                video_id = receipt.get("video_id") or ""
            except Exception:
                pass
        playlist_config = ROOT / "state" / "youtube-playlists.json"
        if (
            video_id
            and playlist_config.exists()
            and not args.no_playlists
        ):
            playlist_meta = work / (
                "youtube.zh.json"
                if args.primary_language == "zh-Hans"
                else "youtube.json"
            )
            playlist_code = run([
                sys.executable, str(HERE / "playlists.py"), "add",
                "--video-id", video_id,
                "--metadata", str(playlist_meta),
                "--config", str(playlist_config),
            ])
            if playlist_code:
                log("playlist assignment failed; the upload is kept")
        mark = [
            sys.executable, str(CONTENT_SCRIPTS / "fetch_popular.py"), "mark",
            "--id", source_id, "--title", title,
            "--note", f"autopilot Qwen3 commentary; {out_note}; primary={args.primary_language}",
        ]
        if video_id:
            mark += ["--video-id", video_id, "--url", f"https://youtu.be/{video_id}"]
        run(mark, quiet=True)
        completed += 1
        log(f"completed {completed}/{args.episodes}: {title} {video_id}")
        if completed < args.episodes:
            time.sleep(max(0, args.sleep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
