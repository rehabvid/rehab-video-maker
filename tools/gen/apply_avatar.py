#!/usr/bin/env python3
"""Composite the animated host onto a finished video, bottom-right.

Landscape: the avatar is 1/3 of the video height.  Portrait: the avatar is
1/3 of the video width.  The VRM default is ``assets/avatar/me.vrm``.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import avatar_overlay  # noqa: E402


def _probe(path: Path) -> tuple[int, int]:
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path),
    ], text=True).strip()
    w, h = out.split(",")[:2]
    return int(w), int(h)


def _avatar_edge(width: int, height: int) -> int:
    """Square VRM edge: 1/3 height landscape, 1/3 width portrait."""
    edge = width / 3 if height > width else height / 3
    return max(120, int(round(edge)))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True)
    parser.add_argument("--audio", required=True)
    parser.add_argument("--svg", default="/Users/zhaoli/Downloads/lee.svg")
    parser.add_argument("--out")
    parser.add_argument("--fps", type=int, default=8)
    parser.add_argument("--engine", choices=["svg", "vrm"],
                        default=os.environ.get("AVATAR_ENGINE", "vrm"))
    default_vrm = os.environ.get("VRM_MODEL")
    if not default_vrm:
        # The owner's current presenter. Keep the older models as fallbacks so
        # an older checkout or a missing export still renders a host.
        for name in ("me.vrm", "host.vrm", "sample.vrm"):
            candidate = Path("assets/avatar") / name
            if candidate.exists():
                default_vrm = str(candidate)
                break
        else:
            default_vrm = "assets/avatar/me.vrm"
    parser.add_argument("--vrm", default=default_vrm)
    parser.add_argument("--slides", help="slides.json for syllable visemes")
    parser.add_argument("--timing", help="timing.json for syllable visemes")
    parser.add_argument("--offset", type=float, default=0.0,
                        help="seconds into the master timeline where this clip starts")
    args = parser.parse_args(argv)

    video = Path(args.video)
    audio = Path(args.audio)
    svg = Path(args.svg)
    width, height = _probe(video)
    portrait = height > width
    # Landscape reads the avatar by height; portrait by width. The VRM canvas
    # is square, so one edge controls both dimensions.
    avatar_edge = _avatar_edge(width, height)
    margin = max(18, int(width * 0.022))
    margin_bottom = int(height * 0.22) if portrait else max(84, int(height * 0.09))
    tmp = video.with_suffix(".avatar.mov")
    track = None
    if args.slides and args.timing:
        import visemes as viseme_track  # noqa: PLC0415
        track = viseme_track.build(Path(args.slides), Path(args.timing), args.fps, args.offset)
    if args.engine == "vrm" and Path(args.vrm).exists():
        cmd = [
            "node", str(HERE.parents[1] / "tools" / "vrm" / "render_vrm.mjs"),
            "--vrm", str(Path(args.vrm).resolve()), "--audio", str(audio.resolve()),
            "--out", str(tmp), "--height", str(avatar_edge), "--fps", str(args.fps),
        ]
        if track:
            track_path = video.with_suffix(".visemes.json")
            track_path.write_text(json.dumps({"fps": args.fps, "frames": track}))
            cmd += ["--visemes", str(track_path)]
        try:
            subprocess.run(cmd, check=True)
        finally:
            if track:
                track_path.unlink(missing_ok=True)
    else:
        if not svg.exists():
            print(f"avatar svg missing: {svg}", file=sys.stderr)
            return 0
        avatar_overlay.render(svg, audio, tmp, avatar_edge, args.fps, visemes=track)
    in_place = args.out is None
    out = Path(args.out) if args.out else video.with_suffix(".host.mp4")
    subprocess.run([
        "ffmpeg", "-hide_banner", "-v", "error", "-y",
        "-i", str(video), "-i", str(tmp),
        "-filter_complex", f"[1:v]format=rgba[a];[0:v][a]overlay=W-w-{margin}:H-h-{margin_bottom}:format=auto",
        "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "copy", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out),
    ], check=True)
    tmp.unlink(missing_ok=True)
    if in_place:
        out.replace(video)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
