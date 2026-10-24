#!/usr/bin/env python3
"""Build a technical commentary video from slide transcripts and LinkZag visuals.

This is the video-side skill. It consumes a ``slides.json`` produced by the
content skill, plans which slides deserve a custom visual, renders only those
scenes through LinkZag.Show, then reuses the shared narration/caption/assembly
code to produce the final MP4.

The default path is deliberately mixed:

* static technical visuals are one PNG, looped by the assembler;
* selected charts/DAGs/diagrams are short MP4s with deterministic reveal motion;
* title, quote, and end slides keep the existing captioned card renderer.

That avoids encoding every slide as a video just because animation is possible.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
CONTENT_SCRIPTS = REPO / "skills" / "podcast-youtuber-agent" / "scripts"
SHARED_SCRIPTS = REPO / "skills" / "podcast-avatar-commentary" / "scripts"
LINKZAG_MODULE = REPO / "modules" / "linkZagShow"


def _run(cmd: list[str]) -> int:
    print("+ " + " ".join(str(part) for part in cmd))
    return subprocess.run(cmd, cwd=REPO).returncode


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _rel(path: Path) -> str:
    return os.path.relpath(path, REPO).replace(os.sep, "/")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slides", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--work")
    parser.add_argument("--timing", help="existing timing.json; otherwise narrate")
    parser.add_argument("--voice-profile", default="voices/me")
    parser.add_argument("--engine", default="chatterbox", choices=["chatterbox", "edge"])
    parser.add_argument("--device", default="mps", choices=["mps", "cpu"])
    parser.add_argument("--exaggeration", type=float, default=0.5)
    parser.add_argument("--cfg-weight", type=float, default=0.5)
    parser.add_argument("--seed", type=int, default=43)
    parser.add_argument("--voice-python", default=str(REPO / ".venv-voice" / "bin" / "python"))
    parser.add_argument("--module", default=str(LINKZAG_MODULE))
    parser.add_argument("--base-url", help="reuse a running LinkZag renderer")
    parser.add_argument("--keep-scenes", action="store_true")
    parser.add_argument("--skip-visuals", action="store_true")
    parser.add_argument("--force-narrate", action="store_true")
    parser.add_argument("--thumbnail")
    parser.add_argument("--no-thumbnail", action="store_true")
    parser.add_argument("--upload", action="store_true")
    parser.add_argument("--metadata")
    parser.add_argument("--privacy", choices=["private", "unlisted", "public"])
    parser.add_argument("--publish-at")
    args = parser.parse_args(argv)

    slides_path = Path(args.slides).resolve()
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    work = Path(args.work).resolve() if args.work else slides_path.parent
    work.mkdir(parents=True, exist_ok=True)
    timing_path = Path(args.timing).resolve() if args.timing else work / "timing.json"

    if not args.skip_visuals:
        if args.force_narrate or not timing_path.exists():
            narrate = [
                sys.executable,
                str(CONTENT_SCRIPTS / "narrate.py"),
                "--slides", str(slides_path),
                "--out", str(work),
                "--voice-profile", args.voice_profile,
                "--engine", args.engine,
                "--device", args.device,
                "--exaggeration", str(args.exaggeration),
                "--cfg-weight", str(args.cfg_weight),
                "--seed", str(args.seed),
                "--voice-python", args.voice_python,
            ]
            if _run(narrate):
                return 1
            timing_path = work / "timing.json"

        plan_path = work / "visual-plan.json"
        scenes_path = work / "scenes.json"
        visuals_dir = work / "visuals"
        if _run([
            sys.executable, str(HERE / "plan_visuals.py"),
            "--slides", str(slides_path),
            "--timing", str(timing_path),
            "--out", str(plan_path),
        ]):
            return 1
        if _run([
            sys.executable, str(HERE / "make_scenes.py"),
            "--plan", str(plan_path),
            "--module", args.module,
            "--out", str(scenes_path),
        ]):
            return 1
        render = [
            sys.executable, str(HERE / "render_scenes.py"),
            "--manifest", str(scenes_path),
            "--visuals", str(visuals_dir),
            "--module", args.module,
        ]
        if args.base_url:
            render += ["--base-url", args.base_url]
        if args.keep_scenes:
            render.append("--keep-scenes")
        if _run(render):
            return 1

        # Apply the rendered visuals to the measured timeline. The assembler
        # already knows how to loop a still or an MP4 for a b-roll shot.
        plan = _load(plan_path)
        scenes = _load(scenes_path)
        timing = _load(timing_path)
        by_id = {str(s.get("id")): s for s in scenes.get("scenes", [])}
        for shot in timing.get("shots", []):
            sid = str(shot.get("id"))
            scene = by_id.get(sid)
            if not scene:
                continue
            suffix = ".mp4" if scene.get("animated") else ".png"
            visual = visuals_dir / f"shot-{sid}{suffix}"
            if not visual.exists():
                print(f"warning: missing rendered visual {visual}", file=sys.stderr)
                continue
            shot["kind"] = "broll"
            shot["visual"] = _rel(visual)
            shot["visual_type"] = scene.get("type")
        timing_path = work / "timing-visuals.json"
        timing_path.write_text(json.dumps(timing, indent=2) + "\n")
        (work / "slides-visuals.json").write_text(json.dumps(plan, indent=2) + "\n")

    if _run([
        sys.executable,
        str(SHARED_SCRIPTS / "assemble.py"),
        "--timing", str(timing_path),
        "--out", str(out),
        "--root", str(REPO),
    ]):
        return 1

    thumbnail = Path(args.thumbnail).expanduser() if args.thumbnail else out.parent / "thumbnail.png"
    if not args.no_thumbnail and not args.thumbnail:
        thumb_cmd = [
            sys.executable, str(CONTENT_SCRIPTS / "thumbnail.py"),
            "--slides", str(slides_path),
            "--out", str(thumbnail),
            "--root", str(REPO),
        ]
        if _run(thumb_cmd):
            print("warning: thumbnail generation failed; continuing", file=sys.stderr)
            thumbnail = None
    elif args.thumbnail and not thumbnail.exists():
        print(f"warning: thumbnail not found: {thumbnail}", file=sys.stderr)
        thumbnail = None

    if args.upload:
        if not args.metadata:
            print("error: --upload requires --metadata", file=sys.stderr)
            return 1
        upload = [
            sys.executable, str(CONTENT_SCRIPTS / "youtube_upload.py"),
            "--video", str(out),
            "--metadata", args.metadata,
            "--privacy", args.privacy or "private",
        ]
        if thumbnail:
            upload += ["--thumbnail", str(thumbnail)]
        captions = work / "captions.srt"
        if captions.exists():
            upload += ["--captions", str(captions)]
        if args.publish_at:
            upload += ["--publish-at", args.publish_at]
        if _run(upload):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
