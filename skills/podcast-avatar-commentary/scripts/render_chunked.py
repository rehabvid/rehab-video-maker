#!/usr/bin/env python3
"""Render long avatar shots as short, stable chunks and stitch them.

EchoMimicV3-Flash is stable at 1-2 second units on a 32 GB M2. A 7-second
job can wedge MPS. This wrapper splits every avatar shot's measured audio into
~49-frame chunks, calls comfy_client.py once per chunk, then concatenates the
chunk videos into the full shot clip.

The avatar clip is video-only in practice: assemble.py attaches master.wav, so
the per-chunk audio is discarded at the end.

Usage:
  uv run python skills/podcast-avatar-commentary/scripts/render_chunked.py \
    --workflow characters/me/echomimic.api.json \
    --timing build/ep01/timing.json \
    --out build/ep01/avatar \
    --root . \
    --server http://127.0.0.1:8188 \
    --chunk-seconds 1.96
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CLIENT = SCRIPT_DIR / "comfy_client.py"
sys.path.insert(0, str(SCRIPT_DIR))

from lib import ffprobe_duration, load_json, run_ffmpeg, save_json  # noqa: E402


def _extract_audio(src: Path, start: float, duration: float, dest: Path) -> float:
    dest.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{start:.3f}",
            "-t",
            f"{duration:.3f}",
            "-i",
            str(src),
            "-vn",
            "-c:a",
            "libmp3lame",
            "-q:a",
            "2",
            str(dest),
        ]
    )
    return ffprobe_duration(dest)


def _concat(chunks: list[Path], dest: Path, duration: float, fps: int) -> None:
    listing = dest.parent / f"{dest.stem}-chunks.txt"
    listing.write_text(
        "".join(f"file '{p.resolve().as_posix()}'\n" for p in chunks)
    )
    merged = dest.parent / f"{dest.stem}-concat.mp4"
    run_ffmpeg(
        [
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(listing),
            "-c",
            "copy",
            str(merged),
        ]
    )
    # tpad covers the last-chunk rounding shortfall; trim cuts any overrun.
    run_ffmpeg(
        [
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(merged),
            "-vf",
            (
                "tpad=stop_mode=clone:stop_duration=1,"
                f"trim=duration={duration:.3f},setpts=PTS-STARTPTS"
            ),
            "-an",
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(fps),
            str(dest),
        ]
    )
    merged.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--timing", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--root", default=".")
    parser.add_argument("--server", default="http://127.0.0.1:8188")
    parser.add_argument("--chunk-seconds", type=float, default=1.96)
    parser.add_argument("--timeout", type=int, default=2400)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    timing_path = Path(args.timing).resolve()
    timing = load_json(timing_path)
    root = Path(args.root).resolve()
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    workflow = str(Path(args.workflow).resolve())
    fps = int(timing.get("fps", 25))
    shots = [s for s in timing.get("shots", []) if s.get("kind") == "avatar"]
    if not shots:
        print("no avatar shots; nothing to do")
        return 0

    for index, shot in enumerate(shots, start=1):
        sid = shot["id"]
        audio = (timing_path.parent / shot["audio"]).resolve()
        if not audio.exists():
            print(f"error: shot {sid}: missing audio {audio}", file=sys.stderr)
            return 1
        total = float(shot["audio_seconds"])
        work = out_dir / ".chunks" / f"shot-{sid}"
        work.mkdir(parents=True, exist_ok=True)
        chunk_paths: list[Path] = []
        chunk_meta: list[dict] = []
        start = 0.0
        n = 0
        while start < total - 0.02:
            n += 1
            length = min(args.chunk_seconds, total - start)
            cid = f"{sid}c{n:02d}"
            chunk_audio = work / f"{cid}.mp3"
            actual = _extract_audio(audio, start, length, chunk_audio)
            chunk_dir = work / cid
            chunk_dir.mkdir(parents=True, exist_ok=True)
            temp_timing = work / f"timing-{cid}.json"
            chunk_shot = dict(shot)
            chunk_shot.update(
                {
                    "id": cid,
                    "audio": str(chunk_audio),
                    "audio_seconds": actual,
                    "duration": actual,
                    "lead": 0.0,
                    "tail": 0.0,
                }
            )
            save_json(
                temp_timing,
                {
                    "slug": timing.get("slug", "chunk"),
                    "title": timing.get("title", ""),
                    "character": timing.get("character", ""),
                    "voice": timing.get("voice", ""),
                    "fps": fps,
                    "total_seconds": actual,
                    "shots": [chunk_shot],
                },
            )
            cmd = [
                sys.executable,
                str(CLIENT),
                "--workflow",
                workflow,
                "--timing",
                str(temp_timing),
                "--out",
                str(chunk_dir),
                "--root",
                str(root),
                "--server",
                args.server,
                "--timeout",
                str(args.timeout),
                "--same-seed",
            ]
            if args.force:
                cmd.append("--force")
            print(
                f"[{index}/{len(shots)}] shot {sid}: chunk {n} "
                f"({start:.2f}-{start + length:.2f}s, {actual:.2f}s)"
            )
            result = subprocess.run(cmd)
            if result.returncode != 0:
                print(f"error: chunk {cid} failed", file=sys.stderr)
                return result.returncode
            clip = chunk_dir / f"shot-{cid}.mp4"
            if not clip.exists():
                print(f"error: chunk {cid} produced no clip", file=sys.stderr)
                return 1
            chunk_paths.append(clip)
            chunk_meta.append(
                {
                    "chunk": cid,
                    "start": round(start, 3),
                    "audio_seconds": round(actual, 3),
                    "clip": str(clip),
                }
            )
            start += length

        target = out_dir / f"shot-{sid}.mp4"
        _concat(chunk_paths, target, total, fps)
        duration = ffprobe_duration(target)
        save_json(
            out_dir / f"shot-{sid}.json",
            {
                "shot": sid,
                "image": str((root / shot["visual"]).resolve()) if shot.get("visual") else None,
                "seed": shot.get("seed"),
                "frames": round(total * fps),
                "duration": duration,
                "audio_seconds": total,
                "chunks": chunk_meta,
                "workflow": workflow,
            },
        )
        print(f"  wrote {target} ({duration:.2f}s from {len(chunk_paths)} chunks)")

    print(f"done: {len(shots)} avatar shots in {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
