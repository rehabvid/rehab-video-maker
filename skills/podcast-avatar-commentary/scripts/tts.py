#!/usr/bin/env python3
"""Synthesise per-shot narration, measure it, and build the exact timeline.

Timing is always measured from the generated audio, never estimated. The output
`timing.json` is the single source of truth for avatar rendering, captions and
assembly.

Usage:
    python3 tts.py --shots shots.json --out build/ep01 --voice andrew --rate=-6%
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import wave
from pathlib import Path

import edge_tts
import numpy as np

from lib import (
    FPS,
    LEAD,
    LEAD_FIRST,
    TAIL,
    ffprobe_duration,
    load_json,
    quantize,
    save_json,
    write_ass,
    write_srt,
)

VOICES = {
    "andrew": "en-US-AndrewNeural",
    "steffan": "en-US-SteffanNeural",
    "thomas": "en-GB-ThomasNeural",
    "eric": "en-US-EricNeural",
    "ava": "en-US-AvaNeural",
}
DEFAULT_VOICE = "andrew"
DEFAULT_RATE = "-6%"
SAMPLE_RATE = 48_000
CHANNELS = 2
PEAK_TARGET = 0.708  # -3 dBFS


def _fingerprint(text: str, voice: str, rate: str) -> str:
    return hashlib.sha256(f"{voice}|{rate}|{text}".encode()).hexdigest()[:16]


async def _synth_all(jobs: list[tuple[dict, Path, str, str]]) -> None:
    async def one(shot: dict, path: Path, voice: str, rate: str) -> None:
        communicate = edge_tts.Communicate(shot["narration"], voice, rate=rate)
        await communicate.save(str(path))

    await asyncio.gather(*(one(s, p, v, r) for s, p, v, r in jobs))


def _decode_to_wav(src: Path, dst: Path) -> Path:
    import subprocess

    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-v",
            "error",
            "-y",
            "-i",
            str(src),
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            str(CHANNELS),
            "-c:a",
            "pcm_s16le",
            str(dst),
        ],
        check=True,
    )
    return dst


def _read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        if w.getframerate() != SAMPLE_RATE or w.getnchannels() != CHANNELS:
            raise RuntimeError(f"{path} is not {SAMPLE_RATE} Hz stereo")
        frames = w.readframes(w.getnframes())
    data = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    return data.reshape(-1, CHANNELS)


def _build_master(
    timeline: list[dict], out_wav: Path, audio_dir: Path, work_dir: Path, total: float
) -> dict:
    work_dir.mkdir(parents=True, exist_ok=True)
    total_frames = int(np.ceil(total * SAMPLE_RATE)) + 1
    bed = np.zeros((total_frames, CHANNELS), dtype=np.float32)

    for shot in timeline:
        wav = _decode_to_wav(audio_dir / shot["audio"], work_dir / f"{shot['id']}.wav")
        clip = _read_wav(wav)
        start = int(round((shot["start"] + shot["lead"]) * SAMPLE_RATE))
        end = min(start + len(clip), total_frames)
        if end - start != len(clip):
            raise RuntimeError(
                f"shot {shot['id']} would be truncated: speech ends after the video"
            )
        bed[start:end] += clip

    peak = float(np.max(np.abs(bed))) if bed.size else 0.0
    if peak > 0:
        bed *= PEAK_TARGET / peak
    pcm = np.clip(bed * 32767.0, -32768, 32767).astype("<i2")
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())

    return {
        "path": str(out_wav),
        "duration": round(total_frames / SAMPLE_RATE, 3),
        "peak_before_normalise": round(peak, 4),
        "peak_after_normalise": round(PEAK_TARGET if peak else 0.0, 4),
        "clipped_samples": int(np.sum(np.abs(bed) >= 0.999)),
    }


def build(args) -> int:
    shots_path = Path(args.shots)
    data = load_json(shots_path)
    shots = data.get("shots") or []
    if not shots:
        print("error: no shots", file=sys.stderr)
        return 1
    if args.voice not in VOICES:
        print(f"error: unknown voice '{args.voice}' (choose from {', '.join(VOICES)})", file=sys.stderr)
        return 1

    out = Path(args.out)
    audio_dir = out / "audio"
    tmp_dir = out / "tts"
    audio_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    voice_name = VOICES[args.voice]
    rate = args.rate
    manifest_path = audio_dir / "narration.json"
    previous: dict[str, dict] = {}
    if manifest_path.exists():
        try:
            previous = {c["id"]: c for c in json.loads(manifest_path.read_text()).get("cues", [])}
        except (json.JSONDecodeError, KeyError):
            previous = {}

    jobs = []
    results: list[dict | None] = []
    fps = int(data.get("fps") or FPS)
    cursor = 0.0
    timeline: list[dict] = []

    for i, shot in enumerate(shots):
        sid = shot["id"]
        text = (shot.get("narration") or "").strip()
        if not text:
            print(f"error: shot {sid} has no narration", file=sys.stderr)
            return 1
        path = audio_dir / f"shot-{sid}.mp3"
        fp = _fingerprint(text, voice_name, rate)
        cached = previous.get(sid)
        reusable = (
            not args.force
            and path.exists()
            and cached
            and cached.get("fingerprint") == fp
            and cached.get("file") == path.name
        )
        if reusable:
            duration = float(cached["duration"])
        else:
            jobs.append((shot, path, voice_name, rate))
            duration = None
        results.append({"duration": duration, "file": path.name, "fingerprint": fp})

    if jobs:
        print(f"synthesising {len(jobs)} cues with {voice_name} at {rate}")
        try:
            asyncio.run(_synth_all(jobs))
        except Exception as exc:  # noqa: BLE001 - network and service errors vary
            print(f"error: voice synthesis failed: {exc}", file=sys.stderr)
            print("hint: check network access, or place your own mp3s at audio/shot-XX.mp3", file=sys.stderr)
            return 1

    for i, shot in enumerate(shots):
        sid = shot["id"]
        path = audio_dir / f"shot-{sid}.mp3"
        if not path.exists() or path.stat().st_size == 0:
            print(f"error: no audio for shot {sid}", file=sys.stderr)
            return 1
        duration = results[i]["duration"]
        if duration is None:
            duration = ffprobe_duration(path)
        duration = round(float(duration), 3)
        lead = LEAD_FIRST if i == 0 else LEAD
        shot_duration = quantize(lead + duration + TAIL, fps)
        override = float(shot.get("duration") or 0)
        if override > 0:
            shot_duration = max(shot_duration, quantize(override, fps))
        entry = {
            **{k: v for k, v in shot.items() if k not in {"narration"}},
            "narration": shot["narration"],
            "audio": f"audio/{path.name}",
            "audio_seconds": duration,
            "start": round(cursor, 3),
            "duration": round(shot_duration, 3),
            "lead": round(lead, 3),
            "tail": TAIL,
            "fingerprint": results[i]["fingerprint"],
        }
        timeline.append(entry)
        cursor += shot_duration

    total = round(cursor, 3)
    save_json(
        audio_dir / "narration.json",
        {
            "voice": {"key": args.voice, "name": voice_name, "rate": rate},
            "cues": [
                {"id": s["id"], "file": s["audio"].split("/")[-1], "duration": s["audio_seconds"],
                 "fingerprint": s["fingerprint"]}
                for s in timeline
            ],
        },
    )

    timing = {
        "slug": data.get("slug"),
        "title": data.get("title"),
        "character": data.get("character"),
        "voice": {"key": args.voice, "name": voice_name, "rate": rate},
        "fps": fps,
        "total_seconds": total,
        "shots": timeline,
    }
    save_json(out / "timing.json", timing)
    write_srt(timeline, out / "captions.srt")
    write_ass(timeline, out / "captions.ass")
    (out / "cues.txt").write_text(
        "".join(f"# {s['id']}  {s['start']:.2f}s + {s['duration']:.2f}s\n{s['narration']}\n\n" for s in timeline)
    )

    master = _build_master(timeline, out / "master.wav", out, tmp_dir, total)
    if master["clipped_samples"]:
        print("error: master.wav clips; lower the source or normalise manually", file=sys.stderr)
        return 1

    print(f"wrote {out / 'timing.json'}: {len(timeline)} shots, {total:.1f}s")
    print(f"wrote {out / 'master.wav'} ({master['duration']:.1f}s, peak {master['peak_after_normalise']:.2f} FS)")
    print(f"wrote {out / 'captions.srt'} and {out / 'captions.ass'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shots", required=True)
    parser.add_argument("--out", required=True, help="build directory, e.g. build/ep01")
    parser.add_argument("--voice", default=DEFAULT_VOICE, choices=list(VOICES))
    parser.add_argument("--rate", default=DEFAULT_RATE, help="edge-tts rate, use the = form: --rate=-6%%")
    parser.add_argument("--force", action="store_true", help="re-synthesise every cue")
    args = parser.parse_args(argv)
    return build(args)


if __name__ == "__main__":
    raise SystemExit(main())
