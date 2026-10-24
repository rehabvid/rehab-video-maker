#!/usr/bin/env python3
"""End-to-end builder for a 10-15 minute b-roll podcast video.

Steps:

1. validate ``slides.json`` (no avatar shots allowed)
2. synthesise the personal-voice narration and measured timeline
3. assemble 1080p segments, captions and the loudness-normalised MP4
4. optionally upload the result to YouTube

Example::

    uv run python scripts/build.py \
        --slides build/ep01/slides.json \
        --out out/ep01/final.mp4 \
        --voice-profile voices/me \
        --engine chatterbox \
        --upload --metadata build/ep01/youtube.json \
        --thumbnail out/ep01/thumbnail.png
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHARED = HERE.parents[1] / "podcast-avatar-commentary" / "scripts"
ASSEMBLE = SHARED / "assemble.py"
SLIDES = HERE / "slides.py"
NARRATE = HERE / "narrate.py"
THUMBNAIL = HERE / "thumbnail.py"
UPLOAD = HERE / "youtube_upload.py"


def _run(cmd: list[str]) -> int:
    print("+ " + " ".join(str(part) for part in cmd))
    return subprocess.run(cmd).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slides", required=True)
    parser.add_argument("--out", required=True, help="final MP4, e.g. out/ep01/final.mp4")
    parser.add_argument("--work", help="build directory (default: slides.json parent)")
    parser.add_argument("--root", default=".", help="project root for visual paths")
    parser.add_argument("--voice-profile", default="voices/me")
    parser.add_argument("--engine", choices=["chatterbox", "edge"])
    parser.add_argument("--voice", default="andrew", help="edge-tts fallback voice")
    parser.add_argument("--rate", default="-6%", help="edge-tts rate, use --rate=-6%%")
    parser.add_argument("--voice-python", default=".venv-voice/bin/python")
    parser.add_argument("--device", default="mps", choices=["mps", "cpu"])
    parser.add_argument("--exaggeration", type=float, default=0.5)
    parser.add_argument("--cfg-weight", type=float, default=0.5)
    parser.add_argument("--seed", type=int, default=43)
    parser.add_argument("--max-chars", type=int, default=280)
    parser.add_argument("--force-tts", action="store_true")
    parser.add_argument("--music")
    parser.add_argument("--music-volume", type=float, default=0.06)

    parser.add_argument("--upload", action="store_true")
    parser.add_argument("--metadata", help="YouTube metadata JSON")
    parser.add_argument(
        "--privacy",
        choices=["private", "unlisted", "public"],
        help="upload privacy; default private",
    )
    parser.add_argument("--thumbnail", help="existing thumbnail; generated from the deck if omitted")
    parser.add_argument("--no-thumbnail", action="store_true", help="do not generate a thumbnail")
    parser.add_argument("--playlist")
    parser.add_argument("--publish-at")
    parser.add_argument("--upload-dry-run", action="store_true")
    args = parser.parse_args(argv)

    slides = Path(args.slides).resolve()
    work = Path(args.work).resolve() if args.work else slides.parent
    out = Path(args.out).resolve()
    root = Path(args.root).resolve()

    if _run([sys.executable, str(SLIDES), "validate", str(slides), "--root", str(root)]):
        return 1

    narrate = [
        sys.executable,
        str(NARRATE),
        "--slides",
        str(slides),
        "--out",
        str(work),
        "--voice-profile",
        args.voice_profile,
        "--voice-python",
        args.voice_python,
        "--device",
        args.device,
        "--exaggeration",
        str(args.exaggeration),
        "--cfg-weight",
        str(args.cfg_weight),
        "--seed",
        str(args.seed),
        "--max-chars",
        str(args.max_chars),
        "--voice",
        args.voice,
        f"--rate={args.rate}",
    ]
    if args.engine:
        narrate += ["--engine", args.engine]
    if args.force_tts:
        narrate.append("--force")
    if _run(narrate):
        return 1

    assemble = [
        sys.executable,
        str(ASSEMBLE),
        "--timing",
        str(work / "timing.json"),
        "--out",
        str(out),
        "--root",
        str(root),
    ]
    if args.music:
        assemble += ["--music", args.music, "--music-volume", str(args.music_volume)]
    if _run(assemble):
        return 1

    if not args.upload:
        print(f"final: {out}")
        return 0

    thumbnail: Path | None = (
        Path(args.thumbnail).expanduser() if args.thumbnail else None
    )
    if thumbnail is not None and not thumbnail.exists():
        print(f"error: thumbnail not found: {thumbnail}", file=sys.stderr)
        return 1
    if thumbnail is None and not args.no_thumbnail:
        thumbnail = out.parent / "thumbnail.png"
        if _run(
            [
                sys.executable,
                str(THUMBNAIL),
                "--slides",
                str(slides),
                "--out",
                str(thumbnail),
                "--root",
                str(root),
            ]
        ):
            return 1

    upload = [sys.executable, str(UPLOAD), "--video", str(out)]
    # Build always starts private. Public/scheduled publication must be an
    # explicit CLI decision, not something inherited from a metadata file.
    upload += ["--privacy", args.privacy or "private"]
    if args.metadata:
        upload += ["--metadata", args.metadata]
    if thumbnail is not None:
        upload += ["--thumbnail", str(thumbnail)]
    if args.playlist:
        upload += ["--playlist", args.playlist]
    if args.publish_at:
        upload += ["--publish-at", args.publish_at]
    captions = work / "captions.srt"
    if captions.exists():
        upload += ["--captions", str(captions)]
    if args.upload_dry_run:
        upload.append("--dry-run")
    return _run(upload)


if __name__ == "__main__":
    raise SystemExit(main())
