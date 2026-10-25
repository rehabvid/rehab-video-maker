#!/usr/bin/env python3
"""Autonomous commentary queue: select, write, render and upload.

This is intentionally a thin coordinator. It uses OpenCode itself as the
editorial writer, then hands the result to the existing content and slideshow
skills. Every upload is private by default.

Run from the repository root::

    nohup .venv/bin/python skills/podcast-youtuber-agent/scripts/autopilot.py \
      --episodes 2 > build/autopilot/autopilot.log 2>&1 &

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


def writer_prompt(candidate: dict, work: Path) -> str:
    title = candidate.get("title") or "Podcast commentary"
    source_url = candidate.get("url") or ""
    return f"""You are the podcast-content-agent for this repository. Work only inside:
{work}

Source metadata is in {work / 'source.json'}. The full transcript is in the
`transcription.transcript` field. Read enough of it to verify names, numbers,
dates, and claims. You may use web research for the host/guest.

Produce:
1. `script.txt` - 1,900-2,100 words of continuous spoken commentary. At the
   measured Qwen3 slide-by-slide pace of roughly 145-150 wpm this is roughly
   13-14.5 minutes. Do not exceed 2,100 words. Start with a 15-25 second who-is-who
   introduction (host and guest, current roles, one credibility fact each), then
   a specific hook, 3-5 ideas with your own analysis, and a low-key close. No
   headings, bullets, stage directions, or invented facts. Cite claims in the
   metadata; do not put citations in the spoken text.
2. `people.json` - host/guest names, roles, 2-4 sentence verified notes, source
   URLs. If the host is unnamed, say so and use `the host`.
3. `slides.json` - run:
   `uv run python skills/podcast-content-agent/scripts/slides.py draft --script {work / 'script.txt'} --out {work / 'slides.json'} --title "{title}" --voice-profile voices/me --engine qwen3 --fps 30 --wpm 150`
   Then edit it: 35-55 slides, clear headings, first title and last end card.
   Keep `"format": "broll-slides"` and `"engine": "qwen3"`. Add explicit
   `visual` hints to 6-10 technical slides. Use only real data in chart data;
   DAG/diagram/PetriNet hints are allowed for workflows, architectures and
   causal chains.
4. `youtube.json` - private upload metadata: title, 2-3 paragraph description,
   source URL ({source_url}), chapters, AI-voice disclosure, tags,
   `"containsSyntheticMedia": true`, `"privacyStatus": "private"`.
   Chapters may be approximate at this stage.
5. Run `uv run python skills/podcast-content-agent/scripts/slides.py validate
   {work / 'slides.json'} --root . --wpm 150` and fix all errors.

Do not run narrate.py, build.py, render_scenes.py, or upload anything. Stop
after the files validate. Work efficiently; read the transcript in chunks.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episodes", type=int, default=2)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--sleep", type=int, default=15)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    AUTOPILOT.mkdir(parents=True, exist_ok=True)
    if STOP.exists():
        log(f"stop file exists: {STOP}")
        return 0

    completed = 0
    while completed < args.episodes:
        if STOP.exists():
            log("stop file detected; exiting")
            break
        candidate = select_candidate()
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
        source_file = work / "source.json"
        with source_file.open("w") as handle:
            subprocess.run(
                [sys.executable, str(CONTENT_SCRIPTS / "fetch_popular.py"), "get", source_id],
                cwd=ROOT, stdout=handle, stderr=subprocess.PIPE, text=True, check=False,
            )
        if not source_file.exists() or source_file.stat().st_size < 100:
            log("empty source file; stopping")
            break

        prompt = writer_prompt(candidate, work)
        (work / "writer-prompt.txt").write_text(prompt + "\n")
        if args.dry_run:
            log("dry-run: writer prompt written; not invoking OpenCode")
            return 0
        write_code = run([
            "opencode", "run", "--auto", "--model", args.model,
            "--title", f"autopilot-writer-{slug}", prompt,
        ])
        if write_code:
            log(f"writer failed for {slug}; stopping")
            break
        if not (work / "script.txt").exists() or not (work / "slides.json").exists():
            log(f"writer did not produce script/slides for {slug}; stopping")
            break
        validate = run([
            sys.executable, str(CONTENT_SCRIPTS / "slides.py"),
            "validate", str(work / "slides.json"), "--root", ".", "--wpm", "160",
        ], quiet=True)
        if validate:
            log(f"slides failed validation for {slug}; stopping")
            break

        out_dir = ROOT / "out" / "autopilot" / slug
        out_dir.mkdir(parents=True, exist_ok=True)
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
            "--preset", "veryfast",
        ])
        if build_code:
            log(f"build/upload failed for {slug}; stopping")
            break
        receipt_path = out_dir / "youtube-upload.json"
        video_id = ""
        if receipt_path.exists():
            try:
                receipt = _load(receipt_path)
                video_id = receipt.get("video_id") or ""
            except Exception:
                pass
        mark = [
            sys.executable, str(CONTENT_SCRIPTS / "fetch_popular.py"), "mark",
            "--id", source_id, "--title", title,
            "--note", f"autopilot Qwen3 commentary; output {out_dir / 'final.mp4'}",
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
